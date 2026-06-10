"""ForensiQ — Testes: páginas de registo de Nova ocorrência e Novo item de prova.

Estes formulários pesados são servidos como PÁGINA COMPLETA — o atalho da barra
lateral navega directamente para `/occurrences/new/` e `/evidences/new/` (já não
há superfície modal: ação-in-place fica para ações curtas como encaminhar). GET
renderiza a casca + o formulário com `action` nativo; POST válido cria e
redireciona (302) para o detalhe; POST inválido devolve 400 com os erros na
própria página. Os atalhos "Nova X" da sidebar (gateados a agente/staff) são
links de navegação simples.

Exercem o caminho HTTP real (serializer + génese de apreensão), não fabricam.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import (
    Evidence,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Occurrence,
)
from core.tests_base import auth_cookie
from core.tests_factories import CrimeTipoFactory, make_occ as _occ, make_user as _user

User = get_user_model()


class NewFormPageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Form', type=InstitutionType.OPC, sigla='PSP-FO'
        )
        cls.agent = _user('form_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        # Não-agente sem staff: não pode registar → não vê os atalhos.
        cls.expert = _user('form_expert', User.Profile.FORENSIC_EXPERT)
        cls.crime = CrimeTipoFactory()
        cls.occ = _occ(cls.agent, 'FORM-1')

    def _auth(self, user):
        auth_cookie(self.client, user)

    # -- Ocorrência: página completa ------------------------------------------

    def test_occurrence_get_pagina_completa(self):
        self._auth(self.agent)
        body = self.client.get('/occurrences/new/').content.decode()
        self.assertIn('<!DOCTYPE', body)
        self.assertIn('action="/occurrences/new/"', body)
        self.assertIn('data-crime-cascade', body)
        # Localização auto-localizada (geo-field) e data/hora pré-preenchida.
        self.assertIn('data-geo-field', body)
        self.assertIn('name="date_time" value="20', body)
        # Já não é modal.
        self.assertNotIn('hx-post="/occurrences/new/"', body)
        self.assertNotIn('data-modal-title="Nova ocorrência"', body)

    def test_occurrence_post_valido_redireciona(self):
        self._auth(self.agent)
        r = self.client.post('/occurrences/new/', {
            'number': 'NUIPC-FORM-OK-1',
            'description': 'Ocorrência criada pela página.',
            'date_time': '2026-06-01T10:00',
            'crime_type': self.crime.id,
        })
        occ = Occurrence.objects.get(number='NUIPC-FORM-OK-1')
        self.assertRedirects(r, f'/occurrences/{occ.pk}/', fetch_redirect_response=False)

    def test_occurrence_post_invalido_400_na_pagina(self):
        self._auth(self.agent)
        r = self.client.post('/occurrences/new/', {
            # falta 'number' (obrigatório) → erro de validação
            'description': 'Sem número.',
            'date_time': '2026-06-01T10:00',
            'crime_type': self.crime.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('<!DOCTYPE', r.content.decode())
        self.assertFalse(Occurrence.objects.filter(description='Sem número.').exists())

    # -- Item de prova: página completa ---------------------------------------

    def test_evidence_get_renders_type_fields(self):
        self._auth(self.agent)
        page = self.client.get('/evidences/new/').content.decode()
        self.assertIn('<!DOCTYPE', page)
        self.assertIn('action="/evidences/new/"', page)
        # Campos por-tipo (id-section), p.ex. o IMEI de MOBILE_DEVICE.
        self.assertIn('id="f-tsd-MOBILE_DEVICE-imei"', page)
        self.assertIn('data-id-type="MOBILE_DEVICE"', page)
        self.assertIn('data-geo-field', page)
        self.assertNotIn('hx-post="/evidences/new/"', page)

    def test_evidence_post_valido_cria_e_redireciona(self):
        self._auth(self.agent)
        r = self.client.post('/evidences/new/', {
            'occurrence': self.occ.id,
            'type': Evidence.EvidenceType.MOBILE_DEVICE,
            'description': 'Telemóvel registado pela página.',
        })
        ev = Evidence.objects.filter(occurrence=self.occ).latest('id')
        self.assertRedirects(r, f'/evidences/{ev.pk}/', fetch_redirect_response=False)
        # Registo = apreensão: a génese nasce na mesma transação.
        self.assertEqual(ev.custody_chain.count(), 1)

    def test_evidence_post_invalido_400(self):
        self._auth(self.agent)
        r = self.client.post('/evidences/new/', {
            'occurrence': self.occ.id,
            # falta 'type' (obrigatório)
            'description': 'Sem tipo.',
        })
        self.assertEqual(r.status_code, 400)

    # -- Sidebar: atalhos "Nova X" como links de navegação --------------------

    def test_sidebar_mostra_atalhos_para_agente(self):
        self._auth(self.agent)
        body = self.client.get('/dashboard/').content.decode()
        self.assertIn('app-sidebar__link--action', body)
        self.assertIn('href="/occurrences/new/"', body)
        self.assertIn('href="/evidences/new/"', body)
        self.assertIn('Nova ocorrência', body)
        self.assertIn('Novo item', body)
        # Navegação, não modal.
        self.assertNotIn('hx-get="/occurrences/new/?modal=1"', body)
        self.assertNotIn('data-modal-title="Nova ocorrência"', body)

    def test_sidebar_esconde_atalhos_para_nao_agente(self):
        self._auth(self.expert)
        body = self.client.get('/dashboard/').content.decode()
        self.assertNotIn('app-sidebar__link--action', body)
        self.assertNotIn('href="/occurrences/new/"', body)
        self.assertNotIn('href="/evidences/new/"', body)
