"""
ForensiQ — ViewSets para a API REST.

Cada entidade tem um ViewSet dedicado com permissões baseadas em perfil.
O campo 'agent' é preenchido automaticamente com o utilizador autenticado.

Endpoints:
- /api/users/           — gestão de utilizadores (admin apenas cria)
- /api/occurrences/     — ocorrências (AGENT cria, todos consultam)
- /api/evidences/       — evidências (AGENT cria, todos consultam)
- /api/devices/         — dispositivos digitais (AGENT cria, todos consultam)
- /api/custody/         — cadeia de custódia (AGENT/EXPERT criam, todos consultam)
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework import serializers as drf_serializers  # Para converter ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .pdf_export import generate_evidence_pdf
from .audit import log_access

from .models import (
    AuditLog,
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
)
from .permissions import IsAgent, IsAgentOrExpert, IsOwnerOrReadOnly
from .serializers import (
    ChainOfCustodySerializer,
    DigitalDeviceSerializer,
    EvidenceSerializer,
    OccurrenceSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserSerializer,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserViewSet(viewsets.ModelViewSet):
    """
    API de utilizadores.

    - Listagem e detalhe: qualquer utilizador autenticado.
    - Criação: apenas administradores.
    - me/ — retorna o perfil do utilizador autenticado.
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

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_staff:
            return qs
        if hasattr(user, 'profile') and user.profile == 'AGENT':
            return qs.filter(agent=user)
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

    queryset = Evidence.objects.select_related('occurrence', 'agent').all()
    serializer_class = EvidenceSerializer
    permission_classes = [IsAuthenticated, IsAgent, IsOwnerOrReadOnly]
    http_method_names = ['get', 'post', 'head', 'options']  # sem PUT/PATCH/DELETE

    def get_throttles(self):
        if self.action == 'create':
            self.throttle_scope = 'evidence_upload'
            return [ScopedRateThrottle()]
        if self.action == 'export_pdf':
            self.throttle_scope = 'pdf_export'
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_staff and hasattr(user, 'profile') and user.profile == 'AGENT':
            qs = qs.filter(occurrence__agent=user)
        occurrence_id = self.request.query_params.get('occurrence')
        if occurrence_id:
            qs = qs.filter(occurrence_id=occurrence_id)
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
        # get_object() aplica permissões e 404. Substituímos o queryset pela
        # versão optimizada (select_related + prefetch_related) para evitar
        # N+1 no corpo do PDF e na cadeia de custódia.
        self.queryset = (
            Evidence.objects
            .select_related('occurrence__agent', 'agent')
            .prefetch_related('custody_chain__agent')
        )
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
