"""
ForensiQ — Serializers para a API REST.

Cada entidade do modelo de dados tem um serializer dedicado.
Campos sensíveis (hashes, timestamps automáticos) são read-only.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import (
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    """Serializer público de utilizador (sem PII sensível)."""

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name',
            'profile', 'badge_number',
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

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
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

    O campo integrity_hash é calculado automaticamente pelo modelo
    e nunca pode ser definido pelo cliente.
    Evidências são imutáveis após criação (ISO/IEC 27037).
    """

    agent_name = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return obj.agent.get_full_name() or obj.agent.username

    class Meta:
        model = Evidence
        fields = [
            'id', 'occurrence', 'type', 'description',
            'photo', 'gps_lat', 'gps_lon',
            'timestamp_seizure', 'serial_number',
            'agent', 'agent_name', 'integrity_hash',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'agent', 'timestamp_seizure', 'integrity_hash', 'created_at', 'updated_at',
        ]


# ---------------------------------------------------------------------------
# DigitalDevice
# ---------------------------------------------------------------------------

class DigitalDeviceSerializer(serializers.ModelSerializer):
    """Serializer para dispositivos digitais."""

    class Meta:
        model = DigitalDevice
        fields = [
            'id', 'evidence', 'type', 'brand', 'model',
            'condition', 'imei', 'serial_number', 'notes',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ---------------------------------------------------------------------------
# ChainOfCustody
# ---------------------------------------------------------------------------

class ChainOfCustodySerializer(serializers.ModelSerializer):
    """
    Serializer para registos de cadeia de custódia.

    Append-only: apenas criação é permitida.
    O record_hash é calculado automaticamente pelo modelo.
    O previous_state e timestamp são determinados pelo servidor — nunca pelo cliente.
    """

    agent_name = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return obj.agent.get_full_name() or obj.agent.username

    class Meta:
        model = ChainOfCustody
        fields = [
            'id', 'evidence', 'previous_state', 'new_state',
            'agent', 'agent_name', 'timestamp', 'observations',
            'record_hash',
        ]
        read_only_fields = ['id', 'agent', 'previous_state', 'timestamp', 'record_hash']
