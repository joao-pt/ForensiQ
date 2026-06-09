"""
Smoke E2E — valida a FUNDAÇÃO do harness antes dos fluxos detalhados:

  * o servidor live serve o frontend real (CSS/JS de ``src/frontend/static``);
  * a autenticação por cookie JWT funciona sobre http://localhost;
  * o login pelo formulário real conduz ao dashboard;
  * todas as páginas autenticadas renderizam sem erros de JS nem 404 de
    estáticos;
  * a captura de GPS injetada preenche as coordenadas.

Se algo aqui falha, os fluxos seguintes não são fiáveis — por isso é o gate.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_login_via_ui_real(page, make_user, login_via_ui):
    """O formulário real de login autentica e redireciona ao dashboard."""
    make_user("agent", username="agente.smoke", password="Smoke123!")
    login_via_ui("agente.smoke", "Smoke123!")
    assert "/dashboard/" in page.url


def test_protected_pages_render(page, seed, auth_as, js_errors, failed_static):
    """Cada página autenticada carrega com CSS, sem 404 de estáticos nem erros JS."""
    auth_as(seed["expert"])  # perito staff → vê tudo e passa todos os gates
    occ_id = seed["occ"].id
    ev_id = seed["ev"].id

    pages = [
        ("dashboard", "/dashboard/"),
        ("occurrences", "/occurrences/"),
        ("occurrence_new", "/occurrences/new/"),
        ("occurrence_detail", f"/occurrences/{occ_id}/"),
        ("intake", f"/occurrences/{occ_id}/intake/"),
        ("evidences", "/evidences/"),
        ("evidence_new", "/evidences/new/"),
        ("evidence_detail", f"/evidences/{ev_id}/"),
        ("custody", f"/evidences/{ev_id}/custody/"),
        ("custodies", "/custodies/"),
        ("reports", "/reports/"),
        ("stats", "/stats/"),
        ("audit", "/audit/investigation/"),
        ("settings", "/settings/"),
        ("verificacoes", "/verificacoes/"),
    ]

    problems = []
    for name, path in pages:
        resp = page.goto(path, wait_until="load")
        status = resp.status if resp else None
        if status is None or status >= 400:
            problems.append(f"{name} ({path}): HTTP {status}")
            continue
        sheets = page.evaluate("document.styleSheets.length")
        if not sheets:
            problems.append(f"{name} ({path}): sem CSS (styleSheets=0)")

    assert not failed_static, f"Estáticos 404:\n{failed_static}"
    assert not js_errors, f"Erros JS:\n{js_errors}"
    assert not problems, "Páginas com problema:\n" + "\n".join(problems)


def test_no_csp_violations(page, seed, auth_as, csp_violations):
    """
    Nenhuma página dispara violações de Content Security Policy.

    A CSP é estrita por desenho (style-src/script-src sem unsafe-inline) — uma
    violação significa estilo/script inline bloqueado em produção. Cobre as
    páginas com HTMX (injetava o <style> de indicadores) e com Leaflet.
    """
    auth_as(seed["expert"])
    occ_id = seed["occ"].id
    ev_id = seed["ev"].id

    for path in (
        "/dashboard/",          # HTMX + Leaflet
        "/occurrences/",        # HTMX + Leaflet
        "/evidences/",          # HTMX + Leaflet
        "/custodies/",          # HTMX + Leaflet
        f"/occurrences/{occ_id}/",
        f"/evidences/{ev_id}/",
        f"/evidences/{ev_id}/custody/",
        "/reports/",            # HTMX
        "/verificacoes/",       # HTMX
    ):
        page.goto(path, wait_until="load")
        page.wait_for_timeout(300)  # dá tempo ao HTMX/Leaflet de inicializar

    assert not csp_violations, "Violações de CSP:\n" + "\n".join(
        dict.fromkeys(csp_violations)  # dedup preservando ordem
    )


def test_gps_capture_fills_coordinates(page, seed, auth_as):
    """O botão 'Usar a minha localização' (geo-field) preenche lat/lng com a
    geolocalização injetada. (A captura migrou de [data-geo-capture] para o
    componente geo-field [data-geo-field-locate].)"""
    auth_as(seed["expert"])
    page.goto("/occurrences/new/", wait_until="load")
    page.click("[data-geo-field-locate]")
    # expect() é CSP-safe (não usa eval na página); wait_for_function com string
    # seria bloqueado pela CSP estrita durante o polling.
    expect(page.locator("#f-lat")).not_to_have_value("", timeout=8000)
    lat = page.input_value("#f-lat")
    lng = page.input_value("#f-lng")
    assert lat.startswith("38.7"), f"lat inesperada: {lat!r}"
    assert lng.startswith("-9.1"), f"lng inesperada: {lng!r}"
