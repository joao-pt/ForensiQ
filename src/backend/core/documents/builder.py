"""
ForensiQ — Construtor reutilizável de documentos PDF (reportlab).

Fonte ÚNICA para compor qualquer documento da plataforma com identidade de
DOCUMENTO (monocromática, densa, de formulário oficial — distinta da app). O
``DocumentBuilder`` trata do ``SimpleDocTemplate``, dos estilos e do cromo de
página (``core.documents.chrome``) e oferece BLOCOS que se adaptam aos campos:

- ``masthead`` — topo da 1.ª página: tipo de documento (esquerda) + QR pequeno
  (topo-direito) com a hiperligação de verificação por baixo.
- ``section`` — rótulo fino em maiúsculas + régua (sem faixas de cor).
- ``kv_grid`` — pares rótulo/valor condensados, alinhados em N colunas.
- ``data_table`` — tabela leve (cabeçalho a negro sublinhado, listras subtis).

O conteúdo concreto (a guia) limita-se a compor estes blocos. ``Paragraph``
interpreta mini-HTML, por isso todo o texto vindo de dados passa por ``sanitize``
antes de entrar num flowable (defesa contra injeção).
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from io import BytesIO

from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.documents.chrome import (
    FOOTER_H,
    GREY_DARK,
    GREY_DARK_HEX,
    INK,
    MARGIN,
    ROW_FAINT,
    RULE,
    WHITE,
    draw_page_chrome,
)
from core.utils import get_user_display_name

# Carimbo temporal condensado (sem segundos): a guia não precisa de precisão ao
# segundo — privilegia-se a legibilidade.
_TS_FMT = '%d/%m/%Y %H:%M'


# ---------------------------------------------------------------------------
# Sanitização e formatação (partilhadas pelo builder e pelos documentos)
# ---------------------------------------------------------------------------


def sanitize(text):
    """Escapa HTML e limpa controlos. ``Paragraph`` interpreta mini-HTML."""
    if text in (None, ''):
        return ''
    text = _html.escape(str(text))
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\t')
    return text


def fmt_datetime(dt):
    """Data/hora condensada (``—`` se vazio)."""
    if dt is None:
        return '—'
    if hasattr(dt, 'strftime'):
        return dt.strftime(_TS_FMT)
    return str(dt)


def fmt_agent(user):
    """Nome de apresentação de um utilizador, sanitizado para ``Paragraph``."""
    return sanitize(get_user_display_name(user))


# ---------------------------------------------------------------------------
# Estilos tipográficos — Helvetica, pequena, monocromática
# ---------------------------------------------------------------------------


def _build_styles():
    base = getSampleStyleSheet()
    return {
        'mast_title': ParagraphStyle(
            'FQMastTitle', parent=base['Normal'], fontName='Helvetica-Bold',
            fontSize=15, leading=17, textColor=INK, spaceAfter=1,
        ),
        'mast_sub': ParagraphStyle(
            'FQMastSub', parent=base['Normal'], fontSize=7.5, leading=9,
            textColor=GREY_DARK, spaceAfter=1,
        ),
        'mast_issuer': ParagraphStyle(
            'FQMastIssuer', parent=base['Normal'], fontSize=7, leading=9,
            textColor=GREY_DARK,
        ),
        'qr_caption': ParagraphStyle(
            'FQQrCaption', parent=base['Normal'], fontSize=6.2, leading=7.6,
            textColor=GREY_DARK, alignment=TA_RIGHT,
        ),
        'section': ParagraphStyle(
            'FQSection', parent=base['Normal'], fontName='Helvetica-Bold',
            fontSize=8.5, leading=10, textColor=GREY_DARK, spaceBefore=9, spaceAfter=0,
        ),
        'kv': ParagraphStyle(
            'FQKv', parent=base['Normal'], fontSize=8.5, leading=10, textColor=INK,
        ),
        'cell': ParagraphStyle(
            'FQCell', parent=base['Normal'], fontSize=7.5, leading=9.2, textColor=INK,
        ),
        'small': ParagraphStyle(
            'FQSmall', parent=base['Normal'], fontSize=7, leading=9,
            textColor=GREY_DARK, spaceAfter=2,
        ),
        'subitem': ParagraphStyle(
            'FQSubitem', parent=base['Normal'], fontSize=7.5, leading=10,
            textColor=INK, leftIndent=10, spaceAfter=1, alignment=TA_LEFT,
        ),
    }


# TableStyle ÚNICO das tabelas de dados: cabeçalho a negro sublinhado, listras
# subtis, sem grelha pesada nem faixas de cor (auditoria D41).
_DATA_TABLE_STYLE = TableStyle(
    [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('TEXTCOLOR', (0, 0), (-1, -1), INK),
        ('LINEBELOW', (0, 0), (-1, 0), 0.8, INK),
        ('LINEBELOW', (0, 1), (-1, -1), 0.25, RULE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, ROW_FAINT]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
)


def qr_image(url, size_cm=2.0):
    """``Image`` Flowable com o QR de ``url`` (error correction M, border mínima)."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=10, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return Image(buf, width=size_cm * cm, height=size_cm * cm)


class DocumentBuilder:
    """Compositor de um documento PDF monocromático. Métodos-FÁBRICA devolvem
    flowables; ``add()`` acrescenta-os; ``render()`` produz os bytes com o rodapé
    em cada página."""

    def __init__(self, *, title, doc_subject, footer_ref=''):
        self.buffer = BytesIO()
        self.content_w = A4[0] - 2 * MARGIN
        self.doc = SimpleDocTemplate(
            self.buffer,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=FOOTER_H + 0.3 * cm,
            title=title,
            author='ForensiQ',
            subject=doc_subject,
        )
        self.styles = _build_styles()
        self.gen_ts = datetime.now().strftime(_TS_FMT)  # noqa: DTZ005 — rótulo local
        self.doc.fq_footer_ref = footer_ref
        self.story = []

    # -- composição --------------------------------------------------------
    def add(self, *items):
        for item in items:
            if isinstance(item, (list, tuple)):
                self.story.extend(item)
            else:
                self.story.append(item)
        return self

    def paragraph(self, text, style='cell'):
        return Paragraph(text, self.styles[style])

    def spacer(self, h_cm=0.2):
        return Spacer(1, h_cm * cm)

    # -- blocos (fábricas) -------------------------------------------------
    def masthead(self, *, doc_type, subtitle, qr_url, qr_caption):
        """Topo da 1.ª página: tipo de documento (esquerda) + QR pequeno (direita)."""
        left = [
            Paragraph(doc_type, self.styles['mast_title']),
            Paragraph(subtitle, self.styles['mast_sub']),
            Paragraph('emitido por ForensiQ', self.styles['mast_issuer']),
        ]
        right = [qr_image(qr_url, size_cm=2.0), Paragraph(qr_caption, self.styles['qr_caption'])]
        t = Table([[left, right]], colWidths=(self.content_w - 3.2 * cm, 3.2 * cm))
        t.setStyle(
            TableStyle(
                [
                    ('VALIGN', (0, 0), (0, 0), 'TOP'),
                    ('VALIGN', (1, 0), (1, 0), 'TOP'),
                    ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]
            )
        )
        return [t, HRFlowable(width='100%', thickness=1.0, color=INK, spaceBefore=6, spaceAfter=6)]

    def section(self, label):
        """Rótulo de secção fino (maiúsculas) + régua — sem faixa de cor."""
        self.add(
            Paragraph(sanitize(label).upper(), self.styles['section']),
            HRFlowable(width='100%', thickness=0.6, color=RULE, spaceBefore=1, spaceAfter=4),
        )
        return self

    def _kv_cell(self, label, value):
        label = sanitize(label)
        value = sanitize(value)
        if not label and not value:
            return ''
        return Paragraph(
            f'<font size="6" color="{GREY_DARK_HEX}">{label.upper()}</font><br/>{value or "—"}',
            self.styles['kv'],
        )

    def kv_grid(self, pairs, ncols=3):
        """Pares (rótulo, valor) condensados, alinhados em ``ncols`` colunas."""
        cells = [self._kv_cell(label, value) for label, value in pairs]
        while len(cells) % ncols:
            cells.append('')
        rows = [cells[i : i + ncols] for i in range(0, len(cells), ncols)]
        col_w = self.content_w / ncols
        t = Table(rows, colWidths=[col_w] * ncols)
        t.setStyle(
            TableStyle(
                [
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]
            )
        )
        return [t, self.spacer(0.1)]

    def data_table(self, header_labels, rows, col_widths):
        """Tabela leve com cabeçalho a negro sublinhado e cabeçalho repetido."""
        t = Table([list(header_labels), *rows], colWidths=col_widths, repeatRows=1)
        t.setStyle(_DATA_TABLE_STYLE)
        return t

    # -- saída -------------------------------------------------------------
    def render(self) -> bytes:
        """Constrói o PDF com o rodapé e devolve os bytes. Fecha o buffer em
        qualquer caminho (``BytesIO.close()`` é idempotente — defesa contra leak
        de file descriptor mesmo se o ``build`` levantar)."""
        try:
            self.doc.build(
                self.story, onFirstPage=draw_page_chrome, onLaterPages=draw_page_chrome
            )
            return self.buffer.getvalue()
        finally:
            self.buffer.close()
