"""
ForensiQ — Testes das views do frontend.

Testa:
- Acesso às páginas de login e dashboard (status 200, template correcto).
- Conteúdo básico das páginas (elementos HTML esperados).
"""

from django.test import TestCase
from django.urls import reverse


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


class DashboardPageTest(TestCase):
    """Testes para a página do dashboard."""

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
