"""
ForensiQ — Testes da política de transições de custódia (ADR-0019 §3).

``core/policy/custody_transitions.py`` é a FONTE ÚNICA das guardas de transição
por eixo de ``event_type``: o ``ChainOfCustody.clean()`` chama estes predicados
(e traduz a recusa em ``ValidationError``) e o frontend chama ``next_events`` para
oferecer só as transições que o modelo aceitaria. Estes testes cobrem os
predicados puros por tabela de casos, sem base de dados.

A invariância do COMPORTAMENTO do ``clean()`` após a extração é garantida pelas
baterias de BD existentes (``tests_custody_v2``, ``tests_encaminhar``,
``tests_access`` e os casos de ``derive_legal_state`` em ``tests``): como o
``clean()`` e o ``next_events`` passam a chamar os MESMOS predicados, não há duas
implementações que possam divergir.
"""

from django.test import SimpleTestCase

from core.models import CustodianType, EventType, InstitutionType
from core.policy import custody_transitions as ct

# Slugs (strings), como vêm gravados no ledger (``r.event_type``).
APREENSAO_OBJETO = EventType.APREENSAO_OBJETO.value
APREENSAO_DADOS = EventType.APREENSAO_DADOS.value
DERIVACAO_ITEM = EventType.DERIVACAO_ITEM.value
VALIDACAO = EventType.VALIDACAO_APREENSAO.value
DESPACHO = EventType.DESPACHO_PERICIA.value
INICIO_PERICIA = EventType.INICIO_PERICIA.value
ENCAMINHAMENTO = EventType.ENCAMINHAMENTO_CUSTODIA.value
RECEPCAO = EventType.RECEPCAO_CUSTODIA.value
RESTITUICAO = EventType.RESTITUICAO.value
DESTRUICAO = EventType.DESTRUICAO.value


class PredicadosPurosTests(SimpleTestCase):
    def test_ledger_has_terminal(self):
        self.assertFalse(ct.ledger_has_terminal([]))
        self.assertFalse(ct.ledger_has_terminal([APREENSAO_OBJETO, DESPACHO]))
        self.assertTrue(ct.ledger_has_terminal([APREENSAO_OBJETO, RESTITUICAO]))
        self.assertTrue(ct.ledger_has_terminal([APREENSAO_OBJETO, DESTRUICAO]))

    def test_has_prior_seizure(self):
        self.assertFalse(ct.has_prior_seizure([]))
        self.assertFalse(ct.has_prior_seizure([DERIVACAO_ITEM]))  # derivação não é apreensão
        self.assertTrue(ct.has_prior_seizure([APREENSAO_OBJETO]))
        self.assertTrue(ct.has_prior_seizure([APREENSAO_DADOS, DESPACHO]))

    def test_validation_done(self):
        self.assertFalse(ct.validation_done([APREENSAO_OBJETO]))
        self.assertTrue(ct.validation_done([APREENSAO_OBJETO, VALIDACAO]))

    def test_despacho_done(self):
        self.assertFalse(ct.despacho_done([APREENSAO_OBJETO]))
        self.assertTrue(ct.despacho_done([APREENSAO_OBJETO, DESPACHO]))

    def test_is_in_transit(self):
        self.assertFalse(ct.is_in_transit([]))
        self.assertFalse(ct.is_in_transit([APREENSAO_OBJETO, ENCAMINHAMENTO, RECEPCAO]))
        self.assertTrue(ct.is_in_transit([APREENSAO_OBJETO, ENCAMINHAMENTO]))

    def test_lab_gate_blocks(self):
        # Génese (sem prior) nunca dispara o gate.
        self.assertFalse(ct.lab_gate_blocks(CustodianType.LAB_PUBLICO, []))
        # LAB sem despacho prévio → bloqueia.
        self.assertTrue(ct.lab_gate_blocks(CustodianType.LAB_PUBLICO, [APREENSAO_OBJETO]))
        self.assertTrue(ct.lab_gate_blocks(CustodianType.LAB_PRIVADO, [APREENSAO_OBJETO]))
        # LAB com despacho prévio → passa.
        self.assertFalse(
            ct.lab_gate_blocks(CustodianType.LAB_PUBLICO, [APREENSAO_OBJETO, DESPACHO])
        )
        # Custódio não-laboratório nunca é barrado por este gate.
        self.assertFalse(ct.lab_gate_blocks(CustodianType.OPC, [APREENSAO_OBJETO]))


class GenesisEventForTests(SimpleTestCase):
    def test_sub_componente_deriva(self):
        self.assertEqual(
            ct.genesis_event_for(has_parent=True, is_digital_file=False),
            EventType.DERIVACAO_ITEM,
        )

    def test_sub_componente_vence_digital_file(self):
        self.assertEqual(
            ct.genesis_event_for(has_parent=True, is_digital_file=True),
            EventType.DERIVACAO_ITEM,
        )

    def test_ficheiro_digital_e_apreensao_dados(self):
        self.assertEqual(
            ct.genesis_event_for(has_parent=False, is_digital_file=True),
            EventType.APREENSAO_DADOS,
        )

    def test_objeto_raiz_e_apreensao_objeto(self):
        self.assertEqual(
            ct.genesis_event_for(has_parent=False, is_digital_file=False),
            EventType.APREENSAO_OBJETO,
        )


class NextEventsTests(SimpleTestCase):
    def _values(self, prior_types, **kw):
        return {et.value for et in ct.next_events(prior_types, **kw)}

    def test_ledger_vazio_so_oferece_a_genese_aplicavel(self):
        self.assertEqual(
            ct.next_events([], has_parent=False, is_digital_file=False),
            [EventType.APREENSAO_OBJETO],
        )
        self.assertEqual(
            ct.next_events([], has_parent=False, is_digital_file=True),
            [EventType.APREENSAO_DADOS],
        )
        self.assertEqual(
            ct.next_events([], has_parent=True, is_digital_file=False),
            [EventType.DERIVACAO_ITEM],
        )

    def test_terminal_fecha(self):
        self.assertEqual(ct.next_events([APREENSAO_OBJETO, RESTITUICAO]), [])
        self.assertEqual(ct.next_events([APREENSAO_OBJETO, DESTRUICAO]), [])

    def test_em_transito_so_recepcao(self):
        self.assertEqual(
            ct.next_events([APREENSAO_OBJETO, ENCAMINHAMENTO]),
            [EventType.RECEPCAO_CUSTODIA],
        )

    def test_caso_geral_apos_apreensao(self):
        vals = self._values([APREENSAO_OBJETO])
        # Génese, movimentação legado e receção (fora de trânsito) nunca se oferecem.
        self.assertNotIn(APREENSAO_OBJETO, vals)
        self.assertNotIn(EventType.TRANSFERENCIA_CUSTODIA.value, vals)
        self.assertNotIn(EventType.ASSUNCAO_CUSTODIA.value, vals)
        self.assertNotIn(RECEPCAO, vals)
        # Validação oferece-se (há apreensão, ainda não validada); início NÃO (sem despacho).
        self.assertIn(VALIDACAO, vals)
        self.assertNotIn(INICIO_PERICIA, vals)
        self.assertIn(DESPACHO, vals)
        self.assertIn(ENCAMINHAMENTO, vals)

    def test_validacao_some_depois_de_validada(self):
        self.assertNotIn(VALIDACAO, self._values([APREENSAO_OBJETO, VALIDACAO]))

    def test_inicio_pericia_so_com_despacho(self):
        self.assertNotIn(INICIO_PERICIA, self._values([APREENSAO_OBJETO]))
        self.assertIn(INICIO_PERICIA, self._values([APREENSAO_OBJETO, DESPACHO]))

    def test_derivacao_sem_apreensao_nao_oferece_validacao(self):
        # DERIVACAO_ITEM é génese mas NÃO é apreensão validável (CPP art. 178.º/6).
        self.assertNotIn(VALIDACAO, self._values([DERIVACAO_ITEM]))


class MapaCustodioTests(SimpleTestCase):
    def test_chaves_sao_slugs_de_institution_type_excepto_mp(self):
        esperados = set(InstitutionType.values) - {InstitutionType.MP.value}
        self.assertEqual(set(ct.CUSTODIAN_TYPE_BY_INSTITUTION), esperados)

    def test_mp_nao_promove_custodio(self):
        # MP não tem custódio próprio → custódio em branco (estado 'encaminhada').
        self.assertIsNone(ct.CUSTODIAN_TYPE_BY_INSTITUTION.get(InstitutionType.MP.value))

    def test_lab_promove_custodio_lab_o_que_dispara_o_gate(self):
        self.assertEqual(
            ct.CUSTODIAN_TYPE_BY_INSTITUTION[InstitutionType.LAB_PUBLICO.value],
            CustodianType.LAB_PUBLICO,
        )
        self.assertEqual(
            ct.CUSTODIAN_TYPE_BY_INSTITUTION[InstitutionType.OPC.value],
            CustodianType.OPC,
        )
