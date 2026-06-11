"""ForensiQ — Testes: despacho para perícia em LOTE a partir da ocorrência.

Modelo de domínio (CPP art. 154.º): o despacho é um ATO de autoridade, não uma
deslocação — regista QUEM ordenou a perícia, QUANDO (data do despacho,
declarada) e a referência, sem GPS nem mudança de custódio (herdado do último
evento). O ``timestamp`` do evento é sempre o do servidor; a data do despacho
entra no texto CERTIFICADO de ``observations``, que faz parte da fórmula do
hash. A maquinaria é a MESMA da validação (modal único dos atos certificados,
``_CERTIFIED_ACT_SPECS``); o despacho é repetível (2.ª perícia — Art. 158.º).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core.models import (
    CustodianType,
    EventType,
    Institution,
    InstitutionMembership,
    InstitutionType,
)
from core.tests_base import BaseAPITestCase, auth_cookie
from core.tests_factories import (
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)
from core.utils import legal_state_of, sort_custody_chain

User = get_user_model()


def _dtl(dt):
    """Valor de um input ``datetime-local`` (YYYY-MM-DDTHH:MM) em hora local."""
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


class DespacharLoteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Dsp', type=InstitutionType.OPC, sigla='PSP-DS')
        cls.agent = _user('dsp_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'DSP-1')
        # Dois itens despacháveis JÁ (apreensão validada — CPP 178.º/5-6).
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        _event(cls.ev1, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)
        _event(cls.ev2, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)
        # Item com apreensão POR VALIDAR: só despachável incluindo a validação.
        cls.ev_pend = _evidence(cls.occ, cls.agent)
        _event(cls.ev_pend, cls.agent, inst=cls.opc)
        # Item EM TRÂNSITO: não despachável (a receção tem de fechar primeiro).
        cls.ev_transit = _evidence(cls.occ, cls.agent)
        _event(cls.ev_transit, cls.agent, inst=cls.opc)
        _event(
            cls.ev_transit, cls.agent,
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.OPC, inst=cls.opc,
            bearer_nome='Rui', bearer_apelido='Faria', bearer_matricula='PSP-78',
        )

    def _post(self, data):
        auth_cookie(self.client, self.agent)
        return self.client.post(f'/occurrences/{self.occ.id}/despachar/', data)

    def _get(self, suffix=''):
        auth_cookie(self.client, self.agent)
        return self.client.get(f'/occurrences/{self.occ.id}/despachar/{suffix}')

    def _last(self, ev):
        return sort_custody_chain(ev.custody_chain.all())[-1]

    def _payload(self, ids, **extra):
        data = {
            'modal': '1',
            'evidence_ids': ids,
            'validated_by': 'Procurador João Macedo',
            'validated_at': _dtl(timezone.now()),
        }
        data.update(extra)
        return data

    # -- Modal / listagem ------------------------------------------------

    def test_modal_lista_so_itens_despachaveis(self):
        body = self._get('?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento
        self.assertIn(f'value="{self.ev1.id}"', body)
        self.assertIn(f'value="{self.ev2.id}"', body)
        # Pendente de validação TAMBÉM aparece (despachável incluindo-a),
        # com o alerta e a opção expressa de incluir a validação.
        self.assertIn(f'value="{self.ev_pend.id}"', body)
        self.assertIn('name="include_validation"', body)
        self.assertIn('POR VALIDAR', body)
        self.assertNotIn(f'value="{self.ev_transit.id}"', body)  # em trânsito
        self.assertIn('name="validated_by"', body)
        self.assertIn('name="validated_at"', body)
        self.assertIn('name="justification"', body)
        self.assertIn('Quem ordenou a perícia', body)
        # Ato jurídico: o modal não pede GPS nem local.
        self.assertNotIn('name="gps_lat"', body)
        self.assertNotIn('name="location_name"', body)

    # -- Despacho OK -------------------------------------------------------

    def test_despacha_em_lote_sem_mudar_o_estado(self):
        r = self._post(self._payload(
            [self.ev1.id, self.ev2.id], justification='Despacho 77/26 — exame pericial.',
        ))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{self.occ.id}/')
        for ev in (self.ev1, self.ev2):
            ult = self._last(ev)
            self.assertEqual(ult.event_type, EventType.DESPACHO_PERICIA)
            # Quem ordenou + data do despacho + referência: texto CERTIFICADO
            # (observations entra na fórmula do hash).
            self.assertIn('Perícia ordenada por Procurador João Macedo', ult.observations)
            self.assertIn('Despacho 77/26 — exame pericial.', ult.observations)
            # Ato sem deslocação: sem GPS; custódio herdado do último evento.
            self.assertIsNone(ult.gps_lat)
            self.assertEqual(ult.custodian_institution_id, self.opc.id)
            # O estado de custódia NÃO muda (o despacho não desloca a prova).
            self.assertEqual(legal_state_of(ev), 'a_guarda_opc')

    def test_despacho_abre_o_gate_de_pericia(self):
        """Com o despacho registado, INICIO_PERICIA passa a ser aceite."""
        self._post(self._payload([self.ev1.id]))
        rec = _event(
            self.ev1, self.agent, event_type=EventType.INICIO_PERICIA,
            custodian_type=CustodianType.LAB_PUBLICO,
        )
        self.assertEqual(rec.event_type, EventType.INICIO_PERICIA)
        self.assertEqual(legal_state_of(self.ev1), 'em_pericia')

    def test_despacho_e_repetivel(self):
        """2.ª perícia (Art. 158.º): um novo despacho é aceite no mesmo item."""
        self._post(self._payload([self.ev1.id]))
        r = self._post(self._payload([self.ev1.id], justification='Nova perícia.'))
        self.assertEqual(r.status_code, 204)
        tipos = [x.event_type for x in sort_custody_chain(self.ev1.custody_chain.all())]
        self.assertEqual(tipos.count(EventType.DESPACHO_PERICIA), 2)

    def test_despacho_parcial_so_dos_selecionados(self):
        r = self._post(self._payload([self.ev1.id]))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self._last(self.ev1).event_type, EventType.DESPACHO_PERICIA)
        self.assertEqual(self._last(self.ev2).event_type, EventType.VALIDACAO_APREENSAO)

    # -- Apreensão por validar (CPP 178.º/5-6): despacho inclui a validação --

    def test_pendente_sem_checkbox_devolve_erro(self):
        """Item por validar selecionado sem a opção expressa → recusado, e
        nada entra no ledger (nem validação, nem despacho)."""
        r = self._post(self._payload([self.ev1.id, self.ev_pend.id]))
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('por validar', body)
        self.assertIn(self.ev_pend.code, body)
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)
        self.assertEqual(self._last(self.ev_pend).event_type, EventType.APREENSAO_OBJETO)

    def test_pendente_com_checkbox_regista_validacao_e_despacho(self):
        """Com «o despacho inclui a validação»: VALIDACAO_APREENSAO entra
        imediatamente antes do DESPACHO, pela mesma autoridade — a validação
        implícita da jurisprudência fica explícita no ledger."""
        r = self._post(self._payload(
            [self.ev1.id, self.ev_pend.id], include_validation='1',
            justification='Despacho 90/26.',
        ))
        self.assertEqual(r.status_code, 204)
        tipos = [x.event_type for x in sort_custody_chain(self.ev_pend.custody_chain.all())]
        self.assertEqual(
            tipos,
            [EventType.APREENSAO_OBJETO, EventType.VALIDACAO_APREENSAO,
             EventType.DESPACHO_PERICIA],
        )
        eventos = sort_custody_chain(self.ev_pend.custody_chain.all())
        self.assertIn('Apreensão validada por Procurador João Macedo', eventos[1].observations)
        self.assertIn('Validação incluída no despacho', eventos[1].observations)
        self.assertIn('Perícia ordenada por Procurador João Macedo', eventos[2].observations)
        # O item já validado leva SÓ o despacho (não revalida).
        tipos_ev1 = [x.event_type for x in sort_custody_chain(self.ev1.custody_chain.all())]
        self.assertEqual(tipos_ev1.count(EventType.VALIDACAO_APREENSAO), 1)
        self.assertEqual(tipos_ev1[-1], EventType.DESPACHO_PERICIA)

    # -- Validação de entrada --------------------------------------------

    def test_sem_selecao_devolve_erro(self):
        r = self._post(self._payload([]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Selecione pelo menos um item', r.content.decode())

    def test_sem_autoridade_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], validated_by=''))
        self.assertEqual(r.status_code, 400)
        self.assertIn('quem ordenou', r.content.decode())

    def test_data_no_futuro_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], validated_at=_dtl(timezone.now() + timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('futuro', r.content.decode())

    def test_data_anterior_a_genese_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], validated_at=_dtl(timezone.now() - timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anteceder', r.content.decode())
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)


class DespachoCaminhoUnicoTest(TestCase):
    """O despacho tem UM caminho de registo (o modal certificado, que pede
    quem/quando/referência): o formulário genérico da timeline deixa de
    oferecer DESPACHO_PERICIA e as páginas do item ligam ao modal da
    ocorrência. As guardas do MODELO não mudam — é só o ecrã que fecha o
    segundo caminho sem certificação (a API recusa o evento "nu" na fronteira)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP DUn', type=InstitutionType.OPC, sigla='PSP-DU')
        cls.agent = _user('dun_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'DUN-1')
        cls.ev = _evidence(cls.occ, cls.agent)
        _event(cls.ev, cls.agent, inst=cls.opc)

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url)

    def test_timeline_nao_oferece_despacho_no_select_generico(self):
        body = self._get(f'/evidences/{self.ev.id}/custody/').content.decode()
        self.assertNotIn('<option value="DESPACHO_PERICIA"', body)
        # O caminho certo está lá: botão dedicado para o modal da ocorrência.
        self.assertIn(f'/occurrences/{self.occ.id}/despachar/', body)

    def test_detalhe_do_item_liga_ao_modal(self):
        body = self._get(f'/evidences/{self.ev.id}/').content.decode()
        self.assertIn(f'/occurrences/{self.occ.id}/despachar/', body)

    def test_detalhe_da_ocorrencia_tem_botao(self):
        body = self._get(f'/occurrences/{self.occ.id}/').content.decode()
        self.assertIn(f'/occurrences/{self.occ.id}/despachar/', body)


class DespachoAPITest(BaseAPITestCase):
    """A fronteira de escrita externa é a MESMA da validação: o serializer
    recusa o despacho "nu" (sem identificação de quem o proferiu) e aceita o
    evento certificado."""

    def setUp(self):
        super().setUp()
        self.occ = _occ(self.agent, 'DAPI-1')
        self.ev = _evidence(self.occ, self.agent)
        _event(self.ev, self.agent)
        _event(self.ev, self.agent, event_type=EventType.VALIDACAO_APREENSAO)

    def test_api_recusa_despacho_sem_identificacao(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': self.ev.pk,
            'event_type': 'DESPACHO_PERICIA',
            'custodian_type': 'OPC',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identificação', str(r.data))
        self.assertEqual(self.ev.custody_chain.count(), 2)

    def test_api_recusa_despacho_com_apreensao_por_validar(self):
        """A guarda do MODELO vale também na API: apreensão por validar →
        o despacho é recusado (CPP 178.º/5-6)."""
        ev2 = _evidence(self.occ, self.agent)
        _event(ev2, self.agent)   # apreensão SEM validação
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': ev2.pk,
            'event_type': 'DESPACHO_PERICIA',
            'custodian_type': 'OPC',
            'observations': 'Perícia ordenada pelo Procurador João Macedo.',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('VALIDADA', str(r.data))
        self.assertEqual(ev2.custody_chain.count(), 1)

    def test_api_aceita_despacho_certificado(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': self.ev.pk,
            'event_type': 'DESPACHO_PERICIA',
            'custodian_type': 'OPC',
            'observations': 'Perícia ordenada pelo Procurador João Macedo (Art. 154.º).',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['event_type'], 'DESPACHO_PERICIA')
