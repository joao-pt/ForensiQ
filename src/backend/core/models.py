"""
ForensiQ — Modelos de dados core.

Entidades principais:
- User: utilizador com perfil AGENT (first responder) ou EXPERT (perito forense)
- Occurrence: ocorrência / cena de crime
- Evidence: evidência apreendida (com hash SHA-256 para integridade)
- DigitalDevice: dispositivo digital associado a uma evidência
- ChainOfCustody: registo imutável (append-only) de transições de custódia

Conformidade: ISO/IEC 27037 — hash SHA-256 em metadados de prova.
"""

import hashlib
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone


# ---------------------------------------------------------------------------
# Utilizador personalizado
# ---------------------------------------------------------------------------

class User(AbstractUser):
    """Utilizador do sistema com perfil baseado em roles."""

    class Profile(models.TextChoices):
        AGENT = 'AGENT', 'Agente / First Responder'
        EXPERT = 'EXPERT', 'Perito Forense Digital'

    profile = models.CharField(
        max_length=10,
        choices=Profile.choices,
        default=Profile.AGENT,
        verbose_name='Perfil',
        help_text='Define as permissões e vistas disponíveis.',
    )
    badge_number = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Número de identificação / crachá',
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Telefone de contacto',
    )

    class Meta:
        verbose_name = 'Utilizador'
        verbose_name_plural = 'Utilizadores'
        ordering = ['username']

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.get_profile_display()})'

    @property
    def is_agent(self):
        return self.profile == self.Profile.AGENT

    @property
    def is_expert(self):
        return self.profile == self.Profile.EXPERT


# ---------------------------------------------------------------------------
# Ocorrência
# ---------------------------------------------------------------------------

class Occurrence(models.Model):
    """Ocorrência policial / cena de crime."""

    number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Número da ocorrência',
        help_text='Identificador único (ex.: NUIPC ou referência interna).',
    )
    description = models.TextField(
        verbose_name='Descrição',
        help_text='Descrição sumária da ocorrência.',
    )
    date_time = models.DateTimeField(
        default=timezone.now,
        verbose_name='Data/hora da ocorrência',
    )
    gps_lat = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        verbose_name='Latitude GPS',
    )
    gps_lon = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        verbose_name='Longitude GPS',
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Morada aproximada',
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='occurrences',
        verbose_name='Agente responsável',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ocorrência'
        verbose_name_plural = 'Ocorrências'
        ordering = ['-date_time']

    def __str__(self):
        return f'Ocorrência {self.number}'

    def clean(self):
        super().clean()
        if (self.gps_lat is not None) != (self.gps_lon is not None):
            raise ValidationError(
                'Latitude e longitude devem ser ambas definidas ou ambas vazias.'
            )


# ---------------------------------------------------------------------------
# Evidência
# ---------------------------------------------------------------------------

def evidence_photo_path(instance, filename):
    """Caminho de upload: evidencias/<occurrence_number>/<uuid>_<filename>."""
    return f'evidencias/{instance.occurrence.number}/{uuid.uuid4().hex[:8]}_{filename}'


class Evidence(models.Model):
    """Evidência apreendida numa ocorrência (com integridade SHA-256)."""

    class EvidenceType(models.TextChoices):
        DIGITAL_DEVICE = 'DIGITAL_DEVICE', 'Dispositivo Digital'
        DOCUMENT = 'DOCUMENT', 'Documento'
        STORAGE_MEDIA = 'STORAGE_MEDIA', 'Suporte de Armazenamento'
        PHOTO = 'PHOTO', 'Fotografia'
        OTHER = 'OTHER', 'Outro'

    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.PROTECT,
        related_name='evidences',
        verbose_name='Ocorrência',
    )
    type = models.CharField(
        max_length=20,
        choices=EvidenceType.choices,
        verbose_name='Tipo de evidência',
    )
    description = models.TextField(
        verbose_name='Descrição',
    )
    photo = models.ImageField(
        upload_to=evidence_photo_path,
        blank=True,
        null=True,
        verbose_name='Fotografia da evidência',
    )
    gps_lat = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        verbose_name='Latitude GPS (apreensão)',
    )
    gps_lon = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        verbose_name='Longitude GPS (apreensão)',
    )
    timestamp_seizure = models.DateTimeField(
        default=timezone.now,
        verbose_name='Data/hora da apreensão',
    )
    serial_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Número de série',
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='evidences',
        verbose_name='Agente que apreendeu',
    )
    integrity_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='Hash SHA-256 (integridade)',
        help_text='Calculado automaticamente no momento do registo.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Evidência'
        verbose_name_plural = 'Evidências'
        ordering = ['-timestamp_seizure']

    def __str__(self):
        return f'Evidência #{self.pk} — {self.get_type_display()} ({self.occurrence.number})'

    def compute_integrity_hash(self):
        """
        Calcula hash SHA-256 dos metadados da evidência.
        Conforme ISO/IEC 27037 — integridade de metadados no momento do registo.
        """
        data = (
            f'{self.occurrence_id}|'
            f'{self.type}|'
            f'{self.description}|'
            f'{self.gps_lat}|{self.gps_lon}|'
            f'{self.timestamp_seizure.isoformat()}|'
            f'{self.serial_number}|'
            f'{self.agent_id}'
        )
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """
        Override: apenas permite criação (imutável após registo).
        Calcula o hash de integridade no momento do registo.
        Conformidade ISO/IEC 27037 — metadados de prova não são alteráveis.
        """
        if self.pk is not None:
            raise ValidationError(
                'Registos de evidência são imutáveis após criação. '
                'Não é permitido alterar metadados de prova.'
            )
        self.integrity_hash = self.compute_integrity_hash()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override: NUNCA permite eliminação de registos de evidência."""
        raise ValidationError(
            'Registos de evidência são imutáveis. '
            'Não é permitido eliminar registos de prova.'
        )

    def clean(self):
        super().clean()
        if (self.gps_lat is not None) != (self.gps_lon is not None):
            raise ValidationError(
                'Latitude e longitude devem ser ambas definidas ou ambas vazias.'
            )


# ---------------------------------------------------------------------------
# Dispositivo Digital
# ---------------------------------------------------------------------------

class DigitalDevice(models.Model):
    """Dispositivo digital associado a uma evidência."""

    class DeviceType(models.TextChoices):
        SMARTPHONE = 'SMARTPHONE', 'Smartphone'
        TABLET = 'TABLET', 'Tablet'
        LAPTOP = 'LAPTOP', 'Computador Portátil'
        DESKTOP = 'DESKTOP', 'Computador de Secretária'
        USB_DRIVE = 'USB_DRIVE', 'Pen USB'
        HARD_DRIVE = 'HARD_DRIVE', 'Disco Rígido'
        SIM_CARD = 'SIM_CARD', 'Cartão SIM'
        SD_CARD = 'SD_CARD', 'Cartão SD'
        CAMERA = 'CAMERA', 'Câmara'
        DRONE = 'DRONE', 'Drone'
        OTHER = 'OTHER', 'Outro'

    class DeviceCondition(models.TextChoices):
        FUNCTIONAL = 'FUNCTIONAL', 'Funcional'
        DAMAGED = 'DAMAGED', 'Danificado'
        LOCKED = 'LOCKED', 'Bloqueado'
        OFF = 'OFF', 'Desligado'
        UNKNOWN = 'UNKNOWN', 'Desconhecido'

    evidence = models.ForeignKey(
        Evidence,
        on_delete=models.PROTECT,
        related_name='digital_devices',
        verbose_name='Evidência associada',
    )
    type = models.CharField(
        max_length=20,
        choices=DeviceType.choices,
        verbose_name='Tipo de dispositivo',
    )
    brand = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Marca',
    )
    model = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Modelo',
    )
    condition = models.CharField(
        max_length=20,
        choices=DeviceCondition.choices,
        default=DeviceCondition.UNKNOWN,
        verbose_name='Estado do dispositivo',
    )
    imei = models.CharField(
        max_length=20,
        blank=True,
        default='',
        validators=[RegexValidator(regex=r'^(\d{15})?$', message='IMEI deve conter exactamente 15 dígitos.')],
        verbose_name='IMEI',
        help_text='International Mobile Equipment Identity (15 dígitos).',
    )
    serial_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Número de série',
    )
    notes = models.TextField(
        blank=True,
        default='',
        verbose_name='Observações',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Dispositivo Digital'
        verbose_name_plural = 'Dispositivos Digitais'
        ordering = ['-created_at']

    def __str__(self):
        label = f'{self.brand} {self.model}'.strip() or self.get_type_display()
        return f'{label} ({self.get_condition_display()})'


# ---------------------------------------------------------------------------
# Cadeia de Custódia (append-only — NUNCA permite UPDATE/DELETE)
# ---------------------------------------------------------------------------

class ChainOfCustody(models.Model):
    """
    Registo imutável de transição na cadeia de custódia.

    Máquina de estados:
    APREENDIDA → EM_TRANSPORTE → RECEBIDA_LABORATORIO → EM_PERICIA
    → CONCLUIDA → DEVOLVIDA | DESTRUIDA

    Regras:
    - Append-only: save() só permite criação, nunca atualização.
    - delete() está bloqueado.
    - Cada registo inclui hash SHA-256 do registo anterior (blockchain-like).
    - Transições são validadas pela máquina de estados.
    """

    class CustodyState(models.TextChoices):
        APREENDIDA = 'APREENDIDA', 'Apreendida'
        EM_TRANSPORTE = 'EM_TRANSPORTE', 'Em Transporte'
        RECEBIDA_LABORATORIO = 'RECEBIDA_LABORATORIO', 'Recebida no Laboratório'
        EM_PERICIA = 'EM_PERICIA', 'Em Perícia'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'
        DEVOLVIDA = 'DEVOLVIDA', 'Devolvida'
        DESTRUIDA = 'DESTRUIDA', 'Destruída'

    # Transições válidas: estado_atual → [estados_seguintes_possíveis]
    VALID_TRANSITIONS = {
        '': [CustodyState.APREENDIDA],  # estado inicial (sem estado anterior)
        CustodyState.APREENDIDA: [CustodyState.EM_TRANSPORTE],
        CustodyState.EM_TRANSPORTE: [CustodyState.RECEBIDA_LABORATORIO],
        CustodyState.RECEBIDA_LABORATORIO: [CustodyState.EM_PERICIA],
        CustodyState.EM_PERICIA: [CustodyState.CONCLUIDA],
        CustodyState.CONCLUIDA: [CustodyState.DEVOLVIDA, CustodyState.DESTRUIDA],
        CustodyState.DEVOLVIDA: [],  # estado terminal
        CustodyState.DESTRUIDA: [],  # estado terminal
    }

    evidence = models.ForeignKey(
        Evidence,
        on_delete=models.PROTECT,
        related_name='custody_chain',
        verbose_name='Evidência',
    )
    previous_state = models.CharField(
        max_length=25,
        choices=CustodyState.choices,
        blank=True,
        default='',
        verbose_name='Estado anterior',
    )
    new_state = models.CharField(
        max_length=25,
        choices=CustodyState.choices,
        verbose_name='Novo estado',
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='custody_actions',
        verbose_name='Responsável pela transição',
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        verbose_name='Data/hora da transição',
    )
    observations = models.TextField(
        blank=True,
        default='',
        verbose_name='Observações',
    )
    record_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='Hash SHA-256 do registo',
        help_text='Hash que encadeia com o registo anterior (integridade).',
    )

    class Meta:
        verbose_name = 'Registo de Custódia'
        verbose_name_plural = 'Registos de Custódia'
        ordering = ['evidence', 'timestamp']

    def __str__(self):
        prev = self.get_previous_state_display() or '(início)'
        return f'Evidência #{self.evidence_id}: {prev} → {self.get_new_state_display()}'

    def clean(self):
        """Valida a transição de estado conforme a máquina de estados."""
        super().clean()

        # Verificar se a transição é válida
        allowed = self.VALID_TRANSITIONS.get(self.previous_state, [])
        if self.new_state not in allowed:
            raise ValidationError({
                'new_state': (
                    f'Transição inválida: '
                    f'{self.get_previous_state_display() or "(início)"} '
                    f'→ {self.get_new_state_display()}. '
                    f'Estados permitidos: {", ".join(str(s) for s in allowed) or "nenhum (estado terminal)"}.'
                )
            })

    def compute_record_hash(self):
        """
        Calcula hash SHA-256 encadeando com o registo anterior.
        Garante integridade tipo blockchain na cadeia de custódia.
        """
        # Obter hash do registo anterior (se existir)
        previous_record = (
            ChainOfCustody.objects
            .filter(evidence=self.evidence)
            .order_by('-timestamp')
            .first()
        )
        previous_hash = previous_record.record_hash if previous_record else '0' * 64

        data = (
            f'{previous_hash}|'
            f'{self.evidence_id}|'
            f'{self.previous_state}|{self.new_state}|'
            f'{self.agent_id}|'
            f'{self.timestamp.isoformat()}|'
            f'{self.observations}'
        )
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """
        Override: apenas permite criação (append-only).
        O previous_state é determinado automaticamente a partir do último
        registo da evidência — nunca confiamos no valor enviado pelo cliente.
        O timestamp usa timezone.now() do servidor (NTP-synced).
        Calcula hash e valida transição antes de gravar.

        A lógica é envolvida em transaction.atomic() com select_for_update()
        para evitar race conditions entre a leitura do último registo e a escrita.
        """
        if self.pk is not None:
            raise ValidationError(
                'Registos de cadeia de custódia são imutáveis. '
                'Não é permitido atualizar registos existentes.'
            )

        with transaction.atomic():
            # Auto-determinar previous_state a partir do último registo
            # select_for_update() garante que nenhum outro processo insere
            # registos concorrentes enquanto estamos a processar este
            last_record = (
                ChainOfCustody.objects
                .select_for_update()
                .filter(evidence=self.evidence)
                .order_by('-timestamp')
                .first()
            )
            self.previous_state = last_record.new_state if last_record else ''

            # Timestamp sempre do servidor (NTP-synced) — nunca do cliente
            self.timestamp = timezone.now()

            self.full_clean()
            self.record_hash = self.compute_record_hash()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override: NUNCA permite eliminação de registos de custódia."""
        raise ValidationError(
            'Registos de cadeia de custódia são imutáveis. '
            'Não é permitido eliminar registos.'
        )
