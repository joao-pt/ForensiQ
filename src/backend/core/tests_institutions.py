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
