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
# Validadores customizados
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MB


def validate_image_max_size(value):
    """
    Validação de upload conforme OWASP:
    - Tamanho <= 25 MB (proteção DoS).
    - MIME real via Pillow.verify() (protege contra SVG/polyglots).
    - Formato na whitelist (JPEG/PNG/WEBP).

    Nota: Pillow.verify() fecha o ficheiro; o stream é reposicionado
    no fim para que o Django possa voltar a gravar.
    """
    if value.size > MAX_IMAGE_BYTES:
        raise ValidationError(
            f'O ficheiro excede o tamanho máximo permitido de 25 MB '
            f'(tamanho actual: {value.size / (1024*1024):.1f} MB).'
        )

    try:
        from PIL import Image  # lazy import
    except ImportError:  # pragma: no cover
        return

    try:
        value.seek(0)
        with Image.open(value) as img:
            img.verify()
            fmt = (img.format or '').upper()
    except Exception as exc:
        raise ValidationError(
            'O ficheiro não é uma imagem válida ou está corrompido.'
        ) from exc
    finally:
        try:
            value.seek(0)
        except Exception:
            pass

    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            f'Formato de imagem não permitido: {fmt or "desconhecido"}. '
            f'Permitidos: {", ".join(sorted(ALLOWED_IMAGE_FORMATS))}.'
        )


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
        # Normalizar número da ocorrência (collapse spaces + strip)
        if self.number:
            self.number = ' '.join(self.number.split())
        if (self.gps_lat is not None) != (self.gps_lon is not None):
            raise ValidationError(
                'Latitude e longitude devem ser ambas definidas ou ambas vazias.'
            )
        if self.date_time and self.date_time > timezone.now():
            raise ValidationError({
                'date_time': 'A data da ocorrência não pode estar no futuro.'
            })

    def save(self, *args, **kwargs):
        """Chama full_clean para garantir que validadores de campo correm."""
        self.full_clean()
        super().save(*args, **kwargs)


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
        validators=[validate_image_max_size],
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
        indexes = [
            models.Index(fields=['occurrence', '-timestamp_seizure'], name='ev_occ_ts_idx'),
            models.Index(fields=['agent', '-timestamp_seizure'], name='ev_agent_ts_idx'),
        ]

    def __str__(self):
        return f'Evidência #{self.pk} — {self.get_type_display()} ({self.occurrence.number})'

    def _compute_photo_hash(self):
        """SHA-256 do conteúdo binário da fotografia (ou '' se não houver)."""
        if not self.photo:
            return ''
        try:
            self.photo.open('rb')
            hasher = hashlib.sha256()
            for chunk in self.photo.chunks():
                hasher.update(chunk)
            return hasher.hexdigest()
        finally:
            try:
                self.photo.close()
            except Exception:
                pass

    def compute_integrity_hash(self):
        """
        Calcula hash SHA-256 dos metadados + bytes da fotografia da evidência.
        Conforme ISO/IEC 27037 — integridade total (metadados e artefacto).
        """
        photo_hash = self._compute_photo_hash()
        data = (
            f'{self.occurrence_id}|'
            f'{self.type}|'
            f'{self.description}|'
            f'{self.gps_lat}|{self.gps_lon}|'
            f'{self.timestamp_seizure.isoformat()}|'
            f'{self.serial_number}|'
            f'{self.agent_id}|'
            f'photo={photo_hash}'
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
        # full_clean garante que validadores de campo (GPS, etc.) correm
        self.full_clean()
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
        if self.timestamp_seizure and self.timestamp_seizure > timezone.now():
            raise ValidationError({
                'timestamp_seizure': 'A data da apreensão não pode estar no futuro.'
            })


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
    sequence = models.PositiveIntegerField(
        default=0,
        verbose_name='Sequência',
        help_text=(
            'Número sequencial (1..N) por evidência. Determina a ordem '
            'canónica da cadeia de custódia, independente de resolução '
            'temporal do timestamp.'
        ),
    )

    class Meta:
        verbose_name = 'Registo de Custódia'
        verbose_name_plural = 'Registos de Custódia'
        ordering = ['evidence', 'sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['evidence', 'sequence'],
                name='unique_custody_sequence_per_evidence',
            ),
        ]
        indexes = [
            models.Index(fields=['evidence', 'sequence'], name='coc_ev_seq_idx'),
            models.Index(fields=['agent', '-timestamp'], name='coc_agent_ts_idx'),
        ]

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

        Determinístico: qualquer perito independente pode recalcular o hash
        a partir dos campos públicos do registo e do hash do registo anterior,
        verificando a integridade da cadeia (ISO/IEC 27037).

        Fórmula: SHA-256(previous_hash | evidence_id | previous_state | new_state |
                         agent_id | timestamp_iso | observations)
        """
        previous_record = (
            ChainOfCustody.objects
            .filter(evidence=self.evidence)
            .order_by('-sequence')
            .first()
        )
        previous_hash = previous_record.record_hash if previous_record else '0' * 64

        data = (
            f'{previous_hash}|'
            f'seq={self.sequence}|'
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
            # Auto-determinar previous_state e sequence a partir do último registo.
            # select_for_update() garante serialização entre escritores concorrentes
            # na mesma evidência.
            last_record = (
                ChainOfCustody.objects
                .select_for_update()
                .filter(evidence=self.evidence)
                .order_by('-sequence')
                .first()
            )
            self.previous_state = last_record.new_state if last_record else ''
            self.sequence = (last_record.sequence + 1) if last_record else 1

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


# ---------------------------------------------------------------------------
# AuditLog — Registo imutável de acessos (append-only)
# ---------------------------------------------------------------------------

class AuditLog(models.Model):
    """
    Registo de auditoria imutável (append-only) que documenta cada acesso a recursos.

    Conformidade: ISO/IEC 27037 — rastreia QUEM, QUANDO, O QUÊ e COM QUE CONTEXTO.

    Campos:
    - user: utilizador que efetuou a ação (nullable para acessos anónimos)
    - action: tipo de ação (VIEW, CREATE, EXPORT_PDF)
    - resource_type: tipo de recurso (OCCURRENCE, EVIDENCE, DEVICE, CUSTODY)
    - resource_id: ID da instância do recurso
    - ip_address: endereço IP do cliente (GenericIPAddressField suporta IPv4 e IPv6)
    - correlation_id: UUID da requisição (para rastrear entre logs)
    - timestamp: momento exato (sempre do servidor, UTC)
    - details: JSONField com contexto adicional (ex: hash, tamanho, metadados)

    Imutabilidade:
    - save() — bloqueia atualizações (só permite inserts)
    - delete() — bloqueia eliminações
    """

    class Action(models.TextChoices):
        """Ações que são auditadas."""
        VIEW = 'VIEW', 'Visualização'
        CREATE = 'CREATE', 'Criação'
        EXPORT_PDF = 'EXPORT_PDF', 'Exportação PDF'

    class ResourceType(models.TextChoices):
        """Tipos de recursos auditados."""
        OCCURRENCE = 'OCCURRENCE', 'Ocorrência'
        EVIDENCE = 'EVIDENCE', 'Evidência'
        DEVICE = 'DEVICE', 'Dispositivo Digital'
        CUSTODY = 'CUSTODY', 'Cadeia de Custódia'

    # Relação com o utilizador (nullable para acessos anónimos)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='Utilizador',
        help_text='Utilizador que efetuou a ação (nulo para anónimos).',
    )

    # Tipo de ação realizada
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        db_index=True,
        verbose_name='Ação',
        help_text='VIEW: visualização; CREATE: criação; EXPORT_PDF: exportação.',
    )

    # Tipo de recurso acedido
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
        db_index=True,
        verbose_name='Tipo de Recurso',
        help_text='OCCURRENCE, EVIDENCE, DEVICE, CUSTODY.',
    )

    # ID da instância do recurso
    resource_id = models.IntegerField(
        db_index=True,
        verbose_name='ID do Recurso',
        help_text='Chave primária do recurso acedido.',
    )

    # Endereço IP do cliente
    ip_address = models.GenericIPAddressField(
        verbose_name='Endereço IP',
        help_text='IPv4 ou IPv6 do cliente (extraído de X-Forwarded-For ou REMOTE_ADDR).',
    )

    # UUID de correlação da requisição
    correlation_id = models.CharField(
        max_length=36,
        blank=True,
        default='',
        db_index=True,
        verbose_name='ID de Correlação',
        help_text='UUID da requisição para rastreamento entre logs.',
    )

    # Timestamp (sempre do servidor em UTC)
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name='Timestamp',
        help_text='Momento exato do acesso (UTC, auto-preenchido).',
    )

    # Contexto adicional em JSON
    details = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Detalhes',
        help_text='Contexto adicional: hash, tamanho, metadados, etc.',
    )

    class Meta:
        verbose_name = 'Registo de Auditoria'
        verbose_name_plural = 'Registos de Auditoria'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
            models.Index(fields=['resource_type', 'resource_id', '-timestamp']),
            models.Index(fields=['correlation_id']),
        ]

    def __str__(self):
        return (
            f'{self.action} {self.resource_type}({self.resource_id}) '
            f'por {self.user or "anónimo"} em {self.timestamp}'
        )

    def save(self, *args, **kwargs):
        """
        Override: AuditLog é append-only.

        Permite apenas inserts (pk é None). Bloqueia atualizações.
        """
        if self.pk is not None:
            raise ValidationError(
                'Registos de auditoria são imutáveis. '
                'Não é permitido atualizar registos existentes.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override: NUNCA permite eliminação de registos de auditoria."""
        raise ValidationError(
            'Registos de auditoria são imutáveis. '
            'Não é permitido eliminar registos.'
        )
