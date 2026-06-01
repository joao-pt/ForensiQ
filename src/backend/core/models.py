"""
ForensiQ — Modelos de dados core.

Entidades principais:
- User: utilizador com função (``profile``) + credencial (``clearance``) — ADR-0017
- Institution / InstitutionMembership: organização custódia (ADR-0017)
- Occurrence: ocorrência / cena de crime
- Evidence: evidência apreendida (com hash SHA-256 para integridade)
- ChainOfCustody: ledger de eventos imutável (append-only) da custódia

Conformidade: ISO/IEC 27037 — hash SHA-256 em metadados de prova.
"""

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from core.validators import (
    validate_iccid,
    validate_imei,
    validate_imsi,
    validate_mac,
    validate_vin,
)

# ---------------------------------------------------------------------------
# Gerador de códigos humanos ANO-TIPO-SEQ (ex.: OCC-2026-00001)
# ---------------------------------------------------------------------------

CODE_MAX_ATTEMPTS = 5
MAX_SEQUENCE_ATTEMPTS = 10  # Audit 2026-05-18 §3 N10 — retry de AuditLog.sequence


def _next_yearly_code(prefix, model, year, field='code', width=5):
    """Gera o próximo código ``PREFIX-YYYY-N…`` para o ano indicado.

    A unicidade é garantida pelo constraint único no campo ``code``; em
    caso de colisão concorrente o chamador faz retry até
    ``CODE_MAX_ATTEMPTS``. Consulta o MAX existente para o ano (``startswith``
    tira partido do índice) e soma 1. ``width`` controla o zero-padding
    (ex.: ``width=4`` → ``OC-2026-0001``; ``width=5`` → ``OCC-2026-00001``).
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
    return f'{prefix}-{year}-{seq:0{width}d}'


def _next_local_index(evidence):
    """Próximo índice local (sufixo do código hierárquico) — ADR-0016 §1.

    Item-raiz → posição entre os itens-raiz da ocorrência; sub-componente →
    posição entre os irmãos (filhos do mesmo pai). Cada âmbito tem o seu
    ``UniqueConstraint``; o chamador serializa com ``select_for_update`` no
    âmbito e faz retry sob colisão concorrente.
    """
    if evidence.parent_evidence_id is None:
        qs = Evidence.objects.filter(
            occurrence_id=evidence.occurrence_id, parent_evidence__isnull=True
        )
    else:
        qs = Evidence.objects.filter(parent_evidence_id=evidence.parent_evidence_id)
    last = qs.order_by('-local_index').values_list('local_index', flat=True).first()
    return (last or 0) + 1


def _derive_evidence_code(evidence):
    """Código hierárquico completo do item (ADR-0016 §1).

    Item-raiz: ``{occurrence.code}.{local_index}``. Sub-componente:
    ``{parent.code}.{local_index}`` (o pai já tem o código completo
    materializado, pois a prova é imutável após criação).
    """
    if evidence.parent_evidence_id is None:
        base = evidence.occurrence.code
    else:
        base = evidence.parent_evidence.code
    return f'{base}.{evidence.local_index}'


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
    """Utilizador do sistema: função (``profile``) + credencial (``clearance``).

    Dois eixos independentes (ADR-0017): a *função* diz o que a pessoa faz na
    cadeia de custódia; a *credencial* diz a amplitude de visibilidade de
    leitura a que está habilitada. A visibilidade nacional é uma credencial,
    não um papel — peritos e chefes de serviço são habilitados a ``NACIONAL``.
    """

    class Profile(models.TextChoices):
        FIRST_RESPONDER = 'FIRST_RESPONDER', 'Agente / Primeiro interveniente'
        FORENSIC_EXPERT = 'FORENSIC_EXPERT', 'Perito forense digital'
        EVIDENCE_CUSTODIAN = 'EVIDENCE_CUSTODIAN', 'Custódio / Fiel depositário'
        CASE_AUTHORITY = 'CASE_AUTHORITY', 'Autoridade judiciária (MP)'
        CHEFE_SERVICO = 'CHEFE_SERVICO', 'Chefe de serviço (só-leitura)'
        AUDITOR = 'AUDITOR', 'Auditor (só-leitura)'

    class Clearance(models.TextChoices):
        NORMAL = 'NORMAL', 'Normal (need-to-know)'
        NACIONAL = 'NACIONAL', 'Nacional (leitura nacional)'

    profile = models.CharField(
        max_length=20,
        choices=Profile.choices,
        default=Profile.FIRST_RESPONDER,
        verbose_name='Função',
        help_text='Papel na cadeia de custódia (ADR-0017).',
    )
    clearance = models.CharField(
        max_length=10,
        choices=Clearance.choices,
        default=Clearance.NORMAL,
        verbose_name='Credencial',
        help_text='Amplitude de visibilidade de leitura. NACIONAL = leitura a nível nacional.',
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
        return self.profile == self.Profile.FIRST_RESPONDER

    @property
    def is_expert(self):
        return self.profile == self.Profile.FORENSIC_EXPERT

    @property
    def has_national_clearance(self):
        """Habilitação de leitura nacional (credencial, não função) — ADR-0017."""
        return self.clearance == self.Clearance.NACIONAL


# ---------------------------------------------------------------------------
# Instituições (organização) — ADR-0017
#
# A custódia é institucional: a prova fica à guarda de uma instituição
# (OPC, laboratório, tribunal, serviço do MP) e uma pessoa dessa instituição
# executa e assina os atos. Conjunto básico para a prova de conceito; não é
# prova e não está sujeito aos invariantes de imutabilidade.
# ---------------------------------------------------------------------------


class InstitutionType(models.TextChoices):
    """Tipo de instituição custódia (promove o eixo ``CustodianType``)."""

    OPC = 'OPC', 'Órgão de polícia criminal'
    LAB_PUBLICO = 'LAB_PUBLICO', 'Laboratório público'
    LAB_PRIVADO = 'LAB_PRIVADO', 'Laboratório privado'
    TRIBUNAL = 'TRIBUNAL', 'Tribunal'
    MP = 'MP', 'Ministério Público'
    DEPOSITARIO = 'DEPOSITARIO', 'Depositário'


class Institution(models.Model):
    """Entidade que detém prova à sua guarda (a custódia é institucional)."""

    name = models.CharField(max_length=255, verbose_name='Nome')
    type = models.CharField(
        max_length=20,
        choices=InstitutionType.choices,
        verbose_name='Tipo',
    )
    sigla = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Sigla',
    )
    is_active = models.BooleanField(default=True, verbose_name='Ativa')

    class Meta:
        verbose_name = 'Instituição'
        verbose_name_plural = 'Instituições'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'type'],
                name='uniq_institution_name_type',
            ),
        ]

    def __str__(self):
        return f'{self.sigla or self.name} ({self.get_type_display()})'


class InstitutionMembership(models.Model):
    """Pertença de uma pessoa a uma instituição (M2M com atributos)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='institution_memberships',
        verbose_name='Utilizador',
    )
    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        related_name='memberships',
        verbose_name='Instituição',
    )
    is_active = models.BooleanField(default=True, verbose_name='Ativa')
    joined_at = models.DateTimeField(default=timezone.now, verbose_name='Membro desde')

    class Meta:
        verbose_name = 'Pertença a instituição'
        verbose_name_plural = 'Pertenças a instituições'
        ordering = ['institution', 'user']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'institution'],
                name='uniq_membership_user_institution',
            ),
        ]

    def __str__(self):
        return f'{self.user} @ {self.institution}'


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
        max_length=32,
        unique=True,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Código do caso',
        help_text='Gerado automaticamente no formato OC-YYYY-NNNN (ano de registo) — ADR-0016.',
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
        """Chama full_clean e atribui ``code`` (OC-YYYY-NNNN) na criação.

        O ano é o de REGISTO (``timezone.now()``), não o do crime — ADR-0016 §1;
        a data do crime/apreensão fica em ``date_time``.
        """
        self.full_clean()
        is_new = self.pk is None
        if is_new and not self.code:
            year = timezone.now().year
            for _ in range(CODE_MAX_ATTEMPTS):
                self.code = _next_yearly_code('OC', type(self), year=year, width=4)
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
                'Não foi possível gerar um código OC-YYYY-NNNN único após várias tentativas.'
            )
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Evidência
# ---------------------------------------------------------------------------


class EvidenceQuerySet(models.QuerySet):
    """QuerySet de Evidence com helpers comuns."""

    def with_current_state(self):
        """Anota cada evidência com ``current_event_type`` (último evento).

        Com o ledger de eventos (ADR-0015) deixou de existir um campo de
        estado gravado; o "estado actual" passa a ser o ``event_type`` do
        registo com maior ``sequence`` por ``evidence_id`` — invariante
        mantida pelo append-only de ChainOfCustody.save(). O índice
        ``coc_ev_seq_idx`` suporta a ordenação sem table scan.

        Para o **estado legal derivado** (não o event_type cru) usa-se a
        função pura :func:`derive_legal_state` sobre a sequência completa de
        eventos — esta anotação serve apenas filtros/contagens por tipo de
        evento e a leitura barata do último evento.
        """
        latest_event = (
            ChainOfCustody.objects.filter(evidence=OuterRef('pk'))
            .order_by('-sequence')
            .values('event_type')[:1]
        )
        return self.annotate(current_event_type=Subquery(latest_event))


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

    class AcquisitionVerification(models.TextChoices):
        """Estado da verificação source==cópia (ISO 27037 §5.4.4)."""

        VERIFICADO = 'VERIFICADO', 'Verificado (source == cópia)'
        NAO_VERIFICAVEL = 'NAO_VERIFICAVEL', 'Não verificável (live/móvel)'
        PENDENTE = 'PENDENTE', 'Pendente'

    class SealCondition(models.TextChoices):
        """Condição de um selo de prova (inicial ou na receção de um evento)."""

        INTACTO = 'INTACTO', 'Intacto'
        PARTIDO = 'PARTIDO', 'Partido'
        VIOLADO = 'VIOLADO', 'Violado'
        AUSENTE = 'AUSENTE', 'Ausente'

    code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Código do item',
        help_text='Código hierárquico derivado (ex.: OC-2026-0001.1.1) — ADR-0016.',
    )
    local_index = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Índice local',
        help_text=(
            'Sufixo do código hierárquico: posição no âmbito — na ocorrência se '
            'item-raiz, no pai se sub-componente (ADR-0016 §1).'
        ),
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
    # --- Apreensão de dados (ADR-0016 §3) ---
    # Para evidência DIGITAL_FILE adquirida no terreno: o exhibit é a CÓPIA no
    # suporte; o dispositivo-fonte fica fora do sistema (metadado em
    # type_specific_data). O acquisition_hash é carimbado uma vez sobre os
    # dados copiados — distinto do integrity_hash (hash de verificação do
    # registo). Fonte/ferramenta/nível vivem em type_specific_data.
    acquisition_hash = models.CharField(
        max_length=128,
        blank=True,
        default='',
        verbose_name='Hash de aquisição',
        help_text='Hash carimbado uma vez sobre os dados copiados (≠ integrity_hash).',
    )
    acquisition_hash_algo = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Algoritmo do hash de aquisição',
        help_text='Ex.: SHA-256, SHA-1, MD5.',
    )
    acquisition_verification_status = models.CharField(
        max_length=20,
        choices=AcquisitionVerification.choices,
        blank=True,
        default='',
        verbose_name='Verificação da aquisição',
        help_text='ISO 27037 §5.4.4 — exceção documentada para aquisição live/móvel.',
    )
    acquisition_verification_note = models.TextField(
        blank=True,
        default='',
        verbose_name='Nota de verificação da aquisição',
    )
    # --- Selagem inicial na génese (ADR-0016 §4) ---
    bag_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Número do saco de prova',
    )
    initial_seal_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Número do selo inicial',
    )
    seal_packaging_description = models.TextField(
        blank=True,
        default='',
        verbose_name='Descrição do acondicionamento',
    )
    initial_condition = models.CharField(
        max_length=20,
        choices=SealCondition.choices,
        blank=True,
        default='',
        verbose_name='Condição inicial',
    )
    sealed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='sealed_evidences',
        verbose_name='Selado por',
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
        constraints = [
            # Índice local único por âmbito (ADR-0016 §1): por ocorrência para
            # itens-raiz; por pai para sub-componentes. O contador de sub-itens
            # nunca consome o da ocorrência (evita a regressão tipo SENAITE).
            models.UniqueConstraint(
                fields=['occurrence', 'local_index'],
                condition=models.Q(parent_evidence__isnull=True),
                name='uniq_evidence_root_local_index',
            ),
            models.UniqueConstraint(
                fields=['parent_evidence', 'local_index'],
                condition=models.Q(parent_evidence__isnull=False),
                name='uniq_evidence_child_local_index',
            ),
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
            # Campos nucleares de aquisição + selagem inicial (ADR-0016 §6).
            f'|acq={self.acquisition_hash}'
            f'|acqalgo={self.acquisition_hash_algo}'
            f'|bag={_hash_escape(self.bag_number)}'
            f'|seal0={_hash_escape(self.initial_seal_number)}'
            f'|pack={_hash_escape(self.seal_packaging_description)}'
            f'|cond0={self.initial_condition}'
            f'|sealedby={self.sealed_by_id or ""}'
        )
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """
        Override: apenas permite criação (imutável após registo).
        Calcula o hash de integridade e atribui o ``code`` hierárquico
        (ex.: OC-2026-0001.1.1) no momento do registo — ADR-0016 §1.
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
        # Índice local + código hierárquico (ADR-0016 §1). O índice atribui-se
        # sob lock do âmbito (ocorrência se raiz; pai se sub-componente) para
        # serializar criações concorrentes; o UniqueConstraint do âmbito + retry
        # cobrem a colisão tardia. Os códigos NÃO entram no integrity_hash.
        for _ in range(CODE_MAX_ATTEMPTS):
            try:
                with transaction.atomic():
                    if self.parent_evidence_id is None:
                        Occurrence.objects.select_for_update().filter(
                            pk=self.occurrence_id
                        ).first()
                    else:
                        Evidence.objects.select_for_update().filter(
                            pk=self.parent_evidence_id
                        ).first()
                    self.local_index = _next_local_index(self)
                    self.code = _derive_evidence_code(self)
                    super().save(*args, **kwargs)
                return
            except IntegrityError as exc:
                msg = str(exc).lower()
                if 'code' not in msg and 'local_index' not in msg:
                    raise
                self.code = ''
                self.local_index = 0
                self.pk = None
        raise RuntimeError(
            'Não foi possível gerar um código hierárquico único após várias tentativas.'
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
            iccid = data.get('iccid')
            if iccid:
                try:
                    validate_iccid(iccid)
                except ValidationError as exc:
                    errors['type_specific_data'] = f'iccid: {"; ".join(exc.messages)}'

        if self.type == self.EvidenceType.NETWORK_DEVICE:
            mac = data.get('mac')
            if mac:
                try:
                    validate_mac(mac)
                except ValidationError as exc:
                    errors['type_specific_data'] = f'mac: {"; ".join(exc.messages)}'

        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------------------
# Validador histórico de IMEI (DigitalDevice removido no T05)
# ---------------------------------------------------------------------------


def _digital_device_imei_validator(value):
    r"""Aceita string vazia (campo opcional) ou IMEI Luhn-válido.

    NOTA: o modelo DigitalDevice foi removido no T05 (subsumido por
    Evidence + type_specific_data, ADR-0010). Esta função é RETIDA apenas
    para integridade do histórico de migrações — a migração histórica
    `0014_alter_digitaldevice_imei` referencia-a pelo caminho
    `core.models._digital_device_imei_validator`, e removê-la parte a
    reconstrução do estado das migrações. A validação Luhn de IMEI em uso
    vive agora em Evidence._validate_type_specific_data via validate_imei.
    """
    if not value:
        return
    validate_imei(value)


# ---------------------------------------------------------------------------
# Cadeia de Custódia — LEDGER DE EVENTOS (append-only, NUNCA UPDATE/DELETE)
# ---------------------------------------------------------------------------


class EventType(models.TextChoices):
    """Acto processual registado em cada evento do ledger (ADR-0015/0016, CPP).

    Génese (1.º movimento) por proveniência (ADR-0016 §2):
    - ``APREENSAO_OBJETO`` — objeto físico apreendido (CPP art. 178.º).
    - ``APREENSAO_DADOS`` — dados adquiridos no terreno e copiados para suporte
      autónomo (Lei do Cibercrime art. 16.º/7-b); só para ``DIGITAL_FILE``.
    - ``DERIVACAO_ITEM`` — sub-componente autonomizado (em regra no laboratório);
      só para evidência com ``parent_evidence``.

    Movimentação (ADR-0017 §6): ``TRANSFERENCIA_CUSTODIA`` (push — entrega em
    pessoa) e ``ASSUNCAO_CUSTODIA`` (pull — membro da instituição que tem o
    item armazenado chama-o a si).
    """

    # --- Génese (1.º movimento) ---
    APREENSAO_OBJETO = 'APREENSAO_OBJETO', 'Apreensão de objeto'
    APREENSAO_DADOS = 'APREENSAO_DADOS', 'Apreensão de dados informáticos'
    DERIVACAO_ITEM = 'DERIVACAO_ITEM', 'Autonomizado no laboratório'
    # --- Atos subsequentes ---
    VALIDACAO_APREENSAO = 'VALIDACAO_APREENSAO', 'Validação da apreensão'
    DESPACHO_PERICIA = 'DESPACHO_PERICIA', 'Despacho para perícia'
    INICIO_PERICIA = 'INICIO_PERICIA', 'Início de perícia'
    CONCLUSAO_PERICIA = 'CONCLUSAO_PERICIA', 'Conclusão de perícia'
    TRANSFERENCIA_CUSTODIA = 'TRANSFERENCIA_CUSTODIA', 'Transferência de custódia'
    ASSUNCAO_CUSTODIA = 'ASSUNCAO_CUSTODIA', 'Assunção de custódia'
    RESTITUICAO = 'RESTITUICAO', 'Restituição'  # terminal
    PERDA_FAVOR_ESTADO = 'PERDA_FAVOR_ESTADO', 'Perda a favor do Estado'
    DESTRUICAO = 'DESTRUICAO', 'Destruição'  # terminal


class CustodianType(models.TextChoices):
    """Quem detém a prova APÓS o evento (eixo ortogonal ao event_type)."""

    LOCAL_CRIME = 'LOCAL_CRIME', 'Local do crime'
    OPC = 'OPC', 'Órgão de polícia criminal'
    LAB_PUBLICO = 'LAB_PUBLICO', 'Laboratório público'
    LAB_PRIVADO = 'LAB_PRIVADO', 'Laboratório privado'
    TRIBUNAL = 'TRIBUNAL', 'Tribunal'
    DEPOSITARIO = 'DEPOSITARIO', 'Depositário'
    PROPRIETARIO = 'PROPRIETARIO', 'Proprietário'


# Eventos que fecham o ledger — nenhum evento é aceite depois de um deles.
TERMINAL_EVENTS = {EventType.RESTITUICAO, EventType.DESTRUICAO}

# Eventos de génese (1.º movimento) — exatamente um, na posição 1 (ADR-0016 §2).
GENESIS_EVENTS = {
    EventType.APREENSAO_OBJETO,
    EventType.APREENSAO_DADOS,
    EventType.DERIVACAO_ITEM,
}

# Génese que constitui uma APREENSÃO validável (CPP art. 178.º/6; valida-se uma
# vez). A derivação de item (DERIVACAO_ITEM) não é uma apreensão autónoma.
SEIZURE_GENESIS_EVENTS = {EventType.APREENSAO_OBJETO, EventType.APREENSAO_DADOS}

# Prazo legal de validação da apreensão (CPP Art. 178.º/6). O incumprimento é
# assinalado (validation_overdue) no momento em que o evento VALIDACAO é gravado,
# nunca bloqueado; para leitura/feed (T06) deriva-se dos timestamps gravados.
VALIDATION_DEADLINE = timedelta(hours=72)


def derive_legal_state(eventos_ordenados):
    """Estado legal DERIVADO da sequência de eventos (ADR-0015 §6).

    Função pura — única fonte das strings de estado em todo o backend
    (filtros, serializer, stats) e no frontend/CSS. Recebe a lista de
    registos ``ChainOfCustody`` de uma evidência **ordenada por sequence**
    e devolve uma de:

        a_guarda_opc | validada | em_pericia | pericia_concluida |
        encaminhada | restituida | perdida_favor_estado | destruida

    O estado segue o ÚLTIMO acto relevante (a custódia é não-linear: várias
    perícias e encaminhamentos em ordem livre — CPP Art. 158.º), com duas
    excepções de presença: os terminais e a perda a favor do Estado.

    - último DESTRUICAO/RESTITUICAO → ``destruida``/``restituida`` (fecham).
    - existe PERDA_FAVOR_ESTADO (sem terminal posterior) → ``perdida_favor_estado``
      (estatuto legal forte; domina mesmo uma perícia em curso).
    - último INICIO_PERICIA → ``em_pericia``; último CONCLUSAO_PERICIA → ``pericia_concluida``.
    - último TRANSFERENCIA_CUSTODIA/ASSUNCAO_CUSTODIA → ``a_guarda_opc`` se de
      volta ao OPC, senão ``encaminhada`` (lab/tribunal/depositário/proprietário).
    - DESPACHO_PERICIA/VALIDACAO_APREENSAO/génese como último → patamar atingido
      (``validada`` se já houve validação, senão ``a_guarda_opc``).
    """
    if not eventos_ordenados:
        return 'a_guarda_opc'

    tipos = [r.event_type for r in eventos_ordenados]
    ultimo = eventos_ordenados[-1]
    et = ultimo.event_type

    # Terminais (pelo último evento) fecham o ledger.
    if et == EventType.DESTRUICAO:
        return 'destruida'
    if et == EventType.RESTITUICAO:
        return 'restituida'

    # Perda a favor do Estado: estatuto legal forte — domina enquanto presente
    # (terminal posterior já tratado acima), incl. sobre uma perícia em curso.
    if EventType.PERDA_FAVOR_ESTADO in tipos:
        return 'perdida_favor_estado'

    # A partir daqui, o estado segue o ÚLTIMO acto relevante (não-linearidade).
    if et == EventType.INICIO_PERICIA:
        return 'em_pericia'
    if et == EventType.CONCLUSAO_PERICIA:
        return 'pericia_concluida'
    if et in (EventType.TRANSFERENCIA_CUSTODIA, EventType.ASSUNCAO_CUSTODIA):
        # De volta ao OPC = à guarda do OPC; qualquer outro custódio = encaminhada.
        return 'a_guarda_opc' if ultimo.custodian_type == CustodianType.OPC else 'encaminhada'

    # DESPACHO_PERICIA / VALIDACAO_APREENSAO / génese como último: patamar atingido.
    if EventType.VALIDACAO_APREENSAO in tipos:
        return 'validada'
    return 'a_guarda_opc'


# Conjunto canónico de estados legais derivados (para validação de filtros).
LEGAL_STATES = frozenset(
    {
        'a_guarda_opc',
        'validada',
        'em_pericia',
        'pericia_concluida',
        'encaminhada',
        'restituida',
        'perdida_favor_estado',
        'destruida',
    }
)


def _hash_escape(value):
    r"""Escapa separadores do hash em campos de texto livre (ADR-0013).

    Ordem fixa e irreversível: backslash PRIMEIRO, depois os separadores
    ``|`` e ``,``. Impede que ``location_name``/``storage_location`` colidam
    com a estrutura da string de dados do ``record_hash``.
    """
    return (value or '').replace('\\', '\\\\').replace('|', '\\|').replace(',', '\\,')


def _hash_str(value):
    """Serializa um campo do hash: None → '' (dado em falta), determinístico."""
    return '' if value is None else str(value)


class ChainOfCustody(models.Model):
    """
    Registo imutável de UM evento do ledger de custódia (ADR-0015).

    Ledger de eventos (não máquina de estados): cada registo documenta um
    acto processual da trajetória da prova — ``event_type`` diz *o que
    aconteceu*, ``custodian_type`` diz *em mãos de quem ficou*, e o GPS +
    ``location_name``/``storage_location`` dizem *onde* (ADR-0013). O estado
    legal é DERIVADO da leitura do log (:func:`derive_legal_state`), nunca
    gravado como coluna.

    Regras:
    - Append-only: save() só permite criação, nunca atualização.
    - delete() está bloqueado.
    - Cada registo inclui hash SHA-256 encadeado com o anterior (ADR-0013).
    - Guardas mínimas no clean() (não um grafo): 1.º evento = APREENSAO;
      VALIDACAO exige APREENSAO e só uma vez (≤72h assinalado); INICIO_PERICIA
      exige DESPACHO_PERICIA prévio; terminais (RESTITUICAO/DESTRUICAO) fecham.
    """

    # Enums expostos também como atributos de classe para retrocompatibilidade
    # de imports antigos (``ChainOfCustody.EventType``).
    EventType = EventType
    CustodianType = CustodianType

    code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Código do movimento',
        help_text='Movimento do item: {código do item}-M{sequência} (ex.: OC-2026-0001.1-M01).',
    )
    evidence = models.ForeignKey(
        Evidence,
        on_delete=models.PROTECT,
        related_name='custody_chain',
        verbose_name='Evidência',
    )
    event_type = models.CharField(
        max_length=25,
        choices=EventType.choices,
        verbose_name='Tipo de evento',
    )
    custodian_type = models.CharField(
        max_length=20,
        choices=CustodianType.choices,
        blank=True,
        default='',
        verbose_name='Custódio após o evento',
    )
    custodian_institution = models.ForeignKey(
        'Institution',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='custody_events',
        verbose_name='Instituição custódia (titular)',
        help_text='Instituição à guarda de quem o item fica após o evento (ADR-0017).',
    )
    custodian_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='custody_holdings',
        verbose_name='Custódio pessoal após o evento',
        help_text=(
            'Pessoa que detém ativamente o item após o evento. Null = custódia '
            'institucional (armazenado; qualquer membro pode assumir) — ADR-0017.'
        ),
    )
    location_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Local (POI OSM)',
    )
    storage_location = models.CharField(
        max_length=120,
        blank=True,
        default='',
        verbose_name='Localização interna de armazenamento',
    )
    gps_lat = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        verbose_name='Latitude GPS (evento)',
    )
    gps_lng = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        verbose_name='Longitude GPS (evento)',
    )
    gps_accuracy_m = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Precisão GPS reportada (m)',
        help_text=(
            'Raio de incerteza em metros reportado pelo dispositivo. '
            'Metadado de precisão — não altera a coordenada gravada.'
        ),
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='custody_actions',
        verbose_name='Responsável pelo evento',
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        verbose_name='Data/hora do evento',
    )
    observations = models.TextField(
        blank=True,
        default='',
        verbose_name='Observações',
    )
    # --- Selagem por-evento (a cada handover — ADR-0016 §4) ---
    sealed = models.BooleanField(
        default=False,
        verbose_name='Selado',
    )
    seal_condition_on_receipt = models.CharField(
        max_length=20,
        choices=Evidence.SealCondition.choices,
        blank=True,
        default='',
        verbose_name='Condição do selo na receção',
    )
    new_seal_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Novo número de selo',
        help_text='Re-selagem gera um novo número (o selo não é fixo por item).',
    )
    relinquished_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='custody_relinquishments',
        verbose_name='Entregue por',
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

    # Flag DERIVADA (não-coluna): assinala VALIDACAO fora do prazo de 72h.
    # Calculada em clean(); facto juridicamente relevante, não bloqueia.
    validation_overdue = False

    def __str__(self):
        ev_label = self.evidence.code if self.evidence_id else f'#{self.evidence_id}'
        evento = self.get_event_type_display() if self.event_type else '(evento)'
        custodio = self.get_custodian_type_display() if self.custodian_type else '—'
        return f'Item {ev_label}: {evento} → {custodio}'

    def clean(self):
        """Guardas mínimas do ledger de eventos (ADR-0015) + quantização GPS.

        Não é um grafo de transições: aplica apenas as restrições legais
        reais, lendo os eventos anteriores da mesma evidência (dentro do
        ``select_for_update`` de :meth:`save`).
        """
        super().clean()

        prior = list(
            ChainOfCustody.objects.filter(evidence=self.evidence).order_by('sequence')
        )
        prior_types = [r.event_type for r in prior]

        evidence = self.evidence

        # Génese (1.º evento): exatamente um evento de génese, na posição 1,
        # coerente com a proveniência da evidência (ADR-0016 §2).
        if not prior:
            if self.event_type not in GENESIS_EVENTS:
                raise ValidationError(
                    {
                        'event_type': (
                            'O primeiro evento tem de ser de génese (apreensão de '
                            'objeto/dados ou derivação de item).'
                        )
                    }
                )
            # APREENSAO_DADOS só para DIGITAL_FILE (cópia em suporte autónomo).
            if (
                self.event_type == EventType.APREENSAO_DADOS
                and evidence.type != Evidence.EvidenceType.DIGITAL_FILE
            ):
                raise ValidationError(
                    {
                        'event_type': (
                            'APREENSAO_DADOS só é válida para evidência do tipo '
                            'DIGITAL_FILE (cópia de dados).'
                        )
                    }
                )
            # DERIVACAO_ITEM só para sub-componente (tem evidência-pai).
            if (
                self.event_type == EventType.DERIVACAO_ITEM
                and evidence.parent_evidence_id is None
            ):
                raise ValidationError(
                    {
                        'event_type': (
                            'DERIVACAO_ITEM só é válida como génese de um '
                            'sub-componente (com evidência-pai).'
                        )
                    }
                )
            # APREENSAO_OBJETO só para item-raiz (sub-componentes derivam-se).
            if (
                self.event_type == EventType.APREENSAO_OBJETO
                and evidence.parent_evidence_id is not None
            ):
                raise ValidationError(
                    {
                        'event_type': (
                            'Um sub-componente (com evidência-pai) entra por '
                            'DERIVACAO_ITEM, não por APREENSAO_OBJETO.'
                        )
                    }
                )
            # Derivação de pai com evento terminal é proibida (ADR-0016 edge 2).
            if self.event_type == EventType.DERIVACAO_ITEM and ChainOfCustody.objects.filter(
                evidence_id=evidence.parent_evidence_id,
                event_type__in=TERMINAL_EVENTS,
            ).exists():
                raise ValidationError(
                    {
                        'event_type': (
                            'Não se autonomiza um componente de prova já '
                            'restituída/destruída (evidência-pai fechada).'
                        )
                    }
                )
        elif self.event_type in GENESIS_EVENTS:
            raise ValidationError(
                {'event_type': 'Um evento de génese só pode ser o primeiro evento.'}
            )

        # Terminais fecham o ledger — nenhum evento depois de RESTITUICAO/DESTRUICAO,
        # em QUALQUER posição (semântica de presença, ADR-0015; robusto a sequences
        # fora de ordem hipotéticas).
        if any(t in TERMINAL_EVENTS for t in prior_types):
            raise ValidationError(
                {
                    'event_type': (
                        'A evidência tem um evento terminal (restituição/destruição); '
                        'não são aceites mais eventos.'
                    )
                }
            )

        # VALIDACAO_APREENSAO: exige apreensão prévia, uma vez, ≤72h (assinalado).
        if self.event_type == EventType.VALIDACAO_APREENSAO:
            seizure = next(
                (r for r in prior if r.event_type in SEIZURE_GENESIS_EVENTS), None
            )
            if seizure is None:
                raise ValidationError(
                    {'event_type': 'VALIDACAO_APREENSAO requer uma apreensão prévia.'}
                )
            if EventType.VALIDACAO_APREENSAO in prior_types:
                raise ValidationError(
                    {'event_type': 'A apreensão só pode ser validada uma vez.'}
                )
            ts = self.timestamp or timezone.now()
            self.validation_overdue = ts - seizure.timestamp > VALIDATION_DEADLINE

        # INICIO_PERICIA: exige DESPACHO_PERICIA anterior (CPP Art. 154.º/158.º).
        if (
            self.event_type == EventType.INICIO_PERICIA
            and EventType.DESPACHO_PERICIA not in prior_types
        ):
            raise ValidationError(
                {
                    'event_type': (
                        'INICIO_PERICIA requer um DESPACHO_PERICIA anterior '
                        '(CPP Art. 154.º).'
                    )
                }
            )

        # Coerência GPS: lat e lng ambas presentes ou ambas ausentes (como Occurrence).
        if (self.gps_lat is not None) != (self.gps_lng is not None):
            raise ValidationError(
                'Latitude e longitude devem ser ambas definidas ou ambas vazias.'
            )

        # Quantização GPS a 7 casas (ADR-0013), ANTES do hash — garante
        # valor em memória == valor na BD == valor recalculado pelo perito.
        q = Decimal('0.0000001')
        if self.gps_lat is not None:
            self.gps_lat = self.gps_lat.quantize(q)
        if self.gps_lng is not None:
            self.gps_lng = self.gps_lng.quantize(q)

    def compute_record_hash(self, previous_hash=None):
        """
        Calcula o ``record_hash`` SHA-256 encadeado (fórmula única, ADR-0013).

        Determinístico e puro: recebe ``previous_hash`` como parâmetro para
        não depender de queries à DB. Qualquer perito independente pode
        recalcular o hash a partir dos campos relidos da BD e do hash do
        registo anterior, verificando a integridade da cadeia (ISO/IEC 27037).

        Fórmula (17 segmentos por ``|``, ordem fixa — contrato irreversível):

            previous_hash | seq=N | evidence_id | event_type | custodian_type |
            agent_id | timestamp_iso | gps_lat | gps_lng | gps_accuracy_m |
            esc(location_name) | esc(storage_location) | observations |
            sealed=0/1 | seal_condition_on_receipt | esc(new_seal_number) |
            relinquished_by_id   (selo por-evento — ADR-0016 §6)

        Regras de serialização (ADR-0013):
        - Todos os campos entram SEMPRE; campo ``None`` → string vazia
          (``_hash_str``) na sua posição fixa (dado em falta determinístico).
        - ``event_type`` e ``custodian_type`` são enums controlados (sem
          separadores) → entram CRUS.
        - ``location_name`` e ``storage_location`` são texto livre → passam
          por ``_hash_escape`` (``\\`` → ``\\\\``, ``|`` → ``\\|``,
          ``,`` → ``\\,``), impedindo colisão com os separadores.
        - ``gps_lat``/``gps_lng`` já quantizados a 7 casas no ``clean()``.

        Args:
            previous_hash: hash do registo anterior (hex string). Se None,
                cai para leitura da DB via ``_lookup_previous_hash()`` apenas
                para compatibilidade com chamadores que não o passam; os novos
                (incluindo ``save()``) fornecem-no dentro do
                ``transaction.atomic()`` + ``select_for_update()`` (fix B-C2).
        """
        if previous_hash is None:
            # NOTE: impure path — reads ChainOfCustody via last-record query.
            # Mantido para compatibilidade com código legacy que não passa
            # previous_hash. Novas chamadas (incluindo save() abaixo) devem
            # passar o valor explicitamente dentro do transaction.atomic()
            # + select_for_update().
            previous_hash = self._lookup_previous_hash()

        data = (
            f'{previous_hash}|'
            f'seq={self.sequence}|'
            f'{self.evidence_id}|'
            f'{self.event_type}|'
            f'{self.custodian_type}|'
            f'{self.agent_id}|'
            f'{self.timestamp.isoformat()}|'
            f'{_hash_str(self.gps_lat)}|'
            f'{_hash_str(self.gps_lng)}|'
            f'{_hash_str(self.gps_accuracy_m)}|'
            f'{_hash_escape(self.location_name)}|'
            f'{_hash_escape(self.storage_location)}|'
            f'{self.observations}'
            # Campos de selo por-evento (ADR-0016 §6).
            f'|sealed={int(self.sealed)}'
            f'|sealcond={self.seal_condition_on_receipt}'
            f'|newseal={_hash_escape(self.new_seal_number)}'
            f'|relinq={self.relinquished_by_id or ""}'
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
        O ``sequence`` é determinado automaticamente a partir do último
        registo da evidência — nunca confiamos em valor enviado pelo cliente.
        O timestamp usa timezone.now() do servidor (NTP-synced).
        Valida as guardas (clean) e calcula o hash encadeado antes de gravar.

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

                    # Auto-determinar sequence a partir do último registo.
                    # select_for_update() garante serialização entre escritores
                    # concorrentes na mesma evidência quando já existem registos.
                    last_record = (
                        ChainOfCustody.objects.select_for_update()
                        .filter(evidence=self.evidence)
                        .order_by('-sequence')
                        .first()
                    )
                    self.sequence = (last_record.sequence + 1) if last_record else 1

                    # Timestamp sempre do servidor (NTP-synced) — nunca do cliente
                    self.timestamp = timezone.now()

                    if not self.code:
                        # Código do movimento = {código do item}-M{sequência}
                        # (ADR-0016 §1). Não há contador próprio da cadeia: a
                        # identidade do movimento é a do item + o nº de sequência.
                        self.code = f'{self.evidence.code}-M{self.sequence:02d}'

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
            'Não foi possível gerar um código de movimento único após várias tentativas.'
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
