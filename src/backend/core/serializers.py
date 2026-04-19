"""
ForensiQ — Serializers para a API REST.

Cada entidade do modelo de dados tem um serializer dedicado.
Campos sensíveis (hashes, timestamps automáticos) são read-only.
Validações de ownership bloqueiam IDOR a nível de payload (Wave 2c).
"""

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
)
from .validators import validate_imei, validate_imsi, validate_vin

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers partilhados
# ---------------------------------------------------------------------------

def _user_can_access_occurrence(user, occurrence) -> bool:
    """Verifica se ``user`` pode operar sobre uma ``occurrence``.

    Política (ver ADR-0010 e permissions.py):
    - Staff / superuser: acesso total (admin).
    - EXPERT: acesso a todas as ocorrências (é a única forma de receber
      custódia no laboratório e escrever no dossier).
    - AGENT: apenas às ocorrências de que é responsável (``agent`` FK).
    - Outros perfis autenticados: sem acesso.
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


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    """Serializer público (listagem) — sem ``badge_number`` nem PII.

    Usado em selects de frontend (ex. dropdown de custódia). Não expõe
    email, telefone ou crachá — apenas identidade operacional mínima.
    """

    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        """Nome completo, com fallback para username."""
        return obj.get_full_name() or obj.username

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name',
            'first_name', 'last_name', 'profile',
        ]
        read_only_fields = ['id']


class UserDetailSerializer(serializers.ModelSerializer):
    """Serializer privado — apenas para o utilizador autenticado (/me/)."""

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'profile', 'badge_number', 'phone',
        ]
        read_only_fields = ['id', 'profile', 'badge_number']


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer para criação de utilizador (inclui password)."""

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password', 'first_name', 'last_name',
            'profile', 'badge_number', 'phone',
        ]
        read_only_fields = ['id']

    def validate_password(self, value):
        """Corre AUTH_PASSWORD_VALIDATORS do Django contra a palavra-passe."""
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        # Defesa em profundidade (CWE-521): repete validate_password contra
        # os AUTH_PASSWORD_VALIDATORS antes de gravar o hash, já com o user
        # construído (permite ao UserAttributeSimilarityValidator comparar
        # a senha com username/email/first_name).
        password_validation.validate_password(password, user=user)
        user.set_password(password)
        user.save()
        return user


# ---------------------------------------------------------------------------
# Occurrence
# ---------------------------------------------------------------------------

class OccurrenceSerializer(serializers.ModelSerializer):
    """Serializer para ocorrências policiais."""

    agent_name = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return obj.agent.get_full_name() or obj.agent.username

    class Meta:
        model = Occurrence
        fields = [
            'id', 'number', 'description', 'date_time',
            'gps_lat', 'gps_lon', 'address',
            'agent', 'agent_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'agent', 'created_at', 'updated_at']


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceSerializer(serializers.ModelSerializer):
    """
    Serializer para evidências.

    O campo ``integrity_hash`` é calculado automaticamente pelo modelo e
    nunca pode ser definido pelo cliente. Evidências são imutáveis após
    criação (ISO/IEC 27037).

    Campos específicos do tipo (IMEI, VIN, IMSI, MAC, ...) entram via
    ``type_specific_data``; os validadores de formato correm no serializer
    e no ``Model.clean()`` (defesa em profundidade).

    Os campos ``external_lookup_*`` são **read-only** — só o endpoint de
    lookup (a integrar via Wave 2d) pode materializar o snapshot no
    registo.
    """

    agent_name = serializers.SerializerMethodField()
    parent_evidence = serializers.PrimaryKeyRelatedField(
        queryset=Evidence.objects.all(),
        allow_null=True,
        required=False,
    )
    type_specific_data = serializers.JSONField(required=False)

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return obj.agent.get_full_name() or obj.agent.username

    class Meta:
        model = Evidence
        fields = [
            'id', 'occurrence', 'type', 'parent_evidence',
            'description', 'photo',
            'gps_lat', 'gps_lon',
            'timestamp_seizure', 'serial_number',
            'agent', 'agent_name', 'integrity_hash',
            'type_specific_data',
            'external_lookup_snapshot',
            'external_lookup_source',
            'external_lookup_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'agent', 'timestamp_seizure', 'integrity_hash',
            'external_lookup_snapshot',
            'external_lookup_source',
            'external_lookup_at',
            'created_at', 'updated_at',
        ]

    def validate_occurrence(self, occurrence):
        """AGENT só pode criar evidências em ocorrências próprias."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return occurrence
        if not _user_can_access_occurrence(request.user, occurrence):
            raise serializers.ValidationError(
                'Não pode criar evidências em ocorrências de outros agentes.'
            )
        return occurrence

    def validate(self, attrs):
        """Validação cruzada: tipo × type_specific_data × parent."""
        attrs = super().validate(attrs)
        tsd = attrs.get('type_specific_data')
        if tsd is None and self.instance is not None:
            tsd = self.instance.type_specific_data or {}
        tsd = tsd or {}
        if not isinstance(tsd, dict):
            raise serializers.ValidationError({
                'type_specific_data': 'Deve ser um objecto JSON (dicionário).'
            })

        etype = attrs.get('type') or (self.instance and self.instance.type)

        # --- Validadores por tipo (espelhados no Model.clean — defesa em
        #     profundidade). Qualquer alteração num lado deve reflectir-se no
        #     outro.
        errors = {}
        if etype == Evidence.EvidenceType.MOBILE_DEVICE:
            imei = tsd.get('imei')
            if imei:
                try:
                    validate_imei(imei)
                except DjangoValidationError as exc:
                    errors['type_specific_data'] = (
                        f'imei: {"; ".join(exc.messages)}'
                    )
        elif etype == Evidence.EvidenceType.SIM_CARD:
            imsi = tsd.get('imsi')
            if imsi:
                try:
                    validate_imsi(imsi)
                except DjangoValidationError as exc:
                    errors['type_specific_data'] = (
                        f'imsi: {"; ".join(exc.messages)}'
                    )
        elif etype == Evidence.EvidenceType.VEHICLE:
            vin = tsd.get('vin')
            if vin:
                try:
                    validate_vin(vin)
                except DjangoValidationError as exc:
                    errors['type_specific_data'] = (
                        f'vin: {"; ".join(exc.messages)}'
                    )
        if errors:
            raise serializers.ValidationError(errors)

        # --- Parent evidence: tem de partilhar ocorrência.
        parent = attrs.get('parent_evidence')
        if parent is not None:
            occ = attrs.get('occurrence') or (
                self.instance and self.instance.occurrence
            )
            occ_id = occ.id if occ is not None else None
            if parent.occurrence_id != occ_id:
                raise serializers.ValidationError({
                    'parent_evidence': (
                        'Sub-componente tem de pertencer à mesma ocorrência.'
                    )
                })

        return attrs


# ---------------------------------------------------------------------------
# DigitalDevice
# ---------------------------------------------------------------------------

class DigitalDeviceSerializer(serializers.ModelSerializer):
    """Serializer para dispositivos digitais.

    Valida ownership: a evidência referenciada tem de pertencer a uma
    ocorrência acessível ao utilizador (AGENT dono, EXPERT ou staff).
    Fecha o IDOR identificado na auditoria 2026-04-19.
    """

    class Meta:
        model = DigitalDevice
        fields = [
            'id', 'evidence', 'type', 'brand', 'model',
            'condition', 'imei', 'serial_number', 'notes',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_evidence(self, evidence):
        """Bloqueia IDOR — só ownership da ocorrência permite associar."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return evidence
        if not _user_can_access_occurrence(request.user, evidence.occurrence):
            raise serializers.ValidationError(
                'Não tem permissão para associar um dispositivo a esta evidência.'
            )
        return evidence


# ---------------------------------------------------------------------------
# ChainOfCustody
# ---------------------------------------------------------------------------

class ChainOfCustodySerializer(serializers.ModelSerializer):
    """
    Serializer para registos de cadeia de custódia.

    Append-only: apenas criação é permitida.
    O ``record_hash`` é calculado automaticamente pelo modelo.
    O ``previous_state`` e o ``timestamp`` são determinados pelo servidor —
    nunca pelo cliente.

    Valida ownership: só AGENT dono da ocorrência, EXPERT ou staff podem
    criar registos (fecha IDOR identificado na auditoria 2026-04-19).
    """

    agent_name = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return obj.agent.get_full_name() or obj.agent.username

    class Meta:
        model = ChainOfCustody
        fields = [
            'id', 'evidence', 'sequence', 'previous_state', 'new_state',
            'agent', 'agent_name', 'timestamp', 'observations',
            'record_hash',
        ]
        read_only_fields = [
            'id', 'agent', 'sequence', 'previous_state', 'timestamp', 'record_hash',
        ]

    def validate_evidence(self, evidence):
        """Só dono da ocorrência (AGENT), EXPERT ou staff registam custódia."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return evidence
        if not _user_can_access_occurrence(request.user, evidence.occurrence):
            raise serializers.ValidationError(
                'Não tem permissão para registar custódia nesta evidência.'
            )
        return evidence
