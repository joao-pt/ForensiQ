"""
E2E — regressão visual (screenshot + diff de pixels com tolerância).

Apanha mudanças não-intencionais de layout/cor/tipografia (ex.: um ajuste de
token que descalibra um ecrã). Alvo: o formulário de nova ocorrência em tema
claro forçado e SEM dados — determinístico (sem timestamps/códigos gerados).

Limitações (assumidas): a baseline é específica do ambiente de render (este
Chromium/SO). Por isso este teste tem o marcador ``visual`` e é EXCLUÍDO do CI
(`-m "not visual"`); corre localmente. Na 1.ª execução cria a baseline.
"""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageChops

pytestmark = [pytest.mark.e2e, pytest.mark.visual]

_BASELINE_DIR = Path(__file__).parent / "__screenshots__"
_TOLERANCE = 0.01      # até 1% de pixels podem diferir (antialiasing/hinting)
_PIXEL_THRESHOLD = 24  # diferença por canal a partir da qual um pixel "mudou"


def _changed_ratio(baseline_path, current_png):
    base = Image.open(baseline_path).convert("RGB")
    cur = Image.open(io.BytesIO(current_png)).convert("RGB")
    if base.size != cur.size:
        return 1.0
    diff = (
        ImageChops.difference(base, cur)
        .convert("L")
        .point(lambda p: 255 if p > _PIXEL_THRESHOLD else 0)
    )
    changed = diff.histogram()[-1]  # nº de pixels a 255 (mudaram)
    return changed / float(base.width * base.height)


def test_new_occurrence_form_visual(page, auth_as, make_user):
    page.emulate_media(color_scheme="light")  # tema determinístico
    agent = make_user("agent", username="vis.agent", password="Vis123456!")
    auth_as(agent)
    page.goto("/occurrences/new/", wait_until="load")
    page.evaluate("() => document.fonts.ready")  # fontes carregadas antes do shot
    shot = page.locator("article.detail").screenshot(animations="disabled")

    _BASELINE_DIR.mkdir(exist_ok=True)
    baseline = _BASELINE_DIR / "new_occurrence_form_light.png"
    if not baseline.exists():
        baseline.write_bytes(shot)
        pytest.skip("baseline visual criada (1.ª execução) — confirmar e versionar")

    ratio = _changed_ratio(baseline, shot)
    assert ratio < _TOLERANCE, (
        f"regressão visual: {ratio:.2%} de pixels diferentes (tolerância {_TOLERANCE:.0%})"
    )
