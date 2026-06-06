"""
E2E — receção no laboratório (intake, fase 2 do handoff — ADR-0016 v2).

Só um perito (FORENSIC_EXPERT/staff) recebe. A receção fecha um encaminhamento
em curso: o ledger é semeado até EM TRÂNSITO (apreensão → validação → despacho →
encaminhamento via portador) antes de submeter a receção no laboratório.
"""

from decimal import Decimal

import pytest

from core.models import (
    ChainOfCustody,
    Institution,
    InstitutionType,
    Portador,
)
from core.tests_factories import (
    ChainOfCustodyFactory,
    EvidenceMobileFactory,
    ExpertFactory,
    OccurrenceFactory,
    UserFactory,
)

pytestmark = pytest.mark.e2e


def test_intake_recebe_prova_encaminhada(page, auth_as, live_server):
    agent = UserFactory.create(username="ag.intk", password="Aa123456!")
    expert = ExpertFactory.create(username="pe.intk", password="Ee123456!")
    occ = OccurrenceFactory.create(agent=agent)
    ev = EvidenceMobileFactory.create(occurrence=occ, agent=agent)
    lab = Institution.objects.create(
        name="Lab E2E",
        type=InstitutionType.LAB_PUBLICO,
        sigla="LAB-E2E",
        gps_lat=Decimal("38.7256000"),
        gps_lng=Decimal("-9.1430000"),
    )
    portador = Portador.objects.create(
        matricula="E2E-INTK-1", nome="Ana", apelido="Costa", posto="Agente"
    )
    # Ledger até EM TRÂNSITO: apreensão → validação → despacho → encaminhamento.
    ChainOfCustodyFactory.create(evidence=ev, agent=agent)  # APREENSAO_OBJETO
    for et in (
        ChainOfCustody.EventType.VALIDACAO_APREENSAO,
        ChainOfCustody.EventType.DESPACHO_PERICIA,
    ):
        ChainOfCustodyFactory.create(
            evidence=ev,
            agent=agent,
            event_type=et,
            custodian_type=ChainOfCustody.CustodianType.OPC,
        )
    ChainOfCustody.objects.create(
        evidence=ev,
        agent=agent,
        event_type=ChainOfCustody.EventType.ENCAMINHAMENTO_CUSTODIA,
        custodian_type=ChainOfCustody.CustodianType.LAB_PUBLICO,
        custodian_institution=lab,
        bearer=portador,
    )
    auth_as(expert)

    before = ChainOfCustody.objects.filter(evidence=ev).count()

    page.goto(f"/occurrences/{occ.id}/intake/", wait_until="load")
    # A checkbox do item em trânsito vem pré-marcada; submeter regista a
    # RECEPCAO_CUSTODIA (fase 2) em lote atómico.
    with page.expect_response(
        lambda r: "/intake/" in r.url and r.request.method == "POST"
    ):
        page.click("button[type=submit]")

    after = ChainOfCustody.objects.filter(evidence=ev).count()
    assert after == before + 1, f"esperava +1 evento (receção) ({before}→{after})"
