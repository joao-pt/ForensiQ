"""
Glue entre Django (pytest-django ``live_server``) e Playwright.

Fornece, para todos os testes E2E:

  * **configuração do browser** — base_url do servidor live, locale pt-PT,
    fuso de Lisboa, viewport desktop e **geolocalização fixa** (Marquês de
    Pombal) com permissão concedida, para testar a captura GPS de forma
    determinística sem hardware;
  * **bloqueio de pedidos externos** — tiles de mapa (Leaflet), etc. são
    abortados para os testes correrem offline e sem flakiness; o tráfego para
    o servidor local (``/static/``, ``/media/``, ``/api/``) passa;
  * **autenticação** — ``auth_as(user)`` injeta o cookie JWT (rápido, sem UI em
    cada teste) e ``login_via_ui`` exercita o formulário real de login;
  * **factories** — ``make_user`` e ``seed`` criam dados reais na BD de teste;
  * **diagnóstico** — ``js_errors`` e ``failed_static`` capturam erros de JS e
    404 de estáticos por página.

Notas:
  * todos os fixtures que tocam a BD dependem (direta ou indiretamente) de
    ``live_server``, que ativa o acesso transacional necessário para a thread
    do servidor ver os dados cometidos;
  * a geolocalização e o locale coincidem com os ``tests_factories`` (Lisboa).
"""

import os

# O Playwright sync corre um event-loop num greenlet; o Django, ao ver um loop
# ativo, bloquearia operações ORM síncronas (SynchronousOnlyOperation) na
# criação da BD de teste e nos factories. O loop do Playwright NÃO é concorrente
# com o ORM (greenlet cooperativo), logo desativamos a guarda — fix padrão para
# pytest-playwright + pytest-django. Tem de ser definido antes de qualquer ORM.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from urllib.parse import urlparse  # noqa: E402

import pytest  # noqa: E402

from core.auth import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME  # noqa: E402

# Lisboa — Marquês de Pombal (coincide com OccurrenceFactory / EvidenceFactory).
E2E_GEO = {"latitude": 38.7223340, "longitude": -9.1393366, "accuracy": 12.0}

# Origens externas permitidas no browser de teste: NENHUMA. O IBM Plex passou a
# self-hosted (css/fonts.css), por isso os testes correm totalmente offline.
# Pedidos externos (ex.: tiles de mapa) são abortados — sem flakiness. Se algum
# template ainda referenciar fontes externas, a CSP apertada (font-src 'self')
# dispara uma violação que o test_no_csp_violations apanha.
_ALLOWED_EXTERNAL = ()

# Mensagens de consola a IGNORAR como "erro de JS": resultam do bloqueio
# deliberado de recursos externos (tiles de mapa), não de defeitos da aplicação.
# As violações de CSP são capturadas à parte (fixture `csp_violations`); as
# exceções JS reais (pageerror) são SEMPRE registadas.
_CONSOLE_NOISE = (
    "Failed to load resource",
    "net::ERR_",
    "ERR_FAILED",
    "the server responded with a status",
    "favicon",
)


# --------------------------------------------------------------------------- #
# Configuração do contexto do browser
# --------------------------------------------------------------------------- #
@pytest.fixture
def browser_context_args(browser_context_args, live_server):
    """Aponta o browser ao servidor live e fixa locale/fuso/GPS/viewport."""
    return {
        **browser_context_args,
        "base_url": live_server.url,
        "locale": "pt-PT",
        "timezone_id": "Europe/Lisbon",
        "viewport": {"width": 1440, "height": 900},
        "geolocation": E2E_GEO,
        "permissions": ["geolocation"],
    }


@pytest.fixture(autouse=True)
def _block_external(context, live_server):
    """Aborta pedidos a origens externas (tiles, etc.) — testes offline."""
    host = urlparse(live_server.url).netloc

    def _route(route):
        url = route.request.url
        if (
            host in url
            or url.startswith(("data:", "blob:"))
            or any(h in url for h in _ALLOWED_EXTERNAL)
        ):
            route.continue_()
        else:
            route.abort()

    context.route("**/*", _route)
    yield


@pytest.fixture(autouse=True)
def _seed_evidence_fields(live_server):
    """Garante a config de campos por-tipo (``EvidenceFieldDef``) em cada teste.

    Estes campos VIVEM na BD, semeados por uma migração de DADOS
    (``0027_seed_evidence_fields``). O ``live_server`` corre sob
    ``TransactionTestCase``, que faz flush das tabelas entre testes e NÃO restaura
    dados de migração — pelo que, depois do 1.º teste, ``EvidenceFieldDef`` fica
    vazia e o formulário de evidência perde os identificadores por tipo (ex.: IMEI).
    Isto tornava ``test_type_specific_fields_toggle_by_type`` dependente da ordem
    (passava isolado, falhava no conjunto). Re-semeia se a tabela estiver vazia,
    reutilizando o seed da própria migração (fonte única). Os dados ficam cometidos
    (autocommit), visíveis para a thread do servidor live.
    """
    import importlib

    from django.apps import apps as django_apps

    from core.models import EvidenceFieldDef

    if not EvidenceFieldDef.objects.exists():
        mig = importlib.import_module('core.migrations.0027_seed_evidence_fields')
        mig.seed_fields(django_apps, None)
    yield


# --------------------------------------------------------------------------- #
# Autenticação
# --------------------------------------------------------------------------- #
def _auth_cookies(user, base_url):
    """Cookies JWT (access + refresh) para `user`, prontos a injetar."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    return [
        {"name": ACCESS_COOKIE_NAME, "value": str(refresh.access_token), "url": base_url},
        {"name": REFRESH_COOKIE_NAME, "value": str(refresh), "url": base_url},
    ]


@pytest.fixture
def auth_as(context, live_server):
    """Autentica o context como `user` injetando o cookie JWT (sem passar pela UI)."""

    def _auth(user):
        context.add_cookies(_auth_cookies(user, live_server.url))
        return user

    return _auth


@pytest.fixture
def login_via_ui(page):
    """Faz login pelo formulário REAL (`/login/`). Devolve quando no dashboard."""

    def _login(username, password):
        page.goto("/login/")
        page.fill("#username", username)
        page.fill("#password", password)
        page.click("#btn-login")
        page.wait_for_url("**/dashboard/")

    return _login


# --------------------------------------------------------------------------- #
# Factories / dados de teste
# --------------------------------------------------------------------------- #
@pytest.fixture
def make_user(live_server):
    """Cria utilizadores reais na BD de teste. `kind` ∈ {'agent', 'expert'}."""
    from core.tests_factories import ExpertFactory, UserFactory

    def _make(kind="agent", **kwargs):
        factory = ExpertFactory if kind == "expert" else UserFactory
        return factory.create(**kwargs)

    return _make


@pytest.fixture
def tiny_image(tmp_path):
    """Caminho para um JPEG mínimo válido — para testar o upload de fotografia."""
    from PIL import Image

    path = tmp_path / "evidencia.jpg"
    Image.new("RGB", (8, 8), (90, 110, 140)).save(str(path), "JPEG")
    return str(path)


@pytest.fixture
def seed(live_server):
    """
    Semeia um cenário mínimo coerente: agente + perito (staff), uma ocorrência
    com um telemóvel apreendido e um evento de custódia. Devolve os objetos.
    """
    from core.tests_factories import (
        ChainOfCustodyFactory,
        EvidenceMobileFactory,
        ExpertFactory,
        OccurrenceFactory,
        UserFactory,
    )

    agent = UserFactory.create(username="ag_e2e", password="Aa123456!")
    expert = ExpertFactory.create(
        username="pe_e2e", password="Ee123456!", is_staff=True, is_superuser=True
    )
    occ = OccurrenceFactory.create(agent=agent)
    ev = EvidenceMobileFactory.create(occurrence=occ, agent=agent)
    cc = ChainOfCustodyFactory.create(evidence=ev, agent=agent)
    return {"agent": agent, "expert": expert, "occ": occ, "ev": ev, "cc": cc}


# --------------------------------------------------------------------------- #
# Diagnóstico por página
# --------------------------------------------------------------------------- #
@pytest.fixture
def js_errors(page):
    """
    Exceções JS não apanhadas (pageerror) + erros de consola REAIS.

    Exclui violações de CSP (capturadas em ``csp_violations``) e ruído de rede
    do bloqueio de externos — para isolar crashes/erros de lógica.
    """
    errors = []

    def _on_console(msg):
        if msg.type != "error":
            return
        text = msg.text
        if "Content Security Policy" in text:  # capturado em csp_violations
            return
        if any(n in text for n in _CONSOLE_NOISE):
            return
        errors.append(("console", text))

    page.on("pageerror", lambda exc: errors.append(("pageerror", str(exc))))
    page.on("console", _on_console)
    return errors


@pytest.fixture
def csp_violations(page):
    """Recolhe violações de Content Security Policy reportadas na consola."""
    violations = []

    def _on_console(msg):
        if msg.type == "error" and "Content Security Policy" in msg.text:
            violations.append(msg.text)

    page.on("console", _on_console)
    return violations


@pytest.fixture
def failed_static(page):
    """Recolhe respostas >=400 para recursos /static/ (CSS/JS não servidos)."""
    failed = []

    def _on_response(resp):
        if resp.status >= 400 and "/static/" in resp.url:
            failed.append((resp.status, resp.url))

    page.on("response", _on_response)
    return failed
