"""
E2E — registo de evidências: campos específicos por tipo (mostrar/esconder via
JS) e upload de fotografia (o fluxo que rebentou com 500 em produção).
"""

import pytest
from playwright.sync_api import expect

from core.models import EventType, Evidence
from core.tests_factories import OccurrenceFactory, UserFactory

from .pages import is_evidence_detail, is_evidence_registered

pytestmark = pytest.mark.e2e


def test_type_specific_fields_toggle_by_type(page, auth_as, live_server):
    """Escolher o tipo ativa só os identificadores desse tipo; os outros ficam
    desativados (não submetidos), evitando colisão de chaves entre tipos."""
    agent = UserFactory.create(username="ag.ev.toggle", password="Aa123456!")
    OccurrenceFactory.create(agent=agent)
    auth_as(agent)

    page.goto("/evidences/new/", wait_until="load")
    imei = page.locator("#f-tsd-MOBILE_DEVICE-imei")
    vin = page.locator("#f-tsd-VEHICLE-vin")
    # A ligação tipo→campos corre no DOMContentLoaded (identifier-lookup.js).
    # Espera o campo estar no DOM antes de interagir (robustez sob carga: evita
    # o one-shot is_disabled correr contra um frame ainda a assentar).
    expect(imei).to_be_attached()
    page.select_option("#f-type", value=Evidence.EvidenceType.MOBILE_DEVICE)

    # O IMEI (telemóvel) fica ativo e visível; o VIN (veículo) fica desativado.
    # Asserções com auto-retry (não one-shot) — absorvem a latência de binding.
    expect(imei).to_be_enabled()
    expect(imei).to_be_visible()
    expect(vin).to_be_disabled()


def test_create_evidence_with_photo(page, auth_as, live_server, tiny_image):
    """Registo completo de um telemóvel com fotografia → cria a evidência."""
    agent = UserFactory.create(username="ag.ev.create", password="Aa123456!")
    occ = OccurrenceFactory.create(agent=agent)
    auth_as(agent)

    page.goto("/evidences/new/", wait_until="load")
    page.select_option("#f-occ", value=str(occ.id))
    page.select_option("#f-type", value=Evidence.EvidenceType.MOBILE_DEVICE)
    page.fill("#f-desc", "Smartphone preto apreendido ao suspeito (teste E2E).")
    page.set_input_files("#f-photo", tiny_image)
    page.click("button[type=submit]")

    # Fluxo encadeado (§6): o sucesso segue para a página de continuação.
    page.wait_for_url(is_evidence_registered, timeout=10000)
    ev = Evidence.objects.filter(occurrence=occ).order_by("-id").first()
    assert ev is not None
    assert ev.photo, "a evidência devia ter ficado com a fotografia carregada"

    # «Concluir» fecha o encadeado na ficha do item.
    page.click("text=Concluir")
    page.wait_for_url(is_evidence_detail, timeout=10000)


def test_chained_subcomponent_registration(page, auth_as, live_server):
    """Fluxo encadeado (§6): registar um veículo e, a partir da continuação,
    o componente eletrónico (filho) e o rastreador GPS (neto) — contexto
    trancado (?parent=), génese DERIVACAO_ITEM automática, e o bloqueio de
    profundidade explicado no nível máximo (3)."""
    agent = UserFactory.create(username="ag.ev.chain", password="Aa123456!")
    occ = OccurrenceFactory.create(agent=agent)
    auth_as(agent)

    page.goto("/evidences/new/", wait_until="load")
    page.select_option("#f-occ", value=str(occ.id))
    page.select_option("#f-type", value=Evidence.EvidenceType.VEHICLE)
    page.fill("#f-desc", "Veículo pai (fluxo encadeado E2E).")
    page.click("button[type=submit]")
    page.wait_for_url(is_evidence_registered, timeout=10000)

    page.click("text=Registar sub-componente deste item")
    page.wait_for_url(lambda url: "?parent=" in url, timeout=10000)
    # Contexto trancado: sem selects de ocorrência/pai; breadcrumb do nível.
    expect(page.locator("#f-occ")).to_have_count(0)
    expect(page.locator("#f-parent")).to_have_count(0)
    expect(page.get_by_text("novo sub-componente")).to_be_visible()

    page.select_option("#f-type", value=Evidence.EvidenceType.VEHICLE_COMPONENT)
    page.fill("#f-desc", "Centralina dentro do veículo (E2E).")
    page.click("button[type=submit]")
    page.wait_for_url(is_evidence_registered, timeout=10000)

    # Neto (3.º nível, ainda admissível) a partir da continuação do filho.
    page.click("text=Registar sub-componente deste item")
    page.wait_for_url(lambda url: "?parent=" in url, timeout=10000)
    page.select_option("#f-type", value=Evidence.EvidenceType.GPS_TRACKER)
    page.fill("#f-desc", "Rastreador GPS dentro da centralina (E2E).")
    page.click("button[type=submit]")
    page.wait_for_url(is_evidence_registered, timeout=10000)

    # No nível máximo a continuação explica o bloqueio em vez do botão.
    expect(page.get_by_text("Profundidade máxima atingida")).to_be_visible()
    expect(
        page.get_by_text("Registar sub-componente deste item")
    ).to_have_count(0)

    pai = Evidence.objects.get(occurrence=occ, parent_evidence__isnull=True)
    filho = Evidence.objects.get(occurrence=occ, parent_evidence=pai)
    neto = Evidence.objects.get(occurrence=occ, parent_evidence=filho)
    assert neto.code == f"{pai.code}.1.1"
    for item in (filho, neto):
        genese = item.custody_chain.get()
        assert genese.event_type == EventType.DERIVACAO_ITEM


def test_create_evidence_requires_occurrence_and_type(page, auth_as, live_server):
    """Sem ocorrência/tipo (required) a submissão é bloqueada no cliente."""
    agent = UserFactory.create(username="ag.ev.req", password="Aa123456!")
    OccurrenceFactory.create(agent=agent)
    auth_as(agent)

    page.goto("/evidences/new/", wait_until="load")
    page.click("button[type=submit]")

    assert page.url.endswith("/evidences/new/")
    assert page.eval_on_selector("#f-occ", "el => el.validity.valid") is False
