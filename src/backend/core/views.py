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
from django.http import HttpResponse
from rest_framework import serializers as drf_serializers  # Para converter ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from .pdf_export import generate_evidence_pdf

from .models import (
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
        """Retorna o perfil do utilizador autenticado."""
        serializer = self.get_serializer(request.user)
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

    def perform_create(self, serializer):
        serializer.save(agent=self.request.user)


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

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_staff and hasattr(user, 'profile') and user.profile == 'AGENT':
            qs = qs.filter(occurrence__agent=user)
        occurrence_id = self.request.query_params.get('occurrence')
        if occurrence_id:
            qs = qs.filter(occurrence_id=occurrence_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(agent=self.request.user)

    @action(detail=True, methods=['get'], url_path='pdf')
    def export_pdf(self, request, pk=None):
        """
        Gera e devolve o relatório forense da evidência em formato PDF.

        GET /api/evidences/<id>/pdf/

        Conformidade: ISO/IEC 27037 — inclui hash SHA-256, timestamp UTC,
        cadeia de custódia completa e declaração de integridade.
        """
        evidence = self.get_object()  # 404 automático se não existir
        # Pré-carregar relações para evitar N+1 queries
        evidence.occurrence  # noqa: B018 — força o load da FK
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
            serializer.save(agent=self.request.user)
        except DjangoValidationError as exc:
            # Converter ValidationError do Django para DRF (retorna 400)
            raise drf_serializers.ValidationError(exc.message_dict)

    @action(detail=False, methods=['get'], url_path='evidence/(?P<evidence_id>[0-9]+)/timeline')
    def timeline(self, request, evidence_id=None):
        """Retorna a timeline completa de custódia para uma evidência."""
        records = self.queryset.filter(evidence_id=evidence_id).order_by('timestamp')
        serializer = self.get_serializer(records, many=True)
        return Response(serializer.data)
