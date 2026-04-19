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
    `fq_access` (ADR-0009) antes de cada pedido.
    """

    @classmethod
    def setUpTestData(cls):
        cls.test_user = User.objects.create_user(
            username='test_agent',
            password='testpass123',
            profile='AGENT',
        )

    def setUp(self):
        # Importar aqui para evitar dependência circular em classe base.
        from core.auth import ACCESS_COOKIE_NAME
        token = AccessToken.for_user(self.test_user)
        self.client.cookies[ACCESS_COOKIE_NAME] = str(token)


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

    def test_occurrences_page_contains_map_tab(self):
        """A página de ocorrências deve conter a aba de mapa."""
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="tab-map"', content)

    def test_occurrences_page_contains_map_container(self):
        """A página de ocorrências deve conter o contentor do mapa Leaflet."""
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="map-container"', content)

    def test_occurrences_page_loads_leaflet(self):
        """A página de ocorrências deve carregar o Leaflet.js."""
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('leaflet', content.lower())


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
        """A página de nova evidência deve conter o selector de tipo.

        O wizard Wave 2b usa um <select id="type"> com optgroups preenchidos
        dinamicamente a partir de CONFIG.EVIDENCE_TYPE_GROUPS; o antigo
        id="type-selector" foi descontinuado.
        """
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="type"', content)
        self.assertIn('name="type"', content)

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


class OccurrenceDetailPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de detalhe da ocorrência (requer JWT cookie)."""

    def test_occurrence_detail_returns_200(self):
        """A página de detalhe da ocorrência deve retornar HTTP 200."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        self.assertEqual(response.status_code, 200)

    def test_occurrence_detail_uses_correct_template(self):
        """A página de detalhe deve usar o template occurrence_detail.html."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        self.assertTemplateUsed(response, 'occurrence_detail.html')

    def test_occurrence_detail_contains_case_header(self):
        """A página de detalhe deve conter o cabeçalho do caso."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="case-header"', content)

    def test_occurrence_detail_contains_evidence_container(self):
        """A página de detalhe deve conter o contentor de evidências."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="evidence-container"', content)

    def test_occurrence_detail_contains_map(self):
        """A página de detalhe deve conter o elemento do mapa."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="case-map"', content)

    def test_occurrence_detail_contains_devices_section(self):
        """A página de detalhe deve conter a secção de dispositivos."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="devices-section"', content)

    def test_occurrence_detail_contains_custody_summary(self):
        """A página de detalhe deve conter o resumo de custódia."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="custody-summary"', content)

    def test_occurrence_detail_loads_leaflet(self):
        """A página de detalhe deve carregar o Leaflet.js."""
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('leaflet', content.lower())

    def test_occurrence_detail_redirects_without_auth(self):
        """A página de detalhe deve redirecionar para login sem JWT cookie."""
        self.client.cookies.clear()
        response = self.client.get(reverse('occurrence_detail', kwargs={'occurrence_id': 1}))
        self.assertRedirects(response, '/login/', fetch_redirect_response=False)


class CustodyTimelinePageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de timeline da cadeia de custódia (requer JWT cookie)."""

    def test_custody_timeline_page_returns_200(self):
        """A página de timeline deve retornar HTTP 200."""
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        self.assertEqual(response.status_code, 200)

    def test_custody_timeline_page_uses_correct_template(self):
        """A página de timeline deve usar o template custody_timeline.html."""
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        self.assertTemplateUsed(response, 'custody_timeline.html')

    def test_custody_timeline_page_contains_progress_bar(self):
        """A página de timeline deve conter a barra de progresso de estados."""
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="state-progress"', content)

    def test_custody_timeline_page_contains_timeline_container(self):
        """A página de timeline deve conter o contentor da timeline."""
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="timeline-container"', content)

    def test_custody_timeline_page_contains_transition_modal(self):
        """A página de timeline deve conter o modal de transição."""
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="transition-modal"', content)

    def test_custody_timeline_page_contains_evidence_header(self):
        """A página de timeline deve conter o cabeçalho da evidência."""
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        content = response.content.decode('utf-8')
        self.assertIn('id="evidence-header"', content)

    def test_custody_timeline_page_redirects_without_auth(self):
        """A página de timeline deve redirecionar para login sem JWT cookie."""
        self.client.cookies.clear()
        response = self.client.get(reverse('custody_timeline', kwargs={'evidence_id': 1}))
        self.assertRedirects(response, '/login/', fetch_redirect_response=False)
