"""
E2E — criação de instituição via MODAL de AÇÃO (ação-in-place) sob CSP estrita.

Valida a fundação de interação da Fase 7: o gatilho [data-modal-open] carrega o
formulário por HTMX para o <dialog> central, o modal abre, o seletor de mapa
(map-picker.js) arranca dentro do modal e a submissão cria a instituição e
recarrega a lista (HX-Redirect) — tudo sem violar a CSP (sem inline handlers).
"""

import pytest
from playwright.sync_api import expect

from core.models import Institution
from core.tests_factories import UserFactory

pytestmark = pytest.mark.e2e


def test_institution_modal_create_flow(page, auth_as, live_server, csp_violations, js_errors):
    """Abrir o modal, preencher e submeter cria a instituição e recarrega a lista."""
    admin = UserFactory.create(username="inst.e2e", password="Aa123456!", is_staff=True)
    auth_as(admin)

    page.goto("/institutions/", wait_until="load")
    # O <dialog> começa fechado (dialog:not([open]) → display:none).
    expect(page.locator("#app-modal")).to_be_hidden()

    # Alvo específico: a sidebar global tem agora outros [data-modal-open]
    # (atalhos "Nova X"), por isso seleciona-se o gatilho da instituição pelo título.
    page.click("[data-modal-title='Nova instituição']")
    # Abre e mostra o formulário injetado por HTMX.
    expect(page.locator("#app-modal")).to_be_visible()
    expect(page.locator("#f-i-name")).to_be_visible()
    # O título do modal vem do data-modal-title do gatilho.
    expect(page.locator("#app-modal-title")).to_have_text("Nova instituição")

    page.fill("#f-i-name", "Laboratório E2E")
    page.select_option("#f-i-type", "LAB_PUBLICO")
    page.fill("#f-i-sigla", "LAB-E2E")
    page.fill("#f-i-address", "Rua de Teste, 1, Lisboa")
    page.fill("#f-i-lat", "38.7197003")
    page.fill("#f-i-lng", "-9.1466657")
    page.click("#app-modal button[type=submit]")

    # Sucesso → 204 + HX-Redirect para a lista; a nova instituição aparece.
    page.wait_for_url("**/institutions/", timeout=10000)
    expect(page.get_by_text("Laboratório E2E")).to_be_visible()
    assert Institution.objects.filter(name="Laboratório E2E").exists()
    assert not csp_violations, csp_violations
    assert not js_errors, js_errors


def test_institution_modal_closes_on_cancel(page, auth_as, live_server):
    """O botão Cancelar (data-modal-close) fecha o modal sem criar nada."""
    admin = UserFactory.create(username="inst.cancel", password="Aa123456!", is_staff=True)
    auth_as(admin)

    page.goto("/institutions/", wait_until="load")
    # Alvo específico: a sidebar global tem agora outros [data-modal-open]
    # (atalhos "Nova X"), por isso seleciona-se o gatilho da instituição pelo título.
    page.click("[data-modal-title='Nova instituição']")
    expect(page.locator("#app-modal")).to_be_visible()
    page.click("#app-modal [data-modal-close]")
    expect(page.locator("#app-modal")).to_be_hidden()


def test_institution_map_click_sets_coordinates(page, auth_as, live_server):
    """Clicar no mapa do seletor fixa o pino e preenche lat/lng (map-picker.js)."""
    admin = UserFactory.create(username="inst.map", password="Aa123456!", is_staff=True)
    auth_as(admin)

    page.goto("/institutions/", wait_until="load")
    # Alvo específico: a sidebar global tem agora outros [data-modal-open]
    # (atalhos "Nova X"), por isso seleciona-se o gatilho da instituição pelo título.
    page.click("[data-modal-title='Nova instituição']")
    expect(page.locator(".map-picker")).to_be_visible()
    # Espera o Leaflet montar: o container ganha a classe `leaflet-container`.
    page.wait_for_selector(".map-picker.leaflet-container", timeout=8000)

    box = page.locator(".map-picker").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    # O clique escreve coordenadas (7 casas) nos inputs-alvo.
    expect(page.locator("#f-i-lat")).not_to_have_value("", timeout=5000)
    expect(page.locator("#f-i-lng")).not_to_have_value("")
