"""
E2E — verificação pública via QR (ADR-0012), SEM autenticação.

A página /v/<short_hash>/ permite a um perito confirmar que recebeu o talão
certo sem expor dados sensíveis. Hash válido → página pública (200); hash
inválido → não encontrado (404).
"""

import pytest

from core.qr_verify import short_hash_for
from core.tests_factories import OccurrenceFactory, UserFactory

pytestmark = pytest.mark.e2e


def test_public_verify_renders_for_valid_hash(page, live_server):
    """Hash válido renderiza a página pública (sem login) com o código do caso."""
    agent = UserFactory.create(username="ag.pub", password="Aa123456!")
    occ = OccurrenceFactory.create(agent=agent)
    short_hash = short_hash_for(occ.id)

    resp = page.goto(f"/v/{short_hash}/", wait_until="load")  # SEM autenticação
    assert resp is not None and resp.status == 200
    occ.refresh_from_db()
    if occ.code:
        assert occ.code in page.content()


def test_public_verify_notfound_for_invalid_hash(page, live_server):
    """Hash com o comprimento certo mas inexistente → 404 (página 'não encontrado')."""
    resp = page.goto("/v/abcdef000000/", wait_until="load")
    assert resp is not None and resp.status == 404
