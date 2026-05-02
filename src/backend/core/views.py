"""
ForensiQ — ViewSets para a API REST.

Cada entidade tem um ViewSet dedicado com permissões baseadas em perfil.
O campo 'agent' é preenchido automaticamente com o utilizador autenticado.

Endpoints:
- /api/users/              — gestão de utilizadores (admin apenas cria)
- /api/occurrences/        — ocorrências (AGENT cria, todos consultam)
- /api/evidences/          — evidências (AGENT cria, todos consultam)
- /api/evidences/lookup/imei/<imei>/ — enriquecimento IMEI via imeidb.xyz
- /api/evidences/lookup/vin/<vin>/   — redirect para vindecoder.eu
- /api/devices/            — dispositivos digitais (AGENT cria, todos consultam)
- /api/custody/            — cadeia de custódia (AGENT/EXPERT criam, todos consultam)
- /api/stats/              — dashboard agregado
- /api/stats/dashboard/    — payload estável consumido pelo dashboard (Wave 2d)
- /api/health/             — healthcheck (liveness + DB)
"""

import logging
import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_safe
from rest_framework import (
    filters,
    serializers as drf_serializers,  # Para converter ValidationError
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .audit import log_access
from .models import (
    AuditLog,
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
)
from .pdf_export import generate_evidence_pdf, generate_occurrence_pdf
from .permissions import IsAgent, IsAgentOrExpert, IsOwnerOrReadOnly
from .serializers import (
    CascadeCustodyRequestSerializer,
    ChainOfCustodySerializer,
    DigitalDeviceSerializer,
    EvidenceSerializer,
    OccurrenceSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserSerializer,
)
from .services.imei_lookup import LookupError as ImeiLookupError, lookup_imei
from .services.vin_lookup import build_vindecoder_url
from .validators import validate_imei, validate_vin

User = get_user_model()

log = logging.getLogger(__name__)

# TTL de cache para lookups externos (30 dias — ADR-0008). Mantém alinhado
# com ``CACHES['default']['TIMEOUT']`` mas declarado localmente para o
# endpoint ser explícito sobre a política forense (imutabilidade do IMEI).
_LOOKUP_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30


def _user_can_access_occurrence(user, occurrence) -> bool:
    """Helper partilhado por views e serializers (IDOR / ownership).

    Regra: staff / EXPERT vêem tudo; AGENT só ocorrências próprias.
    Qualquer outro perfil autenticado é bloqueado.
    """
    if user is None or not user.is_authenticated:
        return False
    if getattr(user, 'is_staff', False):
        return True
    profile = getattr(user, 'profile', None)
    if profile == 'EXPERT':
        return True
    if profile == 'AGENT':
        return occurrence.agent_id == user.id
    return False


def _user_can_lookup(user) -> bool:
    """Só AGENT / EXPERT (ou staff) podem consultar APIs externas."""
    if user is None or not user.is_authenticated:
        return False
    if getattr(user, 'is_staff', False):
        return True
    return getattr(user, 'profile', None) in ('AGENT', 'EXPERT')


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserViewSet(viewsets.ModelViewSet):
    """
    API de utilizadores.

    - Listagem e detalhe: qualquer utilizador autenticado (sem badge_number).
    - Criação: apenas administradores.
    - me/ — retorna o perfil completo do utilizador autenticado (com badge).
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        """Retorna o perfil do utilizador autenticado (inclui email e phone)."""
        serializer = UserDetailSerializer(request.user, context={'request': request})
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Occurrence
# ---------------------------------------------------------------------------

class OccurrenceViewSet(viewsets.ModelViewSet):
    """
    API de ocorrências.

    - Criação/edição: apenas AGENT.
    - Consulta: qualquer utilizador autenticado.
    - O campo 'agent' é preenchido automaticamente.
    """

    queryset = Occurrence.objects.select_related('agent').all()
    serializer_class = OccurrenceSerializer
    permission_classes = [IsAuthenticated, IsAgent, IsOwnerOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    # Campos pesquisáveis via ?search= — NUIPC/número, descrição livre,
    # morada e código gerado (OCC-YYYY-NNNNN). Resolve queixa de filtros
    # inoperantes (revisão UX 2026-05-02).
    search_fields = ['number', 'code', 'description', 'address']
    ordering_fields = ['date_time', 'created_at', 'number']
    ordering = ['-date_time']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_staff and hasattr(user, 'profile') and user.profile == 'AGENT':
            qs = qs.filter(agent=user)
        # Filtro opcional por estado actual de custódia das evidências da
        # ocorrência. Reutiliza Evidence.objects.with_current_state() para
        # manter a definição de "estado actual" coerente com os outros
        # endpoints e o dashboard.
        state = self.request.query_params.get('state')
        if state:
            valid_states = {s for s, _ in ChainOfCustody.CustodyState.choices}
            if state not in valid_states:
                raise drf_serializers.ValidationError({
                    'state': f'Estado inválido. Valores aceites: {", ".join(sorted(valid_states))}.'
                })
            occ_ids = (
                Evidence.objects.with_current_state()
                .filter(current_state=state)
                .values_list('occurrence_id', flat=True)
            )
            qs = qs.filter(id__in=list(occ_ids))
        return qs

    def retrieve(self, request, *args, **kwargs):
        """Override: auditoria de visualização."""
        occurrence = self.get_object()
        log_access(
            request=request,
            action=AuditLog.Action.VIEW,
            resource_type=AuditLog.ResourceType.OCCURRENCE,
            resource_id=occurrence.pk,
        )
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        occurrence = serializer.save(agent=self.request.user)
        log_access(
            request=self.request,
            action=AuditLog.Action.CREATE,
            resource_type=AuditLog.ResourceType.OCCURRENCE,
            resource_id=occurrence.pk,
        )

    def get_throttles(self):
        if self.action == 'export_pdf':
            self.throttle_scope = 'pdf_export'
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @action(detail=True, methods=['get'], url_path='pdf')
    def export_pdf(self, request, pk=None):
        """GET /api/occurrences/<id>/pdf/ — resumo consolidado do caso.

        Contém descrição da ocorrência, inventário de itens de prova
        (raiz + sub-componentes) e estado actual de custódia. Serve o
        agente responsável para um overview único do processo.
        """
        # ownership: get_queryset já filtra AGENT para ocorrências próprias
        base_qs = self.get_queryset().filter(pk=pk)
        optimized_qs = base_qs.select_related('agent').prefetch_related(
            'evidences__agent',
            'evidences__parent_evidence',
            'evidences__sub_components',
            'evidences__custody_chain',
            'evidences__digital_devices',
        )
        self.queryset = optimized_qs
        occurrence = self.get_object()

        log_access(
            request=request,
            action=AuditLog.Action.EXPORT_PDF,
            resource_type=AuditLog.ResourceType.OCCURRENCE,
            resource_id=occurrence.pk,
        )

        try:
            pdf_bytes = generate_occurrence_pdf(occurrence)
        except Exception as exc:  # noqa: BLE001 — erro claro no cliente
            return Response(
                {'error': f'Erro ao gerar PDF: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        filename = f'ForensiQ_Caso_{occurrence.pk:04d}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(pdf_bytes)
        return response


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceViewSet(viewsets.ModelViewSet):
    """
    API de evidências.

    - Criação: apenas AGENT.
    - Consulta: qualquer utilizador autenticado.
    - Edição/eliminação: BLOQUEADAS (imutável após registo — ISO/IEC 27037).
    - O campo 'agent' e 'integrity_hash' são preenchidos automaticamente.
    - Filtragem por ocorrência: ?occurrence=<id>
    """

    queryset = (
        Evidence.objects
        .select_related('occurrence', 'agent')
        .prefetch_related('sub_components')
        .all()
    )
    serializer_class = EvidenceSerializer
    permission_classes = [IsAuthenticated, IsAgent, IsOwnerOrReadOnly]
    http_method_names = ['get', 'post', 'head', 'options']  # sem PUT/PATCH/DELETE
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    # Pesquisa atravessa para a ocorrência (?search= no NUIPC funciona).
    search_fields = [
        'code', 'description', 'serial_number',
        'occurrence__number', 'occurrence__code', 'occurrence__description',
    ]
    ordering_fields = ['timestamp_seizure', 'created_at', 'code']
    ordering = ['-timestamp_seizure']

    def get_throttles(self):
        if self.action == 'create':
            self.throttle_scope = 'evidence_upload'
            return [ScopedRateThrottle()]
        if self.action == 'export_pdf':
            self.throttle_scope = 'pdf_export'
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        """Aplica sempre o filtro de ownership antes do filtro por query param.

        Nota: é crítico que este método seja a ÚNICA porta de entrada para o
        queryset operativo. Actions que substituem ``self.queryset``
        directamente passam a ignorar o filtro e abrem IDOR (bug corrigido
        em 2026-04-19 no ``export_pdf``).
        """
        qs = super().get_queryset().with_current_state()
        user = self.request.user
        if not user.is_staff and hasattr(user, 'profile') and user.profile == 'AGENT':
            qs = qs.filter(occurrence__agent=user)
        occurrence_id = self.request.query_params.get('occurrence')
        if occurrence_id:
            qs = qs.filter(occurrence_id=occurrence_id)
        parent_id = self.request.query_params.get('parent')
        if parent_id:
            qs = qs.filter(parent_evidence_id=parent_id)
        state = self.request.query_params.get('state')
        if state:
            valid_states = {s for s, _ in ChainOfCustody.CustodyState.choices}
            if state not in valid_states:
                raise drf_serializers.ValidationError({
                    'state': f'Estado inválido. Valores aceites: {", ".join(sorted(valid_states))}.'
                })
            qs = qs.filter(current_state=state)
        return qs

    def retrieve(self, request, *args, **kwargs):
        """Override: auditoria de visualização."""
        evidence = self.get_object()
        log_access(
            request=request,
            action=AuditLog.Action.VIEW,
            resource_type=AuditLog.ResourceType.EVIDENCE,
            resource_id=evidence.pk,
            details={'hash': evidence.integrity_hash},
        )
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        evidence = serializer.save(agent=self.request.user)
        log_access(
            request=self.request,
            action=AuditLog.Action.CREATE,
            resource_type=AuditLog.ResourceType.EVIDENCE,
            resource_id=evidence.pk,
            details={'hash': evidence.integrity_hash},
        )

    @action(detail=True, methods=['get'], url_path='pdf')
    def export_pdf(self, request, pk=None):
        """
        Gera e devolve o relatório forense da evidência em formato PDF.

        GET /api/evidences/<id>/pdf/

        Conformidade: ISO/IEC 27037 — inclui hash SHA-256, timestamp UTC,
        cadeia de custódia completa e declaração de integridade.
        """
        # IDOR fix (2026-04-19): em vez de substituir ``self.queryset`` —
        # o que atalhava o filtro por ownership de ``get_queryset()`` —
        # aplicamos ``.filter(pk=pk)`` sobre o queryset filtrado e depois
        # optimizamos com select_related/prefetch_related. Se o utilizador
        # não for dono da ocorrência, get_object() devolve 404 (não 200).
        base_qs = self.get_queryset().filter(pk=pk)
        optimized_qs = base_qs.select_related(
            'occurrence__agent', 'agent',
        ).prefetch_related('custody_chain__agent')
        self.queryset = optimized_qs
        evidence = self.get_object()

        # Auditoria: exportação PDF
        log_access(
            request=request,
            action=AuditLog.Action.EXPORT_PDF,
            resource_type=AuditLog.ResourceType.EVIDENCE,
            resource_id=evidence.pk,
            details={'hash': evidence.integrity_hash},
        )

        try:
            pdf_bytes = generate_evidence_pdf(evidence)
        except Exception as exc:
            return Response(
                {'error': f'Erro ao gerar PDF: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        filename = f'ForensiQ_Evidencia_{evidence.pk:04d}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(pdf_bytes)
        return response


# ---------------------------------------------------------------------------
# DigitalDevice
# ---------------------------------------------------------------------------

class DigitalDeviceViewSet(viewsets.ModelViewSet):
    """
    API de dispositivos digitais.

    - Criação/edição: AGENT.
    - Consulta: qualquer utilizador autenticado.
    - Filtragem por evidência: ?evidence=<id>
    """

    queryset = DigitalDevice.objects.select_related('evidence').all()
    serializer_class = DigitalDeviceSerializer
    permission_classes = [IsAuthenticated, IsAgent]
    http_method_names = ['get', 'post', 'head', 'options']  # sem PUT/PATCH/DELETE
    filter_backends = [filters.SearchFilter]
    search_fields = [
        'brand', 'model', 'commercial_name',
        'serial_number', 'imei', 'notes',
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_staff and hasattr(user, 'profile') and user.profile == 'AGENT':
            qs = qs.filter(evidence__occurrence__agent=user)
        evidence_id = self.request.query_params.get('evidence')
        if evidence_id:
            qs = qs.filter(evidence_id=evidence_id)
        return qs


# ---------------------------------------------------------------------------
# ChainOfCustody
# ---------------------------------------------------------------------------

class ChainOfCustodyViewSet(viewsets.ModelViewSet):
    """
    API da cadeia de custódia.

    - Criação: AGENT ou EXPERT (conforme a fase da custódia).
    - Consulta: qualquer utilizador autenticado.
    - Edição/eliminação: BLOQUEADAS (append-only — 405 Method Not Allowed).
    - O campo 'agent' é preenchido automaticamente.
    - Filtragem por evidência: ?evidence=<id>
    """

    queryset = ChainOfCustody.objects.select_related('evidence', 'agent').all()
    serializer_class = ChainOfCustodySerializer
    permission_classes = [IsAuthenticated, IsAgentOrExpert]
    http_method_names = ['get', 'post', 'head', 'options']  # sem PUT/PATCH/DELETE
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'code', 'observations',
        'evidence__code', 'evidence__description',
        'evidence__occurrence__number',
    ]
    ordering_fields = ['timestamp', 'sequence']
    # Ordem canónica de uma cadeia de custódia: ASCENDENTE por sequência
    # (do primeiro registo APREENDIDA ao último). Quem precisar do mais
    # recente primeiro (ex: listagem global) passa ?ordering=-timestamp.
    ordering = ['sequence']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_staff and hasattr(user, 'profile') and user.profile == 'AGENT':
            qs = qs.filter(evidence__occurrence__agent=user)
        evidence_id = self.request.query_params.get('evidence')
        if evidence_id:
            qs = qs.filter(evidence_id=evidence_id)
        return qs

    def perform_create(self, serializer):
        try:
            custody_record = serializer.save(agent=self.request.user)
            log_access(
                request=self.request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.CUSTODY,
                resource_id=custody_record.pk,
                details={'evidence_id': custody_record.evidence_id, 'new_state': custody_record.new_state},
            )
        except DjangoValidationError as exc:
            # Converter ValidationError do Django para DRF (retorna 400)
            raise drf_serializers.ValidationError(exc.message_dict)

    @action(detail=False, methods=['get'], url_path='evidence/(?P<evidence_id>[0-9]+)/timeline')
    def timeline(self, request, evidence_id=None):
        """Retorna a timeline completa de custódia para uma evidência."""
        records = (
            ChainOfCustody.objects
            .select_related('agent', 'evidence__occurrence')
            .filter(evidence_id=evidence_id)
            .order_by('sequence')
        )
        serializer = self.get_serializer(records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='cascade')
    def cascade(self, request):
        """POST /api/custody/cascade/ — transição atómica de várias evidências.

        Permite ao utilizador mover um item-pai e os seus sub-componentes
        (ex: telemóvel + cartão SIM + cartão de memória) para o mesmo
        estado de custódia numa única acção, em vez de o fazer item a
        item. Ver decisão UX no plano (Bloco E).

        Garantias:
        - Atomicidade: ou todas as transições são gravadas, ou nenhuma
          (envolto em ``transaction.atomic()``).
        - Cada ``ChainOfCustody.save()`` mantém o seu próprio
          ``select_for_update`` por evidência — não há contenção entre
          evidências distintas.
        - Ownership: utilizador tem de poder operar sobre TODAS as
          evidências (AGENT dono, EXPERT ou staff). Caso contrário 403.
        - Validação da máquina de estados é feita por cada
          ``ChainOfCustody.save()``; se uma evidência rejeitar a
          transição, todas revertem e o cliente recebe 400 com
          ``evidence_id`` e mensagem.
        - Auditoria: cria um ``AuditLog`` por cada registo criado.
        """
        payload = CascadeCustodyRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        evidence_ids = payload.validated_data['evidence_ids']
        new_state = payload.validated_data['new_state']
        observations = payload.validated_data.get('observations', '')

        evidences = list(
            Evidence.objects.select_related('occurrence', 'occurrence__agent')
            .filter(id__in=evidence_ids)
        )
        if len(evidences) != len(set(evidence_ids)):
            return Response(
                {'detail': 'Uma ou mais evidências não existem.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        for ev in evidences:
            if not _user_can_access_occurrence(request.user, ev.occurrence):
                return Response(
                    {'detail': f'Sem permissão sobre a evidência {ev.code or ev.pk}.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        created_records = []
        try:
            with transaction.atomic():
                for ev in evidences:
                    record = ChainOfCustody(
                        evidence=ev,
                        new_state=new_state,
                        observations=observations,
                        agent=request.user,
                    )
                    record.save()
                    created_records.append(record)
                    log_access(
                        request=request,
                        action=AuditLog.Action.CREATE,
                        resource_type=AuditLog.ResourceType.CUSTODY,
                        resource_id=record.pk,
                        details={
                            'evidence_id': ev.pk,
                            'new_state': new_state,
                            'cascade': True,
                        },
                    )
        except DjangoValidationError as exc:
            # Identifica a evidência que falhou — útil para o frontend
            # mostrar mensagem específica (ex: "filho já está em estado
            # terminal e não pode regredir").
            failed_ev = evidences[len(created_records)] if len(created_records) < len(evidences) else None
            return Response(
                {
                    'evidence_id': failed_ev.pk if failed_ev else None,
                    'evidence_code': failed_ev.code if failed_ev else None,
                    'error': exc.message_dict if hasattr(exc, 'message_dict') else exc.messages,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ChainOfCustodySerializer(created_records, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Enriquecimento externo (IMEI / VIN)
# ---------------------------------------------------------------------------

class EvidenceIMEILookupView(APIView):
    """GET /api/evidences/lookup/imei/<imei>/ — consulta imeidb.xyz com cache.

    Fluxo:
    1. Valida IMEI (Luhn + 15 dígitos) → 400 se inválido.
    2. Consulta cache (``lookup:imei:<imei>``) — TTL 30 dias (ADR-0008).
    3. Cache miss → consulta serviço, guarda na cache, devolve.
    4. Falha da API externa → 503 com mensagem PT-PT (não degrada o fluxo:
       o agente continua a registar manualmente).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, imei: str):
        if not _user_can_lookup(request.user):
            return Response(
                {'detail': 'Perfil sem permissão para consultar APIs externas.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            validate_imei(imei)
        except DjangoValidationError as exc:
            return Response(
                {'detail': exc.messages[0] if exc.messages else 'IMEI inválido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f'lookup:imei:{imei}'
        cached = cache.get(cache_key)
        if cached is not None:
            # Hit: devolve o mesmo payload + metadados de cache.
            payload = dict(cached)
            return Response({
                **payload,
                'cached': True,
                'cached_at': payload.get('_cached_at'),
                'source': 'imeidb.xyz',
            })

        try:
            data = lookup_imei(imei)
        except ImeiLookupError as exc:
            # 503 — cliente sabe que é temporário e pode preencher manual.
            return Response(
                {'detail': str(exc), 'cached': False},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Schema drift: se a normalização não encontrou brand+model, a API
        # upstream provavelmente renomeou chaves. Não cacheamos respostas
        # parciais (evita envenenar cache 30d) e devolvemos 503 para o
        # agente preencher manualmente. Log WARNING com as chaves cruas
        # para ops investigarem.
        if not data.get('normalised_complete'):
            raw_keys = list(data.get('raw', {}).keys())
            log.warning(
                'imeidb schema drift imei=%s raw_keys=%s', imei, raw_keys
            )
            return Response(
                {
                    'detail': (
                        'Resposta parcial de imeidb.xyz (schema inesperado). '
                        'Preenche manualmente.'
                    ),
                    'cached': False,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Anexa carimbo temporal e guarda na cache (30 dias).
        data['_cached_at'] = timezone.now().isoformat()
        cache.set(cache_key, data, _LOOKUP_CACHE_TTL_SECONDS)

        return Response({
            **data,
            'cached': False,
            'source': 'imeidb.xyz',
        })


class EvidenceVINLookupView(APIView):
    """GET /api/evidences/lookup/vin/<vin>/ — URL externa para vindecoder.eu.

    Sem scraping (ver ADR-0010). Resposta é imediata: apenas constrói o URL
    que o frontend abrirá numa nova aba para o agente confirmar visualmente.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, vin: str):
        if not _user_can_lookup(request.user):
            return Response(
                {'detail': 'Perfil sem permissão para consultar APIs externas.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            validate_vin(vin)
        except DjangoValidationError as exc:
            return Response(
                {'detail': exc.messages[0] if exc.messages else 'VIN inválido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        normalised_vin = vin.strip().upper()
        url = build_vindecoder_url(normalised_vin)
        return Response({
            'vin': normalised_vin,
            'url': url,
            'source': 'vindecoder.eu',
            'note': (
                'Abre o URL numa nova aba e confirma os dados manualmente.'
            ),
        })


# ---------------------------------------------------------------------------
# Stats (dashboard) — endpoint agregado para evitar round-trips do frontend
# ---------------------------------------------------------------------------

class StatsView(APIView):
    """
    GET /api/stats/ — devolve contagens agregadas para o dashboard.

    Ao expor um único endpoint evitamos N round-trips (ocorrências, evidências,
    dispositivos, cadeia de custódia) e beneficiamos de uma única transacção
    coerente. AGENT vê apenas os seus; staff/EXPERT vêem totais globais.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        occ_qs = Occurrence.objects.all()
        ev_qs = Evidence.objects.all()
        dev_qs = DigitalDevice.objects.all()
        coc_qs = ChainOfCustody.objects.all()

        if not user.is_staff and getattr(user, 'profile', None) == 'AGENT':
            occ_qs = occ_qs.filter(agent=user)
            ev_qs = ev_qs.filter(occurrence__agent=user)
            dev_qs = dev_qs.filter(evidence__occurrence__agent=user)
            coc_qs = coc_qs.filter(evidence__occurrence__agent=user)

        evidence_by_type = dict(
            ev_qs.values_list('type').annotate(n=Count('id')).values_list('type', 'n')
        )
        custody_by_state = dict(
            coc_qs.values_list('new_state').annotate(n=Count('id')).values_list('new_state', 'n')
        )

        return Response({
            'occurrences': occ_qs.count(),
            'evidences': ev_qs.count(),
            'devices': dev_qs.count(),
            'custody_records': coc_qs.count(),
            'evidence_by_type': evidence_by_type,
            'custody_by_state': custody_by_state,
        })


class DashboardStatsView(APIView):
    """
    GET /api/stats/dashboard/ — payload estável consumido pelo dashboard (Wave 2d).

    Schema público (contrato com o frontend):
        {
            "total_occurrences": int,
            "open_occurrences": int,
            "total_evidences": int,
            "evidences_by_type": {"MOBILE_DEVICE": int, ...},
            "custodies_in_transit": int,
            "evidences_in_analysis": int,    # itens cujo último estado é EM_PERICIA
        }

    Ownership: AGENT vê apenas o seu scope; EXPERT / staff vêem totais.
    Uma ocorrência é considerada "aberta" enquanto nenhuma das suas
    evidências atinge um estado terminal de custódia (DEVOLVIDA/DESTRUIDA).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        occ_qs = Occurrence.objects.all()
        ev_qs = Evidence.objects.all()
        coc_qs = ChainOfCustody.objects.all()

        if not user.is_staff and getattr(user, 'profile', None) == 'AGENT':
            occ_qs = occ_qs.filter(agent=user)
            ev_qs = ev_qs.filter(occurrence__agent=user)
            coc_qs = coc_qs.filter(evidence__occurrence__agent=user)

        total_occurrences = occ_qs.count()
        total_evidences = ev_qs.count()

        # "Open": ocorrências cujas evidências ainda não têm registo em
        # estado terminal (DEVOLVIDA / DESTRUIDA). Simplificamos contando
        # as ocorrências que NÃO têm evidências nesses estados — evita
        # joins caros e é coerente com a UX do dashboard.
        terminal_states = [
            ChainOfCustody.CustodyState.DEVOLVIDA,
            ChainOfCustody.CustodyState.DESTRUIDA,
        ]
        closed_occurrence_ids = (
            coc_qs.filter(new_state__in=terminal_states)
            .values_list('evidence__occurrence_id', flat=True)
            .distinct()
        )
        open_occurrences = occ_qs.exclude(id__in=list(closed_occurrence_ids)).count()

        evidences_by_type = dict(
            ev_qs.values_list('type')
            .annotate(n=Count('id'))
            .values_list('type', 'n')
        )

        # Para cada evidência, identificar o ÚLTIMO estado de custódia.
        # Counts de "Em trânsito" e "Em perícia" devem reflectir o estado
        # actual, não o histórico (caso contrário um item que esteve em
        # trânsito e agora está em perícia seria contado em ambos).
        #
        # Invariante: estado actual = registo com max(sequence) por evidence_id.
        # Esta lógica foi auditada (2026-05-02) e está correcta — não muda para
        # subquery SQL porque o índice composto coc_ev_seq_idx torna a iteração
        # Python eficaz para o volume típico de operação. Refactor opcional
        # noutra fase usando Evidence.objects.with_current_state().
        latest_states = list(coc_qs.values('evidence_id', 'new_state', 'sequence'))
        latest_by_ev = {}
        for r in latest_states:
            cur = latest_by_ev.get(r['evidence_id'])
            if cur is None or r['sequence'] > cur['sequence']:
                latest_by_ev[r['evidence_id']] = r

        custodies_in_transit = sum(
            1 for r in latest_by_ev.values()
            if r['new_state'] == ChainOfCustody.CustodyState.EM_TRANSPORTE
        )
        evidences_in_analysis = sum(
            1 for r in latest_by_ev.values()
            if r['new_state'] == ChainOfCustody.CustodyState.EM_PERICIA
        )

        return Response({
            'total_occurrences': total_occurrences,
            'open_occurrences': open_occurrences,
            'total_evidences': total_evidences,
            'evidences_by_type': evidences_by_type,
            'custodies_in_transit': custodies_in_transit,
            'evidences_in_analysis': evidences_in_analysis,
        })


# ---------------------------------------------------------------------------
# Media servida com auditoria — fotos de evidência (substitui static() em prod)
# ---------------------------------------------------------------------------

class MediaServeView(APIView):
    """GET /media/<path> — serve fotos de evidência com auth + auditoria.

    Em produção, Gunicorn (sem nginx à frente) não serve ``/media/`` por
    defeito, e mesmo que servisse, fotos de evidência têm de exigir
    autenticação e ownership da ocorrência (ISO/IEC 27037 — controlo de
    acesso a prova). Esta view substitui o ``static(MEDIA_URL, ...)`` que
    apenas existia em ``DEBUG``.

    Garantias:
    - Path traversal bloqueado via ``Path.resolve().is_relative_to``.
    - Ownership: o utilizador tem de poder aceder à ocorrência cujo
      ``number`` aparece no path (``evidencias/<number>/<file>``).
    - Auditoria: cada acesso gera ``AuditLog(action=VIEW,
      resource_type=EVIDENCE)`` com ``details.media_path``.
    - Cache HTTP privado (1h) — fotos não mudam após criação (Evidence
      é imutável).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, path):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        try:
            target = (media_root / path).resolve(strict=True)
        except (FileNotFoundError, RuntimeError):
            raise Http404('Ficheiro não encontrado.')
        # Path traversal: garante que o ficheiro está dentro de MEDIA_ROOT.
        try:
            target.relative_to(media_root)
        except ValueError:
            raise Http404('Caminho inválido.')
        if not target.is_file():
            raise Http404('Ficheiro não encontrado.')

        # Ownership: extrai occurrence number do path
        # (evidencias/<number>/<uuid>_<filename>).
        parts = Path(path).parts
        if len(parts) >= 2 and parts[0] == 'evidencias':
            occurrence_number = parts[1]
            occurrence = Occurrence.objects.filter(number=occurrence_number).first()
            if occurrence is None:
                raise Http404('Ocorrência não encontrada.')
            if not _user_can_access_occurrence(request.user, occurrence):
                return Response(
                    {'detail': 'Sem permissão para aceder a esta foto.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            related_evidence_id = (
                Evidence.objects.filter(occurrence=occurrence, photo=path)
                .values_list('id', flat=True).first()
            )
            log_access(
                request=request,
                action=AuditLog.Action.VIEW,
                resource_type=AuditLog.ResourceType.EVIDENCE,
                resource_id=related_evidence_id or occurrence.pk,
                details={'media_path': path},
            )
        # Caminhos fora de evidencias/ (ex: assets futuros) são bloqueados
        # por defeito — abrir explicitamente quando houver caso de uso.
        else:
            return Response(
                {'detail': 'Acesso a este caminho não autorizado.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        content_type, _ = mimetypes.guess_type(str(target))
        response = FileResponse(
            open(target, 'rb'),
            content_type=content_type or 'application/octet-stream',
        )
        response['Content-Disposition'] = f'inline; filename="{target.name}"'
        # Evidence é imutável: cache 1h é seguro e reduz GETs repetidos.
        response['Cache-Control'] = 'private, max-age=3600'
        return response


# ---------------------------------------------------------------------------
# Healthcheck — liveness simples + prova que a DB responde
# ---------------------------------------------------------------------------

@require_safe
def healthcheck(request):
    """GET /api/health/ — 200 se a DB responde, 503 caso contrário.

    Alinha com a convenção do Fly.io / Kubernetes (``/healthz`` equivalente).
    Não exige autenticação para permitir probes externos simples.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ok'})
    except Exception:  # noqa: BLE001 — devolvemos 503 em qualquer erro de DB
        return JsonResponse({'status': 'degraded'}, status=503)
