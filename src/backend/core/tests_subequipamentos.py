"""
ForensiQ — Testes da árvore de sub-componentes (roadmap §6): guardas de
profundidade/ciclo do modelo e ordem de ÁRVORE das listas por ocorrência
(Lote 1 — regressão: ``parent_evidence_id`` ASC punha as raízes NULL em último
no PostgreSQL; a ordenação lexicográfica punha .10 antes de .2); génese
DERIVACAO_ITEM automática no registo do filho, com custódio HERDADO do
custódio atual do pai (Lote 2 — decisão §6: uma apreensão validável, a do
pai; a sub-árvore herda a base legal).
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.frontend_views import _intake_world, _occurrence_items, _tree_sort_key
from core.models import (
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Occurrence,
    Portador,
)
from core.tests_base import auth_cookie
from core.tests_factories import (
    CrimeTipoFactory,
    InstitutionFactory,
    UserFactory,
    make_chain,
    make_user,
)
from core.utils import validation_status_of

User = get_user_model()


def _occ(agent, n):
    return Occurrence.objects.create(
        number=f'NUIPC-SUB-{n}',
        crime_type=CrimeTipoFactory(),
        description='caso de teste de sub-componentes',
        date_time=timezone.now(),
        agent=agent,
    )


def _ev(occ, agent, etype=Evidence.EvidenceType.MOBILE_DEVICE, parent=None):
    return Evidence.objects.create(
        occurrence=occ,
        type=etype,
        description='item',
        timestamp_seizure=timezone.now(),
        agent=agent,
        parent_evidence=parent,
    )


class TreeDepthGuardTest(TestCase):
    """Guardas de profundidade e ciclo de ``Evidence.clean()`` — MAX_TREE_DEPTH."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, 'D1')

    def test_tres_niveis_sao_permitidos(self):
        raiz = _ev(self.occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(
            self.occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=raiz
        )
        neto = _ev(
            self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=filho
        )
        self.assertEqual(neto.code, f'{raiz.code}.1.1')
        self.assertEqual(neto.get_depth(), Evidence.MAX_TREE_DEPTH)

    def test_quarto_nivel_e_recusado(self):
        raiz = _ev(self.occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(
            self.occ,
            self.agent,
            Evidence.EvidenceType.VEHICLE_COMPONENT,
            parent=raiz,
        )
        neto = _ev(
            self.occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=filho
        )
        with self.assertRaises(ValidationError) as ctx:
            _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=neto)
        self.assertIn('parent_evidence', ctx.exception.message_dict)
        self.assertIn(
            'Profundidade', str(ctx.exception.message_dict['parent_evidence'])
        )

    def test_ciclo_e_recusado(self):
        raiz = _ev(self.occ, self.agent)
        filho = _ev(
            self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz
        )
        # A imutabilidade impede gravar um ciclo; a guarda defende contra dados
        # corrompidos — verifica-se em memória, sem persistir.
        raiz.parent_evidence = filho
        self.assertTrue(raiz._parent_contains_self())
        with self.assertRaises(ValidationError) as ctx:
            raiz.clean()
        self.assertIn('Ciclo', str(ctx.exception.message_dict['parent_evidence']))


class TreeOrderTest(TestCase):
    """Ordem de árvore das listas por ocorrência (raiz antes dos filhos; irmãos
    por índice numérico) e anotação ``tree_depth``."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()

    def test_raiz_antes_dos_filhos_e_filhos_adjacentes(self):
        occ = _occ(self.agent, 'O1')
        raiz1 = _ev(occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=raiz1)
        neto = _ev(occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=filho)
        raiz2 = _ev(occ, self.agent)
        itens = _occurrence_items(occ)
        self.assertEqual(
            [e.code for e in itens],
            [raiz1.code, filho.code, neto.code, raiz2.code],
        )
        self.assertEqual([e.tree_depth for e in itens], [1, 2, 3, 1])

    def test_irmaos_ordenam_numericamente_nao_lexicograficamente(self):
        occ = _occ(self.agent, 'O2')
        raiz = _ev(occ, self.agent)
        filhos = [
            _ev(occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
            for _ in range(10)
        ]
        itens = _occurrence_items(occ)
        # .10 vem depois de .9 (lexicograficamente viria logo a seguir a .1).
        self.assertEqual(
            [e.code for e in itens],
            [raiz.code] + [f.code for f in filhos],
        )
        self.assertEqual(itens[-1].code, f'{raiz.code}.10')

    def test_chave_tolerante_a_codigo_fora_do_padrao(self):
        occ = _occ(self.agent, 'O3')
        raiz = _ev(occ, self.agent)
        raiz.code = 'LIXO-SEM-PADRAO.x'
        self.assertEqual(_tree_sort_key(raiz), (float('inf'),))

    def test_intake_usa_a_mesma_ordem_de_arvore(self):
        occ = _occ(self.agent, 'O4')
        raiz1 = _ev(occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=raiz1)
        raiz2 = _ev(occ, self.agent)
        evidences, _states, _eventos = _intake_world(occ)
        self.assertEqual(
            [e.code for e in evidences], [raiz1.code, filho.code, raiz2.code]
        )


class GeneseAutomaticaDoFilhoTest(TestCase):
    """Lote 2 — registar um sub-componente em /evidences/new/ cria a génese
    DERIVACAO_ITEM na MESMA transação, com custódio herdado do custódio ATUAL
    do pai (último evento do ledger — terreno: OPC; laboratório: LAB)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Subequip', type=InstitutionType.OPC, sigla='PSP-SUB'
        )
        cls.agent = make_user('sub_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'G1')

    def _post_new(self, **extra):
        auth_cookie(self.client, self.agent)
        data = {
            'occurrence': self.occ.id,
            'type': Evidence.EvidenceType.MOBILE_DEVICE,
            'description': 'Item de teste do registo encadeado.',
        }
        data.update(extra)
        return self.client.post('/evidences/new/', data)

    def _latest(self):
        return Evidence.objects.filter(occurrence=self.occ).latest('id')

    def test_filho_nasce_com_derivacao_na_mesma_transacao(self):
        self._post_new()
        pai = self._latest()
        r = self._post_new(
            type=Evidence.EvidenceType.SIM_CARD, parent_evidence=pai.id
        )
        self.assertEqual(r.status_code, 302)
        filho = self._latest()
        events = list(filho.custody_chain.all())
        self.assertEqual(
            len(events), 1, 'o registo do filho devia criar exatamente a génese'
        )
        g = events[0]
        self.assertEqual(g.event_type, EventType.DERIVACAO_ITEM)
        self.assertEqual(g.custodian_type, CustodianType.OPC)
        self.assertEqual(g.custodian_institution_id, self.opc.id)
        self.assertEqual(g.agent_id, self.agent.id)
        # Eixo da validação: o filho não tem apreensão própria a validar — a
        # base legal herda-se do pai (SEIZURE_GENESIS_EVENTS exclui a derivação).
        self.assertIsNone(validation_status_of(filho))

    def test_heranca_vem_do_pai_nao_da_pertenca_do_operador(self):
        self._post_new()
        pai = self._latest()
        # Entre o registo do pai e o do filho, o agente muda de instituição —
        # a génese do filho herda do PAI, não da pertença atual do operador.
        InstitutionMembership.objects.filter(user=self.agent).update(is_active=False)
        outra = Institution.objects.create(
            name='GNR Subequip', type=InstitutionType.OPC, sigla='GNR-SUB'
        )
        InstitutionMembership.objects.create(user=self.agent, institution=outra)
        self._post_new(
            type=Evidence.EvidenceType.SIM_CARD, parent_evidence=pai.id
        )
        g = self._latest().custody_chain.get()
        self.assertEqual(g.custodian_institution_id, self.opc.id)

    def test_filho_derivado_no_laboratorio_herda_o_lab(self):
        lab = InstitutionFactory(name='LPC Subequip', sigla='LPC-SUB')
        portador = Portador.objects.create(
            matricula='SUB-001', nome='Rui', apelido='Marques', posto='Agente'
        )
        self._post_new()
        pai = self._latest()
        make_chain(
            pai,
            (
                EventType.VALIDACAO_APREENSAO,
                {'custodian_type': CustodianType.OPC,
                 'custodian_institution': self.opc},
            ),
            (
                EventType.DESPACHO_PERICIA,
                {'custodian_type': CustodianType.OPC,
                 'custodian_institution': self.opc},
            ),
            (
                EventType.ENCAMINHAMENTO_CUSTODIA,
                {'custodian_type': CustodianType.LAB_PUBLICO,
                 'custodian_institution': lab, 'bearer': portador},
            ),
            (
                EventType.RECEPCAO_CUSTODIA,
                {'custodian_type': CustodianType.LAB_PUBLICO,
                 'custodian_institution': lab},
            ),
            agent=self.agent,
        )
        self._post_new(
            type=Evidence.EvidenceType.SIM_CARD, parent_evidence=pai.id
        )
        g = self._latest().custody_chain.get()
        self.assertEqual(g.event_type, EventType.DERIVACAO_ITEM)
        self.assertEqual(g.custodian_type, CustodianType.LAB_PUBLICO)
        self.assertEqual(g.custodian_institution_id, lab.id)

    def test_pai_sem_ledger_recua_para_custodio_de_raiz(self):
        # Pai criado fora da consola (caminho API: sem génese automática) — o
        # filho não tem de onde herdar e recua para o custódio de raiz.
        pai = _ev(self.occ, self.agent)
        self._post_new(
            type=Evidence.EvidenceType.SIM_CARD, parent_evidence=pai.id
        )
        g = self._latest().custody_chain.get()
        self.assertEqual(g.event_type, EventType.DERIVACAO_ITEM)
        self.assertEqual(g.custodian_type, CustodianType.OPC)
        self.assertEqual(g.custodian_institution_id, self.opc.id)

    def test_atos_do_filho_apontam_a_base_herdada(self):
        self._post_new()
        pai = self._latest()
        self._post_new(
            type=Evidence.EvidenceType.SIM_CARD, parent_evidence=pai.id
        )
        filho = self._latest()
        r = self.client.get(f'/evidences/{filho.id}/atos/')
        self.assertContains(r, 'base legal')
        self.assertContains(r, pai.code)
        self.assertNotContains(r, 'Sem atos de autoridade')


class FluxoEncadeadoTest(TestCase):
    """Lote 3 — fluxo encadeado do registo (§6): ``?parent=`` tranca o
    contexto, o sucesso segue para a página de continuação, o selector de pai
    não oferece o impossível e a ficha ganha «Adicionar sub-componente»."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Encadeado', type=InstitutionType.OPC, sigla='PSP-ENC'
        )
        cls.agent = make_user('enc_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'F1')

    def _post_new(self, action='/evidences/new/', **extra):
        auth_cookie(self.client, self.agent)
        data = {
            'occurrence': self.occ.id,
            'type': Evidence.EvidenceType.MOBILE_DEVICE,
            'description': 'Item do fluxo encadeado.',
        }
        data.update(extra)
        return self.client.post(action, data)

    def _latest(self):
        return Evidence.objects.filter(occurrence=self.occ).latest('id')

    def test_form_com_parent_tranca_contexto(self):
        self._post_new()
        pai = self._latest()
        r = self.client.get(f'/evidences/new/?parent={pai.id}')
        self.assertContains(r, 'novo sub-componente')
        self.assertContains(r, f'value="{self.occ.id}"')
        self.assertContains(r, pai.code)
        # Contexto trancado: sem selects de ocorrência/pai.
        self.assertNotContains(r, 'id="f-occ"')
        self.assertNotContains(r, 'id="f-parent"')

    def test_parent_invalido_da_404(self):
        self._post_new()
        pai = self._latest()
        folha = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=pai)
        auth_cookie(self.client, self.agent)
        self.assertEqual(
            self.client.get(f'/evidences/new/?parent={folha.id}').status_code, 404
        )
        # Item no nível máximo (3) também não admite filhos.
        raiz = _ev(self.occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(
            self.occ, self.agent, Evidence.EvidenceType.VEHICLE_COMPONENT, parent=raiz
        )
        neto = _ev(
            self.occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=filho
        )
        self.assertEqual(
            self.client.get(f'/evidences/new/?parent={neto.id}').status_code, 404
        )
        self.assertEqual(
            self.client.get('/evidences/new/?parent=99999').status_code, 404
        )

    def test_post_redireciona_para_a_continuacao(self):
        r = self._post_new()
        ev = self._latest()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'/evidences/{ev.pk}/registado/')
        # E o POST encadeado (action com ?parent=) cria o filho trancado.
        r = self._post_new(
            action=f'/evidences/new/?parent={ev.id}',
            type=Evidence.EvidenceType.SIM_CARD,
            parent_evidence=ev.id,
        )
        filho = self._latest()
        self.assertEqual(r['Location'], f'/evidences/{filho.pk}/registado/')
        self.assertEqual(filho.parent_evidence_id, ev.id)

    def test_continuacao_de_raiz_oferece_filho_e_irmao(self):
        self._post_new()
        raiz = self._latest()
        r = self.client.get(f'/evidences/{raiz.id}/registado/')
        self.assertContains(r, f'/evidences/new/?parent={raiz.id}')
        self.assertContains(r, f'/evidences/new/?occurrence={self.occ.id}')
        self.assertContains(r, 'Concluir')
        self.assertNotContains(r, 'Outro componente de')

    def test_continuacao_de_filho_folha_explica_o_bloqueio(self):
        self._post_new()
        pai = self._latest()
        self._post_new(
            type=Evidence.EvidenceType.SIM_CARD, parent_evidence=pai.id
        )
        folha = self._latest()
        r = self.client.get(f'/evidences/{folha.id}/registado/')
        self.assertContains(r, 'não admite sub-componentes')
        self.assertNotContains(r, f'/evidences/new/?parent={folha.id}')
        # Irmão: «outro componente» do MESMO pai.
        self.assertContains(r, f'/evidences/new/?parent={pai.id}')
        self.assertContains(r, pai.code)

    def test_selector_sem_folhas_nem_nivel_maximo(self):
        raiz = _ev(self.occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(
            self.occ, self.agent, Evidence.EvidenceType.VEHICLE_COMPONENT, parent=raiz
        )
        neto = _ev(
            self.occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=filho
        )
        folha = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
        auth_cookie(self.client, self.agent)
        r = self.client.get('/evidences/new/')
        self.assertContains(r, f'value="{raiz.id}" data-occurrence="{self.occ.id}"')
        self.assertContains(r, f'value="{filho.id}" data-occurrence="{self.occ.id}"')
        # Nível máximo e folha não se oferecem como pai (a recusa dura
        # continua no clean()).
        self.assertNotContains(r, f'value="{neto.id}" data-occurrence')
        self.assertNotContains(r, f'value="{folha.id}" data-occurrence')

    def test_ficha_mostra_adicionar_subcomponente_so_quando_admissivel(self):
        self._post_new()
        raiz = self._latest()
        r = self.client.get(f'/evidences/{raiz.id}/')
        self.assertContains(r, f'/evidences/new/?parent={raiz.id}')
        folha = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
        r = self.client.get(f'/evidences/{folha.id}/')
        self.assertNotContains(r, f'/evidences/new/?parent={folha.id}')
