"""
E2E — atalhos "Nova X" da sidebar abrem os formulários PESADOS como modais
ação-in-place (Fase 7, último bloco), e os componentes que ligavam só no load
REHIDRATAM dentro do modal injetado por HTMX:

  * Nova ocorrência → a cascata de crime (crime-cascade.js) reinicializa em
    fq:modal-open e carrega subcategorias/tipos por fetch dentro do modal;
  * Novo item → a sincronia tipo→campos (identifier-lookup.js) reinicializa e
    ativa só os identificadores do tipo escolhido dentro do modal.

Valida o caminho ponta-a-ponta no browser, incluindo o contrato de submissão
(sucesso no modal → 204 + HX-Redirect → o HTMX navega), sob CSP estrita.
"""

import pytest
from playwright.sync_api import expect

from core.models import Evidence, Occurrence
from core.tests_factories import CrimeTipoFactory, OccurrenceFactory, UserFactory

from .pages import is_occurrence_detail, select_crime

pytestmark = pytest.mark.e2e


def test_occurrence_modal_cascade_rehydrates_and_submits(
    page, auth_as, live_server, csp_violations, js_errors
):
    """O atalho da sidebar abre o modal; a cascata rehidrata (carrega N2/N3 por
    fetch); submeter cria a ocorrência e navega para o detalhe (204 + HX-Redirect)."""
    agent = UserFactory.create(username="ag.modal.occ", password="Aa123456!")
    tipo = CrimeTipoFactory.create()  # cria a cadeia N3→N2→N1
    auth_as(agent)

    page.goto("/occurrences/", wait_until="load")
    expect(page.locator("#app-modal")).to_be_hidden()
    # Atalho global da sidebar (alvo pelo título — há outros [data-modal-open]).
    page.click("[data-modal-title='Nova ocorrência']")
    expect(page.locator("#app-modal")).to_be_visible()
    expect(page.locator("#app-modal-title")).to_have_text("Nova ocorrência")
    expect(page.locator("#f-number")).to_be_visible()

    page.fill("#f-number", "NUIPC.MODAL-001/2026.LISBOA")
    page.fill("#f-dt", "2026-05-30T14:30")
    page.fill("#f-desc", "Ocorrência criada pelo modal (teste E2E).")
    # A cascata SÓ existe se o crime-cascade.js rehidratou no modal injetado.
    select_crime(page, tipo.subcategoria.categoria.id, tipo.subcategoria.id, tipo.id)
    expect(page.locator("#app-modal [data-crime-priority]")).not_to_have_text("", timeout=5000)

    page.click("#app-modal button[type=submit]")
    page.wait_for_url(is_occurrence_detail, timeout=10000)
    assert Occurrence.objects.filter(number="NUIPC.MODAL-001/2026.LISBOA").exists()
    assert not csp_violations, csp_violations
    assert not js_errors, js_errors


def test_occurrence_modal_invalid_keeps_errors_in_modal(page, auth_as, live_server):
    """Submeter o modal sem número devolve o fragmento com erro DENTRO do modal
    (400 → swap), sem navegar e sem criar nada."""
    agent = UserFactory.create(username="ag.modal.err", password="Aa123456!")
    tipo = CrimeTipoFactory.create()
    auth_as(agent)

    page.goto("/occurrences/", wait_until="load")
    page.click("[data-modal-title='Nova ocorrência']")
    expect(page.locator("#f-desc")).to_be_visible()
    # Preenche tudo MENOS o número, mas remove o `required` para chegar ao servidor.
    page.fill("#f-desc", "Sem número — erro de servidor.")
    select_crime(page, tipo.subcategoria.categoria.id, tipo.subcategoria.id, tipo.id)
    page.eval_on_selector("#f-number", "el => el.removeAttribute('required')")
    page.click("#app-modal button[type=submit]")

    # O modal mantém-se aberto com o formulário (o erro voltou para #app-modal-body).
    expect(page.locator("#app-modal")).to_be_visible()
    expect(page.locator("#app-modal #f-desc")).to_be_visible()
    assert page.url.endswith("/occurrences/")
    assert not Occurrence.objects.filter(description="Sem número — erro de servidor.").exists()


def test_evidence_modal_type_toggle_rehydrates(page, auth_as, live_server, js_errors):
    """O atalho "Novo item" abre o modal; escolher o tipo ativa só os
    identificadores desse tipo DENTRO do modal (identifier-lookup.js rehidratou)."""
    agent = UserFactory.create(username="ag.modal.ev", password="Aa123456!")
    OccurrenceFactory.create(agent=agent)
    auth_as(agent)

    page.goto("/evidences/", wait_until="load")
    page.click("[data-modal-title='Novo item de prova']")
    expect(page.locator("#app-modal")).to_be_visible()
    expect(page.locator("#app-modal-title")).to_have_text("Novo item de prova")

    imei = page.locator("#app-modal #f-tsd-MOBILE_DEVICE-imei")
    vin = page.locator("#app-modal #f-tsd-VEHICLE-vin")
    expect(imei).to_be_attached()
    page.select_option("#f-type", value=Evidence.EvidenceType.MOBILE_DEVICE)
    expect(imei).to_be_enabled()
    expect(imei).to_be_visible()
    expect(vin).to_be_disabled()
    assert not js_errors, js_errors
