"""
E2E — acessibilidade automática (axe-core sobre cada página, nos DOIS temas).

O axe-core deteta uma fração das questões WCAG (~30-50%), mas as que deteta são
fiáveis. Falhamos em qualquer violação de impacto **serious/critical** — incluindo
contraste, agora que os tokens de texto cumprem AA nos dois temas.

Notas:
  * testamos tema claro E escuro (`emulate_media`), porque o ForensiQ alterna via
    prefers-color-scheme e o contraste difere entre eles;
  * o axe injeta-se via page.evaluate one-shot (Runtime.evaluate), que a CSP
    estrita NÃO bloqueia (ao contrário do new Function do polling).
"""

import pytest
from axe_playwright_python.sync_playwright import Axe

from .pages import app_pages

pytestmark = pytest.mark.e2e

_axe = Axe()
_BLOCKING = ("serious", "critical")


def _blocking_violations(results):
    """Lista das violações graves/críticas, com detalhe do nó para depuração."""
    out = []
    for v in results.response["violations"]:
        if v.get("impact") not in _BLOCKING:
            continue
        for node in v["nodes"]:
            data = (node.get("any") or [{}])[0].get("data") or {}
            out.append(
                f"{v['id']} @ {node.get('target')}"
                + (
                    f" (fg={data.get('fgColor')} bg={data.get('bgColor')}"
                    f" ratio={data.get('contrastRatio')})"
                    if data.get("contrastRatio")
                    else ""
                )
            )
    return out


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_authenticated_pages_have_no_serious_a11y_violations(page, seed, auth_as, scheme):
    page.emulate_media(color_scheme=scheme)
    auth_as(seed["expert"])
    occ_id = seed["occ"].id
    ev_id = seed["ev"].id
    # Lista canonica unica (pages.app_pages - auditoria D114): o axe passa a
    # varrer TODAS as rotas (intake e verificacoes entram; eram drift).
    pages = {name: spec['path'] for name, spec in app_pages(occ_id, ev_id).items()}
    problems = {}
    for name, path in pages.items():
        page.goto(path, wait_until="load")
        results = _axe.run(page)
        blocking = _blocking_violations(results)
        if blocking:
            problems[f"{name} [{scheme}]"] = blocking

    assert not problems, "Violações graves de acessibilidade:\n" + "\n".join(
        f"  {name}: {viols}" for name, viols in problems.items()
    )


def test_login_page_has_no_serious_a11y_violations(page, live_server):
    # O login escolhe o tema pela hora local (não por prefers-color-scheme),
    # por isso testa-se uma vez no tema vigente.
    page.goto("/login/", wait_until="load")
    results = _axe.run(page)
    assert not _blocking_violations(results), _blocking_violations(results)
