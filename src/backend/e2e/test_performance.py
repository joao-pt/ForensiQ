"""
E2E — orçamentos de rapidez (in-suite, correm no CI).

Não medem performance absoluta de produção (servidor local, DEBUG, sem rede),
mas protegem contra REGRESSÕES grosseiras: um salto no tempo de resposta do
servidor denuncia, por exemplo, uma explosão de queries N+1; uma interação
lenta denuncia um fetch que deixou de responder. Orçamentos folgados de
propósito. A auditoria de rapidez ABSOLUTA (LCP/INP/CLS) faz-se com o Lighthouse
(ver docs/testing/ e scripts/run_lighthouse.ps1).
"""

import time

import pytest
from playwright.sync_api import expect

from core.tests_factories import CrimeTipoFactory, OccurrenceFactory, UserFactory

from .pages import app_pages, select_crime

pytestmark = pytest.mark.e2e

# Tempo de RENDER do servidor (responseEnd - requestStart), em ms.
_SERVER_BUDGET_MS = 2000
# Latência de uma interação (round-trip de um fetch local), em ms.
_INTERACTION_BUDGET_MS = 2500


def _server_render_ms(page):
    """Tempo entre o pedido e a última resposta do documento (render do servidor)."""
    return page.evaluate(
        "(() => { const n = performance.getEntriesByType('navigation')[0];"
        " return n ? (n.responseEnd - n.requestStart) : 0; })()"
    )


def test_pages_render_within_server_budget(page, seed, auth_as):
    auth_as(seed["expert"])
    occ_id = seed["occ"].id
    ev_id = seed["ev"].id
    # Subconjunto mais pesado da lista canonica (pages.app_pages - D114).
    perf_keys = ('dashboard', 'occurrences', 'occurrence_detail', 'evidences',
                 'evidence_detail', 'custody', 'stats')
    all_pages = app_pages(occ_id, ev_id)
    pages = {name: all_pages[name]['path'] for name in perf_keys}
    slow = {}
    for name, path in pages.items():
        page.goto(path, wait_until="load")
        ms = _server_render_ms(page)
        if ms > _SERVER_BUDGET_MS:
            slow[name] = round(ms)

    assert not slow, f"Páginas acima do orçamento de {_SERVER_BUDGET_MS}ms: {slow}"


def test_crime_cascade_interaction_is_responsive(page, auth_as, live_server):
    """A cascata (fetch da subcategoria→tipo) responde dentro do orçamento."""
    agent = UserFactory.create(username="ag.perf.casc", password="Aa123456!")
    tipo = CrimeTipoFactory.create()
    auth_as(agent)

    page.goto("/occurrences/new/", wait_until="load")
    t0 = time.perf_counter()
    select_crime(page, tipo.subcategoria.categoria.id, tipo.subcategoria.id, tipo.id)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _INTERACTION_BUDGET_MS, f"cascata demorou {elapsed_ms:.0f}ms"


def test_htmx_search_interaction_is_responsive(page, auth_as, live_server):
    """Filtrar a lista por HTMX atualiza a grelha dentro do orçamento."""
    agent = UserFactory.create(username="ag.perf.htmx", password="Aa123456!")
    OccurrenceFactory.create(number="NUIPC.PERF-A/2026.LX", agent=agent)
    OccurrenceFactory.create(number="NUIPC.PERF-B/2026.LX", agent=agent)
    auth_as(agent)

    page.goto("/occurrences/", wait_until="load")
    t0 = time.perf_counter()
    page.fill("input[name='q_number']", "PERF-A")
    expect(page.locator("#occ-grid")).not_to_contain_text("PERF-B")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # inclui o debounce de 350ms do HTMX; o orçamento contempla-o.
    assert elapsed_ms < _INTERACTION_BUDGET_MS, f"filtro HTMX demorou {elapsed_ms:.0f}ms"
