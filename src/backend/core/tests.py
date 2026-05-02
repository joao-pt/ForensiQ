"""
ForensiQ — Testes unitários para os modelos core.

Testa:
- Criação de utilizadores (AGENT e EXPERT)
- Criação de ocorrências e evidências
- Hash SHA-256 automático em evidências
- Máquina de estados da cadeia de custódia
- Imutabilidade da cadeia de custódia (append-only)

Nota de taxonomia (ver ADR-0010): os tipos de Evidence passaram de 5
genéricos para 18 digital-first. Tradução dos usos históricos:
DIGITAL_DEVICE → MOBILE_DEVICE / COMPUTER (dispositivos autónomos)
DOCUMENT       → OTHER_DIGITAL (fallback — papel deixou de existir)
PHOTO          → DIGITAL_FILE  (captura / fotografia digital)
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import (
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
    User,
)


class UserModelTest(TestCase):
    """Testes para o modelo User personalizado."""

    def test_create_agent(self):
        user = User.objects.create_user(
            username='agente01',
            password='test12345',
            profile=User.Profile.AGENT,
            badge_number='AGT-1234',
        )
        self.assertTrue(user.is_agent)
        self.assertFalse(user.is_expert)
        self.assertEqual(user.badge_number, 'AGT-1234')

    def test_create_expert(self):
        user = User.objects.create_user(
            username='perito01',
            password='test12345',
            profile=User.Profile.EXPERT,
        )
        self.assertFalse(user.is_agent)
        self.assertTrue(user.is_expert)


class OccurrenceModelTest(TestCase):
    """Testes para o modelo Occurrence."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01', password='test12345',
        )

    def test_create_occurrence(self):
        # Campo gps_* tem max_digits=10, decimal_places=7 — o total de
        # dígitos inteiros é 3 (90 ou -180) e fraccionários até 7.
        # "38.7223340" tem 9 dígitos = 2 inteiros + 7 decimais → ok.
        # "-9.1393366" tem 8 dígitos = 1 inteiro + 7 decimais → ok.
        occ = Occurrence.objects.create(
            number='NUIPC-2026-001',
            description='Furto de telemóvel na via pública.',
            agent=self.agent,
            gps_lat=Decimal('38.7223340'),
            gps_lon=Decimal('-9.1393366'),
        )
        # __str__ combina NUIPC + código interno gerado (OCC-YYYY-NNNNN).
        self.assertTrue(str(occ).startswith('Ocorrência NUIPC-2026-001'))
        self.assertIn('OCC-', str(occ))
        self.assertIsNotNone(occ.created_at)


class EvidenceModelTest(TestCase):
    """Testes para o modelo Evidence (inclui hash SHA-256)."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01', password='test12345',
        )
        self.occurrence = Occurrence.objects.create(
            number='NUIPC-2026-001',
            description='Furto de telemóvel.',
            agent=self.agent,
        )

    def test_create_evidence_with_auto_hash(self):
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='iPhone 15 Pro encontrado no local.',
            agent=self.agent,
        )
        # Hash SHA-256 deve ser calculado automaticamente
        self.assertEqual(len(ev.integrity_hash), 64)
        self.assertNotEqual(ev.integrity_hash, '')

    def test_hash_is_deterministic(self):
        """O mesmo conjunto de metadados gera sempre o mesmo hash."""
        ts = timezone.now()
        ev = Evidence(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.OTHER_DIGITAL,
            description='Ficheiro recuperado.',
            timestamp_seizure=ts,
            agent=self.agent,
        )
        hash1 = ev.compute_integrity_hash()
        hash2 = ev.compute_integrity_hash()
        self.assertEqual(hash1, hash2)

    def test_update_blocked(self):
        """Atualizar uma evidência existente deve levantar ValidationError."""
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone original.',
            agent=self.agent,
        )
        ev.description = 'Tentativa de alteração.'
        with self.assertRaises(ValidationError):
            ev.save()

    def test_delete_blocked(self):
        """Eliminar uma evidência deve levantar ValidationError."""
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone.',
            agent=self.agent,
        )
        with self.assertRaises(ValidationError):
            ev.delete()


class DigitalDeviceModelTest(TestCase):
    """Testes para o modelo DigitalDevice."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01', password='test12345',
        )
        self.occurrence = Occurrence.objects.create(
            number='NUIPC-2026-002',
            description='Apreensão de portátil.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.COMPUTER,
            description='Portátil Lenovo.',
            agent=self.agent,
        )

    def test_create_device(self):
        device = DigitalDevice.objects.create(
            evidence=self.evidence,
            type=DigitalDevice.DeviceType.LAPTOP,
            brand='Lenovo',
            model='ThinkPad X1',
            condition=DigitalDevice.DeviceCondition.FUNCTIONAL,
            serial_number='SN-ABC-12345',
        )
        self.assertIn('Lenovo', str(device))
        self.assertIn('ThinkPad X1', str(device))


class ChainOfCustodyModelTest(TestCase):
    """Testes para a cadeia de custódia (máquina de estados + imutabilidade)."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01', password='test12345',
        )
        self.expert = User.objects.create_user(
            username='perito01', password='test12345',
            profile=User.Profile.EXPERT,
        )
        self.occurrence = Occurrence.objects.create(
            number='NUIPC-2026-003',
            description='Apreensão.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone Samsung.',
            agent=self.agent,
        )

    def test_valid_first_transition(self):
        """Primeira transição: '' → APREENDIDA."""
        record = ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
            observations='Apreensão no local.',
        )
        record.save()
        self.assertEqual(len(record.record_hash), 64)

    def test_valid_sequential_transitions(self):
        """Transições sequenciais válidas pela máquina de estados."""
        ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        ).save()

        ChainOfCustody(
            evidence=self.evidence,
            previous_state=ChainOfCustody.CustodyState.APREENDIDA,
            new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
            agent=self.agent,
        ).save()

        self.assertEqual(
            ChainOfCustody.objects.filter(evidence=self.evidence).count(), 2
        )

    def test_invalid_transition_raises_error(self):
        """Transição inválida deve levantar ValidationError."""
        with self.assertRaises(ValidationError):
            ChainOfCustody(
                evidence=self.evidence,
                previous_state='',
                new_state=ChainOfCustody.CustodyState.EM_PERICIA,  # Inválido!
                agent=self.agent,
            ).save()

    def test_update_blocked(self):
        """Atualizar um registo existente deve levantar ValidationError."""
        record = ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        )
        record.save()

        record.observations = 'Tentativa de alteração.'
        with self.assertRaises(ValidationError):
            record.save()

    def test_delete_blocked(self):
        """Eliminar um registo deve levantar ValidationError."""
        record = ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        )
        record.save()

        with self.assertRaises(ValidationError):
            record.delete()

    def test_hash_chain_integrity(self):
        """Hashes encadeiam-se (blockchain-like)."""
        r1 = ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        )
        r1.save()

        r2 = ChainOfCustody(
            evidence=self.evidence,
            previous_state=ChainOfCustody.CustodyState.APREENDIDA,
            new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
            agent=self.agent,
        )
        r2.save()

        # Os hashes devem ser diferentes
        self.assertNotEqual(r1.record_hash, r2.record_hash)
        # Ambos devem ter 64 caracteres (SHA-256 hex)
        self.assertEqual(len(r1.record_hash), 64)
        self.assertEqual(len(r2.record_hash), 64)
