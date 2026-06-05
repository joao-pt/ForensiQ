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
- /api/custody/            — cadeia de custódia (AGENT/EXPERT criam, todos consultam)
- /api/stats/              — dashboard agregado
- /api/stats/dashboard/    — payload estável consumido pelo dashboard (Wave 2d)
- /api/health/             — healthcheck (liveness + DB)
- /api/reverse-geocode/    — geocodificação inversa (proxy Nominatim, GDPR)
"""

import logging
import math
import mimetypes
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import (
    filters,
    generics,
    serializers as drf_serializers,  # Para converter ValidationError
    status,
    viewsets,
)
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import access
from .audit import log_access
from .filters import CustodyFilter, EvidenceFilter, OccurrenceFilter
from .models import (
    LEGAL_STATES,
    TERMINAL_EVENTS,
    AuditLog,
    ChainOfCustody,
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    Evidence,
    Occurrence,
    PoliticaCriminalPrioridade,
    PrioridadeCrimeTipo,
    derive_legal_state,
)
from .pdf_export import generate_evidence_pdf, generate_occurrence_pdf
from .permissions import CanAccessCustodyApi, IsAgent, IsAgentOrExpert, IsOwnerOrReadOnly
from .serializers import (
    ActivityFeedSerializer,
    CascadeCustodyRequestSerializer,
    ChainOfCustodySerializer,
    CrimeCategoriaSerializer,
    CrimeSubcategoriaSerializer,
    CrimeTipoSimpleSerializer,
    EvidenceSerializer,
    OccurrenceSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserSerializer,
)
from .services.imei_lookup import LookupError as ImeiLookupError, lookup_imei, mask_imei
from .services.vin_lookup import build_vindecoder_url
from .throttles import HealthcheckRateThrottle
from .validators import validate_imei, validate_vin

User = get_user_model()

log = logging.getLogger(__name__)

# TTL de cache para lookups externos (30 dias — ADR-0008). Mantém alinhado
# com ``CACHES['default']['TIMEOUT']`` mas declarado localmente para o
# endpoint ser explícito sobre a política forense (imutabilidade do IMEI).
_LOOKUP_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30


def _user_can_access_occurrence(user, occurrence) -> bool:
    """Acesso à OCORRÊNCIA (need-to-know — ADR-0017; fonte única em core.access)."""
    return access.can_access_occurrence(user, occurrence)


def _user_can_lookup(user) -> bool:
    """Só FIRST_RESPONDER / FORENSIC_EXPERT (ou staff) consultam APIs externas."""
    if user is None or not user.is_authenticated:
        return False
    if getattr(user, 'is_staff', False):
        return True
    return getattr(user, 'profile', None) in ('FIRST_RESPONDER', 'FORENSIC_EXPERT')


def _evidence_ids_in_legal_state(custody_qs, state):
    """IDs das evidências cujo estado legal DERIVADO (ADR-0015) é ``state``.

    O estado legal não é coluna — calcula-se com ``derive_legal_state`` sobre
    a sequência de eventos de cada evidência. ``custody_qs`` delimita o
    universo (ownership já aplicado pelo chamador).
    """
    eventos_por_evidencia = {}
    for rec in custody_qs.order_by('evidence_id', 'sequence'):
        eventos_por_evidencia.setdefault(rec.evidence_id, []).append(rec)
    return [
        ev_id
        for ev_id, eventos in eventos_por_evidencia.items()
        if derive_legal_state(eventos) == state
    ]


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

    queryset = Occurrence.objects.select_related('agent', 'crime_type').all()
    serializer_class = OccurrenceSerializer
    permission_classes = [IsAuthenticated, IsAgent, IsOwnerOrReadOnly]
    # POST-only (ADR-0014): a Occurrence é imutável na BD (triggers 0013); expor
    # PUT/PATCH/DELETE oferecia um caminho de escrita que a BD recusa. GET para
    # consulta + acções @action (pdf). Sem update/destroy.
    http_method_names = ['get', 'post', 'head', 'options']
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = OccurrenceFilter
    # Campos pesquisáveis via ?search= — NUIPC/número, descrição livre,
    # morada e código gerado (OCC-YYYY-NNNNN). Resolve queixa de filtros
    # inoperantes (revisão UX 2026-05-02).
    search_fields = ['number', 'code', 'description', 'address']
    ordering_fields = ['date_time', 'created_at', 'number']
    ordering = ['-date_time']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        qs = access.scope_occurrences(user, base_qs=qs)
        # Filtro opcional por ESTADO LEGAL DERIVADO (ADR-0015) das evidências
        # da ocorrência. O estado não é coluna — deriva-se da sequência de
        # eventos via derive_legal_state, mantendo a definição coerente com os
        # outros endpoints e o dashboard.
        state = self.request.query_params.get('state')
        if state:
            if state not in LEGAL_STATES:
                raise drf_serializers.ValidationError(
                    {
                        'state': (
                            f'Estado inválido. Valores aceites: '
                            f'{", ".join(sorted(LEGAL_STATES))}.'
                        )
                    }
                )
            custody_qs = access.scope_custody(user)
            ev_ids = _evidence_ids_in_legal_state(custody_qs, state)
            occ_ids = (
                Evidence.objects.filter(id__in=ev_ids)
                .values_list('occurrence_id', flat=True)
                .distinct()
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
        # Audit 2026-05-18 §3 N12 — prefetch alinhado com o que
        # `pdf_export.generate_occurrence_pdf` itera: para cada
        # evidência: custody_chain (ordenada por -sequence para
        # `_current_custody_state` apanhar o último); para cada
        # sub-componente: também o seu custody_chain.
        from django.db.models import Prefetch

        custody_qs = ChainOfCustody.objects.select_related('agent').order_by('-sequence')
        base_qs = self.get_queryset().filter(pk=pk)
        optimized_qs = base_qs.select_related('agent').prefetch_related(
            'evidences__agent',
            'evidences__parent_evidence',
            'evidences__sub_components',
            Prefetch('evidences__custody_chain', queryset=custody_qs),
            Prefetch('evidences__sub_components__custody_chain', queryset=custody_qs),
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
                # Chave `detail` — contrato de erro canónico (handler global).
                {'detail': f'Erro ao gerar PDF: {exc}'},
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
        Evidence.objects.select_related('occurrence', 'agent')
        .prefetch_related('sub_components')
        .all()
    )
    serializer_class = EvidenceSerializer
    permission_classes = [IsAuthenticated, IsAgent, IsOwnerOrReadOnly]
    http_method_names = ['get', 'post', 'head', 'options']  # sem PUT/PATCH/DELETE
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = EvidenceFilter
    # Pesquisa atravessa para a ocorrência (?search= no NUIPC funciona).
    search_fields = [
        'code',
        'description',
        'serial_number',
        'occurrence__number',
        'occurrence__code',
        'occurrence__description',
    ]
    ordering_fields = ['timestamp_seizure', 'created_at', 'code', 'type']
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
        qs = access.scope_evidences(user, base_qs=qs)
        occurrence_id = self.request.query_params.get('occurrence')
        if occurrence_id:
            qs = qs.filter(occurrence_id=occurrence_id)
        parent_id = self.request.query_params.get('parent')
        if parent_id:
            qs = qs.filter(parent_evidence_id=parent_id)
        state = self.request.query_params.get('state')
        if state:
            if state not in LEGAL_STATES:
                raise drf_serializers.ValidationError(
                    {
                        'state': (
                            f'Estado inválido. Valores aceites: '
                            f'{", ".join(sorted(LEGAL_STATES))}.'
                        )
                    }
                )
            # Estado legal derivado (ADR-0015) — não é coluna; computa-se sobre
            # a sequência de eventos. Universo de custódia segue o need-to-know.
            custody_qs = access.scope_custody(user)
            ev_ids = _evidence_ids_in_legal_state(custody_qs, state)
            qs = qs.filter(id__in=ev_ids)
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
        # Audit 2026-05-18 §3 N12 — prefetch alinhado com o que
        # `pdf_export.generate_evidence_pdf` itera: sub_components
        # (+ os seus custody_chain) e o próprio custody_chain ordenado.
        from django.db.models import Prefetch

        custody_qs = ChainOfCustody.objects.select_related('agent').order_by('-sequence')
        base_qs = self.get_queryset().filter(pk=pk)
        optimized_qs = base_qs.select_related(
            'occurrence__agent',
            'agent',
        ).prefetch_related(
            'sub_components',
            Prefetch('custody_chain', queryset=custody_qs),
            Prefetch('sub_components__custody_chain', queryset=custody_qs),
        )
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
                # Chave `detail` — contrato de erro canónico (handler global).
                {'detail': f'Erro ao gerar PDF: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        filename = f'ForensiQ_Evidencia_{evidence.pk:04d}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(pdf_bytes)
        return response


# ---------------------------------------------------------------------------
# ChainOfCustody
# ---------------------------------------------------------------------------


class ChainOfCustodyViewSet(viewsets.ModelViewSet):
    """
    API da cadeia de custódia.

    - Criação: qualquer perfil que o modelo de acesso autorize a escrever no item
      (custódio atual, membro da instituição que o detém, override do perito,
      despacho da autoridade do caso, ou staff) — a autorização é feita por
      ``access.can_append_custody`` em ``perform_create``/``cascade``. Perfis
      só-leitura (CHEFE_SERVICO/AUDITOR) nunca escrevem.
    - Consulta: qualquer utilizador autenticado (com âmbito need-to-know).
    - Edição/eliminação: BLOQUEADAS (append-only — 405 Method Not Allowed).
    - O campo 'agent' é preenchido automaticamente.
    - Filtragem por evidência: ?evidence=<id>
    """

    queryset = ChainOfCustody.objects.select_related('evidence', 'agent').all()
    serializer_class = ChainOfCustodySerializer
    # CanAccessCustodyApi (não IsAgentOrExpert): admite os perfis que o modelo de
    # acesso autoriza a escrever (inclui CASE_AUTHORITY e EVIDENCE_CUSTODIAN) e
    # delega a decisão item-level a access.can_append_custody em perform_create/
    # cascade. IsAgentOrExpert bloqueava indevidamente esses perfis.
    permission_classes = [IsAuthenticated, CanAccessCustodyApi]
    http_method_names = ['get', 'post', 'head', 'options']  # sem PUT/PATCH/DELETE
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = CustodyFilter
    search_fields = [
        'code',
        'observations',
        'evidence__code',
        'evidence__description',
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
        qs = access.scope_custody(user, base_qs=qs)
        evidence_id = self.request.query_params.get('evidence')
        if evidence_id:
            qs = qs.filter(evidence_id=evidence_id)
        return qs

    def perform_create(self, serializer):
        # Gate de ESCRITA (ADR-0017 §5): só quem detém o item (ou pode assumi-lo),
        # o perito (override) ou a autoridade do caso (atos de despacho) regista.
        evidence = serializer.validated_data.get('evidence')
        event_type = serializer.validated_data.get('event_type')
        if evidence is not None and not access.can_append_custody(
            self.request.user, evidence, event_type
        ):
            raise drf_serializers.ValidationError(
                {'detail': 'Sem permissão para registar eventos de custódia neste item (ADR-0017).'}
            )
        try:
            custody_record = serializer.save(agent=self.request.user)
            log_access(
                request=self.request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.CUSTODY,
                resource_id=custody_record.pk,
                details={
                    'evidence_id': custody_record.evidence_id,
                    'event_type': custody_record.event_type,
                    'custodian_type': custody_record.custodian_type,
                },
            )
        except DjangoValidationError as exc:
            # Converter ValidationError do Django para DRF (retorna 400)
            raise drf_serializers.ValidationError(exc.message_dict)

    @action(detail=False, methods=['get'], url_path='evidence/(?P<evidence_id>[0-9]+)/timeline')
    def timeline(self, request, evidence_id=None):
        """Retorna a timeline completa de custódia para uma evidência."""
        records = (
            ChainOfCustody.objects.select_related('agent', 'evidence__occurrence')
            .filter(evidence_id=evidence_id)
            .order_by('sequence')
        )
        serializer = self.get_serializer(records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='cascade')
    def cascade(self, request):
        """POST /api/custody/cascade/ — evento atómico em várias evidências.

        Permite ao utilizador registar o mesmo evento num item-pai e nos seus
        sub-componentes (ex: telemóvel + cartão SIM + cartão de memória) numa
        única acção, em vez de o fazer item a item. Caso de uso típico: o
        intake EXPERT-only (ADR-0012) emite ``event_type=TRANSFERENCIA_CUSTODIA`` para
        ``custodian_type=LAB_PUBLICO`` em lote.

        Garantias:
        - Atomicidade: ou todos os eventos são gravados, ou nenhum
          (envolto em ``transaction.atomic()``).
        - Cada ``ChainOfCustody.save()`` mantém o seu próprio
          ``select_for_update`` por evidência — não há contenção entre
          evidências distintas.
        - Ownership: o utilizador tem de poder ESCREVER em TODAS as evidências
          (access.can_append_custody por item — custódio atual / override do
          perito / despacho da autoridade do caso / staff). Caso contrário 403.
        - As guardas do ledger (ADR-0015) são validadas por cada
          ``ChainOfCustody.save()``; se uma evidência rejeitar o evento,
          todas revertem e o cliente recebe 400 com ``evidence_id`` e mensagem.
        - Auditoria: cria um ``AuditLog`` por cada registo criado.
        """
        payload = CascadeCustodyRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        evidence_ids = payload.validated_data['evidence_ids']
        event_type = payload.validated_data['event_type']
        custodian_type = payload.validated_data.get('custodian_type', '')
        observations = payload.validated_data.get('observations', '')
        location_name = payload.validated_data.get('location_name', '')
        storage_location = payload.validated_data.get('storage_location', '')
        gps_lat = payload.validated_data.get('gps_lat')
        gps_lng = payload.validated_data.get('gps_lng')
        gps_accuracy_m = payload.validated_data.get('gps_accuracy_m')

        evidences = list(
            Evidence.objects.select_related('occurrence', 'occurrence__agent').filter(
                id__in=evidence_ids
            )
        )
        if len(evidences) != len(set(evidence_ids)):
            return Response(
                {'detail': 'Uma ou mais evidências não existem.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Gate de ESCRITA item-level (ADR-0017 §5) — o MESMO que perform_create.
        # Antes usava _user_can_access_occurrence (acesso de LEITURA à ocorrência),
        # o que deixava o titular da ocorrência injetar QUALQUER evento (incl.
        # terminais) em itens detidos por outro custódio/laboratório. can_append_custody
        # exige deter o item / override de perito / despacho da autoridade do caso.
        for ev in evidences:
            if not access.can_append_custody(request.user, ev, event_type):
                return Response(
                    {
                        'detail': (
                            'Sem permissão para registar este evento na evidência '
                            f'{ev.code or ev.pk} (ADR-0017).'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        created_records = []
        try:
            with transaction.atomic():
                for ev in evidences:
                    record = ChainOfCustody(
                        evidence=ev,
                        event_type=event_type,
                        custodian_type=custodian_type,
                        location_name=location_name,
                        storage_location=storage_location,
                        gps_lat=gps_lat,
                        gps_lng=gps_lng,
                        gps_accuracy_m=gps_accuracy_m,
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
                            'event_type': event_type,
                            'custodian_type': custodian_type,
                            'location_name': location_name,
                            'cascade': True,
                        },
                    )
        except DjangoValidationError as exc:
            # Identifica a evidência que falhou — útil para o frontend
            # mostrar mensagem específica (ex: "filho já está em estado
            # terminal e não pode regredir").
            failed_ev = (
                evidences[len(created_records)] if len(created_records) < len(evidences) else None
            )
            return Response(
                {
                    'evidence_id': failed_ev.pk if failed_ev else None,
                    'evidence_code': failed_ev.code if failed_ev else None,
                    # Chave canónica `detail` — alinhada com o handler global
                    # (`core.exceptions.forensiq_exception_handler`). Os campos
                    # `evidence_id`/`evidence_code` são contexto adicional para
                    # o frontend identificar qual evidência rejeitou o evento.
                    'detail': exc.message_dict if hasattr(exc, 'message_dict') else exc.messages,
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

    Throttle: 5 req/min por utilizador (scope ``imei_lookup``) — mitiga
    exaustão do saldo pago em `imeidb.xyz` por agente isolado. Audit
    2026-05-18 §3 N8.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'imei_lookup'

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
            return Response(
                {
                    **payload,
                    'cached': True,
                    'cached_at': payload.get('_cached_at'),
                    'source': 'imeidb.xyz',
                }
            )

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
            log.warning('imeidb schema drift imei=%s raw_keys=%s', mask_imei(imei), raw_keys)
            return Response(
                {
                    'detail': (
                        'Resposta parcial de imeidb.xyz (schema inesperado). Preenche manualmente.'
                    ),
                    'cached': False,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Anexa carimbo temporal e guarda na cache (30 dias).
        data['_cached_at'] = timezone.now().isoformat()
        cache.set(cache_key, data, _LOOKUP_CACHE_TTL_SECONDS)

        return Response(
            {
                **data,
                'cached': False,
                'source': 'imeidb.xyz',
            }
        )


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
        return Response(
            {
                'vin': normalised_vin,
                'url': url,
                'source': 'vindecoder.eu',
                'note': ('Abre o URL numa nova aba e confirma os dados manualmente.'),
            }
        )


# ---------------------------------------------------------------------------
# Reverse Geocode — proxy server-side para Nominatim (GDPR)
# ---------------------------------------------------------------------------


class ReverseGeocodeView(APIView):
    """GET /api/reverse-geocode/?lat=XX&lon=YY — geocodificação inversa.

    Proxy server-side para o Nominatim (OpenStreetMap) de modo a que as
    coordenadas GPS nunca saiam para terceiros a partir do browser do agente
    (requisito GDPR — dados de localização de ocorrências policiais).

    Throttle: 10 req/min por utilizador (scope ``reverse_geocode``).
    """

    permission_classes = [IsAuthenticated, IsAgentOrExpert]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'reverse_geocode'

    _NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse'
    _USER_AGENT = 'ForensiQ/1.0 (forensiq.pt)'
    _TIMEOUT_SECONDS = 5

    def get(self, request):
        # --- validação dos parâmetros ---
        lat_raw = request.query_params.get('lat')
        lon_raw = request.query_params.get('lon')

        if not lat_raw or not lon_raw:
            return Response(
                {'detail': 'Parâmetros "lat" e "lon" são obrigatórios.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (ValueError, TypeError):
            return Response(
                {'detail': '"lat" e "lon" devem ser números válidos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (-90 <= lat <= 90):
            return Response(
                {'detail': '"lat" deve estar entre -90 e 90.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (-180 <= lon <= 180):
            return Response(
                {'detail': '"lon" deve estar entre -180 e 180.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- chamada ao Nominatim (server-side) ---
        try:
            resp = httpx.get(
                self._NOMINATIM_URL,
                params={'lat': lat, 'lon': lon, 'format': 'json'},
                headers={
                    'User-Agent': self._USER_AGENT,
                    'Accept-Language': 'pt',
                },
                timeout=self._TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            log.warning('Nominatim unreachable: %s', exc)
            return Response(
                {'detail': 'Serviço de geocodificação indisponível.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        data = resp.json()
        address = data.get('address', {})

        # Devolver apenas os campos que o frontend precisa para compor
        # a morada (road, house_number, city/town/village, country).
        return Response(
            {
                'display_name': data.get('display_name', ''),
                'address': {
                    'road': address.get('road', ''),
                    'house_number': address.get('house_number', ''),
                    'city': (
                        address.get('city') or address.get('town') or address.get('village') or ''
                    ),
                    'country': address.get('country', ''),
                },
            }
        )


# ---------------------------------------------------------------------------
# POIs próximos — proxy server-side para Overpass (ADR-0015)
# ---------------------------------------------------------------------------


class NearbyPOIsView(APIView):
    """GET /api/nearby-pois/?lat=&lon=&radius= — POIs OSM próximos.

    Proxy server-side para a Overpass API (OpenStreetMap), à imagem da
    :class:`ReverseGeocodeView`: as coordenadas GPS do agente nunca saem
    para terceiros a partir do browser (minimização RGPD). Como o proxy é
    server-side, a CSP ``connect-src`` NÃO precisa de autorizar Overpass.

    Devolve candidatos úteis para nomear o local de um evento de custódia
    (esquadra, tribunal, laboratório/hospital, bombeiros, banco, posto de
    combustível) — o agente selecciona um e o ``location_name`` fica gravado
    no ledger. Degradação graciosa: em indisponibilidade do Overpass devolve
    502 e o agente preenche o ``location_name`` manualmente.

    Throttle: scope partilhado ``reverse_geocode`` (10 req/min em produção).
    """

    permission_classes = [IsAuthenticated, IsAgentOrExpert]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'reverse_geocode'

    _OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
    _USER_AGENT = 'ForensiQ/1.0 (forensiq.pt)'
    _TIMEOUT_SECONDS = 5
    _DEFAULT_RADIUS_M = 500
    _MAX_RADIUS_M = 2000
    _MAX_RESULTS = 30

    # amenities OSM úteis para nomear nós da cadeia de custódia.
    _USEFUL_AMENITIES = {
        'police',
        'courthouse',
        'fire_station',
        'hospital',
        'fuel',
        'bank',
        'prison',
        'townhall',
    }

    def get(self, request):
        lat_raw = request.query_params.get('lat')
        lon_raw = request.query_params.get('lon')

        if not lat_raw or not lon_raw:
            return Response(
                {'detail': 'Parâmetros "lat" e "lon" são obrigatórios.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (ValueError, TypeError):
            return Response(
                {'detail': '"lat" e "lon" devem ser números válidos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (-90 <= lat <= 90):
            return Response(
                {'detail': '"lat" deve estar entre -90 e 90.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (-180 <= lon <= 180):
            return Response(
                {'detail': '"lon" deve estar entre -180 e 180.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        radius = self._DEFAULT_RADIUS_M
        radius_raw = request.query_params.get('radius')
        if radius_raw:
            try:
                radius = int(float(radius_raw))
            except (ValueError, TypeError):
                return Response(
                    {'detail': '"radius" deve ser um número válido (metros).'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            radius = max(1, min(radius, self._MAX_RADIUS_M))

        amenity_regex = '|'.join(sorted(self._USEFUL_AMENITIES))
        query = (
            f'[out:json][timeout:{self._TIMEOUT_SECONDS}];'
            f'('
            f'node["amenity"~"^({amenity_regex})$"](around:{radius},{lat},{lon});'
            f'way["amenity"~"^({amenity_regex})$"](around:{radius},{lat},{lon});'
            f');out center {self._MAX_RESULTS};'
        )

        try:
            resp = httpx.post(
                self._OVERPASS_URL,
                data={'data': query},
                headers={'User-Agent': self._USER_AGENT},
                timeout=self._TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            log.warning('Overpass unreachable: %s', exc)
            return Response(
                {'detail': 'Serviço de POIs indisponível.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            elements = resp.json().get('elements', [])
        except ValueError:
            log.warning('Overpass devolveu JSON inválido')
            return Response(
                {'detail': 'Serviço de POIs indisponível.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        pois = []
        for el in elements:
            tags = el.get('tags', {})
            amenity = tags.get('amenity')
            if amenity not in self._USEFUL_AMENITIES:
                continue
            # nodes têm lat/lon directos; ways trazem 'center'.
            poi_lat = el.get('lat', el.get('center', {}).get('lat'))
            poi_lon = el.get('lon', el.get('center', {}).get('lon'))
            if poi_lat is None or poi_lon is None:
                continue
            nome = tags.get('name') or tags.get('official_name') or amenity
            pois.append(
                {
                    'nome': nome,
                    'tipo': amenity,
                    'lat': poi_lat,
                    'lon': poi_lon,
                    'dist_m': round(_haversine_m(lat, lon, poi_lat, poi_lon)),
                }
            )

        pois.sort(key=lambda p: p['dist_m'])
        return Response(pois[: self._MAX_RESULTS])


def _haversine_m(lat1, lon1, lat2, lon2):
    """Distância em metros entre dois pontos (fórmula de Haversine)."""
    r = 6371000.0  # raio médio da Terra (m)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Taxonomia de crimes — seletor em cascata N1>N2>N3 (read-only)
# ---------------------------------------------------------------------------


class CrimeCategoryListView(generics.ListAPIView):
    """GET /api/crime-categories/ — categorias N1 da Tabela de Crimes Registados."""

    queryset = CrimeCategoria.objects.order_by('codigo')
    serializer_class = CrimeCategoriaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


class CrimeSubcategoryListView(generics.ListAPIView):
    """GET /api/crime-subcategories/?categoria=<id> — subcategorias N2."""

    serializer_class = CrimeSubcategoriaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = CrimeSubcategoria.objects.order_by('codigo')
        categoria = self.request.query_params.get('categoria')
        if categoria:
            qs = qs.filter(categoria_id=categoria)
        return qs


class CrimeTypeListView(generics.ListAPIView):
    """GET /api/crime-types/?subcategoria=<id> — tipos N3 (+ flag de prioridade).

    ``is_prioritaria`` deriva da versão activa da Política Criminal (eixo
    INVESTIGAÇÃO, Art. 5.º). O conjunto de ids prioritários é pré-calculado
    aqui e passado ao serializer (sem N+1). A derivação final continua a
    ocorrer em ``Occurrence._aplicar_prioridade`` no momento do POST.
    """

    serializer_class = CrimeTipoSimpleSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = CrimeTipo.objects.filter(is_active=True).order_by('codigo')
        subcategoria = self.request.query_params.get('subcategoria')
        if subcategoria:
            qs = qs.filter(subcategoria_id=subcategoria)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        vigente = PoliticaCriminalPrioridade.objects.vigente()
        prioritaria_ids = set()
        if vigente is not None:
            assoc = vigente.associacoes.filter(eixo=PrioridadeCrimeTipo.Eixo.INVESTIGACAO)
            subcategoria = self.request.query_params.get('subcategoria')
            if subcategoria:
                assoc = assoc.filter(crime_tipo__subcategoria_id=subcategoria)
            prioritaria_ids = set(assoc.values_list('crime_tipo_id', flat=True))
        context['prioritaria_ids'] = prioritaria_ids
        return context


# ---------------------------------------------------------------------------
# Stats (dashboard) — endpoint agregado para evitar round-trips do frontend
# ---------------------------------------------------------------------------


class StatsView(APIView):
    """
    GET /api/stats/ — contagens agregadas (LEGACY v1, fronteira congelada).

    **v2 (T11):** o dashboard novo é alimentado por ``DashboardStatsView``
    (`/api/stats/dashboard/`, com deltas/séries/estado derivado). Este endpoint
    e a `/stats/` page (`stats.js`, com breakdown por taxonomia antiga) ficam
    **congelados** — não construir features novas em cima; serão removidos ou
    reescritos na reinvenção do frontend (Fase 3). Mantido por ora porque a
    página `/stats/` v1 ainda o consome.

    Ao expor um único endpoint evitamos N round-trips (ocorrências, evidências,
    cadeia de custódia) e beneficiamos de uma única transacção coerente.
    AGENT vê apenas os seus; staff/EXPERT vêem totais globais.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        occ_qs = access.scope_occurrences(user)
        ev_qs = access.scope_evidences(user)
        coc_qs = access.scope_custody(user)

        evidence_by_type = dict(
            ev_qs.values_list('type').annotate(n=Count('id')).values_list('type', 'n')
        )
        # Agregação por ESTADO LEGAL DERIVADO (ADR-0015), não por event_type cru:
        # cada evidência conta uma vez, no seu estado derivado actual.
        custody_by_state = {state: 0 for state in sorted(LEGAL_STATES)}
        eventos_por_evidencia = {}
        for rec in coc_qs.order_by('evidence_id', 'sequence'):
            eventos_por_evidencia.setdefault(rec.evidence_id, []).append(rec)
        for eventos in eventos_por_evidencia.values():
            custody_by_state[derive_legal_state(eventos)] += 1

        return Response(
            {
                'occurrences': occ_qs.count(),
                'evidences': ev_qs.count(),
                'custody_records': coc_qs.count(),
                'evidence_by_type': evidence_by_type,
                'custody_by_state': custody_by_state,
            }
        )


class DashboardStatsView(APIView):
    """
    GET /api/stats/dashboard/ — payload estável consumido pelo dashboard (Wave 2d).

    Schema público (contrato com o frontend):
        {
            "total_occurrences": int,
            "open_occurrences": int,
            "total_evidences": int,
            "evidences_by_type": {"MOBILE_DEVICE": int, ...},
            "custodies_in_transit": int,     # itens cujo estado derivado é "encaminhada"
            "evidences_in_analysis": int,    # itens cujo estado derivado é "em_pericia"
        }

    Ownership: AGENT vê apenas o seu scope; EXPERT / staff vêem totais.
    Uma ocorrência é considerada "aberta" enquanto nenhuma das suas
    evidências atinge um evento terminal de custódia (RESTITUICAO/DESTRUICAO).
    Os agregados de estado usam o ESTADO LEGAL DERIVADO (ADR-0015), não o
    event_type cru.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        occ_qs = access.scope_occurrences(user)
        ev_qs = access.scope_evidences(user)
        coc_qs = access.scope_custody(user)

        total_occurrences = occ_qs.count()
        total_evidences = ev_qs.count()

        # "Open": ocorrências cujas evidências ainda não têm um evento
        # terminal (RESTITUICAO / DESTRUICAO). Contamos as ocorrências que
        # NÃO têm evidências com esses eventos — evita joins caros e é
        # coerente com a UX do dashboard.
        terminal_events = list(TERMINAL_EVENTS)
        closed_occurrence_ids = (
            coc_qs.filter(event_type__in=terminal_events)
            .values_list('evidence__occurrence_id', flat=True)
            .distinct()
        )
        open_occurrences = occ_qs.exclude(id__in=list(closed_occurrence_ids)).count()

        evidences_by_type = dict(
            ev_qs.values_list('type').annotate(n=Count('id')).values_list('type', 'n')
        )

        # Estado legal DERIVADO (ADR-0015) por evidência: a derivação é uma
        # função pura da sequência completa de eventos. Agrupamos os eventos
        # por evidência (ordenados por sequence, suportado pelo índice
        # coc_ev_seq_idx) e derivamos o estado uma vez por item.
        eventos_por_evidencia = {}
        for rec in coc_qs.order_by('evidence_id', 'sequence'):
            eventos_por_evidencia.setdefault(rec.evidence_id, []).append(rec)

        derived_by_ev = {
            ev_id: derive_legal_state(eventos)
            for ev_id, eventos in eventos_por_evidencia.items()
        }

        custodies_in_transit = sum(1 for s in derived_by_ev.values() if s == 'encaminhada')
        evidences_in_analysis = sum(1 for s in derived_by_ev.values() if s == 'em_pericia')

        # Distribuição completa por estado legal derivado. Usado pelo
        # dashboard para a visualização "Cadeia de custódia" (river bar +
        # cards). Itens sem qualquer registo ainda ficam fora — não foram
        # apreendidos formalmente, é o caso de seed parcial / wizard a meio.
        evidences_by_current_state = {state: 0 for state in sorted(LEGAL_STATES)}
        for s in derived_by_ev.values():
            evidences_by_current_state[s] += 1
        # Itens sem nenhum registo de custódia (raros — wizard incompleto).
        evidences_without_custody = total_evidences - len(derived_by_ev)

        return Response(
            {
                'total_occurrences': total_occurrences,
                'open_occurrences': open_occurrences,
                'total_evidences': total_evidences,
                'evidences_by_type': evidences_by_type,
                'evidences_by_current_state': evidences_by_current_state,
                'evidences_without_custody': evidences_without_custody,
                'custodies_in_transit': custodies_in_transit,
                'evidences_in_analysis': evidences_in_analysis,
                # --- Enriquecimento T07 (aditivo) ---
                'deltas_24h': self._deltas_24h(occ_qs, ev_qs, coc_qs),
                'total_active': self._total_active(coc_qs, total_evidences),
                'occurrences_series_7d': self._occurrences_series_7d(occ_qs),
            }
        )

    # ------------------------------------------------------------------
    # Helpers do enriquecimento T07
    # ------------------------------------------------------------------

    @staticmethod
    def _deltas_24h(occ_qs, ev_qs, coc_qs):
        """Variação das últimas 24h vs as 24h anteriores (T07).

        Compara a janela [agora-24h, agora] (``last_24h``) com a janela
        [agora-48h, agora-24h] (``prev_24h``) para ocorrências, evidências e
        eventos de custódia. ``delta`` = ``last_24h - prev_24h`` (positivo =
        aceleração da actividade). Ocorrências e evidências contam por
        ``created_at``; os eventos de custódia por ``timestamp`` (o ledger não
        tem ``created_at``).
        """
        now = timezone.now()
        h24 = now - timedelta(hours=24)
        h48 = now - timedelta(hours=48)

        def janelas(qs, campo):
            last_n = qs.filter(**{f'{campo}__gte': h24, f'{campo}__lte': now}).count()
            prev_n = qs.filter(**{f'{campo}__gte': h48, f'{campo}__lt': h24}).count()
            return {'last_24h': last_n, 'prev_24h': prev_n, 'delta': last_n - prev_n}

        return {
            'occurrences': janelas(occ_qs, 'created_at'),
            'evidences': janelas(ev_qs, 'created_at'),
            'custody_events': janelas(coc_qs, 'timestamp'),
        }

    @staticmethod
    def _total_active(coc_qs, total_evidences):
        """Nº de evidências cujo estado legal derivado NÃO é terminal (T07).

        Uma evidência está "activa" enquanto o seu último evento de custódia
        não é terminal (RESTITUICAO/DESTRUICAO — ``TERMINAL_EVENTS``).
        Evidências sem qualquer registo de custódia contam como activas
        (ainda não saíram do circuito). Deriva o estado por evidência a partir
        da sequência de eventos, coerente com o resto do dashboard.
        """
        eventos_por_evidencia = {}
        for rec in coc_qs.order_by('evidence_id', 'sequence'):
            eventos_por_evidencia.setdefault(rec.evidence_id, []).append(rec)
        terminais = {
            ev_id
            for ev_id, eventos in eventos_por_evidencia.items()
            if eventos[-1].event_type in TERMINAL_EVENTS
        }
        # Activas = todas as evidências menos as que estão em estado terminal.
        # Itens sem custódia não entram em ``terminais`` → contam como activas.
        return total_evidences - len(terminais)

    @staticmethod
    def _occurrences_series_7d(occ_qs):
        """Série diária de ocorrências criadas nos últimos 7 dias (T07).

        Devolve 7 objectos ``{"date": "YYYY-MM-DD", "count": N}`` do mais
        antigo (há 6 dias) ao dia de hoje, inclusive dias com zero. A agregação
        usa o dia LOCAL (``timezone.localdate``) para alinhar com o fuso do
        projecto — uma ocorrência criada às 23h conta no dia local correcto.
        """
        hoje = timezone.localdate()
        dias = [hoje - timedelta(days=offset) for offset in range(6, -1, -1)]
        inicio = dias[0]
        # Janela [inicio_local_00h, agora]; agrega por dia local via
        # TruncDate, que respeita o TIME_ZONE activo do projecto.
        inicio_dt = timezone.make_aware(datetime.combine(inicio, dt_time.min))
        contagens = dict(
            occ_qs.filter(created_at__gte=inicio_dt)
            .annotate(dia=TruncDate('created_at'))
            .values('dia')
            .annotate(n=Count('id'))
            .values_list('dia', 'n')
        )
        return [{'date': dia.isoformat(), 'count': contagens.get(dia, 0)} for dia in dias]


# ---------------------------------------------------------------------------
# Activity Feed — feed read-only de actividade sobre o AuditLog (T06)
# ---------------------------------------------------------------------------


class ActivityFeedView(generics.ListAPIView):
    """GET /api/activity-feed/ — feed read-only de actividade (T06).

    Lista os eventos do ``AuditLog`` (append-only) por ``-timestamp``,
    paginado pela paginação default do projecto. Read-only: apenas GET é
    exposto (``ListAPIView``); POST/PUT/PATCH/DELETE devolvem 405.

    Âmbito (documentado, ADR-0017):
    - Leitura nacional (staff ou credencial NACIONAL) vê TODOS os eventos.
    - Qualquer outro perfil (FIRST_RESPONDER, FORENSIC_EXPERT NORMAL,
      CASE_AUTHORITY, EVIDENCE_CUSTODIAN…) vê APENAS os eventos que praticou
      (``user_id == request.user.id``). Como o ``AuditLog`` regista acessos a
      prova potencialmente sob segredo de justiça, não se expõe a actividade de
      terceiros a quem não tem leitura nacional.

    O sinal ``is_priority_alert`` (ADR-0014 §7) destaca a criação de
    ocorrências prioritárias. Para evitar N+1, os ids das ocorrências
    prioritárias REFERENCIADAS pela página corrente são resolvidos numa única
    query e passados ao serializer via contexto.
    """

    serializer_class = ActivityFeedSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = AuditLog.objects.select_related('user').order_by('-timestamp')
        user = self.request.user
        # Só leitura nacional (staff ou credencial NACIONAL) vê TODO o registo de
        # auditoria; qualquer outro perfil (FIRST_RESPONDER, FORENSIC_EXPERT NORMAL,
        # CASE_AUTHORITY, EVIDENCE_CUSTODIAN…) vê APENAS os eventos que praticou —
        # *need-to-know* (ADR-0017). Antes só o FIRST_RESPONDER era restringido, o
        # que vazava o registo global a todos os outros perfis não-nacionais.
        if not access.has_national_read(user):
            qs = qs.filter(user_id=user.id)
        return qs

    def get_serializer_context(self):
        """Pré-carrega os ids de ocorrências prioritárias da página (sem N+1).

        Resolve, numa só query, quais das ocorrências referenciadas pelos
        eventos CREATE/OCCURRENCE da página corrente têm
        ``priority=PRIORITARIA``. Ocorrências entretanto eliminadas não
        constam do resultado → ``is_priority_alert=False`` para elas.
        """
        context = super().get_serializer_context()
        page = getattr(self, '_paginated_object_list', None)
        occ_ids = [
            log.resource_id
            for log in (page or [])
            if log.action == AuditLog.Action.CREATE
            and log.resource_type == AuditLog.ResourceType.OCCURRENCE
        ]
        priority_ids = set()
        if occ_ids:
            priority_ids = set(
                Occurrence.objects.filter(
                    id__in=occ_ids,
                    priority=Occurrence.Priority.PRIORITARIA,
                ).values_list('id', flat=True)
            )
        context['priority_occurrence_ids'] = priority_ids
        return context

    def paginate_queryset(self, queryset):
        """Guarda a página materializada para o contexto resolver prioridades."""
        page = super().paginate_queryset(queryset)
        # Quando há paginação, ``page`` é a lista da página corrente; caso
        # contrário (paginação desligada) usamos o queryset inteiro.
        self._paginated_object_list = page if page is not None else list(queryset)
        return page


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

        # Ownership: extrai occurrence code do path
        # (evidencias/<code>/<uuid>_<filename>). O ``code`` é o
        # OCC-YYYY-NNNNN gerado pelo sistema (sem caracteres especiais);
        # NUIPCs reais contêm ``/`` que partia o path em segmentos extra
        # e fazia o lookup falhar (ex.: NUIPC.812/2026.LISBOA).
        parts = Path(path).parts
        if len(parts) >= 2 and parts[0] == 'evidencias':
            occurrence_ref = parts[1]
            # Compatibilidade com uploads antigos (anteriores ao fix):
            # tentar primeiro pelo ``code``, depois pelo ``number``.
            occurrence = (
                Occurrence.objects.filter(code=occurrence_ref).first()
                or Occurrence.objects.filter(number=occurrence_ref).first()
            )
            if occurrence is None:
                raise Http404('Ocorrência não encontrada.')
            if not _user_can_access_occurrence(request.user, occurrence):
                return Response(
                    {'detail': 'Sem permissão para aceder a esta foto.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            related_evidence_id = (
                Evidence.objects.filter(occurrence=occurrence, photo=path)
                .values_list('id', flat=True)
                .first()
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
        # FileResponse assume a posse do handle e fecha-o quando a resposta é
        # fechada; um `with` fecharia o ficheiro antes do streaming (SIM115 N/A).
        response = FileResponse(
            open(target, 'rb'),  # noqa: SIM115
            content_type=content_type or 'application/octet-stream',
        )
        response['Content-Disposition'] = f'inline; filename="{target.name}"'
        # Evidence é imutável: cache 1h é seguro e reduz GETs repetidos.
        response['Cache-Control'] = 'private, max-age=3600'
        return response


# ---------------------------------------------------------------------------
# Healthcheck — liveness simples + prova que a DB responde
# ---------------------------------------------------------------------------


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([HealthcheckRateThrottle])
def healthcheck(request):
    """GET /api/health/ — 200 se a DB responde, 503 caso contrário.

    Alinha com a convenção do Fly.io / Kubernetes (``/healthz`` equivalente).
    Não exige autenticação para permitir probes externos simples, mas aplica
    ``HealthcheckRateThrottle`` (por IP) para travar varredura/amplificação
    anónima da BD sem nunca travar probes legítimos.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return Response({'status': 'ok'})
    except Exception:  # noqa: BLE001 — devolvemos 503 em qualquer erro de DB
        return Response({'status': 'degraded'}, status=503)
