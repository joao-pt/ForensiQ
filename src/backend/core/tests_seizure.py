"""ForensiQ — Testes: registar um item de prova É apreendê-lo (génese automática).

Modelo do dono (ADR-0016 §2): não há prova registada sem ficar sob custódia. O
ato de registo cria, na MESMA transação, o evento de génese (APREENSAO_OBJETO /
APREENSAO_DADOS) à guarda do OPC do agente — deixando o item pronto a encaminhar.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import (
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionMembership,
    InstitutionType,
    derive_legal_state,
)
from core.tests_access import _occ, _user
from core.utils import sort_custody_chain

User = get_user_model()


class RegistoEhApreensaoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Seizure', type=InstitutionType.OPC, sigla='PSP-SZ'
        )
        cls.agent = _user('seiz_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'SEIZ-1')

    def _post_new_evidence(self, **extra):
        self.client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(self.agent))
        data = {
            'occurrence': self.occ.id,
            'type': Evidence.EvidenceType.MOBILE_DEVICE,
            'description': 'Telemovel apreendido ao suspeito.',
        }
        data.update(extra)
        return self.client.post('/evidences/new/', data)

    def test_registo_cria_genese_de_apreensao(self):
        r = self._post_new_evidence()
        self.assertEqual(r.status_code, 302)
        ev = Evidence.objects.filter(occurrence=self.occ).latest('id')
        events = list(ev.custody_chain.all())
        self.assertEqual(len(events), 1, 'o registo devia criar exatamente a génese')
        g = events[0]
        self.assertEqual(g.event_type, EventType.APREENSAO_OBJETO)
        self.assertEqual(g.custodian_type, CustodianType.OPC)
        self.assertEqual(g.custodian_institution_id, self.opc.id)
        self.assertEqual(g.agent_id, self.agent.id)

    def test_item_fica_a_guarda_do_opc_pronto_a_encaminhar(self):
        self._post_new_evidence()
        ev = Evidence.objects.filter(occurrence=self.occ).latest('id')
        estado = derive_legal_state(sort_custody_chain(ev.custody_chain.all()))
        self.assertEqual(estado, 'a_guarda_opc')

    def test_genese_herda_gps_do_local_de_apreensao(self):
        r = self._post_new_evidence(gps_lat='38.7197003', gps_lng='-9.1466657')
        self.assertEqual(r.status_code, 302)
        ev = Evidence.objects.filter(occurrence=self.occ).latest('id')
        g = ev.custody_chain.get()
        self.assertIsNotNone(g.gps_lat)
        self.assertEqual(str(g.gps_lat), '38.7197003')

    def test_agente_sem_pertenca_genese_sem_instituicao(self):
        # Um agente sem pertença institucional ainda apreende (custódio OPC), mas
        # sem instituição associada — não bloqueia o registo.
        loner = _user('seiz_loner', User.Profile.FIRST_RESPONDER)
        self.client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(loner))
        occ = _occ(loner, 'SEIZ-2')
        r = self.client.post('/evidences/new/', {
            'occurrence': occ.id,
            'type': Evidence.EvidenceType.MOBILE_DEVICE,
            'description': 'Item sem instituicao.',
        })
        self.assertEqual(r.status_code, 302)
        ev = Evidence.objects.filter(occurrence=occ).latest('id')
        g = ev.custody_chain.get()
        self.assertEqual(g.event_type, EventType.APREENSAO_OBJETO)
        self.assertIsNone(g.custodian_institution_id)
