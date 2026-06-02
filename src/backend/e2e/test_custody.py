"""
E2E — registo de evento na cadeia de custódia (ledger append-only, ADR-0015).

O dropdown ``valid_events`` só apresenta transições que as guardas do ledger
aceitam, por isso escolher a primeira opção é uma transição garantidamente
válida — testamos o caminho de sucesso de ponta a ponta.
"""

import pytest

from core.models import ChainOfCustody
from core.tests_factories import (
    ChainOfCustodyFactory,
    EvidenceMobileFactory,
    OccurrenceFactory,
    UserFactory,
)

pytestmark = pytest.mark.e2e


def test_register_custody_event_appends_to_ledger(page, auth_as, live_server):
    agent = UserFactory.create(username="ag.cust", password="Aa123456!")
    occ = OccurrenceFactory.create(agent=agent)
    ev = EvidenceMobileFactory.create(occurrence=occ, agent=agent)
    ChainOfCustodyFactory.create(evidence=ev, agent=agent)  # APREENSAO_OBJETO inicial
    auth_as(agent)

    before = ChainOfCustody.objects.filter(evidence=ev).count()

    page.goto(f"/evidences/{ev.id}/custody/", wait_until="load")
    page.locator("#custody-register summary").click()  # abrir o <details>
    first_value = (
        page.locator("#r-event option:not([value=''])").first.get_attribute("value")
    )
    assert first_value, "o ledger devia oferecer pelo menos uma transição válida"
    page.select_option("#r-event", value=first_value)

    with page.expect_response(
        lambda r: "/custody/" in r.url and r.request.method == "POST"
    ):
        page.click("#custody-register button[type=submit]")

    after = ChainOfCustody.objects.filter(evidence=ev).count()
    assert after == before + 1, f"esperava +1 evento no ledger ({before}→{after})"
