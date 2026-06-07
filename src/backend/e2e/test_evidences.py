"""
E2E — registo de evidências: campos específicos por tipo (mostrar/esconder via
JS) e upload de fotografia (o fluxo que rebentou com 500 em produção).
"""

import pytest
from playwright.sync_api import expect

from core.models import Evidence
from core.tests_factories import OccurrenceFactory, UserFactory

from .pages import is_evidence_detail

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

    page.wait_for_url(is_evidence_detail, timeout=10000)
    ev = Evidence.objects.filter(occurrence=occ).order_by("-id").first()
    assert ev is not None
    assert ev.photo, "a evidência devia ter ficado com a fotografia carregada"


def test_create_evidence_requires_occurrence_and_type(page, auth_as, live_server):
    """Sem ocorrência/tipo (required) a submissão é bloqueada no cliente."""
    agent = UserFactory.create(username="ag.ev.req", password="Aa123456!")
    OccurrenceFactory.create(agent=agent)
    auth_as(agent)

    page.goto("/evidences/new/", wait_until="load")
    page.click("button[type=submit]")

    assert page.url.endswith("/evidences/new/")
    assert page.eval_on_selector("#f-occ", "el => el.validity.valid") is False
