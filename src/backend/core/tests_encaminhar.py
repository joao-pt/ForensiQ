"""ForensiQ — Testes: encaminhar prova em LOTE a partir da ocorrência (handoff v2).

Modelo do dono: depois de registar (= apreender) os itens, o agente encaminha a
prova TODA junta a um portador, com destino — 1 evento ENCAMINHAMENTO_CUSTODIA por
item, SEM GPS (em trânsito até à receção). O custódio é promovido pelo tipo do
destino, por isso o gate de laboratório (CPP Art. 154.º) dispara para destinos LAB.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import (
    EventType,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Portador,
    ProvaEmTransito,
    derive_legal_state,
)
from core.tests_access import _event, _evidence, _occ, _user
from core.utils import sort_custody_chain

User = get_user_model()


class EncaminharLoteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Enc', type=InstitutionType.OPC, sigla='PSP-EN')
        cls.opc2 = Institution.objects.create(name='PJ Enc', type=InstitutionType.OPC, sigla='PJ-EN')
        cls.lab = Institution.objects.create(name='LPC Enc', type=InstitutionType.LAB_PUBLICO, sigla='LPC-EN')
        cls.agent = _user('enc_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.portador = Portador.objects.create(
            matricula='ENC-P-001', nome='Ana', apelido='Silva', posto='Agente principal'
        )
        cls.occ = _occ(cls.agent, 'ENC-1')
        # Dois itens à guarda do OPC (génese feita) → encamináveis.
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)

    def _auth(self):
        self.client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(self.agent))

    def _get(self, url):
        self._auth()
        return self.client.get(url)

    def _post(self, url, data):
        self._auth()
        return self.client.post(url, data)

    def _enc_url(self):
        return f'/occurrences/{self.occ.id}/encaminhar/'

    def _last(self, ev):
        return sort_custody_chain(ev.custody_chain.all())[-1]

    # -- Modal / listagem ------------------------------------------------

    def test_modal_lista_itens_encaminhaveis(self):
        body = self._get(self._enc_url() + '?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento
        self.assertIn(f'value="{self.ev1.id}"', body)
        self.assertIn(f'value="{self.ev2.id}"', body)
        self.assertIn('name="bearer"', body)
        self.assertIn('name="custodian_institution"', body)

    # -- Encaminhamento OK ------------------------------------------------

    def test_encaminha_para_opc_cria_eventos_em_transito(self):
        r = self._post(self._enc_url(), {
            'modal': '1', 'evidence_ids': [self.ev1.id, self.ev2.id],
            'bearer': self.portador.id, 'custodian_institution': self.opc2.id,
        })
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{self.occ.id}/')
        for ev in (self.ev1, self.ev2):
            ult = self._last(ev)
            self.assertEqual(ult.event_type, EventType.ENCAMINHAMENTO_CUSTODIA)
            self.assertEqual(ult.bearer_id, self.portador.id)
            self.assertEqual(ult.bearer_matricula, 'ENC-P-001')  # snapshot na cadeia
            self.assertIsNone(ult.gps_lat)
            self.assertIsNone(ult.gps_lng)
            self.assertEqual(
                derive_legal_state(sort_custody_chain(ev.custody_chain.all())), 'em_transito'
            )

    def test_prova_em_transito_criada_para_destino(self):
        self._post(self._enc_url(), {
            'modal': '1', 'evidence_ids': [self.ev1.id],
            'bearer': self.portador.id, 'custodian_institution': self.opc2.id,
        })
        self.assertTrue(
            ProvaEmTransito.objects.filter(
                destino_institution=self.opc2, evidence=self.ev1, acknowledged_at__isnull=True
            ).exists()
        )

    # -- Gate de laboratório (CPP Art. 154.º) ----------------------------

    def test_encaminha_para_lab_sem_despacho_e_bloqueado(self):
        r = self._post(self._enc_url(), {
            'modal': '1', 'evidence_ids': [self.ev1.id],
            'bearer': self.portador.id, 'custodian_institution': self.lab.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('DESPACHO_PERICIA', r.content.decode())
        # Rollback: o item continua à guarda do OPC, sem encaminhamento.
        self.assertEqual(self._last(self.ev1).event_type, EventType.APREENSAO_OBJETO)
        self.assertFalse(ProvaEmTransito.objects.filter(evidence=self.ev1).exists())

    # -- Validação de entrada --------------------------------------------

    def test_sem_selecao_devolve_erro(self):
        r = self._post(self._enc_url(), {
            'modal': '1', 'bearer': self.portador.id, 'custodian_institution': self.opc2.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('Selecione pelo menos um item', r.content.decode())

    def test_sem_portador_devolve_erro(self):
        r = self._post(self._enc_url(), {
            'modal': '1', 'evidence_ids': [self.ev1.id], 'custodian_institution': self.opc2.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('portador', r.content.decode())

    # -- Atomicidade do lote (tudo-ou-nada) ------------------------------

    def test_lote_misto_reverte_tudo_se_um_falha(self):
        # ev2 vai para o lab (sem despacho → falha o gate). Como é atómico, ev1
        # também não é encaminhado.
        r = self._post(self._enc_url(), {
            'modal': '1', 'evidence_ids': [self.ev1.id, self.ev2.id],
            'bearer': self.portador.id, 'custodian_institution': self.lab.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._last(self.ev1).event_type, EventType.APREENSAO_OBJETO)
        self.assertEqual(self._last(self.ev2).event_type, EventType.APREENSAO_OBJETO)
