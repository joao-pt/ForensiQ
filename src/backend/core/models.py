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
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from core.validators import validate_imei, validate_imsi, validate_vin

# ---------------------------------------------------------------------------
# Gerador de códigos humanos ANO-TIPO-SEQ (ex.: OCC-2026-00001)
# ---------------------------------------------------------------------------

CODE_MAX_ATTEMPTS = 5
MAX_SEQUENCE_ATTEMPTS = 10  # Audit 2026-05-18 §3 N10 — retry de AuditLog.sequence


def _next_yearly_code(prefix, model, year, field='code'):
    """Gera o próximo código ``PREFIX-YYYY-NNNNN`` para o ano indicado.

    A unicidade é garantida pelo constraint único no campo ``code``; em
    caso de colisão concorrente o chamador faz retry até
    ``CODE_MAX_ATTEMPTS``. Consulta o MAX existente para o ano (``startswith``
    tira partido do índice) e soma 1. Para o primeiro registo de um ano
    cai em ``00001``.
    """
    prefix_filter = f'{prefix}-{year}-'
    last = (
        model.objects.filter(**{f'{field}__startswith': prefix_filter})
        .order_by(f'-{field}')
        .values_list(field, flat=True)
        .first()
    )
    if last:
        try:
            seq = int(last.rsplit('-', 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'{prefix}-{year}-{seq:05d}'


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
            f'(tamanho actual: {value.size / (1024 * 1024):.1f} MB).'
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
        raise ValidationError('O ficheiro não é uma imagem válida ou está corrompido.') from exc
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


def _strip_exif(photo_file):
    """Remove metadados EXIF/IPTC/XMP de uma fotografia carregada.

    Devolve um ``ContentFile`` com os bytes reconstruídos sem metadados,
    preservando formato e dados de pixel. O hash de integridade calculado
    a seguir (``Evidence._compute_photo_hash``) torna-se invariante ao
    EXIF — fotos idênticas em pixels mas distintas em EXIF produzem o
    mesmo ``integrity_hash``.

    Motivação forense: EXIF de telemóveis inclui GPS da captura, modelo
    de câmara e timestamps que podem revelar dados sensíveis da cena a
    quem receba o PDF ou o ficheiro original (auditoria 2026-05-18 §2 S9).

    Fail-open: se Pillow não estiver disponível, devolve o ficheiro
    original sem strip — alinhado com ``validate_image_max_size``, que
    também faz fallback permissivo nesse cenário.
    """
    try:
        from io import BytesIO

        from django.core.files.base import ContentFile
        from PIL import Image
    except ImportError:  # pragma: no cover
        return photo_file

    try:
        photo_file.seek(0)
    except (ValueError, AttributeError):
        pass

    with Image.open(photo_file) as img:
        img.load()
        fmt = (img.format or '').upper()
        buf = BytesIO()
        save_kwargs = {}
        if fmt == 'JPEG':
            # ``quality='keep'`` preserva qualidade original sem
            # re-encoding agressivo; ``exif=b''`` apaga o bloco EXIF.
            save_kwargs = {'quality': 'keep', 'exif': b''}
        elif fmt == 'PNG':
            from PIL.PngImagePlugin import PngInfo

            # PngInfo vazio descarta tEXt/iTXt/zTXt e tempo (tIME).
            save_kwargs = {'pnginfo': PngInfo()}
        elif fmt == 'WEBP':
            save_kwargs = {'exif': b''}
        img.save(buf, format=fmt, **save_kwargs)

    buf.seek(0)
    name = getattr(photo_file, 'name', 'photo')
    return ContentFile(buf.getvalue(), name=name)


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


# ---------------------------------------------------------------------------
# Taxonomia de crimes (dados de referência — ADR-0014)
#
# Espelha a Tabela de Crimes Registados 1.7 (2024) do CSE/INE — DGPJ/SIEJ em 3
# níveis (N1 categorias → N2 subcategorias → N3 tipos). NÃO é prova: é lookup
# editável/versionável no admin e NÃO está sujeita aos invariantes de
# imutabilidade (sem triggers PG). Semeada por `manage.py seed_crime_taxonomy`
# a partir de core/data/tabela_crimes_2024.json.
# ---------------------------------------------------------------------------


class CrimeCategoria(models.Model):
    """Nível 1 da Tabela de Crimes Registados (categorias)."""

    codigo = models.PositiveSmallIntegerField(
        unique=True,
        verbose_name='Código N1',
        help_text='Código oficial da categoria (não contíguo: {1..6, 10}).',
    )
    nome = models.CharField(max_length=255, verbose_name='Categoria')

    class Meta:
        verbose_name = 'Categoria de crime (N1)'
        verbose_name_plural = 'Categorias de crime (N1)'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.nome}'


class CrimeSubcategoria(models.Model):
    """Nível 2 da Tabela de Crimes Registados (subcategorias)."""

    categoria = models.ForeignKey(
        CrimeCategoria,
        on_delete=models.PROTECT,
        related_name='subcategorias',
        verbose_name='Categoria (N1)',
    )
    codigo = models.PositiveSmallIntegerField(verbose_name='Código N2')
    nome = models.CharField(max_length=255, verbose_name='Subcategoria')

    class Meta:
        verbose_name = 'Subcategoria de crime (N2)'
        verbose_name_plural = 'Subcategorias de crime (N2)'
        ordering = ['codigo']
        constraints = [
            models.UniqueConstraint(
                fields=['categoria', 'codigo'],
                name='uniq_subcategoria_categoria_codigo',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.nome}'


class CrimeTipo(models.Model):
    """Nível 3 da Tabela de Crimes Registados (tipos, com código oficial)."""

    subcategoria = models.ForeignKey(
        CrimeSubcategoria,
        on_delete=models.PROTECT,
        related_name='tipos',
        verbose_name='Subcategoria (N2)',
    )
    codigo = models.PositiveIntegerField(
        unique=True,
        verbose_name='Código N3',
        help_text='Código oficial do tipo de crime (alinhado com o INE/DGPJ).',
    )
    descritivo = models.CharField(max_length=255, verbose_name='Tipo de crime')
    is_active = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Falso para tipos retirados em versões futuras da Tabela.',
    )

    class Meta:
        verbose_name = 'Tipo de crime (N3)'
        verbose_name_plural = 'Tipos de crime (N3)'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.descritivo}'


class PoliticaCriminalManager(models.Manager):
    def vigente(self):
        """Devolve a versão activa da Lei de Política Criminal, ou ``None``."""
        return self.filter(is_active=True).first()


class PoliticaCriminalPrioridade(models.Model):
    """Versão de uma Lei de Política Criminal e os crimes que prioriza (ADR-0014).

    A ``priority`` da ``Occurrence`` deriva da versão activa pelo eixo
    ``INVESTIGACAO`` (Art. 5.º — operativo). Trocar de biénio é semear uma nova
    versão e marcá-la activa: operação de dados, sem código.
    """

    lei = models.CharField(max_length=120, verbose_name='Lei')
    biennium = models.CharField(max_length=20, verbose_name='Biénio')
    vigente_desde = models.DateField(verbose_name='Vigente desde')
    vigente_ate = models.DateField(null=True, blank=True, verbose_name='Vigente até')
    is_active = models.BooleanField(default=False, verbose_name='Activa')
    tipos = models.ManyToManyField(
        CrimeTipo,
        through='PrioridadeCrimeTipo',
        related_name='politicas',
    )

    objects = PoliticaCriminalManager()

    class Meta:
        verbose_name = 'Política criminal (prioridade)'
        verbose_name_plural = 'Políticas criminais (prioridade)'
        ordering = ['-vigente_desde']
        constraints = [
            # Garante uma só versão activa em simultâneo.
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='uniq_politica_criminal_activa',
            ),
        ]

    def __str__(self):
        marca = ' [activa]' if self.is_active else ''
        return f'{self.lei} ({self.biennium}){marca}'

    def classifica_prioritaria(self, crime_tipo_id):
        """True se o tipo está no eixo INVESTIGACAO (operativo) desta versão."""
        if crime_tipo_id is None:
            return False
        return self.associacoes.filter(
            crime_tipo_id=crime_tipo_id,
            eixo=PrioridadeCrimeTipo.Eixo.INVESTIGACAO,
        ).exists()


class PrioridadeCrimeTipo(models.Model):
    """Associação versão-de-lei ↔ tipo de crime, com o eixo (Art. 4.º/5.º)."""

    class Eixo(models.TextChoices):
        INVESTIGACAO = 'INVESTIGACAO', 'Investigação prioritária (Art. 5.º)'
        PREVENCAO = 'PREVENCAO', 'Prevenção prioritária (Art. 4.º)'

    politica = models.ForeignKey(
        PoliticaCriminalPrioridade,
        on_delete=models.CASCADE,
        related_name='associacoes',
    )
    crime_tipo = models.ForeignKey(
        CrimeTipo,
        on_delete=models.PROTECT,
        related_name='associacoes_prioridade',
    )
    eixo = models.CharField(max_length=20, choices=Eixo.choices)

    class Meta:
        verbose_name = 'Associação prioridade↔tipo'
        verbose_name_plural = 'Associações prioridade↔tipo'
        constraints = [
            models.UniqueConstraint(
                fields=['politica', 'crime_tipo', 'eixo'],
                name='uniq_politica_tipo_eixo',
            ),
        ]

    def __str__(self):
        return f'{self.politica_id} · {self.crime_tipo_id} · {self.eixo}'


# ---------------------------------------------------------------------------
# Ocorrência
# ---------------------------------------------------------------------------


class Occurrence(models.Model):
    """Ocorrência policial / cena de crime."""

    class Priority(models.TextChoices):
        PRIORITARIA = 'PRIORITARIA', 'Prioritária'
        NORMAL = 'NORMAL', 'Normal'

    class PrioritySource(models.TextChoices):
        LEI = 'LEI', 'Derivada da lei'
        MANUAL = 'MANUAL', 'Override manual'

    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Código do caso',
        help_text='Gerado automaticamente no formato OCC-YYYY-NNNNN.',
    )
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
    gps_lng = models.DecimalField(
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
    crime_type = models.ForeignKey(
        CrimeTipo,
        on_delete=models.PROTECT,
        related_name='occurrences',
        verbose_name='Tipo de crime',
        help_text='Classificação na Tabela de Crimes Registados (N3).',
    )
    priority = models.CharField(
        max_length=12,
        choices=Priority.choices,
        default=Priority.NORMAL,
        verbose_name='Prioridade',
        help_text='Derivada da Política Criminal na criação (ADR-0014).',
    )
    priority_source = models.CharField(
        max_length=6,
        choices=PrioritySource.choices,
        default=PrioritySource.LEI,
        verbose_name='Origem da prioridade',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ocorrência'
        verbose_name_plural = 'Ocorrências'
        ordering = ['-date_time']

    def __str__(self):
        parts = [self.number]
        if self.code and self.code != self.number:
            parts.append(self.code)
        return f'Ocorrência {" · ".join(parts)}'

    def clean(self):
        super().clean()
        # Normalizar número da ocorrência (collapse spaces + strip)
        if self.number:
            self.number = ' '.join(self.number.split())
        if (self.gps_lat is not None) != (self.gps_lng is not None):
            raise ValidationError('Latitude e longitude devem ser ambas definidas ou ambas vazias.')
        if self.date_time and self.date_time > timezone.now():
            raise ValidationError({'date_time': 'A data da ocorrência não pode estar no futuro.'})
        # Prioridade derivada da Política Criminal (ADR-0014). Corre só na
        # criação; a Occurrence é imutável (POST-only + triggers), logo a
        # prioridade fixa-se aqui, pré-gravação.
        if self.pk is None and self.crime_type_id is not None:
            self._aplicar_prioridade()

    def _aplicar_prioridade(self):
        """Deriva ``priority``/``priority_source`` do ``crime_type`` (ADR-0014).

        Eixo operativo = INVESTIGACAO (Art. 5.º) da versão activa da Política
        Criminal. A lei prevalece como fonte; o override manual
        (``priority_source=MANUAL`` no POST) só **eleva** NORMAL→PRIORITÁRIA —
        não permite despromover um crime que a lei marca prioritário.
        """
        vigente = PoliticaCriminalPrioridade.objects.vigente()
        lei_prioritaria = bool(vigente and vigente.classifica_prioritaria(self.crime_type_id))
        override_manual = self.priority_source == self.PrioritySource.MANUAL
        if lei_prioritaria:
            self.priority = self.Priority.PRIORITARIA
            self.priority_source = self.PrioritySource.LEI
        elif override_manual:
            self.priority = self.Priority.PRIORITARIA
            self.priority_source = self.PrioritySource.MANUAL
        else:
            self.priority = self.Priority.NORMAL
            self.priority_source = self.PrioritySource.LEI

    def save(self, *args, **kwargs):
        """Chama full_clean e atribui ``code`` (OCC-YYYY-NNNNN) na criação."""
        self.full_clean()
        is_new = self.pk is None
        if is_new and not self.code:
            year = (self.date_time or timezone.now()).year
            for _ in range(CODE_MAX_ATTEMPTS):
                self.code = _next_yearly_code('OCC', type(self), year=year)
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError as exc:
                    if 'code' not in str(exc).lower():
                        raise
                    self.code = ''
                    self.pk = None
            raise RuntimeError(
                'Não foi possível gerar um código OCC-YYYY-NNNNN único após várias tentativas.'
            )
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Evidência
# ---------------------------------------------------------------------------


class EvidenceQuerySet(models.QuerySet):
    """QuerySet de Evidence com helpers comuns."""

    def with_current_state(self):
        """Anota cada evidência com ``current_state`` (último ChainOfCustody).

        O estado actual é definido pelo registo com maior ``sequence`` por
        ``evidence_id`` — invariante mantida pelo append-only de
        ChainOfCustody.save(). O índice ``coc_ev_seq_idx`` suporta a
        ordenação sem table scan.
        """
        latest_state = (
            ChainOfCustody.objects.filter(evidence=OuterRef('pk'))
            .order_by('-sequence')
            .values('new_state')[:1]
        )
        return self.annotate(current_state=Subquery(latest_state))


def evidence_photo_path(instance, filename):
    """Caminho de upload: evidencias/<occurrence_code>/<uuid>_<filename>.

    Usa o ``code`` da ocorrência (formato OCC-YYYY-NNNNN, gerado pelo
    sistema, sem caracteres especiais) em vez do ``number`` (NUIPC),
    porque NUIPCs reais contêm ``/`` (ex.: ``NUIPC.812/2026.LISBOA``)
    que parte o path para múltiplos segmentos e impede o
    ``MediaServeView`` de fazer o lookup correcto da ocorrência.
    """
    return f'evidencias/{instance.occurrence.code}/{uuid.uuid4().hex[:8]}_{filename}'


class Evidence(models.Model):
    """Evidência apreendida numa ocorrência (com integridade SHA-256).

    Taxonomia focada em prova digital (ISO/IEC 27037). Sem documentos
    de papel ou fotografias soltas — apenas dispositivos, ficheiros e
    suportes com relevância forense digital.

    Suporta hierarquia de sub-componentes (máx. 3 níveis):
    ex. Telemóvel (raiz) → SIM Card (filho) → (sem mais níveis).
    """

    # Profundidade máxima da árvore pai-filho.
    MAX_TREE_DEPTH = 3

    # Tipos terminais — não admitem sub-componentes.
    # Um cartão SIM, cartão de memória, cartão RFID/NFC ou ficheiro digital
    # é, por natureza, indivisível: não há prova forense útil em registar
    # algo "dentro de" um SIM. A validação é aplicada em clean(); o frontend
    # replica a constante (config.js EVIDENCE_LEAF_TYPES) só para UX.
    EVIDENCE_LEAF_TYPES = frozenset(
        {
            'SIM_CARD',
            'MEMORY_CARD',
            'RFID_NFC_CARD',
            'DIGITAL_FILE',
        }
    )

    class EvidenceType(models.TextChoices):
        # --- Dispositivos autónomos (tipicamente raiz) ---
        MOBILE_DEVICE = 'MOBILE_DEVICE', 'Telemóvel / Smartphone / Tablet'
        COMPUTER = 'COMPUTER', 'Computador (PC / portátil / servidor)'
        STORAGE_MEDIA = 'STORAGE_MEDIA', 'Suporte de Armazenamento Externo'
        GAMING_CONSOLE = 'GAMING_CONSOLE', 'Consola de Jogos'
        GPS_TRACKER = 'GPS_TRACKER', 'Rastreador GPS'
        SMART_TAG = 'SMART_TAG', 'Localizador Bluetooth (AirTag / SmartTag / Tile)'
        CCTV_DEVICE = 'CCTV_DEVICE', 'CCTV / DVR / NVR'
        VEHICLE = 'VEHICLE', 'Veículo (container)'
        DRONE = 'DRONE', 'Drone / UAV'
        IOT_DEVICE = 'IOT_DEVICE', 'Dispositivo IoT'
        NETWORK_DEVICE = 'NETWORK_DEVICE', 'Equipamento de Rede'
        DIGITAL_FILE = 'DIGITAL_FILE', 'Ficheiro Digital (captura)'
        RFID_NFC_CARD = 'RFID_NFC_CARD', 'Cartão RFID / NFC'
        OTHER_DIGITAL = 'OTHER_DIGITAL', 'Outro Dispositivo Digital'
        # --- Sub-componentes típicos (tipicamente não-raiz, mas permitido) ---
        SIM_CARD = 'SIM_CARD', 'Cartão SIM'
        MEMORY_CARD = 'MEMORY_CARD', 'Cartão de Memória (SD / microSD / CF)'
        INTERNAL_DRIVE = 'INTERNAL_DRIVE', 'Disco Interno (HDD / SSD / NVMe)'
        VEHICLE_COMPONENT = 'VEHICLE_COMPONENT', 'Componente Electrónico de Veículo'

    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Código do item',
        help_text='Gerado automaticamente no formato ITM-YYYY-NNNNN.',
    )
    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.PROTECT,
        related_name='evidences',
        verbose_name='Ocorrência',
    )
    type = models.CharField(
        max_length=25,
        choices=EvidenceType.choices,
        verbose_name='Tipo de evidência',
    )
    parent_evidence = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,  # impede apagar pai enquanto tem filhos
        null=True,
        blank=True,
        related_name='sub_components',
        verbose_name='Evidência-pai',
        help_text=(
            'Se este item for um componente interno de outra evidência, '
            'indica o pai (máx. 3 níveis).'
        ),
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
    gps_lng = models.DecimalField(
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
    # --- Campos específicos do tipo (flexíveis via JSON) ---
    type_specific_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Dados específicos do tipo',
        help_text=('Campos específicos do tipo de evidência (IMEI, VIN, IMSI, ICCID, MAC, etc.).'),
    )
    external_lookup_snapshot = models.JSONField(
        null=True,
        blank=True,
        verbose_name='Snapshot de consulta externa',
        help_text=(
            'Resposta JSON da API externa (imeidb.xyz, vindecoder, etc.) '
            'à data da consulta. Para auditoria e proveniência ISO 27037.'
        ),
    )
    external_lookup_source = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Fonte da consulta externa',
        help_text='Ex: "imeidb.xyz", "vindecoder.eu".',
    )
    external_lookup_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Data/hora da consulta externa',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EvidenceQuerySet.as_manager()

    class Meta:
        verbose_name = 'Evidência'
        verbose_name_plural = 'Evidências'
        ordering = ['-timestamp_seizure']
        indexes = [
            models.Index(fields=['occurrence', '-timestamp_seizure'], name='ev_occ_ts_idx'),
            models.Index(fields=['agent', '-timestamp_seizure'], name='ev_agent_ts_idx'),
            models.Index(fields=['parent_evidence'], name='ev_parent_idx'),
        ]

    def __str__(self):
        label = self.code or f'#{self.pk}'
        return f'Item {label} — {self.get_type_display()} ({self.occurrence.number})'

    # ------------------------------------------------------------------
    # Hierarquia pai-filho
    # ------------------------------------------------------------------

    def get_depth(self):
        """Devolve o nível na árvore (1 = raiz, 2 = filho de raiz, 3 = neto).

        Percorre `parent_evidence` para cima até à raiz. Inclui um guard
        contra ciclos para o caso (improvável) de dados corrompidos na
        DB devolverem uma árvore cíclica.
        """
        depth = 1
        node = self.parent_evidence
        visited = set()
        if self.pk is not None:
            visited.add(self.pk)
        while node is not None:
            if node.pk in visited:
                # Ciclo detectado — sinaliza com profundidade "acima do máximo"
                # para que o validador falhe de forma óbvia.
                return self.MAX_TREE_DEPTH + 1
            visited.add(node.pk)
            depth += 1
            if depth > self.MAX_TREE_DEPTH + 1:
                # Short-circuit: já excede o máximo, não vale a pena continuar.
                return depth
            node = node.parent_evidence
        return depth

    def _parent_contains_self(self):
        """Verifica se `self` aparece na cadeia ascendente do parent (ciclo)."""
        if self.parent_evidence is None or self.pk is None:
            return False
        node = self.parent_evidence
        visited = set()
        while node is not None:
            if node.pk == self.pk:
                return True
            if node.pk in visited:
                # Corrupção pré-existente na DB — aborta para não fazer loop
                return True
            visited.add(node.pk)
            node = node.parent_evidence
        return False

    # ------------------------------------------------------------------
    # Hash de integridade
    # ------------------------------------------------------------------

    def _compute_photo_hash(self):
        """SHA-256 do conteúdo binário da fotografia (ou '' se não houver).

        Usa ``chunks()`` e evita fechar o stream — o ``ImageField.pre_save``
        chama ``seek(0)`` no mesmo file handle antes de gravar no storage,
        portanto não podemos fechar aqui (ISO/IEC 27037: integridade do
        upload é computada antes da gravação, sem alterar o ficheiro).
        """
        if not self.photo:
            return ''
        hasher = hashlib.sha256()
        for chunk in self.photo.chunks():
            hasher.update(chunk)
        # Repõe posição do cursor para o pre_save do ImageField não encontrar EOF.
        try:
            self.photo.seek(0)
        except (ValueError, AttributeError):
            pass
        return hasher.hexdigest()

    def compute_integrity_hash(self):
        """
        Calcula hash SHA-256 dos metadados + bytes da fotografia da evidência.
        Conforme ISO/IEC 27037 — integridade total (metadados e artefacto).

        O `type_specific_data` é serializado com sort_keys=True para
        garantir determinismo (mesmo dicionário → mesmo hash).
        """
        import json

        photo_hash = self._compute_photo_hash()
        # Serialização determinística do JSON (ordem estável + sem espaços)
        tsd_json = json.dumps(
            self.type_specific_data or {},
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        )
        data = (
            f'{self.occurrence_id}|'
            f'{self.type}|'
            f'{self.parent_evidence_id or ""}|'
            f'{self.description}|'
            f'{self.gps_lat}|{self.gps_lng}|'
            f'{self.timestamp_seizure.isoformat()}|'
            f'{self.serial_number}|'
            f'{self.agent_id}|'
            f'tsd={tsd_json}|'
            f'photo={photo_hash}'
        )
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """
        Override: apenas permite criação (imutável após registo).
        Calcula o hash de integridade e atribui ``code`` (ITM-YYYY-NNNNN)
        no momento do registo.
        Conformidade ISO/IEC 27037 — metadados de prova não são alteráveis.
        """
        if self.pk is not None:
            raise ValidationError(
                'Registos de evidência são imutáveis após criação. '
                'Não é permitido alterar metadados de prova.'
            )
        # full_clean garante que validadores de campo (GPS, etc.) correm
        self.full_clean()
        # Strip EXIF antes do hash para que o ``integrity_hash`` seja
        # invariante a metadados sensíveis (GPS da captura, modelo de
        # câmara, timestamps originais). Auditoria 2026-05-18 §2 S9.
        if self.photo:
            self.photo = _strip_exif(self.photo)
        self.integrity_hash = self.compute_integrity_hash()
        year = (self.timestamp_seizure or timezone.now()).year
        for _ in range(CODE_MAX_ATTEMPTS):
            if not self.code:
                self.code = _next_yearly_code('ITM', type(self), year=year)
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError as exc:
                if 'code' not in str(exc).lower():
                    raise
                self.code = ''
                self.pk = None
        raise RuntimeError(
            'Não foi possível gerar um código ITM-YYYY-NNNNN único após várias tentativas.'
        )

    def delete(self, *args, **kwargs):
        """Override: NUNCA permite eliminação de registos de evidência."""
        raise ValidationError(
            'Registos de evidência são imutáveis. Não é permitido eliminar registos de prova.'
        )

    # ------------------------------------------------------------------
    # Validação (clean)
    # ------------------------------------------------------------------

    def clean(self):
        super().clean()
        if (self.gps_lat is not None) != (self.gps_lng is not None):
            raise ValidationError('Latitude e longitude devem ser ambas definidas ou ambas vazias.')
        if self.timestamp_seizure and self.timestamp_seizure > timezone.now():
            raise ValidationError(
                {'timestamp_seizure': 'A data da apreensão não pode estar no futuro.'}
            )

        # --- Hierarquia pai-filho ---
        if self.parent_evidence_id is not None:
            parent = self.parent_evidence
            # Não pode migrar entre ocorrências
            if parent.occurrence_id != self.occurrence_id:
                raise ValidationError(
                    {
                        'parent_evidence': (
                            'A evidência-pai pertence a uma ocorrência diferente. '
                            'Sub-componentes têm de partilhar a ocorrência com o pai.'
                        )
                    }
                )
            # Não pode haver ciclo (self entre os ancestrais)
            if self._parent_contains_self():
                raise ValidationError(
                    {
                        'parent_evidence': (
                            'Ciclo detectado: esta evidência não pode ser '
                            'descendente de si própria.'
                        )
                    }
                )
            # Profundidade <= 3
            depth = self.get_depth()
            if depth > self.MAX_TREE_DEPTH:
                raise ValidationError(
                    {
                        'parent_evidence': (
                            f'Profundidade da árvore excede o máximo permitido '
                            f'({self.MAX_TREE_DEPTH} níveis). Esta evidência '
                            f'ficaria a {depth} níveis da raiz.'
                        )
                    }
                )
            # Tipos terminais (cartão SIM, etc.) não aceitam sub-componentes.
            if parent.type in self.EVIDENCE_LEAF_TYPES:
                parent_label = parent.get_type_display()
                raise ValidationError(
                    {'parent_evidence': (f'O tipo "{parent_label}" não admite sub-componentes.')}
                )

        # --- Validadores específicos por tipo ---
        self._validate_type_specific_data()

    def _validate_type_specific_data(self):
        """Valida campos em `type_specific_data` conforme o tipo de evidência."""
        data = self.type_specific_data or {}
        if not isinstance(data, dict):
            raise ValidationError({'type_specific_data': 'Deve ser um objecto JSON (dicionário).'})

        errors = {}

        if self.type == self.EvidenceType.MOBILE_DEVICE:
            imei = data.get('imei')
            if imei:
                try:
                    validate_imei(imei)
                except ValidationError as exc:
                    errors['type_specific_data'] = f'imei: {"; ".join(exc.messages)}'

        if self.type == self.EvidenceType.VEHICLE:
            vin = data.get('vin')
            if vin:
                try:
                    validate_vin(vin)
                except ValidationError as exc:
                    errors['type_specific_data'] = f'vin: {"; ".join(exc.messages)}'

        if self.type == self.EvidenceType.SIM_CARD:
            imsi = data.get('imsi')
            if imsi:
                try:
                    validate_imsi(imsi)
                except ValidationError as exc:
                    errors['type_specific_data'] = f'imsi: {"; ".join(exc.messages)}'

        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# Dispositivo Digital
# ---------------------------------------------------------------------------


def _digital_device_imei_validator(value):
    r"""Aceita string vazia (campo opcional) ou IMEI Luhn-válido.

    Cobre o caminho directo DigitalDevice.save() — sem ele, o anterior
    RegexValidator(r'^(\d{15})?$') aceitava qualquer 15 dígitos sem
    verificar Luhn, divergindo do path Evidence._validate_type_specific_data
    que já exigia checksum via validate_imei.
    """
    if not value:
        return
    validate_imei(value)


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
        verbose_name='Modelo (SKU)',
        help_text=(
            'Código técnico do modelo (ex.: A2161). Permite ao perito '
            'identificar a variante exacta — bandas, memória, region-lock.'
        ),
    )
    commercial_name = models.CharField(
        max_length=120,
        blank=True,
        default='',
        verbose_name='Nome comercial',
        help_text=(
            'Nome reconhecido pelo first responder (ex.: iPhone 11 Pro Max). '
            'Preenchido pelo enriquecimento IMEI quando disponível.'
        ),
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
        validators=[_digital_device_imei_validator],
        verbose_name='IMEI',
        help_text='International Mobile Equipment Identity (15 dígitos com checksum Luhn).',
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
        # Prefere nome comercial (reconhecível) e mostra SKU entre parênteses
        # quando ambos existem — útil para listagens e admin.
        if self.commercial_name and self.model:
            label = f'{self.commercial_name} ({self.model})'
        else:
            label = (
                self.commercial_name
                or f'{self.brand} {self.model}'.strip()
                or self.get_type_display()
            )
        return f'{label} ({self.get_condition_display()})'

    def save(self, *args, **kwargs):
        """
        Override: chama full_clean() antes de gravar para garantir que
        validadores de campo (Luhn do IMEI, etc.) correm em todos
        os caminhos de escrita (não apenas via ModelForm/DRF).

        Fix B-C1 da auditoria 2026-04-19.

        Excepção: durante `loaddata` (fixtures) ou signals com `raw=True`
        o kwarg `from_migration=True` pode ser passado para saltar a
        validação — evita falhas em dados legados que não cumpram
        validadores introduzidos posteriormente.
        """
        skip_validation = kwargs.pop('from_migration', False)
        if not skip_validation:
            self.full_clean()
        super().save(*args, **kwargs)


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

    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Código da transição',
        help_text='Gerado automaticamente no formato CC-YYYY-NNNNN.',
    )
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
        ev_label = self.evidence.code if self.evidence_id else f'#{self.evidence_id}'
        return f'Item {ev_label}: {prev} → {self.get_new_state_display()}'

    def clean(self):
        """Valida a transição de estado conforme a máquina de estados."""
        super().clean()

        # Verificar se a transição é válida
        allowed = self.VALID_TRANSITIONS.get(self.previous_state, [])
        if self.new_state not in allowed:
            raise ValidationError(
                {
                    'new_state': (
                        f'Transição inválida: '
                        f'{self.get_previous_state_display() or "(início)"} '
                        f'→ {self.get_new_state_display()}. '
                        f'Estados permitidos: {", ".join(str(s) for s in allowed) or "nenhum (estado terminal)"}.'
                    )
                }
            )

    def compute_record_hash(self, previous_hash=None):
        """
        Calcula hash SHA-256 encadeando com o registo anterior.

        Determinístico e puro: recebe `previous_hash` como parâmetro para
        não depender de queries à DB. Qualquer perito independente pode
        recalcular o hash a partir dos campos públicos do registo e do
        hash do registo anterior, verificando a integridade da cadeia
        (ISO/IEC 27037).

        Fórmula: SHA-256(previous_hash | seq | evidence_id | previous_state |
                         new_state | agent_id | timestamp_iso | observations)

        Fix B-C2 da auditoria 2026-04-19 — antes, esta função fazia uma
        query à DB para obter o registo anterior, tornando-a impura e
        expondo uma race condition (entre a leitura aqui e o INSERT em
        `save()`) quando havia escritas concorrentes na mesma evidência.

        Args:
            previous_hash: hash do registo anterior (hex string). Se None,
                cai para leitura da DB via `_lookup_previous_hash()` apenas
                para compatibilidade com utilizadores antigos (legacy);
                chamadores novos DEVEM fornecer o valor explicitamente,
                tipicamente obtido dentro da mesma transacção do save().
        """
        if previous_hash is None:
            # NOTE: impure path — reads ChainOfCustody via last-record query.
            # Mantido para compatibilidade com código legacy que não passa
            # previous_hash. Novas chamadas (incluindo Evidence.save()
            # abaixo) devem passar o valor explicitamente dentro do
            # `transaction.atomic()` + `select_for_update()`.
            previous_hash = self._lookup_previous_hash()

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

    def _lookup_previous_hash(self):
        """Lê o hash do registo anterior na DB. Não puro — apenas usado
        como fallback de legacy callers sem `previous_hash` explícito."""
        previous_record = (
            ChainOfCustody.objects.filter(evidence=self.evidence).order_by('-sequence').first()
        )
        return previous_record.record_hash if previous_record else '0' * 64

    def save(self, *args, **kwargs):
        """
        Override: apenas permite criação (append-only).
        O previous_state é determinado automaticamente a partir do último
        registo da evidência — nunca confiamos no valor enviado pelo cliente.
        O timestamp usa timezone.now() do servidor (NTP-synced).
        Calcula hash e valida transição antes de gravar.

        A lógica é envolvida em transaction.atomic() com select_for_update()
        para evitar race conditions entre a leitura do último registo e a
        escrita (fix B-C3 da auditoria 2026-04-19). O `previous_hash` é
        passado explicitamente a compute_record_hash() para evitar uma
        segunda query fora do lock (fix B-C2).
        """
        if self.pk is not None:
            raise ValidationError(
                'Registos de cadeia de custódia são imutáveis. '
                'Não é permitido atualizar registos existentes.'
            )

        for _ in range(CODE_MAX_ATTEMPTS):
            try:
                with transaction.atomic():
                    # Lock pessimista na Evidence parent para cobrir o caso
                    # degenerado em que ainda não existe registo de custódia
                    # para esta evidência: nesse caso .first() devolveria None
                    # e o select_for_update() em core_chainofcustody não
                    # adquiriria nenhum lock (não há row), permitindo que
                    # dois pedidos concorrentes calculassem ambos sequence=1
                    # e gerassem IntegrityError tardio (B-C4 da revisão
                    # pré-intercalar). Bloqueando a Evidence parent, qualquer
                    # criação de cadeia para a mesma evidência fica
                    # serializada do início ao fim.
                    Evidence.objects.select_for_update().filter(pk=self.evidence_id).first()

                    # Auto-determinar previous_state e sequence a partir do
                    # último registo. select_for_update() garante serialização
                    # entre escritores concorrentes na mesma evidência quando
                    # já existem registos.
                    last_record = (
                        ChainOfCustody.objects.select_for_update()
                        .filter(evidence=self.evidence)
                        .order_by('-sequence')
                        .first()
                    )
                    self.previous_state = last_record.new_state if last_record else ''
                    self.sequence = (last_record.sequence + 1) if last_record else 1

                    # Timestamp sempre do servidor (NTP-synced) — nunca do cliente
                    self.timestamp = timezone.now()

                    if not self.code:
                        self.code = _next_yearly_code(
                            'CC',
                            ChainOfCustody,
                            year=self.timestamp.year,
                        )

                    self.full_clean()
                    # Passar o hash explicitamente para a função ficar pura e
                    # reaproveitar a leitura já feita dentro do select_for_update.
                    previous_hash = last_record.record_hash if last_record else '0' * 64
                    self.record_hash = self.compute_record_hash(
                        previous_hash=previous_hash,
                    )
                    super().save(*args, **kwargs)
                return
            except IntegrityError as exc:
                if 'code' not in str(exc).lower():
                    raise
                self.code = ''
                self.pk = None
        raise RuntimeError(
            'Não foi possível gerar um código CC-YYYY-NNNNN único após várias tentativas.'
        )

    def delete(self, *args, **kwargs):
        """Override: NUNCA permite eliminação de registos de custódia."""
        raise ValidationError(
            'Registos de cadeia de custódia são imutáveis. Não é permitido eliminar registos.'
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
        EXPORT_CSV = 'EXPORT_CSV', 'Exportação CSV'
        AUDIT_PURGE = 'AUDIT_PURGE', 'Expurgo de Logs (retenção RGPD)'
        SYSTEM_ALERT = 'SYSTEM_ALERT', 'Alerta Operacional (quota/auth)'

    class ResourceType(models.TextChoices):
        """Tipos de recursos auditados."""

        OCCURRENCE = 'OCCURRENCE', 'Ocorrência'
        EVIDENCE = 'EVIDENCE', 'Evidência'
        DEVICE = 'DEVICE', 'Dispositivo Digital'
        CUSTODY = 'CUSTODY', 'Cadeia de Custódia'
        SYSTEM = 'SYSTEM', 'Sistema (meta-auditoria)'

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

    # Sequência global monótona — ordem total entre registos mesmo
    # quando dois inserts caem no mesmo microssegundo. Auditoria
    # 2026-05-18 §3 N10 — fechado em Sem.12. Atribuído em save().
    # Campo populated por migration 0017 para registos existentes.
    sequence = models.BigIntegerField(
        unique=True,
        db_index=True,
        default=0,
        verbose_name='Sequência Global',
        help_text=(
            'Ordem total dos registos de auditoria. Garante ordem '
            'inequívoca entre eventos no mesmo microssegundo.'
        ),
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
        ordering = ['-sequence']
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
        Override: AuditLog é append-only com sequence global monótona.

        Permite apenas inserts (pk é None). Bloqueia atualizações.

        A sequence é atribuída atomicamente como `max(sequence) + 1`.
        Em caso de race condition (dois inserts concorrentes a calcular
        a mesma sequence), a constraint unique levanta IntegrityError e
        re-tentamos até MAX_SEQUENCE_ATTEMPTS. Para o nível de carga do
        AuditLog (não é hot path) o retry é suficientemente raro para
        dispensar advisory lock. Auditoria 2026-05-18 §3 N10.
        """
        if self.pk is not None:
            raise ValidationError(
                'Registos de auditoria são imutáveis. '
                'Não é permitido atualizar registos existentes.'
            )

        from django.db.models import Max

        for _ in range(MAX_SEQUENCE_ATTEMPTS):
            try:
                with transaction.atomic():
                    last_seq = AuditLog.objects.aggregate(m=Max('sequence'))['m'] or 0
                    self.sequence = last_seq + 1
                    super().save(*args, **kwargs)
                return
            except IntegrityError as exc:
                # Só ré-tentamos em colisão de sequence; outras integrity
                # errors (FK, etc.) sobem.
                if 'sequence' not in str(exc).lower():
                    raise
                self.pk = None
                self.sequence = 0
        raise RuntimeError(
            f'Não foi possível atribuir sequence ao AuditLog após '
            f'{MAX_SEQUENCE_ATTEMPTS} tentativas (contenção excessiva).'
        )

    def delete(self, *args, **kwargs):
        """Override: NUNCA permite eliminação de registos de auditoria."""
        raise ValidationError(
            'Registos de auditoria são imutáveis. Não é permitido eliminar registos.'
        )
