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
        # Dois itens despacháveis (génese feita, ledger aberto).
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)
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
        self.assertEqual(self._last(self.ev2).event_type, EventType.APREENSAO_OBJETO)

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
        self.assertEqual(self._last(self.ev1).event_type, EventType.APREENSAO_OBJETO)


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

    def test_api_recusa_despacho_sem_identificacao(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': self.ev.pk,
            'event_type': 'DESPACHO_PERICIA',
            'custodian_type': 'OPC',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identificação', str(r.data))
        self.assertEqual(self.ev.custody_chain.count(), 1)

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
