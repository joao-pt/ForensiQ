"""
ForensiQ — Testes das views do frontend.

Testa:
- Acesso às páginas de login e dashboard (status 200, template correcto).
- Conteúdo básico das páginas (elementos HTML esperados).
- Redirecionamento correcto para /login/ quando sem JWT cookie.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


class AuthenticatedFrontendTestCase(TestCase):
    """
    Classe base para testes de páginas que requerem autenticação JWT (cookie).

    Cria um utilizador de teste e injeta um token JWT válido como cookie
    'forensiq_access' antes de cada pedido.
    """

    @classmethod
    def setUpTestData(cls):
        cls.test_user = User.objects.create_user(
            username='test_agent',
            password='testpass123',
            profile='AGENT',
        )

    def setUp(self):
        token = AccessToken.for_user(self.test_user)
        self.client.cookies['forensiq_access'] = str(token)


class LoginPageTest(TestCase):
    """Testes para a página de login."""

    def test_login_page_returns_200(self):
        """A página de login deve retornar HTTP 200."""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

    def test_login_page_uses_correct_template(self):
        """A página de login deve usar o template login.html."""
        response = self.client.get(reverse('login'))
        self.assertTemplateUsed(response, 'login.html')

    def test_login_page_contains_form(self):
        """A página de login deve conter o formulário de login."""
        response = self.client.get(reverse('login'))
        content = response.content.decode('utf-8')
        self.assertIn('id="login-form"', content)
        self.assertIn('id="username"', content)
        self.assertIn('id="password"', content)

    def test_login_page_contains_branding(self):
        """A página de login deve conter o nome da aplicação."""
        response = self.client.get(reverse('login'))
        content = response.content.decode('utf-8')
        self.assertIn('ForensiQ', content)

    def test_home_redirects_to_login(self):
        """A raiz (/) deve servir a página de login."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')


class DashboardPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página do dashboard (requer JWT cookie)."""

    def test_dashboard_page_returns_200(self):
        """A página do dashboard deve retornar HTTP 200."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_page_uses_correct_template(self):
        """A página do dashboard deve usar o template dashboard.html."""
        response = self.client.get(reverse('dashboard'))
        self.assertTemplateUsed(response, 'dashboard.html')

    def test_dashboard_contains_stats(self):
        """A página do dashboard deve conter a grelha de estatísticas."""
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('id="stats-grid"', content)

    def test_dashboard_contains_agent_actions(self):
        """A página do dashboard deve conter as acções do agente."""
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('id="agent-actions"', content)

    def test_dashboard_contains_expert_actions(self):
        """A página do dashboard deve conter as acções do perito."""
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('id="expert-actions"', content)

    def test_dashboard_loads_auth_js(self):
        """A página do dashboard deve carregar o módulo auth.js."""
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('auth.js', content)

    def test_dashboard_loads_api_js(self):
        """A página do dashboard deve carregar o módulo api.js."""
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('api.js', content)


class OccurrencesPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de listagem de ocorrências (requer JWT cookie)."""

    def test_occurrences_page_returns_200(self):
        """A página de ocorrências deve retornar HTTP 200."""
        response = self.client.get(reverse('occurrences'))
        self.assertEqual(response.status_code, 200)

    def test_occurrences_page_uses_correct_template(self):
        """A página de ocorrências deve usar o template occurrences.html."""
        response = self.client.get(reverse('occurrences'))
        self.assertTemplateUsed(response, 'occurrences.html')

    def test_occurrences_page_contains_search(self):
        """A página de ocorrências deve conter a barra de pesquisa."""
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="search-input"', content)

    def test_occurrences_page_contains_new_button(self):
        """A página de ocorrências deve conter o botão de nova ocorrência."""
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="btn-new-occurrence"', content)

    def test_occurrences_page_contains_list_container(self):
        """A página de ocorrências deve conter o contentor da lista."""
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="occurrences-list"', content)


class OccurrencesNewPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de criação de ocorrência (requer JWT cookie)."""

    def test_occurrences_new_page_returns_200(self):
        """A página de nova ocorrência deve retornar HTTP 200."""
        response = self.client.get(reverse('occurrences_new'))
        self.assertEqual(response.status_code, 200)

    def test_occurrences_new_page_uses_correct_template(self):
        """A página de nova ocorrência deve usar o template occurrences_new.html."""
        response = self.client.get(reverse('occurrences_new'))
        self.assertTemplateUsed(response, 'occurrences_new.html')

    def test_occurrences_new_page_contains_form(self):
        """A página de nova ocorrência deve conter o formulário."""
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="occurrence-form"', content)

    def test_occurrences_new_page_contains_gps_button(self):
        """A página de nova ocorrência deve conter o botão GPS."""
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="btn-gps"', content)

    def test_occurrences_new_page_contains_number_field(self):
        """A página de nova ocorrência deve conter o campo de número."""
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="number"', content)

    def test_occurrences_new_page_contains_description_field(self):
        """A página de nova ocorrência deve conter o campo de descrição."""
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="description"', content)


class EvidencesPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de listagem de evidências (requer JWT cookie)."""

    def test_evidences_page_returns_200(self):
        """A página de evidências deve retornar HTTP 200."""
        response = self.client.get(reverse('evidences'))
        self.assertEqual(response.status_code, 200)

    def test_evidences_page_uses_correct_template(self):
        """A página de evidências deve usar o template evidences.html."""
        response = self.client.get(reverse('evidences'))
        self.assertTemplateUsed(response, 'evidences.html')

    def test_evidences_page_contains_search(self):
        """A página de evidências deve conter a barra de pesquisa."""
        response = self.client.get(reverse('evidences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="search-input"', content)

    def test_evidences_page_contains_new_button(self):
        """A página de evidências deve conter o botão de nova evidência."""
        response = self.client.get(reverse('evidences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="btn-new-evidence"', content)

    def test_evidences_page_contains_list_container(self):
        """A página de evidências deve conter o contentor da lista."""
        response = self.client.get(reverse('evidences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="evidences-list"', content)


class EvidencesNewPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de criação de evidência (requer JWT cookie)."""

    def test_evidences_new_page_returns_200(self):
        """A página de nova evidência deve retornar HTTP 200."""
        response = self.client.get(reverse('evidences_new'))
        self.assertEqual(response.status_code, 200)

    def test_evidences_new_page_uses_correct_template(self):
        """A página de nova evidência deve usar o template evidences_new.html."""
        response = self.client.get(reverse('evidences_new'))
        self.assertTemplateUsed(response, 'evidences_new.html')

    def test_evidences_new_page_contains_form(self):
        """A página de nova evidência deve conter o formulário."""
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="evidence-form"', content)

    def test_evidences_new_page_contains_type_selector(self):
        """A página de nova evidência deve conter o selector de tipo."""
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="type-selector"', content)

    def test_evidences_new_page_contains_gps_button(self):
        """A página de nova evidência deve conter o botão GPS."""
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="btn-gps"', content)

    def test_evidences_new_page_contains_photo_capture(self):
        """A página de nova evidência deve conter a captura de foto."""
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="photo-capture"', content)

    def test_evidences_new_page_contains_integrity_info(self):
        """A página de nova evidência deve mencionar integridade SHA-256."""
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('SHA-256', content)
