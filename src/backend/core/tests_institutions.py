"""ForensiQ — Testes das views de Instituições (lista + criação ação-in-place).

A criação de instituições (pontos de controlo) é ato de administração: staff ou
credencial NACIONAL. A mesma view serve duas superfícies — página completa
(fallback) e fragmento modal (``?modal=1``). Em sucesso no modal devolve 204 +
``HX-Redirect``; em erro reapresenta o fragmento com os erros.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import Institution, InstitutionType
from core.tests_base import auth_cookie
from core.tests_factories import make_user as _user

User = get_user_model()


class InstitutionViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nacional = _user(
            'inst_nacional', User.Profile.FIRST_RESPONDER, clearance=User.Clearance.NACIONAL
        )
        cls.staff = _user('inst_staff', User.Profile.FIRST_RESPONDER)
        cls.staff.is_staff = True
        cls.staff.save(update_fields=['is_staff'])
        cls.normal = _user('inst_normal', User.Profile.FIRST_RESPONDER)
        Institution.objects.create(name='PSP Lisboa', type=InstitutionType.OPC, sigla='PSP-LX')

    def _auth(self, user):
        auth_cookie(self.client, user)

    def _get(self, user, url):
        self._auth(user)
        return self.client.get(url)

    def _post(self, user, url, data):
        self._auth(user)
        return self.client.post(url, data)

    # -- Acesso (staff / NACIONAL gerem; need-to-know normal não) --------

    def test_lista_visivel_a_nacional(self):
        r = self._get(self.nacional, '/institutions/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'PSP Lisboa')

    def test_lista_visivel_a_staff(self):
        self.assertEqual(self._get(self.staff, '/institutions/').status_code, 200)

    def test_lista_negada_a_normal(self):
        self.assertEqual(self._get(self.normal, '/institutions/').status_code, 403)

    def test_negada_a_so_leitura_mesmo_nacional(self):
        # «Só-leitura é só-leitura» (parecer UX 2026-06-12): chefe/auditor leem a
        # consola, mas gerir instituições é escrita — 403 nas duas superfícies.
        for profile in (User.Profile.CHEFE_SERVICO, User.Profile.AUDITOR):
            user = _user(f'inst_ro_{profile}'.lower(), profile,
                         clearance=User.Clearance.NACIONAL)
            self.assertEqual(self._get(user, '/institutions/').status_code, 403)
            self.assertEqual(self._get(user, '/institutions/new/').status_code, 403)

    def test_403_devolve_pagina_com_casca(self):
        # O handler403 rende a casca da app (handler registado + raise
        # PermissionDenied nas views) — nunca texto cru.
        r = self._get(self.normal, '/institutions/')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, '<html', status_code=403)
        self.assertContains(r, 'Sem permissão', status_code=403)

    def test_criar_negada_a_normal(self):
        r = self._post(self.normal, '/institutions/new/', {
            'name': 'Intrusa', 'type': 'OPC', 'address': 'Rua A',
            'gps_lat': '38.7', 'gps_lng': '-9.1',
        })
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Institution.objects.filter(name='Intrusa').exists())

    # -- GET formulário (fragmento modal vs página completa) -------------

    def test_get_modal_devolve_fragmento(self):
        body = self._get(self.nacional, '/institutions/new/?modal=1').content.decode()
        self.assertIn('data-map-picker', body)
        self.assertIn('name="modal"', body)   # campo escondido p/ o POST saber que é modal
        self.assertNotIn('<html', body)        # fragmento, sem a casca da app

    def test_get_pagina_completa(self):
        body = self._get(self.nacional, '/institutions/new/').content.decode()
        self.assertIn('<html', body)           # página completa (fallback no-JS)
        self.assertIn('data-map-picker', body)

    # -- POST sucesso ----------------------------------------------------

    def test_post_modal_sucesso_204_hx_redirect(self):
        r = self._post(self.nacional, '/institutions/new/', {
            'modal': '1', 'name': 'Lab Central', 'type': 'LAB_PUBLICO', 'sigla': 'LPC',
            'address': 'Rua X, Lisboa', 'gps_lat': '38.7197003', 'gps_lng': '-9.1466657',
        })
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], '/institutions/')
        self.assertTrue(Institution.objects.filter(name='Lab Central').exists())

    def test_post_pagina_sucesso_redirect(self):
        r = self._post(self.nacional, '/institutions/new/', {
            'name': 'Tribunal X', 'type': 'TRIBUNAL', 'address': 'Praça Y',
            'gps_lat': '41.1', 'gps_lng': '-8.6',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/institutions/')
        self.assertTrue(Institution.objects.filter(name='Tribunal X').exists())

    # -- POST erro de validação ------------------------------------------

    def test_post_modal_sem_gps_reapresenta_com_erro(self):
        r = self._post(self.nacional, '/institutions/new/', {
            'modal': '1', 'name': 'Sem GPS', 'type': 'OPC', 'address': 'Rua Z',
        })
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('form-error', body)        # erro de campo renderizado
        self.assertIn('data-map-picker', body)   # devolve o fragmento do formulário
        self.assertNotIn('<html', body)          # continua a ser fragmento (modal)
        self.assertFalse(Institution.objects.filter(name='Sem GPS').exists())


class InstitutionEditTest(TestCase):
    """Edição de instituição (parecer item 19) — espelho do modal de criação:
    mesmo gate, mesmo partial parametrizado, update() do serializer; POST
    parcial (semeadas sem GPS continuam editáveis); toggle is_active com
    guard-rail informativo; trilho UPDATE com antes/depois."""

    @classmethod
    def setUpTestData(cls):
        cls.nacional = _user(
            'edit_nacional', User.Profile.FIRST_RESPONDER,
            clearance=User.Clearance.NACIONAL
        )
        cls.normal = _user('edit_normal', User.Profile.FIRST_RESPONDER)
        cls.inst = Institution.objects.create(
            name='Lab Editavel', type=InstitutionType.LAB_PUBLICO, sigla='LAB-ED'
        )

    def _auth(self, user):
        auth_cookie(self.client, user)

    def test_editar_negada_a_normal_e_so_leitura(self):
        self._auth(self.normal)
        url = f'/institutions/{self.inst.id}/edit/'
        self.assertEqual(self.client.get(url).status_code, 403)
        ro = _user('edit_ro', User.Profile.AUDITOR, clearance=User.Clearance.NACIONAL)
        self._auth(ro)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_get_modal_prefill_e_toggle(self):
        self._auth(self.nacional)
        body = self.client.get(
            f'/institutions/{self.inst.id}/edit/?modal=1'
        ).content.decode()
        self.assertIn('Lab Editavel', body)               # valores pré-preenchidos
        self.assertIn('Editar instituição', body)         # título parametrizado
        self.assertIn('name="is_active"', body)           # toggle só na edição
        self.assertNotIn('<html', body)                   # fragmento modal

    def test_post_parcial_edita_sem_gps_e_audita(self):
        from core.models import AuditLog

        # Instituição semeada SEM morada/GPS: a edição da sigla não pode
        # obrigar a inventar coordenadas (POST parcial, vazios removidos).
        self._auth(self.nacional)
        r = self.client.post(f'/institutions/{self.inst.id}/edit/', {
            'modal': '1', 'name': 'Lab Editavel', 'type': 'LAB_PUBLICO',
            'sigla': 'LAB-ED2', 'is_active': '1',
        })
        self.assertEqual(r.status_code, 204)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.sigla, 'LAB-ED2')
        log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE).last()
        self.assertIsNotNone(log)
        self.assertIn('sigla', log.details.get('fields', {}))

    def test_post_inativa_instituicao(self):
        self._auth(self.nacional)
        r = self.client.post(f'/institutions/{self.inst.id}/edit/', {
            'modal': '1', 'name': 'Lab Editavel', 'type': 'LAB_PUBLICO',
        })   # checkbox ausente = inativa
        self.assertEqual(r.status_code, 204)
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.is_active)

    def test_grelha_tem_contactos_e_editar(self):
        self._auth(self.nacional)
        body = self.client.get('/institutions/').content.decode()
        self.assertIn('Telefone', body)
        self.assertIn('Email', body)
        self.assertIn(f'/institutions/{self.inst.id}/edit/', body)
        self.assertIn('data-modal-open', body)

    def test_edicao_nao_forca_morada_gps_obrigatorios(self):
        # O partial é fonte única de criação/edição; na EDIÇÃO morada e GPS não
        # podem sair como `required` (instituições sem georreferência têm de ser
        # editáveis — o POST parcial server-side já cobre isto). Nome continua.
        self._auth(self.nacional)
        body = self.client.get(
            f'/institutions/{self.inst.id}/edit/?modal=1'
        ).content.decode()
        self.assertNotRegex(body, r'name="address"[^>]*required')
        self.assertNotRegex(body, r'name="gps_lat"[^>]*required')
        self.assertNotRegex(body, r'name="gps_lng"[^>]*required')
        self.assertRegex(body, r'name="name"[^>]*required')

    def test_criacao_mantem_morada_gps_obrigatorios(self):
        # Na CRIAÇÃO manual a localização continua obrigatória (GPS-só-no-terreno).
        self._auth(self.nacional)
        body = self.client.get('/institutions/new/?modal=1').content.decode()
        self.assertRegex(body, r'name="address"[^>]*required')
        self.assertRegex(body, r'name="gps_lat"[^>]*required')
