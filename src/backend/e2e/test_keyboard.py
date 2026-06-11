"""
E2E — navegação e operação por TECLADO (a11y de interação, que o axe não cobre).

Cobre os caminhos que um utilizador só-teclado precisa: o skip link, submeter o
login sem rato, e abrir o detalhe a partir de uma linha da grelha com
Enter (forensic-list.js liga ↑/↓/Enter/Espaço às linhas).
"""

import pytest
from playwright.sync_api import expect

from core.tests_factories import OccurrenceFactory, UserFactory

pytestmark = pytest.mark.e2e


def test_skip_link_jumps_to_main(page, seed, auth_as):
    """O primeiro Tab foca o 'saltar para o conteúdo'; Enter salta para o main."""
    auth_as(seed["expert"])
    page.goto("/occurrences/", wait_until="load")
    page.keyboard.press("Tab")
    cls = page.evaluate("document.activeElement ? document.activeElement.className : ''")
    assert "skip-link" in cls, f"o 1.º Tab não focou o skip link (foi: {cls!r})"
    page.keyboard.press("Enter")
    assert "#main-content" in page.url


def test_login_submits_with_keyboard(page, make_user):
    """Preencher e premir Enter no formulário de login autentica (sem rato)."""
    make_user("agent", username="kb.login", password="Kb123456!")
    page.goto("/login/", wait_until="load")
    page.fill("#username", "kb.login")
    page.fill("#password", "Kb123456!")
    page.keyboard.press("Enter")
    page.wait_for_url("**/dashboard/", timeout=10000)
    assert "/dashboard/" in page.url


def test_grid_row_opens_detail_with_enter(page, auth_as, live_server):
    """Focar uma linha e premir Enter navega para o detalhe (a11y da grelha)."""
    agent = UserFactory.create(username="kb.row", password="Kb123456!")
    occ = OccurrenceFactory.create(number="NUIPC.KB/2026.LX", agent=agent)
    auth_as(agent)
    page.goto("/occurrences/", wait_until="load")
    page.locator(f"[data-row][data-id='{occ.id}']").focus()
    page.keyboard.press("Enter")
    page.wait_for_url(f"**/occurrences/{occ.id}/", timeout=10000)
    expect(page.locator("#occ-title")).to_be_visible()
