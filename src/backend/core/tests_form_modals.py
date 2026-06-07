"""ForensiQ — Testes: superfície MODAL dos formulários pesados (ação-in-place).

Os formulários de Nova ocorrência e Novo item de prova servem DUAS superfícies da
mesma lógica de view: a página completa (fallback no-JS / navegação direta) e o
fragmento modal (``?modal=1``). Em modo modal:
  • GET devolve só o fragmento do formulário (sem casca / sem <!DOCTYPE>);
  • POST válido responde 204 + cabeçalho ``HX-Redirect`` (o HTMX navega);
  • POST inválido responde 400 com o fragmento (os erros aparecem no modal).
A sidebar mostra atalhos "Nova X" (gateados a agente/staff) que disparam estes modais.

Os testes exercem o caminho HTTP real (serializer + génese de apreensão), não fabricam.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import Evidence, Institution, InstitutionMembership, InstitutionType, Occurrence
from core.tests_access import _occ, _user
from core.tests_factories import CrimeTipoFactory

User = get_user_model()


class FormModalSurfaceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Modal', type=InstitutionType.OPC, sigla='PSP-MO'
        )
        cls.agent = _user('modal_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        # Não-agente sem staff: não pode registar → não vê os atalhos.
        cls.expert = _user('modal_expert', User.Profile.FORENSIC_EXPERT)
        cls.crime = CrimeTipoFactory()
        cls.occ = _occ(cls.agent, 'MODAL-1')

    def _auth(self, user):
        self.client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(user))

    # -- Ocorrência: GET fragmento vs página -----------------------------------

    def test_occurrence_get_modal_devolve_fragmento(self):
        self._auth(self.agent)
        body = self.client.get('/occurrences/new/?modal=1').content.decode()
        # Fragmento: traz o título do modal, submete por HTMX e marca modal=1...
        self.assertIn('data-modal-title="Nova ocorrência"', body)
        self.assertIn('hx-post="/occurrences/new/"', body)
        self.assertIn('name="modal"', body)
        self.assertIn('data-crime-cascade', body)
        # ...e NÃO traz a casca da página completa.
        self.assertNotIn('<!DOCTYPE', body)
        self.assertNotIn('id="app-modal"', body)

    def test_occurrence_get_pagina_completa_tem_casca(self):
        self._auth(self.agent)
        body = self.client.get('/occurrences/new/').content.decode()
        self.assertIn('<!DOCTYPE', body)
        # Página completa submete nativo (não por HTMX para o modal-body).
        self.assertIn('action="/occurrences/new/"', body)
        self.assertNotIn('hx-post="/occurrences/new/"', body)

    # -- Ocorrência: POST modal fecha o ciclo (204 + HX-Redirect) --------------

    def test_occurrence_post_modal_valido_204_e_hx_redirect(self):
        self._auth(self.agent)
        r = self.client.post('/occurrences/new/', {
            'modal': '1',
            'number': 'NUIPC-MODAL-OK-1',
            'description': 'Ocorrência criada pelo modal.',
            'date_time': '2026-06-01T10:00',
            'crime_type': self.crime.id,
        })
        self.assertEqual(r.status_code, 204)
        occ = Occurrence.objects.get(number='NUIPC-MODAL-OK-1')
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{occ.pk}/')

    def test_occurrence_post_modal_invalido_400_fragmento(self):
        self._auth(self.agent)
        r = self.client.post('/occurrences/new/', {
            'modal': '1',
            # falta 'number' (obrigatório) → erro de validação
            'description': 'Sem número.',
            'date_time': '2026-06-01T10:00',
            'crime_type': self.crime.id,
        })
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('data-modal-title="Nova ocorrência"', body)
        self.assertNotIn('<!DOCTYPE', body)
        self.assertFalse(
            Occurrence.objects.filter(description='Sem número.').exists()
        )

    # -- Item de prova: GET fragmento + POST modal -----------------------------

    def test_evidence_get_modal_devolve_fragmento_multipart(self):
        self._auth(self.agent)
        body = self.client.get('/evidences/new/?modal=1').content.decode()
        self.assertIn('data-modal-title="Novo item de prova"', body)
        self.assertIn('hx-post="/evidences/new/"', body)
        # A fotografia exige multipart no HTMX.
        self.assertIn('hx-encoding="multipart/form-data"', body)
        self.assertIn('data-id-section', body)
        self.assertNotIn('<!DOCTYPE', body)

    def test_evidence_full_page_renders_type_fields(self):
        """Diagnóstico: a página completa (e o fragmento) renderizam os campos
        por-tipo (id-section), p.ex. o IMEI de MOBILE_DEVICE — alvo do e2e."""
        self._auth(self.agent)
        page = self.client.get('/evidences/new/').content.decode()
        self.assertIn('id="f-tsd-MOBILE_DEVICE-imei"', page)
        self.assertIn('data-id-type="MOBILE_DEVICE"', page)
        frag = self.client.get('/evidences/new/?modal=1').content.decode()
        self.assertIn('id="f-tsd-MOBILE_DEVICE-imei"', frag)

    def test_evidence_post_modal_valido_204_e_hx_redirect(self):
        self._auth(self.agent)
        r = self.client.post('/evidences/new/', {
            'modal': '1',
            'occurrence': self.occ.id,
            'type': Evidence.EvidenceType.MOBILE_DEVICE,
            'description': 'Telemóvel registado pelo modal.',
        })
        self.assertEqual(r.status_code, 204)
        ev = Evidence.objects.filter(occurrence=self.occ).latest('id')
        self.assertEqual(r['HX-Redirect'], f'/evidences/{ev.pk}/')
        # Registo = apreensão: a génese nasce na mesma transação.
        self.assertEqual(ev.custody_chain.count(), 1)

    def test_evidence_post_modal_invalido_400_fragmento(self):
        self._auth(self.agent)
        r = self.client.post('/evidences/new/', {
            'modal': '1',
            'occurrence': self.occ.id,
            # falta 'type' (obrigatório)
            'description': 'Sem tipo.',
        })
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('data-modal-title="Novo item de prova"', body)
        self.assertNotIn('<!DOCTYPE', body)

    # -- Sidebar: atalhos "Nova X" gateados ------------------------------------

    def test_sidebar_mostra_atalhos_para_agente(self):
        self._auth(self.agent)
        body = self.client.get('/dashboard/').content.decode()
        self.assertIn('app-sidebar__link--action', body)
        self.assertIn('hx-get="/occurrences/new/?modal=1"', body)
        self.assertIn('hx-get="/evidences/new/?modal=1"', body)
        self.assertIn('Nova ocorrência', body)
        self.assertIn('Novo item', body)

    def test_sidebar_esconde_atalhos_para_nao_agente(self):
        self._auth(self.expert)
        body = self.client.get('/dashboard/').content.decode()
        self.assertNotIn('app-sidebar__link--action', body)
        self.assertNotIn('hx-get="/occurrences/new/?modal=1"', body)
        self.assertNotIn('hx-get="/evidences/new/?modal=1"', body)
