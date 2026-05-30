"""
ForensiQ — Factories para testes (Factory Boy).

Fornece factories declarativas para construir objectos de domínio
reutilizáveis em testes — reduz boilerplate em ``setUp`` e torna os
testes mais legíveis (``UserFactory.create(profile='EXPERT')`` em vez
de ``User.objects.create_user(..., profile=User.Profile.EXPERT, ...)``).

Convenção de localização: em vez de converter ``core/tests.py`` num
package (o que obrigaria a mover também ``tests_api.py``,
``tests_frontend.py``, ``tests_pdf.py``), mantemos os testes como
módulos irmãos e colocamos as factories em ``core/tests_factories.py``
— importável por qualquer test suite (``from core.tests_factories
import UserFactory``).

Perfis de utilizador disponíveis (ADR: só existem dois perfis):
- :class:`UserFactory`    — perfil AGENT (first responder) por omissão.
- :class:`ExpertFactory`  — perfil EXPERT (perito forense digital).

Nota: ``PERITO`` / ``COORDINATOR`` não existem em
``User.Profile``. Mantemos ``PeritoFactory`` como alias histórico de
``ExpertFactory`` para evitar partir testes legados que o importem.

Factories de evidência seguem a taxonomia digital-first (ADR-0010):
- :class:`EvidenceMobileFactory`   — MOBILE_DEVICE (smartphone/telemóvel).
- :class:`EvidenceVehicleFactory`  — VEHICLE (container para componentes).
- :class:`EvidenceSimCardFactory`  — SIM_CARD (sub-componente típico).
"""

from decimal import Decimal

import factory
from django.utils import timezone

from core.models import (
    ChainOfCustody,
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    DigitalDevice,
    Evidence,
    Occurrence,
    User,
)


def _luhn_complete(prefix14: str) -> str:
    """Anexa o check digit de Luhn a um prefixo de 14 dígitos para produzir
    um IMEI válido. Usado pelas factories para que dispositivos criados em
    testes passem o validador de `DigitalDevice.imei` (que exige checksum
    via `_digital_device_imei_validator`).
    """
    total = 0
    for i, ch in enumerate(reversed(prefix14)):
        digit = int(ch)
        # No número final (15 dígitos), prefix14[i] (i a partir do fim) ocupa
        # a posição rev = i+1; posições ímpares são duplicadas.
        if (i + 1) % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    check = (10 - (total % 10)) % 10
    return f'{prefix14}{check}'


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
    profile = User.Profile.AGENT
    badge_number = factory.Sequence(lambda n: f'AGT-{n:05d}')
    phone = factory.Faker('phone_number', locale='pt_PT')
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Usa ``create_user`` para garantir hashing da password."""
        password = kwargs.pop('password', 'TestPass123!')
        user = model_class.objects.create_user(*args, password=password, **kwargs)
        return user


class ExpertFactory(UserFactory):
    """Perito forense digital — acesso a peritagens e pareceres técnicos."""

    username = factory.Sequence(lambda n: f'perito_{n:04d}')
    profile = User.Profile.EXPERT
    badge_number = factory.Sequence(lambda n: f'PJ-{n:05d}')


# Alias retro-compatível: o domínio histórico falava em "perito"; hoje
# o modelo usa ``EXPERT``. Mantemos ``PeritoFactory`` para não partir
# imports legados.
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
    gps_lat = Decimal('38.7223340')
    gps_lng = Decimal('-9.1393366')
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
    gps_lat = Decimal('38.7223340')
    gps_lng = Decimal('-9.1393366')
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
    gps_lat = Decimal('38.7223340')
    gps_lng = Decimal('-9.1393366')
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
# Dispositivo digital
# ---------------------------------------------------------------------------


class DigitalDeviceFactory(factory.django.DjangoModelFactory):
    """Dispositivo digital associado a uma evidência (``MOBILE_DEVICE``)."""

    class Meta:
        model = DigitalDevice

    evidence = factory.SubFactory(EvidenceMobileFactory)
    type = DigitalDevice.DeviceType.SMARTPHONE
    brand = factory.Faker(
        'random_element',
        elements=('Samsung', 'Apple', 'Xiaomi', 'Google'),
    )
    model = factory.Sequence(lambda n: f'Model-{n:04d}')
    condition = DigitalDevice.DeviceCondition.FUNCTIONAL
    serial_number = factory.Sequence(lambda n: f'DEV-SN-{n:010d}')
    # IMEI sequencial com check digit de Luhn calculado — o modelo exige
    # checksum válido via `_digital_device_imei_validator`. Testes que
    # queiram IMEIs inválidos devem passar explicitamente um valor.
    imei = factory.Sequence(lambda n: _luhn_complete(f'{n:014d}'))


# ---------------------------------------------------------------------------
# Cadeia de custódia
# ---------------------------------------------------------------------------


class ChainOfCustodyFactory(factory.django.DjangoModelFactory):
    """Primeira transição '' → APREENDIDA (máquina de estados)."""

    class Meta:
        model = ChainOfCustody

    evidence = factory.SubFactory(EvidenceMobileFactory)
    previous_state = ''
    new_state = ChainOfCustody.CustodyState.APREENDIDA
    agent = factory.SubFactory(UserFactory)
    observations = 'Apreensão inicial no local (factory).'


__all__ = [
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
    'DigitalDeviceFactory',
    'ChainOfCustodyFactory',
]
