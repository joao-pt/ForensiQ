"""
ForensiQ — Testes do verificador de integridade (:mod:`core.integrity`).

Cadeias válidas são criadas append-only (.save()); a adulteração e a "génese
ausente" são INSERIDAS via ``bulk_create`` (que contorna ``save()``/``clean()`` —
não os triggers de imutabilidade, que só bloqueiam UPDATE/DELETE), para exercitar
os ramos de quebra que um ledger bem formado nunca produz.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core import integrity
from core.models import (
    ChainOfCustody,
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionType,
    Occurrence,
    Portador,
    User,
)
from core.tests_factories import CrimeTipoFactory, InstitutionFactory


class IntegrityBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user(
            username='int_agent', password='x12345678', profile=User.Profile.FIRST_RESPONDER
        )
        cls.lab = InstitutionFactory(name='LPC int', sigla='LPC-INT')
        cls.portador = Portador.objects.create(
            matricula='INT-1', nome='Rui', apelido='Marques', posto='Agente'
        )

    def _ev(self, sn):
        occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(), number=f'NUIPC-INT-{sn}',
            description='Integridade.', agent=self.agent,
        )
        return Evidence.objects.create(
            occurrence=occ, type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item', serial_number=sn, agent=self.agent,
        )

    def _save(self, ev, event_type, **kw):
        rec = ChainOfCustody(evidence=ev, event_type=event_type, agent=self.agent, **kw)
        rec.save()
        return rec


class VerifyChainsTest(IntegrityBase):
    def test_valid_chain_intact(self):
        ev = self._ev('V1')
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)
        result = integrity.verify_chains([ev.id])
        self.assertTrue(result['intact'])
        self.assertEqual(result['verified'], 1)
        self.assertEqual(result['total_items'], 1)
        self.assertEqual(result['total_events'], 2)
        self.assertEqual(result['broken'], [])

    def test_tampered_chain_broken(self):
        ev = self._ev('B1')
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        last = ChainOfCustody.objects.filter(evidence=ev).order_by('sequence').last()
        # Insere (bulk_create → sem save()/recálculo) um evento com hash ERRADO.
        ChainOfCustody.objects.bulk_create([
            ChainOfCustody(
                evidence=ev, event_type=EventType.VALIDACAO_APREENSAO, agent=self.agent,
                custodian_type=CustodianType.OPC, sequence=last.sequence + 1,
                timestamp=last.timestamp, record_hash='0' * 64, hash_version=last.hash_version,
            )
        ])
        result = integrity.verify_chains([ev.id])
        self.assertFalse(result['intact'])
        self.assertEqual(result['verified'], 0)
        self.assertEqual(len(result['broken']), 1)
        self.assertEqual(result['broken'][0]['sequence'], last.sequence + 1)


class DetectAnomaliesTest(IntegrityBase):
    def test_em_transito_por_receber(self):
        ev = self._ev('T1')
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.DESPACHO_PERICIA, custodian_type=CustodianType.OPC)
        self._save(
            ev, EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO, custodian_institution=self.lab,
            bearer=self.portador,
        )
        findings = integrity.detect_anomalies([ev.id])
        msgs = [f['msg'] for f in findings]
        self.assertTrue(any('trânsito' in m for m in msgs))

    def test_clean_chain_sem_anomalias(self):
        ev = self._ev('C1')
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)
        self.assertEqual(integrity.detect_anomalies([ev.id]), [])

    def test_genese_ausente(self):
        ev = self._ev('G1')
        # Insere (bulk_create) uma cadeia cujo 1.º evento NÃO é génese.
        ChainOfCustody.objects.bulk_create([
            ChainOfCustody(
                evidence=ev, event_type=EventType.VALIDACAO_APREENSAO, agent=self.agent,
                custodian_type=CustodianType.OPC, sequence=1, timestamp=timezone.now(),
                record_hash='a' * 64, hash_version='hv1',
            )
        ])
        findings = integrity.detect_anomalies([ev.id])
        self.assertTrue(any(f['severity'] == 'alta' for f in findings))
