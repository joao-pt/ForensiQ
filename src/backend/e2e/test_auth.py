"""
E2E — autenticação e autorização (ADR-0009 cookies JWT, ADR-0017 perfis).

Exercita o que os testes de unidade não conseguem: o comportamento REAL no
browser — redireccionamento de páginas protegidas, erro de credenciais na UI,
e os portões de perfil (agente vs perito) em páginas server-rendered.
"""

import pytest

from core.tests_factories import ExpertFactory, OccurrenceFactory, UserFactory

pytestmark = pytest.mark.e2e


def test_unauthenticated_redirects_to_login(page, live_server):
    """Sem cookie de sessão, uma página protegida redireciona para /login/."""
    page.goto("/dashboard/", wait_until="load")
    assert "/login" in page.url, f"esperava redireccionar para login, ficou em {page.url}"


def test_bad_credentials_shows_error(page, make_user):
    """Credenciais inválidas mostram erro visível e mantêm-se em /login/."""
    make_user("agent", username="agente.err", password="Certa123!")
    page.goto("/login/", wait_until="load")
    page.fill("#username", "agente.err")
    page.fill("#password", "ERRADA")
    page.click("#btn-login")
    page.wait_for_selector("#login-error.visible", timeout=5000)
    assert "/login" in page.url
    assert page.locator("#login-error").inner_text().strip() != ""


def test_agent_blocked_from_intake(page, auth_as, live_server):
    """Um agente (FIRST_RESPONDER) não pode aceder à receção (perito-only) → 403."""
    agent = UserFactory.create(username="ag.intake", password="Aa123456!")
    occ = OccurrenceFactory.create(agent=agent)
    auth_as(agent)
    resp = page.goto(f"/occurrences/{occ.id}/intake/", wait_until="load")
    assert resp is not None and resp.status == 403, (
        f"agente devia receber 403 na receção, recebeu {resp.status if resp else None}"
    )


def test_expert_allowed_in_intake(page, auth_as, live_server):
    """Um perito (FORENSIC_EXPERT) acede à receção (200)."""
    agent = UserFactory.create(username="ag.intake2", password="Aa123456!")
    expert = ExpertFactory.create(username="pe.intake", password="Ee123456!")
    occ = OccurrenceFactory.create(agent=agent)
    auth_as(expert)
    resp = page.goto(f"/occurrences/{occ.id}/intake/", wait_until="load")
    assert resp is not None and resp.status == 200
    assert page.locator("h1").first.is_visible()
