"""
E2E — receção no laboratório (intake, ADR-0012 Vaga 2).

Só um perito (FORENSIC_EXPERT/staff) recebe. A transferência para o laboratório
só é válida depois da validação da apreensão (guarda do ledger), por isso o
ledger é semeado até esse ponto antes de submeter a receção.
"""

import pytest

from core.models import ChainOfCustody
from core.tests_factories import (
    ChainOfCustodyFactory,
    EvidenceMobileFactory,
    ExpertFactory,
    OccurrenceFactory,
    UserFactory,
)

pytestmark = pytest.mark.e2e


def test_intake_registers_transfer_to_lab(page, auth_as, live_server):
    agent = UserFactory.create(username="ag.intk", password="Aa123456!")
    expert = ExpertFactory.create(username="pe.intk", password="Ee123456!")
    occ = OccurrenceFactory.create(agent=agent)
    ev = EvidenceMobileFactory.create(occurrence=occ, agent=agent)
    # Ledger pronto para transferência: apreensão + validação da apreensão.
    ChainOfCustodyFactory.create(evidence=ev, agent=agent)  # APREENSAO_OBJETO
    ChainOfCustodyFactory.create(
        evidence=ev,
        agent=agent,
        event_type=ChainOfCustody.EventType.VALIDACAO_APREENSAO,
        custodian_type=ChainOfCustody.CustodianType.OPC,
    )
    auth_as(expert)

    before = ChainOfCustody.objects.filter(evidence=ev).count()

    page.goto(f"/occurrences/{occ.id}/intake/", wait_until="load")
    # As checkboxes dos itens a receber vêm pré-marcadas; submeter regista a
    # TRANSFERENCIA → LAB_PUBLICO em lote atómico.
    with page.expect_response(
        lambda r: "/intake/" in r.url and r.request.method == "POST"
    ):
        page.click("button[type=submit]")

    after = ChainOfCustody.objects.filter(evidence=ev).count()
    assert after == before + 1, f"esperava +1 evento (transferência) ({before}→{after})"
