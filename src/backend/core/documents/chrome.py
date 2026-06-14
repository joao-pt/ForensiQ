"""
ForensiQ — Cromo de página dos documentos PDF (identidade de DOCUMENTO).

A guia de transporte tem identidade própria — sóbria, monocromática, de
formulário oficial — distinta da interface da aplicação. Esta casca dá só o
essencial repetido em cada página: um rodapé fino (referência do documento +
paginação). O cabeçalho/masthead (tipo de documento + QR) é um bloco do corpo,
desenhado uma vez na 1.ª página (ver ``builder.DocumentBuilder.masthead``).
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm

# ---------------------------------------------------------------------------
# Paleta MONOCROMÁTICA (sem cor de marca — a identidade é a de um documento)
# ---------------------------------------------------------------------------
INK = colors.HexColor('#1A1A1A')  # texto principal
GREY_DARK = colors.HexColor('#5A5A5A')  # rótulos / texto secundário
RULE = colors.HexColor('#C8CCD0')  # réguas finas
ROW_FAINT = colors.HexColor('#F4F5F6')  # listras de tabela (subtis)
WHITE = colors.white

# Equivalentes em hex (string) para tags ``<font color=...>`` dentro de Paragraph.
INK_HEX = '#1A1A1A'
GREY_DARK_HEX = '#5A5A5A'

# Geometria — margens apertadas para densidade; rodapé fino.
MARGIN = 1.6 * cm
FOOTER_H = 1.1 * cm


def draw_page_chrome(canvas, doc):
    """Rodapé fino em cada página: referência do documento + paginação. Sem
    cabeçalho de marca (o masthead vive no corpo, só na 1.ª página)."""
    page_w, _ = doc.pagesize
    left = doc.leftMargin
    right_edge = page_w - doc.rightMargin

    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(left, FOOTER_H + 0.22 * cm, right_edge, FOOTER_H + 0.22 * cm)

    canvas.setFillColor(GREY_DARK)
    canvas.setFont('Helvetica', 6.5)
    ref = getattr(doc, 'fq_footer_ref', '')
    left_txt = 'Guia de transporte' + (f' · {ref}' if ref else '') + ' · forensiq.pt'
    canvas.drawString(left, FOOTER_H - 0.05 * cm, left_txt)
    canvas.drawRightString(right_edge, FOOTER_H - 0.05 * cm, f'Página {doc.page}')
    canvas.restoreState()
