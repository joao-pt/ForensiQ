"""ForensiQ — Testes de view da lente de acesso (consolas por papel, ADR-0017).

Exercita o dispatch por lente nas views server-rendered, a propagação do
``?lens=`` (toolbar/qs_base), o fallback silencioso de lente proibida, a
renderização condicional dos chips e o rótulo de âmbito do feed.
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
)
from core.tests_access import _event, _evidence, _occ, _user

User = get_user_model()


class LensFrontendTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lab = Institution.objects.create(
            name='Lab F', type=InstitutionType.LAB_PUBLICO, sigla='LAB-F'
        )
        cls.responder = _user('lf_responder', User.Profile.FIRST_RESPONDER)
        cls.custodian = _user('lf_custodian', User.Profile.EVIDENCE_CUSTODIAN)
        # Perito NORMAL: leitura total por FUNÇÃO (não detém nada).
        cls.perito = _user('lf_perito', User.Profile.FORENSIC_EXPERT)
        cls.perito_nac = _user(
            'lf_perito_nac', User.Profile.FORENSIC_EXPERT, User.Clearance.NACIONAL
        )
        # CHEFE_SERVICO NORMAL: só a lente "custody" → sem chips.
        cls.chefe_norm = _user('lf_chefe_norm', User.Profile.CHEFE_SERVICO)
        InstitutionMembership.objects.create(user=cls.custodian, institution=cls.lab)

        cls.occ = _occ(cls.responder, 'F1')
        cls.ev = _evidence(cls.occ, cls.responder)
        _event(cls.ev, cls.responder, inst=cls.lab)
        _event(
            cls.ev, cls.custodian, event_type=EventType.TRANSFERENCIA_CUSTODIA, inst=cls.lab
        )

    def _get(self, user, url):
        self.client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(user))
        return self.client.get(url)

    def test_hidden_lens_input_no_toolbar(self):
        r = self._get(self.responder, '/occurrences/?lens=mine')
        self.assertEqual(r.status_code, 200)
        self.assertIn('name="lens" value="mine"', r.content.decode())

    def test_lens_proibida_cai_em_default_sem_500(self):
        # FIRST_RESPONDER não tem a lente ALL → ?lens=all cai na default (mine).
        r = self._get(self.responder, '/evidences/?lens=all')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('name="lens" value="mine"', body)
        self.assertNotIn('name="lens" value="all"', body)

    def test_chips_para_multilente(self):
        body = self._get(self.responder, '/occurrences/').content.decode()
        self.assertIn('class="lens-bar"', body)
        self.assertIn('href="?lens=mine"', body)
        self.assertIn('href="?lens=custody"', body)
        # FIRST_RESPONDER (sem leitura total) não tem a lente "Tudo".
        self.assertNotIn('href="?lens=all"', body)

    def test_perito_tem_lente_tudo(self):
        body = self._get(self.perito, '/occurrences/').content.decode()
        self.assertIn('href="?lens=all"', body)

    def test_sem_chips_para_lente_unica(self):
        # CHEFE_SERVICO NORMAL só tem a lente "custody" → sem barra de chips.
        r = self._get(self.chefe_norm, '/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('class="lens-bar"', r.content.decode())

    def test_custody_nao_curtocircuita_full_read_na_view(self):
        # Perito (leitura total) que não detém nada: a lista de evidências em
        # "custody" não mostra o item, mas em "all" mostra.
        all_body = self._get(self.perito, '/evidences/?lens=all').content.decode()
        cust_body = self._get(self.perito, '/evidences/?lens=custody').content.decode()
        self.assertIn(f'data-id="{self.ev.id}"', all_body)
        self.assertNotIn(f'data-id="{self.ev.id}"', cust_body)

    def test_feed_label_minhas_acoes_para_normal(self):
        # Perito NORMAL tem leitura total da prova, mas o feed é só dos seus atos.
        body = self._get(self.perito, '/dashboard/').content.decode()
        self.assertIn('Apenas as minhas ações', body)
        self.assertNotIn('Registo nacional', body)

    def test_feed_label_nacional_para_nacional(self):
        body = self._get(self.perito_nac, '/dashboard/').content.decode()
        self.assertIn('Registo nacional', body)
