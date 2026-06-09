"""
E2E — listas densas com HTMX (ocorrências): pesquisa e filtro atualizam a
grelha sem recarregar a página, e clicar numa linha abre o drawer de detalhe.

Notas de implementação (ver docs/testing/):
  * usamos as asserções ``expect()`` do Playwright (baseadas no protocolo, com
    auto-retry) em vez de ``wait_for_function`` com string — esta última usa
    ``new Function`` na página e é BLOQUEADA pela CSP estrita (sem unsafe-eval)
    durante o polling;
  * o clique na linha é disparado com ``dispatch_event('click')`` porque o
    ``<thead>`` sticky interceta o clique real de rato (e o HTMX reage na mesma
    ao evento click).
"""

import pytest
from playwright.sync_api import expect

from core.tests_factories import OccurrenceFactory, UserFactory

pytestmark = pytest.mark.e2e


def test_search_filters_grid_via_htmx_without_reload(page, auth_as, live_server):
    """Escrever na pesquisa filtra a grelha por HTMX, sem recarregar a página."""
    agent = UserFactory.create(username="ag.search", password="Aa123456!")
    OccurrenceFactory.create(number="NUIPC.ALFA/2026.LX", agent=agent)
    OccurrenceFactory.create(number="NUIPC.BRAVO/2026.LX", agent=agent)
    auth_as(agent)

    page.goto("/occurrences/", wait_until="load")
    grid = page.locator("#occ-grid")
    expect(grid).to_contain_text("ALFA")
    expect(grid).to_contain_text("BRAVO")

    page.evaluate("window.__noreload = true")  # marca de deteção de reload (one-shot)
    page.fill("input[name='q_number']", "ALFA")

    expect(grid).not_to_contain_text("BRAVO")  # swap HTMX filtrou
    expect(grid).to_contain_text("ALFA")
    assert page.evaluate("window.__noreload") is True, "houve reload — não foi swap HTMX"


def test_priority_select_filters_grid(page, auth_as, live_server):
    """Mudar o select de prioridade dispara um filtro HTMX (trigger diferente)."""
    agent = UserFactory.create(username="ag.pri", password="Aa123456!")
    OccurrenceFactory.create(number="NUIPC.NORM1/2026.LX", agent=agent)
    OccurrenceFactory.create(number="NUIPC.NORM2/2026.LX", agent=agent)
    auth_as(agent)

    page.goto("/occurrences/", wait_until="load")
    # Sem mapa de prioridade semeado, ambas são NORMAL → filtrar por prioritárias
    # esvazia a grelha (mensagem de "nenhum resultado").
    page.select_option("select[name='pri']", value="PRIORITARIA")
    expect(page.locator("#occ-grid")).to_contain_text("Nenhum resultado")


def test_row_click_opens_detail_drawer(page, auth_as, live_server):
    """Clicar numa linha carrega o detalhe no drawer via HTMX (conteúdo muda)."""
    agent = UserFactory.create(username="ag.draw", password="Aa123456!")
    occ = OccurrenceFactory.create(number="NUIPC.DRAWER/2026.LX", agent=agent)
    auth_as(agent)

    page.goto("/occurrences/", wait_until="load")
    drawer = page.locator("#app-drawer-body")
    expect(drawer).to_contain_text("Selecione uma ocorrência")
    page.locator(f"[data-row][data-id='{occ.id}']").dispatch_event("click")
    expect(drawer).not_to_contain_text("Selecione uma ocorrência")
