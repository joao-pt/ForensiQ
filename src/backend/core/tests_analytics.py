"""
ForensiQ — Testes do módulo de métricas de fluxo (:mod:`core.analytics`).

As funções puras (``resolve_window``, ``state_distribution``) testam-se sem BD; as
que leem o ledger (``throughput``, ``custody_dwell``, ``aging_sla``) com eventos
criados append-only e retrodatados via *freeze-time* (mock de
``core.models.timezone.now``) — os triggers de imutabilidade do PostgreSQL impedem
retrodatar por ``UPDATE``.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core import analytics
from core.models import (
    ChainOfCustody,
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionType,
    Occurrence,
    ProvaEmTransito,
    User,
)
from core.tests_factories import CrimeTipoFactory, InstitutionFactory


class ResolveWindowTest(TestCase):
    def test_valid_choice(self):
        self.assertEqual(analytics.resolve_window('90'), 90)
        self.assertEqual(analytics.resolve_window('7'), 7)

    def test_default_on_invalid(self):
        self.assertEqual(analytics.resolve_window('abc'), analytics.DEFAULT_WINDOW_DAYS)
        self.assertEqual(analytics.resolve_window(None), analytics.DEFAULT_WINDOW_DAYS)

    def test_default_on_out_of_range(self):
        self.assertEqual(analytics.resolve_window('5'), analytics.DEFAULT_WINDOW_DAYS)


class StateDistributionTest(TestCase):
    def test_split_active_concluded(self):
        states = {
            1: 'em_pericia',
            2: 'em_pericia',
            3: 'a_guarda_opc',
            4: 'restituida',
            5: 'destruida',
        }
        d = analytics.state_distribution(states)
        self.assertEqual(d['total'], 5)
        self.assertEqual(d['active'], 3)       # em_pericia x2 + a_guarda_opc
        self.assertEqual(d['concluded'], 2)    # restituida + destruida (terminais)
        self.assertEqual(d['peak'], 2)         # maior contagem (em_pericia)
        self.assertEqual(d['rows'][0]['key'], 'em_pericia')  # ordenado desc por n
        self.assertEqual(d['rows'][0]['n'], 2)
        terminal = {r['key']: r['terminal'] for r in d['rows']}
        self.assertTrue(terminal['restituida'])
        self.assertFalse(terminal['em_pericia'])

    def test_empty(self):
        d = analytics.state_distribution({})
        self.assertEqual(d['rows'], [])
        self.assertEqual(d['total'], 0)
        self.assertEqual(d['peak'], 0)


class StateCountsTest(TestCase):
    def test_todos_os_estados_com_zeros_e_guarda_de_desconhecidos(self):
        counts = analytics.state_counts({1: 'em_pericia', 2: 'em_pericia', 3: '???'})
        # Todos os estados canónicos presentes (zeros incluídos); valores fora
        # do vocabulário são ignorados (nunca KeyError).
        self.assertEqual(counts['em_pericia'], 2)
        self.assertEqual(counts['restituida'], 0)
        self.assertNotIn('???', counts)


class LegalStatesByEvidenceTest(TestCase):
    """Fonte única do agrupamento ledger→estado (auditoria D14)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user(
            username='an_group', password='x12345678', profile=User.Profile.FIRST_RESPONDER
        )
        occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(), number='NUIPC-AN-G1',
            description='Agrupamento.', agent=cls.agent, date_time=timezone.now(),
        )
        cls.ev1 = Evidence.objects.create(
            occurrence=occ, type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item 1', agent=cls.agent, timestamp_seizure=timezone.now(),
        )
        cls.ev2 = Evidence.objects.create(
            occurrence=occ, type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item 2', agent=cls.agent, timestamp_seizure=timezone.now(),
        )
        for ev in (cls.ev1, cls.ev2):
            ChainOfCustody.objects.create(
                evidence=ev, event_type=EventType.APREENSAO_OBJETO,
                custodian_type=CustodianType.OPC, agent=cls.agent,
            )
        ChainOfCustody.objects.create(
            evidence=cls.ev1, event_type=EventType.VALIDACAO_APREENSAO, agent=cls.agent,
        )

    def test_estado_por_item(self):
        states = analytics.legal_states_by_evidence(ChainOfCustody.objects.all())
        self.assertEqual(states[self.ev1.id], 'validada')
        self.assertEqual(states[self.ev2.id], 'a_guarda_opc')

    def test_with_events_devolve_registos_agrupados_por_ordem_canonica(self):
        states, eventos = analytics.legal_states_by_evidence(
            ChainOfCustody.objects.all(), with_events=True
        )
        self.assertEqual(states[self.ev1.id], 'validada')
        self.assertEqual(
            [r.event_type for r in eventos[self.ev1.id]],
            [EventType.APREENSAO_OBJETO, EventType.VALIDACAO_APREENSAO],
        )
        self.assertEqual(len(eventos[self.ev2.id]), 1)


class LedgerAnalyticsTest(TestCase):
    """Cenário no ledger: validação em atraso, prova em trânsito e dwell time."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user(
            username='an_agent', password='x12345678', profile=User.Profile.FIRST_RESPONDER
        )
        cls.lab = InstitutionFactory(name='LPC analytics', sigla='LPC-AN')

    def _occ(self, n, when):
        return Occurrence.objects.create(
            crime_type=CrimeTipoFactory(), number=f'NUIPC-AN-{n}',
            description='Analytics.', agent=self.agent, date_time=when,
        )

    def _ev(self, occ, sn, when):
        return Evidence.objects.create(
            occurrence=occ, type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item', serial_number=sn, agent=self.agent, timestamp_seizure=when,
        )

    def _save_at(self, ev, event_type, when, **kw):
        with mock.patch('core.models.timezone.now', return_value=when):
            rec = ChainOfCustody(evidence=ev, event_type=event_type, agent=self.agent, **kw)
            rec.save()
        return rec

    def test_flow_sla_and_dwell(self):
        now = timezone.now()
        occ = self._occ('1', now - timedelta(hours=50))

        # ev1: apreendido há 100h, SEM validação → validação em atraso.
        ev1 = self._ev(occ, 'SN-1', now - timedelta(hours=100))
        self._save_at(ev1, EventType.APREENSAO_OBJETO, now - timedelta(hours=100),
                      custodian_type=CustodianType.OPC)
        # ev2: apreendido há 100h e validado há 90h → NÃO em atraso; 1 intervalo de ~10h.
        ev2 = self._ev(occ, 'SN-2', now - timedelta(hours=100))
        self._save_at(ev2, EventType.APREENSAO_OBJETO, now - timedelta(hours=100),
                      custodian_type=CustodianType.OPC)
        self._save_at(ev2, EventType.VALIDACAO_APREENSAO, now - timedelta(hours=90),
                      custodian_type=CustodianType.OPC)
        # ev3: apreendido há 30h, com aviso de prova em trânsito por receber (~28h).
        ev3 = self._ev(occ, 'SN-3', now - timedelta(hours=30))
        enc = self._save_at(ev3, EventType.APREENSAO_OBJETO, now - timedelta(hours=30),
                            custodian_type=CustodianType.OPC)
        ProvaEmTransito.objects.create(
            destino_institution=self.lab, evidence=ev3, encaminhamento_event=enc,
            created_at=now - timedelta(hours=28),
        )

        occ_qs = Occurrence.objects.all()
        evd_qs = Evidence.objects.all()
        cus_qs = ChainOfCustody.objects.all()

        sla = analytics.aging_sla(evd_qs, cus_qs, now=now)
        self.assertEqual(sla['validations_overdue'], 1)        # só ev1
        self.assertEqual(sla['in_transit'], 1)                 # só ev3
        self.assertGreater(sla['oldest_transit_hours'], 24)
        self.assertLess(sla['oldest_transit_hours'], 32)
        self.assertEqual(sla['deadline_hours'], 72)

        dwell = analytics.custody_dwell(cus_qs, now=now)
        self.assertEqual(dwell['intervals'], 1)                # só ev2 tem 2 eventos
        self.assertGreater(dwell['avg_dwell_hours'], 9)
        self.assertLess(dwell['avg_dwell_hours'], 11)          # ~10h
        self.assertEqual(dwell['open_items'], 3)               # nenhum terminal
        self.assertGreater(dwell['longest_open_hours'], 90)    # ev1 parado ~100h

        flow = analytics.throughput(occ_qs, evd_qs, cus_qs, now - timedelta(days=365))
        self.assertEqual(flow['opened'], 1)                    # 1 ocorrência na janela
        self.assertEqual(flow['registered'], 3)                # 3 itens apreendidos
        self.assertEqual(flow['concluded'], 0)                 # nenhum terminal ainda
