"""
E2E — criação e validação de ocorrências (a página com mais interação JS:
cascata de crime N1→N2→N3, captura GPS, badge de prioridade).
"""

import pytest
from playwright.sync_api import expect

from core.models import Occurrence
from core.tests_factories import CrimeTipoFactory, OccurrenceFactory, UserFactory

from .pages import is_occurrence_detail, select_crime

pytestmark = pytest.mark.e2e


def test_create_occurrence_full_flow(page, auth_as, live_server):
    """Preencher o formulário + cascata e submeter cria a ocorrência e redireciona."""
    agent = UserFactory.create(username="ag.create", password="Aa123456!")
    tipo = CrimeTipoFactory.create()  # cria a cadeia N3→N2→N1
    auth_as(agent)

    page.goto("/occurrences/new/", wait_until="load")
    page.fill("#f-number", "NUIPC.E2E-001/2026.LISBOA")
    page.fill("#f-dt", "2026-05-30T14:30")
    page.fill("#f-desc", "Furto de telemóvel na via pública (teste E2E).")
    select_crime(page, tipo.subcategoria.categoria.id, tipo.subcategoria.id, tipo.id)
    page.click("button[type=submit]")

    page.wait_for_url(is_occurrence_detail, timeout=10000)
    assert Occurrence.objects.filter(number="NUIPC.E2E-001/2026.LISBOA").exists()


def test_crime_cascade_updates_priority_hint(page, auth_as, live_server):
    """A cascata carrega subcategorias/tipos por JS e atualiza a dica de prioridade."""
    agent = UserFactory.create(username="ag.cascade", password="Aa123456!")
    tipo = CrimeTipoFactory.create()
    auth_as(agent)

    page.goto("/occurrences/new/", wait_until="load")
    select_crime(page, tipo.subcategoria.categoria.id, tipo.subcategoria.id, tipo.id)
    # A dica passa de vazia a preenchida quando o tipo é escolhido (CSP-safe).
    expect(page.locator("[data-crime-priority]")).not_to_have_text("", timeout=5000)


def test_required_fields_block_empty_submit(page, auth_as, live_server):
    """Submeter vazio é bloqueado pela validação nativa (campos required)."""
    agent = UserFactory.create(username="ag.req", password="Aa123456!")
    auth_as(agent)

    page.goto("/occurrences/new/", wait_until="load")
    page.click("button[type=submit]")

    assert page.url.endswith("/occurrences/new/")
    assert page.eval_on_selector("#f-number", "el => el.validity.valid") is False


def test_duplicate_number_shows_visible_server_error(page, auth_as, live_server):
    """
    Um NUIPC duplicado é rejeitado no servidor e o erro RENDERIZA VISÍVEL.

    Regressão do bug crítico (erros de formulário invisíveis) corrigido na
    auditoria anterior — aqui validado de ponta a ponta no browser.
    """
    agent = UserFactory.create(username="ag.dup", password="Aa123456!")
    tipo = CrimeTipoFactory.create()
    OccurrenceFactory.create(
        number="NUIPC.DUP/2026.LISBOA", agent=agent, crime_type=tipo
    )
    auth_as(agent)

    page.goto("/occurrences/new/", wait_until="load")
    page.fill("#f-number", "NUIPC.DUP/2026.LISBOA")
    page.fill("#f-dt", "2026-05-30T14:30")
    page.fill("#f-desc", "Tentativa de duplicar NUIPC (teste E2E).")
    select_crime(page, tipo.subcategoria.categoria.id, tipo.subcategoria.id, tipo.id)
    page.click("button[type=submit]")

    page.wait_for_selector(".form-error.visible", timeout=8000)
    assert page.url.endswith("/occurrences/new/")
