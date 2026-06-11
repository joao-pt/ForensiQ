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

from core.tests_factories import (
    ChainOfCustodyFactory,
    EvidenceMobileFactory,
    OccurrenceFactory,
)

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
            profile='FIRST_RESPONDER',
        )

    def setUp(self):
        # Cookie JWT na fonte única (auditoria D105).
        from core.tests_base import auth_cookie

        auth_cookie(self.client, self.test_user)


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
        """A página do dashboard deve conter a grelha operacional + território.

        Rearranjo v3 (2026-06): operação à esquerda (banda de prazos
        ``attn-strip``, últimas ocorrências, grelha de tiles ``custody-grid``
        com o estado legal derivado do ledger) e o território à direita
        (mapa alto ``geo-hero__map`` + insets Madeira/Açores). É marcação
        semântica por classe — sem ``id`` antigos de hidratação por JS.
        """
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('class="dash-grid"', content)
        self.assertIn('custody-grid', content)
        self.assertIn('attn-strip', content)
        self.assertIn('cs-tile', content)
        self.assertIn('aria-label="Mapa de Portugal continental"', content)

    def test_dashboard_body_has_no_new_occurrence_cta(self):
        """O CORPO do painel não tem CTA de entrada de dados (Lote 3, 2026-06).

        O painel fica focado na situação (mapa + estado da cadeia + atividade),
        sem ações de entrada de dados no corpo. A entrada rápida de nova
        ocorrência passou a viver como atalho GLOBAL na sidebar (Fase 7,
        ação-in-place) — presente em todas as páginas, fora do <main>, e coberto
        por ``core.tests_new_forms``. Aqui garante-se só que a região principal
        continua sem o antigo botão e sem ligação para o registo.
        """
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        # A sidebar (atalho global) vive num <aside>, fora do <main>: isola-se a
        # região principal para verificar que o corpo do painel não traz CTA.
        main_region = content.split('id="main-content"', 1)[1].split('</main>', 1)[0]
        self.assertNotIn('btn-new-occ', content)
        self.assertNotIn('/occurrences/new/', main_region)

    def test_dashboard_loads_auth_js(self):
        """A página do dashboard deve carregar o módulo auth.js."""
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode('utf-8')
        self.assertIn('auth.js', content)


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
        """A página de ocorrências deve conter os filtros por coluna.

        Os filtros vivem no cabeçalho da grelha (cada ``<th>`` é coluna + filtro,
        ``grid__filter-cell``), dentro de um formulário ``role="search"`` (HTMX,
        debounce). A pesquisa global ``name="q"`` deu lugar a campos por coluna
        (ex.: ``name="q_number"`` para o NUIPC).
        """
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('role="search"', content)
        self.assertIn('grid__filter-cell', content)
        self.assertIn('name="q_number"', content)

    def test_occurrences_page_contains_new_button(self):
        """A página de ocorrências deve conter o botão de nova ocorrência.

        Fase 3: é uma âncora ``btn-accent`` para /occurrences/new/ (substitui
        o antigo ``id="btn-new-occurrence"``).
        """
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('href="/occurrences/new/"', content)
        self.assertIn('Nova ocorrência', content)

    def test_occurrences_page_contains_list_container(self):
        """A página de ocorrências deve conter o contentor da lista.

        Fase 3: o alvo HTMX da grelha é ``id="occ-grid"`` (antes
        ``id="occurrences-list"``).
        """
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="occ-grid"', content)

    def test_occurrences_page_contains_grid_rows(self):
        """A grelha de ocorrências deve usar linhas clicáveis que NAVEGAM.

        A lista é server-rendered numa ``table.grid--clickable`` com linhas
        ``data-row`` que navegam para a página de detalhe (``data-href``); a
        célula do código é um link real (novo separador com Ctrl/middle-click).
        O antigo painel lateral (drawer) foi removido.
        """
        occ = OccurrenceFactory(agent=self.test_user)
        response = self.client.get(reverse('occurrences'))
        content = response.content.decode('utf-8')
        self.assertIn('grid--clickable', content)
        self.assertIn('data-row', content)
        self.assertIn(f'data-href="/occurrences/{occ.id}/"', content)
        self.assertIn(f'href="/occurrences/{occ.id}/"', content)
        self.assertNotIn('?drawer=', content)


class OccurrencesFilterTest(AuthenticatedFrontendTestCase):
    """Filtros da lista de ocorrências (Lote 2): categoria de crime N1 e datas.

    Tranca a parte não-trivial: o join N3→N2→N1
    (``crime_type__subcategoria__categoria_id``) e a filtragem por intervalo de
    datas sobre ``date_time``. Os restantes filtros (prioridade) já existiam.
    """

    def test_filter_by_crime_category(self):
        """``?cat=<id>`` mostra só as ocorrências dessa categoria N1."""
        from core.tests_factories import (
            CrimeCategoriaFactory,
            CrimeSubcategoriaFactory,
            CrimeTipoFactory,
        )

        occ1 = OccurrenceFactory(agent=self.test_user)
        cat1 = occ1.crime_type.subcategoria.categoria
        tipo2 = CrimeTipoFactory(
            codigo=2,
            subcategoria=CrimeSubcategoriaFactory(
                codigo=2,
                categoria=CrimeCategoriaFactory(codigo=2, nome='Outra categoria'),
            ),
        )
        occ2 = OccurrenceFactory(agent=self.test_user, crime_type=tipo2)

        response = self.client.get(f'/occurrences/?cat={cat1.id}')
        content = response.content.decode('utf-8')
        self.assertIn(occ1.number, content)
        self.assertNotIn(occ2.number, content)

    def test_filter_by_date_range(self):
        """``?date_after=<hoje>`` exclui ocorrências anteriores ao intervalo."""
        from datetime import timedelta

        from django.utils import timezone

        recent = OccurrenceFactory(agent=self.test_user)
        old = OccurrenceFactory(
            agent=self.test_user,
            date_time=timezone.now() - timedelta(days=40),
        )

        today = timezone.now().date().isoformat()
        response = self.client.get(f'/occurrences/?date_after={today}')
        content = response.content.decode('utf-8')
        self.assertIn(recent.number, content)
        self.assertNotIn(old.number, content)


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
        """A página de nova ocorrência deve conter o formulário.

        Fase 3: o formulário é server-rendered, faz POST para
        /occurrences/new/ e tem a cascata de crime (``data-crime-cascade``);
        o antigo ``id="occurrence-form"`` foi descontinuado.
        """
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('action="/occurrences/new/"', content)
        self.assertIn('data-crime-cascade', content)

    def test_occurrences_new_page_contains_geo_field(self):
        """A página de nova ocorrência deve conter o campo de localização.

        A captura de coordenadas é agora o geo-field auto-localizado
        (``data-geo-field`` + mapa, geo-field.js); substitui o antigo botão
        ``data-geo-capture``.
        """
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('data-geo-field', content)

    def test_occurrences_new_page_contains_number_field(self):
        """A página de nova ocorrência deve conter o campo de número/NUIPC.

        Fase 3: ``id="f-number"`` / ``name="number"`` (antes ``id="number"``).
        """
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="f-number"', content)
        self.assertIn('name="number"', content)

    def test_occurrences_new_page_contains_description_field(self):
        """A página de nova ocorrência deve conter o campo de descrição.

        Fase 3: ``id="f-desc"`` / ``name="description"`` (antes
        ``id="description"``).
        """
        response = self.client.get(reverse('occurrences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="f-desc"', content)
        self.assertIn('name="description"', content)


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
        """A página de evidências deve conter a barra de pesquisa.

        Fase 3: formulário ``role="search"`` com input ``name="q"`` (HTMX);
        o antigo ``id="search-input"`` deixou de existir.
        """
        response = self.client.get(reverse('evidences'))
        content = response.content.decode('utf-8')
        self.assertIn('role="search"', content)
        self.assertIn('name="q"', content)

    def test_evidences_page_contains_new_button(self):
        """A página de evidências deve conter o botão de novo item de prova.

        Fase 3: âncora ``btn-accent`` para /evidences/new/, visível a agentes
        e staff (o ``test_user`` é FIRST_RESPONDER). Substitui o antigo
        ``id="btn-new-evidence"``.
        """
        response = self.client.get(reverse('evidences'))
        content = response.content.decode('utf-8')
        self.assertIn('href="/evidences/new/"', content)
        self.assertIn('Novo item de prova', content)

    def test_evidences_page_contains_list_container(self):
        """A página de evidências deve conter o contentor da lista.

        Fase 3: o alvo HTMX da grelha é ``id="evd-grid"`` (antes
        ``id="evidences-list"``).
        """
        response = self.client.get(reverse('evidences'))
        content = response.content.decode('utf-8')
        self.assertIn('id="evd-grid"', content)


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
        """A página de nova evidência deve conter o formulário.

        Fase 3: o formulário é server-rendered, faz POST multipart para
        /evidences/new/ (suporta fotografia); o antigo ``id="evidence-form"``
        foi descontinuado.
        """
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('action="/evidences/new/"', content)
        self.assertIn('enctype="multipart/form-data"', content)

    def test_evidences_new_page_contains_type_selector(self):
        """A página de nova evidência deve conter o selector de tipo.

        Fase 3: o ``<select name="type">`` (id ``f-type``) é preenchido
        server-side a partir de ``Evidence.EvidenceType.choices``; os antigos
        ``id="type-selector"`` (v1) e ``id="type"`` (wizard Wave 2b) foram
        descontinuados.
        """
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('id="f-type"', content)
        self.assertIn('name="type"', content)

    def test_evidences_new_page_contains_geo_field(self):
        """A página de nova evidência deve conter o campo de localização.

        Captura de coordenadas pelo geo-field auto-localizado
        (``data-geo-field`` + mapa, geo-field.js); substitui ``data-geo-capture``.
        """
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('data-geo-field', content)

    def test_evidences_new_page_contains_photo_capture(self):
        """A página de nova evidência deve conter o campo de fotografia.

        Fase 3: ``<input type="file" name="photo" accept="image/*">``
        (id ``f-photo``); substitui o antigo ``id="photo-capture"``.
        """
        response = self.client.get(reverse('evidences_new'))
        content = response.content.decode('utf-8')
        self.assertIn('name="photo"', content)
        self.assertIn('accept="image/*"', content)


class OccurrenceDetailPageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de detalhe da ocorrência (requer JWT cookie).

    Fase 3: a view é server-rendered e lê o ORM com o ownership do
    utilizador. Como o ``test_user`` é FIRST_RESPONDER, só vê as ocorrências
    de que é agente — por isso o fixture é criado com ``agent=test_user`` e os
    testes navegam para o ``id`` real (não um ``1`` fixo, que daria 404).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.occurrence = OccurrenceFactory(agent=cls.test_user)
        # Um item de prova dá conteúdo à tabela de evidências do detalhe.
        cls.evidence = EvidenceMobileFactory(
            occurrence=cls.occurrence, agent=cls.test_user
        )

    def _url(self):
        return reverse('occurrence_detail', kwargs={'occurrence_id': self.occurrence.id})

    def test_occurrence_detail_returns_200(self):
        """A página de detalhe da ocorrência deve retornar HTTP 200."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

    def test_occurrence_detail_uses_correct_template(self):
        """A página de detalhe deve usar o template occurrence_detail.html."""
        response = self.client.get(self._url())
        self.assertTemplateUsed(response, 'occurrence_detail.html')

    def test_occurrence_detail_contains_case_header(self):
        """A página de detalhe deve conter o cabeçalho do caso.

        Fase 3: ``<header class="detail__head">`` com o título ``id="occ-title"``
        (código OC-2026-… e badge de prioridade); substitui ``id="case-header"``.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('detail__head', content)
        self.assertIn('id="occ-title"', content)
        self.assertIn(self.occurrence.code, content)

    def test_occurrence_detail_contains_evidence_container(self):
        """A página de detalhe deve conter a tabela de itens de prova.

        Fase 3: secção "Itens de prova" com uma ``table.grid`` de linhas
        ``data-row`` que navegam para a página do item (``data-href``);
        substitui ``id="evidence-container"``.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('Itens de prova', content)
        self.assertIn(f'data-href="/evidences/{self.evidence.id}/"', content)
        self.assertIn(self.evidence.code, content)

    def test_occurrence_detail_contains_map(self):
        """A página de detalhe deve conter o elemento do mapa.

        Fase 3: ``<div class="map-box" data-static-map …>`` com lat/lng da
        ocorrência (hidratado por Leaflet); substitui ``id="case-map"``.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('map-box', content)
        self.assertIn('data-static-map', content)

    def test_occurrence_detail_contains_pdf_action(self):
        """A página de detalhe deve oferecer a guia de transporte (PDF).

        Fase 3: o detalhe deixou de ter um bloco ``custody-summary`` dedicado
        (o estado de custódia é mostrado por item, na própria tabela).
        A acção transversal do caso é a guia PDF, ligada ao endpoint
        de exportação — é esse o substituto que se assere aqui.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn(f'/api/occurrences/{self.occurrence.id}/pdf/', content)
        self.assertIn('Guia PDF', content)

    def test_occurrence_detail_loads_leaflet(self):
        """A página de detalhe deve carregar o Leaflet.js."""
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('leaflet', content.lower())

    def test_occurrence_detail_redirects_without_auth(self):
        """A página de detalhe deve redirecionar para login sem JWT cookie."""
        self.client.cookies.clear()
        response = self.client.get(self._url())
        self.assertRedirects(response, '/login/', fetch_redirect_response=False)


class CustodyTimelinePageTest(AuthenticatedFrontendTestCase):
    """Testes para a página de timeline da cadeia de custódia (requer JWT cookie).

    Fase 3: a página é server-rendered (WI-A). Mostra o trajeto + o ledger de
    eventos + um formulário inline de registo (só com os eventos que as guardas
    do ledger aceitariam). O ``test_user`` é FIRST_RESPONDER e dono da
    ocorrência, logo vê a evidência; o fixture inclui o evento de génese para
    o ledger não vir vazio (e o formulário de registo ficar aberto).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.occurrence = OccurrenceFactory(agent=cls.test_user)
        cls.evidence = EvidenceMobileFactory(
            occurrence=cls.occurrence, agent=cls.test_user
        )
        # Evento de génese (APREENSAO_OBJETO/OPC) — dá conteúdo ao ledger.
        ChainOfCustodyFactory(evidence=cls.evidence, agent=cls.test_user)

    def _url(self):
        return reverse('custody_timeline', kwargs={'evidence_id': self.evidence.id})

    def test_custody_timeline_page_returns_200(self):
        """A página de timeline deve retornar HTTP 200."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

    def test_custody_timeline_page_uses_correct_template(self):
        """A página de timeline deve usar o template custody_timeline.html."""
        response = self.client.get(self._url())
        self.assertTemplateUsed(response, 'custody_timeline.html')

    def test_custody_timeline_page_contains_register_form(self):
        """A página de timeline deve conter o formulário de registo de evento.

        Fase 3: removida a "barra de progresso de estados" (``state-progress``,
        que pintava uma FSM fixa). O estado legal é derivado do ledger e
        mostrado no subtítulo (badge ``state``); o que importa funcionalmente é
        o formulário inline de registo de novo evento — secção
        ``id="custody-register"`` com POST para /evidences/<id>/custody/.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('id="custody-register"', content)
        self.assertIn(f'action="/evidences/{self.evidence.id}/custody/"', content)
        self.assertIn('name="event_type"', content)

    def test_custody_timeline_page_contains_timeline_container(self):
        """A página de timeline deve conter o contentor da timeline.

        Fase 3: o ledger é uma ``<ol class="timeline">`` server-rendered, com
        cada evento em ``li.timeline__item``; substitui ``id="timeline-container"``.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('class="timeline"', content)
        self.assertIn('timeline__item', content)

    def test_custody_timeline_page_renders_record_hash(self):
        """A página deve mostrar o hash encadeado de cada registo do ledger.

        Fase 3: o registo de eventos é server-rendered (Django + HTMX), sem o
        JS antigo (``transition_modal.js`` / ``custody_states.js`` /
        ``CONFIG.CUSTODY_STATES``) nem o botão modal ``btn-new-transition``. A
        abertura do formulário é o ``<summary>`` do ``details#custody-register``.
        O que garante a integridade visível é o hash encadeado por evento,
        com o rótulo "Hash do registo".
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('Hash do registo', content)
        self.assertIn('Registar novo evento', content)

    def test_custody_timeline_page_contains_evidence_header(self):
        """A página de timeline deve conter o cabeçalho da evidência.

        Fase 3: ``<header class="detail__head">`` com o título ``id="ct-title"``
        e o subtítulo (código + tipo + estado); substitui ``id="evidence-header"``.
        """
        response = self.client.get(self._url())
        content = response.content.decode('utf-8')
        self.assertIn('detail__head', content)
        self.assertIn('id="ct-title"', content)
        self.assertIn(self.evidence.code, content)

    def test_custody_timeline_page_redirects_without_auth(self):
        """A página de timeline deve redirecionar para login sem JWT cookie."""
        self.client.cookies.clear()
        response = self.client.get(self._url())
        self.assertRedirects(response, '/login/', fetch_redirect_response=False)
