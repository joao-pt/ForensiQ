"""
E2E — comportamento responsivo móvel (a app é mobile-first).

Em <1024px a sidebar vira off-canvas, aberto pelo botão hambúrguer (#nav-toggle).
Testa-se a abertura/fecho (incl. Escape) via o estado real (body.nav-open +
aria-expanded), não por visibilidade — o painel desliza por transform.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

_MOBILE = {"width": 390, "height": 844}  # ~iPhone 14


def test_mobile_offcanvas_nav_toggles(page, seed, auth_as):
    page.set_viewport_size(_MOBILE)
    auth_as(seed["expert"])
    page.goto("/occurrences/", wait_until="load")

    toggle = page.locator("#nav-toggle")
    expect(toggle).to_be_visible()  # o hambúrguer aparece no móvel
    expect(toggle).to_have_attribute("aria-expanded", "false")
    assert page.evaluate("document.body.classList.contains('nav-open')") is False

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert page.evaluate("document.body.classList.contains('nav-open')") is True

    page.keyboard.press("Escape")  # Escape fecha o off-canvas
    expect(toggle).to_have_attribute("aria-expanded", "false")
    assert page.evaluate("document.body.classList.contains('nav-open')") is False
