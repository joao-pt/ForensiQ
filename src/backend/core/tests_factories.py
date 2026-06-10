"""
ForensiQ — Factories para testes (Factory Boy).

Fornece factories declarativas para construir objectos de domínio
reutilizáveis em testes — reduz boilerplate em ``setUp`` e torna os
testes mais legíveis (``UserFactory.create(profile='FORENSIC_EXPERT')``
em vez de ``User.objects.create_user(..., profile=..., ...)``).

Convenção de localização: em vez de converter ``core/tests.py`` num
package (o que obrigaria a mover também ``tests_api.py``,
``tests_frontend.py``, ``tests_pdf.py``), mantemos os testes como
módulos irmãos e colocamos as factories em ``core/tests_factories.py``
— importável por qualquer test suite (``from core.tests_factories
import UserFactory``).

Perfis de utilizador (função — ADR-0017):
- :class:`UserFactory`    — FIRST_RESPONDER (primeiro interveniente) por omissão.
- :class:`ExpertFactory`  — FORENSIC_EXPERT (perito forense digital).

Nota: ``PeritoFactory`` mantém-se como alias de ``ExpertFactory`` para não
partir imports legados.

Factories de evidência seguem a taxonomia digital-first (ADR-0010):
- :class:`EvidenceMobileFactory`   — MOBILE_DEVICE (smartphone/telemóvel).
- :class:`EvidenceVehicleFactory`  — VEHICLE (container para componentes).
- :class:`EvidenceSimCardFactory`  — SIM_CARD (sub-componente típico).
"""

from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from core.models import (
    AuditLog,
    ChainOfCustody,
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    Evidence,
    Institution,
    InstitutionType,
    Occurrence,
    Portador,
    User,
)

# ---------------------------------------------------------------------------
# Constantes canónicas de teste (fontes ÚNICAS — auditoria D111/D121/D107)
# ---------------------------------------------------------------------------

# Password default da UserFactory e do login real (antes 48 literais em 12
# ficheiros — D111).
TEST_PASSWORD = 'TestPass123!'

# Coordenada-fixture de Lisboa (Marquês de Pombal) usada pelas factories,
# payloads de API e E2E (antes literal em 7 ficheiros — D121).
LISBOA_GPS = (Decimal('38.7223340'), Decimal('-9.1393366'))
LISBOA_GPS_STR = ('38.7223340', '-9.1393366')

# Coordenada do laboratório de Lisboa repetida byte-a-byte em 4 ficheiros
# (default da InstitutionFactory — D109).
LAB_LISBOA_GPS = (Decimal('38.7256000'), Decimal('-9.1430000'))

# IMEI Luhn-válido canónico dos testes de lookup (antes 23 ocorrências — D107).
VALID_IMEI = '490154203237518'

# ---------------------------------------------------------------------------
# Utilizadores
# ---------------------------------------------------------------------------


class UserFactory(factory.django.DjangoModelFactory):
    """Agente (first responder) autenticado. Uso: ``UserFactory.create()``."""

    class Meta:
        model = User
        django_get_or_create = ('username',)

    username = factory.Sequence(lambda n: f'agente_{n:04d}')
    first_name = factory.Faker('first_name', locale='pt_PT')
    last_name = factory.Faker('last_name', locale='pt_PT')
    email = factory.LazyAttribute(lambda o: f'{o.username}@forensiq.test')
    profile = User.Profile.FIRST_RESPONDER
    badge_number = factory.Sequence(lambda n: f'AGT-{n:05d}')
    phone = factory.Faker('phone_number', locale='pt_PT')
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Usa ``create_user`` para garantir hashing da password."""
        password = kwargs.pop('password', TEST_PASSWORD)
        user = model_class.objects.create_user(*args, password=password, **kwargs)
        return user


class ExpertFactory(UserFactory):
    """Perito forense digital — acesso a peritagens e pareceres técnicos."""

    username = factory.Sequence(lambda n: f'perito_{n:04d}')
    profile = User.Profile.FORENSIC_EXPERT
    clearance = User.Clearance.NACIONAL
    badge_number = factory.Sequence(lambda n: f'PJ-{n:05d}')


# Alias retro-compatível: o domínio histórico falava em "perito"; o modelo
# usa ``FORENSIC_EXPERT``. Mantém-se ``PeritoFactory`` para não partir imports.
PeritoFactory = ExpertFactory


# ---------------------------------------------------------------------------
# Taxonomia de crimes (dados de referência — ADR-0014)
# ---------------------------------------------------------------------------


class CrimeCategoriaFactory(factory.django.DjangoModelFactory):
    """Categoria N1 (default: 1 — Crimes contra as pessoas)."""

    class Meta:
        model = CrimeCategoria
        django_get_or_create = ('codigo',)

    codigo = 1
    nome = 'Código Penal - Crimes contra as pessoas'


class CrimeSubcategoriaFactory(factory.django.DjangoModelFactory):
    """Subcategoria N2 (default: 1 — Crimes contra a vida)."""

    class Meta:
        model = CrimeSubcategoria
        django_get_or_create = ('codigo',)

    codigo = 1
    nome = 'Crimes contra a vida'
    categoria = factory.SubFactory(CrimeCategoriaFactory)


class CrimeTipoFactory(factory.django.DjangoModelFactory):
    """Tipo N3 (default: 1 — Homicídio voluntário consumado)."""

    class Meta:
        model = CrimeTipo
        django_get_or_create = ('codigo',)

    codigo = 1
    descritivo = 'Homicidio voluntário consumado'
    subcategoria = factory.SubFactory(CrimeSubcategoriaFactory)
    is_active = True


# ---------------------------------------------------------------------------
# Ocorrência
# ---------------------------------------------------------------------------


class OccurrenceFactory(factory.django.DjangoModelFactory):
    """Ocorrência com coordenadas GPS em Lisboa (Marquês de Pombal)."""

    class Meta:
        model = Occurrence
        django_get_or_create = ('number',)

    number = factory.Sequence(lambda n: f'NUIPC-2026-{n:06d}')
    description = factory.Faker(
        'sentence',
        nb_words=12,
        locale='pt_PT',
    )
    date_time = factory.LazyFunction(timezone.now)
    gps_lat = LISBOA_GPS[0]
    gps_lng = LISBOA_GPS[1]
    address = 'Marquês de Pombal, Lisboa'
    agent = factory.SubFactory(UserFactory)
    crime_type = factory.SubFactory(CrimeTipoFactory)


# ---------------------------------------------------------------------------
# Evidências — taxonomia digital-first (ADR-0010)
# ---------------------------------------------------------------------------


class EvidenceMobileFactory(factory.django.DjangoModelFactory):
    """Evidência do tipo ``MOBILE_DEVICE`` (telemóvel/smartphone)."""

    class Meta:
        model = Evidence

    occurrence = factory.SubFactory(OccurrenceFactory)
    type = Evidence.EvidenceType.MOBILE_DEVICE
    description = factory.Faker(
        'sentence',
        nb_words=10,
        locale='pt_PT',
    )
    serial_number = factory.Sequence(lambda n: f'IMEI-SN-{n:010d}')
    timestamp_seizure = factory.LazyFunction(timezone.now)
    gps_lat = LISBOA_GPS[0]
    gps_lng = LISBOA_GPS[1]
    agent = factory.SubFactory(UserFactory)


class EvidenceVehicleFactory(factory.django.DjangoModelFactory):
    """Evidência do tipo ``VEHICLE`` — container que pode ter sub-componentes
    (ECU, dashcam, telemetry box, etc.)."""

    class Meta:
        model = Evidence

    occurrence = factory.SubFactory(OccurrenceFactory)
    type = Evidence.EvidenceType.VEHICLE
    description = factory.Faker(
        'sentence',
        nb_words=10,
        locale='pt_PT',
    )
    # Número de série genérico do container-veículo. NOTA: o campo
    # ``serial_number`` é uma string livre; o VIN (ISO 3779, 17 chars,
    # sem I/O/Q) vive em ``type_specific_data['vin']``. Prefixo neutro
    # ``VEH-SN-`` evita confundir leitores dos testes.
    serial_number = factory.Sequence(lambda n: f'VEH-SN-{n:010d}')
    timestamp_seizure = factory.LazyFunction(timezone.now)
    gps_lat = LISBOA_GPS[0]
    gps_lng = LISBOA_GPS[1]
    agent = factory.SubFactory(UserFactory)


class EvidenceSimCardFactory(factory.django.DjangoModelFactory):
    """Evidência do tipo ``SIM_CARD`` — sub-componente típico.

    Quando usado como componente de um telemóvel passa-se
    ``parent_evidence=<mobile>`` no override::

        mobile = EvidenceMobileFactory()
        sim = EvidenceSimCardFactory(parent_evidence=mobile,
                                     occurrence=mobile.occurrence)
    """

    class Meta:
        model = Evidence

    occurrence = factory.SubFactory(OccurrenceFactory)
    type = Evidence.EvidenceType.SIM_CARD
    description = factory.Faker(
        'sentence',
        nb_words=8,
        locale='pt_PT',
    )
    serial_number = factory.Sequence(lambda n: f'ICCID-{n:019d}')
    timestamp_seizure = factory.LazyFunction(timezone.now)
    # SIM cards não costumam ter GPS próprio — herdam do pai.
    gps_lat = None
    gps_lng = None
    agent = factory.SubFactory(UserFactory)


# ---------------------------------------------------------------------------
# Instituições e portadores (auditoria D109)
# ---------------------------------------------------------------------------


class InstitutionFactory(factory.django.DjangoModelFactory):
    """Instituição custódia — default: laboratório público de Lisboa (a forma
    que 4 ficheiros repetiam byte-a-byte). Variante OPC em
    :class:`OpcInstitutionFactory`."""

    class Meta:
        model = Institution
        django_get_or_create = ('sigla',)

    name = factory.Sequence(lambda n: f'Laboratório Forense {n:03d}')
    sigla = factory.Sequence(lambda n: f'LAB-{n:03d}')
    type = InstitutionType.LAB_PUBLICO
    gps_lat = LAB_LISBOA_GPS[0]
    gps_lng = LAB_LISBOA_GPS[1]
    is_active = True


class OpcInstitutionFactory(InstitutionFactory):
    """Órgão de polícia criminal (esquadra/diretoria)."""

    name = factory.Sequence(lambda n: f'Esquadra PSP {n:03d}')
    sigla = factory.Sequence(lambda n: f'PSP-{n:03d}')
    type = InstitutionType.OPC


class PortadorFactory(factory.django.DjangoModelFactory):
    """Portador de prova (ADR-0016 v2) — quem conduz entre pontos de controlo."""

    class Meta:
        model = Portador
        django_get_or_create = ('matricula',)

    matricula = factory.Sequence(lambda n: f'PORT-{n:05d}')
    nome = factory.Faker('first_name', locale='pt_PT')
    apelido = factory.Faker('last_name', locale='pt_PT')
    posto = 'Agente'


# ---------------------------------------------------------------------------
# Cadeia de custódia
# ---------------------------------------------------------------------------


class ChainOfCustodyFactory(factory.django.DjangoModelFactory):
    """Primeiro evento do ledger: APREENSAO_OBJETO pelo OPC (ADR-0015)."""

    class Meta:
        model = ChainOfCustody

    evidence = factory.SubFactory(EvidenceMobileFactory)
    event_type = ChainOfCustody.EventType.APREENSAO_OBJETO
    custodian_type = ChainOfCustody.CustodianType.OPC
    agent = factory.SubFactory(UserFactory)
    observations = 'Apreensão inicial no local (factory).'


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


class AuditLogFactory(factory.django.DjangoModelFactory):
    """Registo de auditoria (append-only, ISO/IEC 27037).

    ``timestamp`` (``auto_now_add``) e ``sequence`` (atribuído no ``save()``
    do modelo como ``max(sequence)+1``) são deixados ao modelo — não os
    definimos na factory para não colidir com a invariante de sequência
    global monótona.
    """

    class Meta:
        model = AuditLog

    user = factory.SubFactory(UserFactory)
    action = AuditLog.Action.VIEW
    resource_type = AuditLog.ResourceType.EVIDENCE
    resource_id = factory.Sequence(lambda n: n + 1)
    ip_address = '127.0.0.1'
    correlation_id = factory.Sequence(lambda n: f'test-corr-{n:08d}')
    details = factory.LazyFunction(dict)


# ---------------------------------------------------------------------------
# Helpers de domínio partilhados (auditoria D104/D108/D110)
# ---------------------------------------------------------------------------


def make_user(username, profile, clearance=User.Clearance.NORMAL):
    """Atalho de utilizador com perfil/clearance explícitos (antes ``_user``
    re-implementado em tests_access e cross-importado por 7 módulos — D104)."""
    return UserFactory(username=username, profile=profile, clearance=clearance)


def make_occ(agent, n):
    """Ocorrência mínima de testes de acesso (antes ``_occ`` — D104)."""
    return OccurrenceFactory(
        number=f'NUIPC-ACC-{n}',
        description='caso de teste de acesso',
        agent=agent,
    )


def make_evidence(occ, agent, etype=Evidence.EvidenceType.MOBILE_DEVICE, parent=None):
    """Item mínimo, sem GPS próprio (antes ``_evidence`` — D104)."""
    return Evidence.objects.create(
        occurrence=occ,
        type=etype,
        description='item de teste',
        timestamp_seizure=timezone.now(),
        agent=agent,
        parent_evidence=parent,
    )


def make_event(ev, agent, *, event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
               inst=None, holder=None, **kwargs):
    """Evento de ledger com custódio institucional opcional (antes ``_event`` — D104)."""
    return ChainOfCustody.objects.create(
        evidence=ev,
        event_type=event_type,
        agent=agent,
        custodian_institution=inst,
        custodian_user=holder,
        **kwargs,
    )


def make_chain(evidence, *events, agent=None):
    """Escadinha canónica de eventos do ledger numa chamada (auditoria D110).

    Cada item é um ``EventType`` ou um par ``(EventType, kwargs)`` — os kwargs
    (``custodian_type``, ``custodian_institution``, ``bearer``, GPS, …) vão
    diretos ao ``create``. As guardas do modelo continuam a valer, pelo que a
    ordem tem de ser processualmente válida (génese → validação → …).
    """
    agent = agent or evidence.agent
    records = []
    for item in events:
        event_type, kwargs = item if isinstance(item, (tuple, list)) else (item, {})
        records.append(
            ChainOfCustody.objects.create(
                evidence=evidence, event_type=event_type, agent=agent, **kwargs
            )
        )
    return records


def backdate(obj, **delta):
    """Retrodata ``timestamp`` (``auto_now_add``) via ``.update()`` — o ÚNICO
    caminho que não dispara o ``save()`` imutável (auditoria D108). ``delta``
    são kwargs de ``timedelta`` (``days=3``, ``hours=2``, …)."""
    type(obj).objects.filter(pk=obj.pk).update(timestamp=timezone.now() - timedelta(**delta))
    obj.refresh_from_db()
    return obj


__all__ = [
    'TEST_PASSWORD',
    'LISBOA_GPS',
    'LISBOA_GPS_STR',
    'LAB_LISBOA_GPS',
    'VALID_IMEI',
    'UserFactory',
    'ExpertFactory',
    'PeritoFactory',
    'CrimeCategoriaFactory',
    'CrimeSubcategoriaFactory',
    'CrimeTipoFactory',
    'OccurrenceFactory',
    'EvidenceMobileFactory',
    'EvidenceVehicleFactory',
    'EvidenceSimCardFactory',
    'InstitutionFactory',
    'OpcInstitutionFactory',
    'PortadorFactory',
    'ChainOfCustodyFactory',
    'AuditLogFactory',
    'make_user',
    'make_occ',
    'make_evidence',
    'make_event',
    'make_chain',
    'backdate',
]
