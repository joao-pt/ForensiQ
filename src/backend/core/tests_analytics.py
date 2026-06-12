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
from core.tests_factories import (
    AUTHORITY_KWARGS,
    CrimeTipoFactory,
    InstitutionFactory,
    _fill_authority,
)


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
            act_declared_at=timezone.now(), **AUTHORITY_KWARGS,
        )

    def test_estado_por_item(self):
        # A validação é ATO, não deslocação: o estado de custódia mantém-se
        # a_guarda_opc (o estatuto de validação deriva-se no eixo próprio).
        states = analytics.legal_states_by_evidence(ChainOfCustody.objects.all())
        self.assertEqual(states[self.ev1.id], 'a_guarda_opc')
        self.assertEqual(states[self.ev2.id], 'a_guarda_opc')

    def test_with_events_devolve_registos_agrupados_por_ordem_canonica(self):
        states, eventos = analytics.legal_states_by_evidence(
            ChainOfCustody.objects.all(), with_events=True
        )
        self.assertEqual(states[self.ev1.id], 'a_guarda_opc')
        self.assertEqual(
            [r.event_type for r in eventos[self.ev1.id]],
            [EventType.APREENSAO_OBJETO, EventType.VALIDACAO_APREENSAO],
        )
        self.assertEqual(len(eventos[self.ev2.id]), 1)

    def test_validation_statuses_em_lote_espelha_a_funcao_pura(self):
        """O agrupamento em lote do eixo de validação devolve, por item, o mesmo
        que a derivação individual (fonte única — nunca divergem)."""
        from core.utils import validation_status_of

        statuses = analytics.validation_statuses_by_evidence(ChainOfCustody.objects.all())
        self.assertEqual(statuses[self.ev1.id], 'validada')
        self.assertEqual(statuses[self.ev2.id], 'por_validar')
        for ev in (self.ev1, self.ev2):
            self.assertEqual(statuses[ev.id], validation_status_of(ev))


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
            # Defaults da autoridade (hv4) DENTRO do relógio congelado — a
            # data declarada de um ato retrodatado tem de ser <= ao "agora".
            rec = ChainOfCustody(
                evidence=ev, event_type=event_type, agent=self.agent,
                **_fill_authority(event_type, kw),
            )
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

    def test_dwell_paragem_aberta_extinta_por_disposicao(self):
        """A disposição final (DISPOSAL_EVENTS — inclui a PERDA_FAVOR_ESTADO,
        que NÃO fecha o ledger) extingue a paragem ABERTA do dwell; a extinção
        é POSICIONAL (vale o ÚLTIMO evento): um ato posterior à perda reabre a
        paragem, tal como reabre o prazo da perícia."""
        now = timezone.now()
        occ = self._occ('DW', now - timedelta(hours=200))

        # A: perdido a favor do Estado há 60h (último evento) → paragem aberta
        # extinta; o intervalo apreensão→perda (40h) conta como FECHADO.
        ev_a = self._ev(occ, 'SN-DW-A', now - timedelta(hours=100))
        self._save_at(ev_a, EventType.APREENSAO_OBJETO, now - timedelta(hours=100),
                      custodian_type=CustodianType.OPC)
        self._save_at(ev_a, EventType.PERDA_FAVOR_ESTADO, now - timedelta(hours=60),
                      custodian_type=CustodianType.DEPOSITARIO)

        # B: apreensão em aberto há 10h → paragem aberta normal.
        ev_b = self._ev(occ, 'SN-DW-B', now - timedelta(hours=10))
        self._save_at(ev_b, EventType.APREENSAO_OBJETO, now - timedelta(hours=10),
                      custodian_type=CustodianType.OPC)

        # C: despacho POSTERIOR à perda (decisão judicial legítima) reabre a
        # paragem há 20h — vale o último evento, nunca a presença da perda.
        ev_c = self._ev(occ, 'SN-DW-C', now - timedelta(hours=100))
        self._save_at(ev_c, EventType.APREENSAO_OBJETO, now - timedelta(hours=100),
                      custodian_type=CustodianType.OPC)
        self._save_at(ev_c, EventType.VALIDACAO_APREENSAO, now - timedelta(hours=95),
                      custodian_type=CustodianType.OPC)
        self._save_at(ev_c, EventType.PERDA_FAVOR_ESTADO, now - timedelta(hours=90),
                      custodian_type=CustodianType.DEPOSITARIO)
        self._save_at(ev_c, EventType.DESPACHO_PERICIA, now - timedelta(hours=20),
                      custodian_type=CustodianType.DEPOSITARIO, act_deadline_days=30)

        dwell = analytics.custody_dwell(ChainOfCustody.objects.all(), now=now)
        self.assertEqual(dwell['open_items'], 2)            # B (10h) + C reaberto (20h)
        self.assertGreater(dwell['longest_open_hours'], 19)  # C ~20h…
        self.assertLess(dwell['longest_open_hours'], 21)     # …nunca a perda de A (60h)
        self.assertEqual(dwell['intervals'], 4)             # A:1 + C:3 fechados

    def _despachado(self, occ, sn, *, despacho_age, prazo_dias=30):
        """Item validado e despachado há ``despacho_age`` (prazo em dias, hv4)."""
        ev = self._ev(occ, sn, timezone.now() - despacho_age - timedelta(days=2))
        self._save_at(ev, EventType.APREENSAO_OBJETO,
                      timezone.now() - despacho_age - timedelta(days=2),
                      custodian_type=CustodianType.OPC)
        self._save_at(ev, EventType.VALIDACAO_APREENSAO,
                      timezone.now() - despacho_age - timedelta(days=1),
                      custodian_type=CustodianType.OPC)
        self._save_at(ev, EventType.DESPACHO_PERICIA, timezone.now() - despacho_age,
                      custodian_type=CustodianType.OPC, act_deadline_days=prazo_dias)
        return ev

    def test_pericia_deadlines_em_lote_e_sla(self):
        """O eixo do prazo da perícia: o lote espelha a derivação individual
        (fonte única) e o aging_sla devolve contagens re-deriváveis (ids)."""
        from core.utils import pericia_deadline_of

        now = timezone.now()
        occ = self._occ('PD', now - timedelta(days=50))

        # Despacho recente (prazo 30d) → em prazo (não conta para alertas).
        ev_ok = self._despachado(occ, 'SN-PD-1', despacho_age=timedelta(days=2))
        # Data-limite daqui a ~4 dias → a vencer (dentro da antecedência de 7).
        ev_due = self._despachado(occ, 'SN-PD-2', despacho_age=timedelta(days=26))
        # Data-limite há ~10 dias → vencida.
        ev_late = self._despachado(occ, 'SN-PD-3', despacho_age=timedelta(days=40))
        # Perícia CONCLUÍDA depois do despacho → exigência cumprida (None).
        ev_done = self._despachado(occ, 'SN-PD-4', despacho_age=timedelta(days=40))
        self._save_at(ev_done, EventType.TRANSFERENCIA_CUSTODIA,
                      now - timedelta(days=38), custodian_type=CustodianType.LAB_PUBLICO,
                      custodian_institution=self.lab)
        self._save_at(ev_done, EventType.INICIO_PERICIA, now - timedelta(days=37),
                      custodian_type=CustodianType.LAB_PUBLICO,
                      custodian_institution=self.lab)
        self._save_at(ev_done, EventType.CONCLUSAO_PERICIA, now - timedelta(days=35),
                      custodian_type=CustodianType.LAB_PUBLICO,
                      custodian_institution=self.lab)

        deadlines = analytics.pericia_deadlines_by_evidence(
            ChainOfCustody.objects.all(), now=now
        )
        self.assertEqual(deadlines[ev_ok.id]['status'], 'em_prazo')
        self.assertEqual(deadlines[ev_due.id]['status'], 'a_vencer')
        self.assertEqual(deadlines[ev_late.id]['status'], 'vencida')
        self.assertIsNone(deadlines[ev_done.id])
        for ev in (ev_ok, ev_due, ev_late, ev_done):
            self.assertEqual(deadlines[ev.id], pericia_deadline_of(ev, now=now))

        sla = analytics.aging_sla(
            Evidence.objects.all(), ChainOfCustody.objects.all(), now=now
        )
        self.assertEqual(sla['pericias_overdue'], 1)
        self.assertEqual(sla['pericia_overdue_ids'], {ev_late.id})
        self.assertEqual(sla['pericias_due'], 1)
        self.assertEqual(sla['pericia_due_ids'], {ev_due.id})
        self.assertEqual(sla['pericia_warning_days'], 7)
