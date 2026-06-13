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


# Larguras representativas: telemóvel pequeno/médio, o último ponto antes de o
# carimbo des-empilhar (767) e o limite do off-canvas (1023).
_AUDIT_WIDTHS = [320, 360, 390, 767, 1023]


@pytest.mark.parametrize("url", ["/dashboard/", "/occurrences/"])
@pytest.mark.parametrize("width", _AUDIT_WIDTHS)
def test_mobile_header_no_horizontal_overflow(page, seed, auth_as, width, url):
    """A casca nunca pode forçar scroll horizontal nem empurrar o "Terminar
    sessão" para fora do ecrã.

    Regressão: o cabeçalho é uma linha flex fora de ``.app-grid`` (o único
    contentor que recorta overflow). A data + hora LADO A LADO fixavam a largura
    mínima do header em ~426px → em qualquer telemóvel mais estreito a página
    deslizava e o ``#user-menu-trigger`` (logout) ficava cortado. A correção
    empilha o carimbo <768px. Ver app-shell.css §app-top.
    """
    auth_as(seed["expert"])
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(url, wait_until="load")
    page.evaluate("() => document.fonts.ready")

    m = page.evaluate(
        """() => {
            const um = document.querySelector('#user-menu-trigger').getBoundingClientRect();
            return {
                scrollW: document.documentElement.scrollWidth,
                innerW: window.innerWidth,
                logoutRight: um.right,
            };
        }"""
    )
    assert m["scrollW"] <= m["innerW"] + 1, (
        f"overflow horizontal em {url} @{width}px: "
        f"scrollWidth={m['scrollW']} > innerWidth={m['innerW']}"
    )
    assert m["logoutRight"] <= m["innerW"] + 1, (
        f"'Terminar sessão' fora do ecrã em {url} @{width}px: "
        f"right={m['logoutRight']} > innerWidth={m['innerW']}"
    )
