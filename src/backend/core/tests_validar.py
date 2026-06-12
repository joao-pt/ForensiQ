"""ForensiQ — Testes: validar a apreensão em LOTE a partir da ocorrência.

Modelo de domínio (CPP art. 178.º/6): a validação é um ATO JURÍDICO, não uma
deslocação — regista a AUTORIDADE que validou (nome/cargo) e a data declarada
do ato em campos ESTRUTURADOS (hv4, entram na fórmula do hash), sem GPS nem
mudança de custódio (herdado do último evento). O ``timestamp`` do evento é
sempre o do servidor; ``observations`` leva só a justificação livre. O estado
de custódia não muda (eixo ortogonal — ``validation_status``).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import (
    EventType,
    Institution,
    InstitutionMembership,
    InstitutionType,
)
from core.tests_base import auth_cookie
from core.tests_factories import (
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)
from core.utils import legal_state_of, sort_custody_chain, validation_status_of

User = get_user_model()


def _dtl(dt):
    """Valor de um input ``datetime-local`` (YYYY-MM-DDTHH:MM) em hora local."""
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


class ValidarLoteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Val', type=InstitutionType.OPC, sigla='PSP-VL')
        cls.agent = _user('val_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'VAL-1')
        # Dois itens com génese de apreensão (validáveis).
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)

    def _post(self, data):
        auth_cookie(self.client, self.agent)
        return self.client.post(f'/occurrences/{self.occ.id}/validar/', data)

    def _get(self, suffix=''):
        auth_cookie(self.client, self.agent)
        return self.client.get(f'/occurrences/{self.occ.id}/validar/{suffix}')

    def _last(self, ev):
        return sort_custody_chain(ev.custody_chain.all())[-1]

    def _payload(self, ids, **extra):
        data = {
            'modal': '1',
            'evidence_ids': ids,
            'authority_nome': 'Maria Costa',
            'authority_cargo': 'Procuradora da República',
            'act_declared_at': _dtl(timezone.now()),
        }
        data.update(extra)
        return data

    # -- Modal / listagem ------------------------------------------------

    def test_modal_lista_itens_por_validar(self):
        body = self._get('?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento
        self.assertIn(f'value="{self.ev1.id}"', body)
        self.assertIn(f'value="{self.ev2.id}"', body)
        self.assertIn('name="authority_nome"', body)
        self.assertIn('name="authority_cargo"', body)
        self.assertIn('name="act_declared_at"', body)
        self.assertIn('name="justification"', body)
        # A validação não fixa prazo de perícia (campo próprio do despacho).
        self.assertNotIn('name="act_deadline_days"', body)
        # Ato jurídico: o modal não pede GPS nem local.
        self.assertNotIn('name="gps_lat"', body)
        self.assertNotIn('name="location_name"', body)

    # -- Validação OK ------------------------------------------------------

    def test_valida_em_lote_sem_mudar_o_estado(self):
        r = self._post(self._payload(
            [self.ev1.id, self.ev2.id], justification='Despacho 123/26.',
        ))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{self.occ.id}/')
        for ev in (self.ev1, self.ev2):
            ult = self._last(ev)
            self.assertEqual(ult.event_type, EventType.VALIDACAO_APREENSAO)
            # Autoridade + data declarada ESTRUTURADAS (hv4 — entram na fórmula
            # do hash); observations leva só a justificação livre.
            self.assertEqual(ult.authority_nome, 'Maria Costa')
            self.assertEqual(ult.authority_cargo, 'Procuradora da República')
            self.assertIsNotNone(ult.act_declared_at)
            self.assertIsNone(ult.act_deadline_days)
            self.assertEqual(ult.observations, 'Despacho 123/26.')
            self.assertEqual(ult.hash_version, 'hv4')
            # Ato sem deslocação: sem GPS; custódio herdado do último evento.
            self.assertIsNone(ult.gps_lat)
            self.assertEqual(ult.custodian_institution_id, self.opc.id)
            # Eixos separados: o estado de custódia NÃO muda; o estatuto sim.
            self.assertEqual(legal_state_of(ev), 'a_guarda_opc')
            self.assertEqual(validation_status_of(ev), 'validada')

    def test_validacao_parcial_so_dos_selecionados(self):
        r = self._post(self._payload([self.ev1.id]))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)
        self.assertEqual(self._last(self.ev2).event_type, EventType.APREENSAO_OBJETO)
        self.assertEqual(validation_status_of(self.ev2), 'por_validar')

    def test_item_validado_sai_da_lista(self):
        self._post(self._payload([self.ev1.id, self.ev2.id]))
        body = self._get('?modal=1').content.decode()
        self.assertIn('Sem apreensões por validar', body)

    # -- Validação de entrada --------------------------------------------

    def test_sem_selecao_devolve_erro(self):
        r = self._post(self._payload([]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Selecione pelo menos um item', r.content.decode())

    def test_sem_autoridade_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], authority_nome=''))
        self.assertEqual(r.status_code, 400)
        self.assertIn('nome da autoridade', r.content.decode())

    def test_sem_cargo_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], authority_cargo=''))
        self.assertEqual(r.status_code, 400)
        self.assertIn('cargo da autoridade', r.content.decode())

    def test_data_no_futuro_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], act_declared_at=_dtl(timezone.now() + timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('futuro', r.content.decode())

    def test_data_anterior_a_apreensao_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], act_declared_at=_dtl(timezone.now() - timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anteceder', r.content.decode())
        self.assertEqual(self._last(self.ev1).event_type, EventType.APREENSAO_OBJETO)


class ValidacaoCaminhoUnicoTest(TestCase):
    """O ato de validação tem UM caminho de registo (o modal certificado, que
    pede quem/quando/justificação): o formulário genérico da timeline deixa de
    oferecer VALIDACAO_APREENSAO e as páginas do item ligam ao modal da
    ocorrência enquanto o ato está pendente. As guardas do MODELO não mudam —
    é só o ecrã que fecha o segundo caminho sem certificação."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Uni', type=InstitutionType.OPC, sigla='PSP-UN')
        cls.agent = _user('uni_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ_pend = _occ(cls.agent, 'UNI-P')
        cls.ev_pend = _evidence(cls.occ_pend, cls.agent)
        _event(cls.ev_pend, cls.agent, inst=cls.opc)
        cls.occ_ok = _occ(cls.agent, 'UNI-OK')
        cls.ev_ok = _evidence(cls.occ_ok, cls.agent)
        _event(cls.ev_ok, cls.agent, inst=cls.opc)
        _event(cls.ev_ok, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url)

    def test_timeline_nao_oferece_validacao_no_select_generico(self):
        body = self._get(f'/evidences/{self.ev_pend.id}/custody/').content.decode()
        self.assertNotIn('<option value="VALIDACAO_APREENSAO"', body)
        # O caminho certo está lá: botão dedicado para o modal da ocorrência.
        self.assertIn(f'/occurrences/{self.occ_pend.id}/validar/', body)

    def test_timeline_sem_pendencia_nao_mostra_botao(self):
        body = self._get(f'/evidences/{self.ev_ok.id}/custody/').content.decode()
        self.assertNotIn('Validar apreensão', body)

    def test_detalhe_do_item_liga_ao_modal_quando_pendente(self):
        body = self._get(f'/evidences/{self.ev_pend.id}/').content.decode()
        self.assertIn(f'/occurrences/{self.occ_pend.id}/validar/', body)
        ok = self._get(f'/evidences/{self.ev_ok.id}/').content.decode()
        self.assertNotIn(f'/occurrences/{self.occ_ok.id}/validar/', ok)


class ValidationVisibilityTest(TestCase):
    """Visibilidade transversal do trabalho de validação: tile "A aguardar
    validação" no painel (filtra a tabela local via ?attn=pending, como os
    prazos) e marcador pendente (val-flag) nas grelhas de ocorrências,
    evidências e custódias."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Vis', type=InstitutionType.OPC, sigla='PSP-VS')
        cls.agent = _user('vis_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        # occ_pend: item com apreensão por validar; occ_ok: item já validado.
        cls.occ_pend = _occ(cls.agent, 'VIS-P')
        cls.ev_pend = _evidence(cls.occ_pend, cls.agent)
        _event(cls.ev_pend, cls.agent, inst=cls.opc)
        cls.occ_ok = _occ(cls.agent, 'VIS-OK')
        cls.ev_ok = _evidence(cls.occ_ok, cls.agent)
        _event(cls.ev_ok, cls.agent, inst=cls.opc)
        _event(cls.ev_ok, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url)

    def test_dashboard_tem_tile_a_aguardar_validacao(self):
        body = self._get('/dashboard/').content.decode()
        self.assertIn('A aguardar validação', body)
        self.assertIn('?attn=pending', body)
        self.assertIn('cs-tile--attn', body)

    def test_attn_pending_filtra_tabela_local(self):
        body = self._get('/dashboard/?attn=pending').content.decode()
        self.assertIn(self.occ_pend.number, body)
        self.assertNotIn(self.occ_ok.number, body)

    def test_lista_ocorrencias_marca_processos_pendentes(self):
        body = self._get('/occurrences/').content.decode()
        self.assertIn('val-flag', body)
        # Só o processo pendente leva marcador (1 ocorrência × 1 célula).
        self.assertEqual(body.count('val-flag'), 1)
        self.assertIn('1 item(ns) a aguardar validação', body)

    def test_lista_evidencias_marca_itens_pendentes(self):
        body = self._get('/evidences/').content.decode()
        self.assertEqual(body.count('val-flag'), 1)

    def test_lista_custodias_marca_eventos_de_itens_pendentes(self):
        body = self._get('/custodies/').content.decode()
        # 1 evento do item pendente; os 2 eventos do item validado não marcam.
        self.assertEqual(body.count('val-flag'), 1)

    def test_marcador_na_celula_do_codigo_e_legenda_de_pendencia(self):
        # Parecer UX item 7: o marcador saiu da coluna Estado (col-reduce-hide
        # — sumia no telemóvel) para a célula do Código, que sobrevive à
        # redução; a legenda de pendência fica visível também em desktop.
        for url in ('/evidences/', '/custodies/'):
            body = self._get(url).content.decode()
            code_cells = [c for c in body.split('</td>') if 'grid__code' in c]
            self.assertTrue(any('val-flag' in c for c in code_cells), url)
            state_cells = [c for c in body.split('</td>') if 'class="state state--' in c]
            self.assertFalse(any('val-flag' in c for c in state_cells), url)
            self.assertIn('urgency-legend--always', body)
            self.assertIn('marcadores de pendência', body)
