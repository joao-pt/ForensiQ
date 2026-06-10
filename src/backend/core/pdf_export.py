"""
ForensiQ — Exportação de relatórios forenses em PDF.

Dois geradores:

- ``generate_evidence_pdf(evidence)`` — **relatório por item de prova**.
  Descreve o item-raiz (ou sub-componente) e os seus componentes integrantes
  (SIM, cartões de memória, etc.). Acompanha a cadeia de custódia desse item.
  ISO/IEC 27037: um SIM dentro de um telemóvel viaja com o dispositivo-pai;
  o relatório reflete essa inseparabilidade listando os componentes debaixo
  do item principal, com o seu próprio hash de integridade.

- ``generate_occurrence_pdf(occurrence)`` — **relatório do processo inteiro**.
  Resumo do caso + lista de todos os itens de prova (raiz e filhos) com o
  estado actual de custódia. Usado pelo agente responsável pelo caso para
  um overview único.

Conformidade: ISO/IEC 27037:2012 — preservação e integridade de prova digital.
"""

import html as _html
from datetime import UTC, datetime
from io import BytesIO

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.labels import LEGAL_STATE_LABELS
from core.utils import get_user_display_name, legal_state_of, sort_custody_chain

# ---------------------------------------------------------------------------
# Sanitização — proteção contra injecção em Paragraph
# ---------------------------------------------------------------------------


def _sanitize(text):
    """Escapa HTML e limpa controlos. ReportLab Paragraph interpreta mini-HTML."""
    if not text:
        return ''
    text = _html.escape(str(text))
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\t')
    return text


# ---------------------------------------------------------------------------
# QR codes (ADR-0012 Vaga 1)
# ---------------------------------------------------------------------------


def _build_verify_url(occurrence):
    """URL pública adaptativa de verificação para uma ocorrência.

    Composição: `settings.SITE_URL` + `/v/<short_hash>/`. O short_hash
    é derivado por HMAC do `occurrence.id` (não-enumerável).
    """
    from core.qr_verify import short_hash_for

    base = getattr(settings, 'SITE_URL', 'https://forensiq.pt').rstrip('/')
    return f'{base}/v/{short_hash_for(occurrence.id)}/'


def _qr_flowable(url, size_cm=3.0):
    """Devolve um `Image` Flowable do ReportLab com o QR da URL.

    Bordas mínimas (`border=1`), error correction médio (`M` — 15 %)
    para resistir a desgaste de impressão. PNG embebido em memória.
    """
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,  # auto-fit
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return Image(buf, width=size_cm * cm, height=size_cm * cm)


# ---------------------------------------------------------------------------
# Paleta (alinhada ao design system do frontend — logo usa teal/navy)
# ---------------------------------------------------------------------------
NAVY = colors.HexColor('#0F1115')  # preto-azulado da marca
BRAND_TEAL = colors.HexColor('#2DD4BF')  # teal do anel
BRAND_LIGHT = colors.HexColor('#E6E8EC')  # cinzento-claro do anel oposto
ACCENT_BLUE = colors.HexColor('#1565c0')  # cabeçalhos de tabela
GREEN_OK = colors.HexColor('#0F766E')  # verde-forense para OK
GREY_LIGHT = colors.HexColor('#F5F5F5')
GREY_MED = colors.HexColor('#E0E0E0')
GREY_DARK = colors.HexColor('#6B7280')
WHITE = colors.white
BLACK = colors.black

# Margens e geometria do cabeçalho/rodapé (em pontos — 1 cm ≈ 28.35 pt)
HEADER_HEIGHT = 2.2 * cm  # área reservada para logo + rule
FOOTER_HEIGHT = 1.2 * cm  # rodapé com página X / total
LOGO_BOX_SIZE = 0.9 * cm  # diâmetro do círculo exterior do logo


# ---------------------------------------------------------------------------
# Estilos tipográficos (partilhados pelos dois geradores)
# ---------------------------------------------------------------------------


def _build_styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'FQTitle',
            parent=base['Title'],
            fontSize=16,
            textColor=NAVY,
            spaceAfter=2,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
        ),
        'subtitle': ParagraphStyle(
            'FQSubtitle',
            parent=base['Normal'],
            fontSize=9,
            textColor=GREY_DARK,
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        'doc_title': ParagraphStyle(
            'FQDocTitle',
            parent=base['Normal'],
            fontSize=13,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=2,
            fontName='Helvetica-Bold',
        ),
        'doc_meta': ParagraphStyle(
            'FQDocMeta',
            parent=base['Normal'],
            fontSize=9,
            textColor=GREY_DARK,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        'section': ParagraphStyle(
            'FQSection',
            parent=base['Heading2'],
            fontSize=11,
            textColor=WHITE,
            backColor=NAVY,
            spaceBefore=10,
            spaceAfter=4,
            leftIndent=-6,
            rightIndent=-6,
            borderPad=5,
            fontName='Helvetica-Bold',
        ),
        'subsection': ParagraphStyle(
            'FQSubSection',
            parent=base['Heading3'],
            fontSize=10.5,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=3,
            fontName='Helvetica-Bold',
        ),
        'label': ParagraphStyle(
            'FQLabel',
            parent=base['Normal'],
            fontSize=8,
            textColor=GREY_DARK,
            spaceAfter=1,
            fontName='Helvetica-Bold',
        ),
        'value': ParagraphStyle(
            'FQValue',
            parent=base['Normal'],
            fontSize=10,
            textColor=BLACK,
            spaceAfter=4,
        ),
        'hash': ParagraphStyle(
            'FQHash',
            parent=base['Code'],
            fontSize=7,
            textColor=GREEN_OK,
            fontName='Courier',
            spaceAfter=4,
            leftIndent=4,
        ),
        'footer': ParagraphStyle(
            'FQFooter',
            parent=base['Normal'],
            fontSize=7,
            textColor=GREY_DARK,
            alignment=TA_CENTER,
        ),
        'integrity_ok': ParagraphStyle(
            'FQIntegrity',
            parent=base['Normal'],
            fontSize=10,
            textColor=GREEN_OK,
            alignment=TA_CENTER,
            spaceAfter=4,
            fontName='Helvetica-Bold',
        ),
        'disclaimer': ParagraphStyle(
            'FQDisclaimer',
            parent=base['Normal'],
            fontSize=8,
            alignment=TA_LEFT,
            spaceAfter=4,
            textColor=GREY_DARK,
        ),
    }


# ---------------------------------------------------------------------------
# Logo + cabeçalho e rodapé — aplicado a todas as páginas
# ---------------------------------------------------------------------------


def _draw_logo(canvas, x, y, size=LOGO_BOX_SIZE):
    """Desenha a marca (círculos entrelaçados) sobre o canvas.

    x, y = canto inferior-esquerdo do bounding box.
    Mantém a paleta do logo SVG (NAVY + teal + cinza-claro).
    """
    canvas.saveState()
    # Fundo circular (preto-azulado)
    canvas.setFillColor(NAVY)
    canvas.setStrokeColor(NAVY)
    canvas.circle(x + size / 2, y + size / 2, size / 2, stroke=0, fill=1)

    # Anéis entrelaçados — aproximação da marca ForensiQ
    r = size * 0.28
    cx_left = x + size * 0.38
    cx_right = x + size * 0.62
    cy = y + size / 2
    canvas.setLineWidth(size * 0.05)

    canvas.setStrokeColor(BRAND_TEAL)
    canvas.circle(cx_left, cy, r, stroke=1, fill=0)
    canvas.setStrokeColor(BRAND_LIGHT)
    canvas.circle(cx_right, cy, r, stroke=1, fill=0)
    canvas.restoreState()


def _draw_page_chrome(canvas, doc):
    """Cabeçalho (logo + wordmark) e rodapé (paginação) em cada página."""
    page_w, page_h = doc.pagesize
    top = page_h - 1.2 * cm
    left = doc.leftMargin
    right_edge = page_w - doc.rightMargin

    # ------- Cabeçalho -------
    _draw_logo(canvas, left, top - LOGO_BOX_SIZE + 0.1 * cm, size=LOGO_BOX_SIZE)

    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.setFont('Helvetica-Bold', 12)
    canvas.drawString(left + LOGO_BOX_SIZE + 0.25 * cm, top - 0.3 * cm, 'ForensiQ')
    canvas.setFillColor(GREY_DARK)
    canvas.setFont('Helvetica', 7)
    canvas.drawString(
        left + LOGO_BOX_SIZE + 0.25 * cm,
        top - 0.6 * cm,
        'Plataforma de Prova Digital · ISO/IEC 27037',
    )
    # Subject no canto direito (populated by doc meta)
    subject = getattr(doc, 'fq_header_subject', '')
    if subject:
        canvas.setFillColor(NAVY)
        canvas.setFont('Helvetica-Bold', 9)
        canvas.drawRightString(right_edge, top - 0.3 * cm, subject)
        generated = getattr(doc, 'fq_header_generated', '')
        if generated:
            canvas.setFillColor(GREY_DARK)
            canvas.setFont('Helvetica', 7)
            canvas.drawRightString(right_edge, top - 0.6 * cm, generated)

    # Rule abaixo do cabeçalho
    canvas.setStrokeColor(BRAND_TEAL)
    canvas.setLineWidth(1.2)
    rule_y = top - LOGO_BOX_SIZE - 0.05 * cm
    canvas.line(left, rule_y, right_edge, rule_y)
    canvas.restoreState()

    # ------- Rodapé -------
    canvas.saveState()
    canvas.setStrokeColor(GREY_MED)
    canvas.setLineWidth(0.3)
    canvas.line(left, FOOTER_HEIGHT + 0.3 * cm, right_edge, FOOTER_HEIGHT + 0.3 * cm)

    canvas.setFillColor(GREY_DARK)
    canvas.setFont('Helvetica', 7)
    canvas.drawString(
        left,
        FOOTER_HEIGHT - 0.05 * cm,
        'ForensiQ · UC 21184 Universidade Aberta · Gerado automaticamente',
    )
    canvas.drawRightString(
        right_edge,
        FOOTER_HEIGHT - 0.05 * cm,
        f'Página {doc.page}',
    )
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_datetime(dt):
    if dt is None:
        return '—'
    if hasattr(dt, 'strftime'):
        return dt.strftime('%d/%m/%Y %H:%M:%S UTC')
    return str(dt)


def _fmt_gps(lat, lng):
    """Formata um par GPS com hemisfério correcto (N/S, E/W).

    Portugal continental tem longitude W; imprimir sempre °E (bug
    pré-existente assinalado no ADR-0013) dava a coordenada errada.
    """
    if lat is None or lng is None:
        return 'Não disponível'
    lat_f, lng_f = float(lat), float(lng)
    ns = 'N' if lat_f >= 0 else 'S'
    ew = 'E' if lng_f >= 0 else 'W'
    return f'{abs(lat_f):.6f}°{ns}, {abs(lng_f):.6f}°{ew}'


def _fmt_agent(user):
    return _sanitize(get_user_display_name(user))


def _label_value_rows(pairs, styles, col_widths=(5 * cm, 12 * cm)):
    """Tabela duas colunas (rótulo | valor)."""
    data = []
    for label, value in pairs:
        data.append(
            [
                Paragraph(label, styles['label']),
                Paragraph(str(value) if value else '—', styles['value']),
            ]
        )
    t = Table(data, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (0, -1), GREY_LIGHT),
                ('GRID', (0, 0), (-1, -1), 0.5, GREY_MED),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )
    return [t, Spacer(1, 0.3 * cm)]


def _custody_table(custody_records, styles):
    """Tabela do ledger de eventos da custódia. Devolve lista de flowables."""
    if not custody_records:
        return [
            Paragraph(
                'Nenhum registo de cadeia de custódia.',
                styles['value'],
            ),
            Spacer(1, 0.3 * cm),
        ]

    table_data = [
        [
            Paragraph('#', styles['label']),
            Paragraph('Evento', styles['label']),
            Paragraph('Custódio', styles['label']),
            Paragraph('Local', styles['label']),
            Paragraph('Data/Hora', styles['label']),
            Paragraph('Agente', styles['label']),
        ]
    ]
    for idx, rec in enumerate(custody_records, start=1):
        evento = _sanitize(rec.get_event_type_display()) if rec.event_type else '—'
        custodio = _sanitize(rec.get_custodian_type_display()) if rec.custodian_type else '—'
        local_parts = [
            p for p in (rec.location_name, rec.storage_location) if p
        ]
        local = _sanitize(' · '.join(local_parts)) if local_parts else '—'
        table_data.append(
            [
                Paragraph(str(idx), styles['value']),
                Paragraph(evento, styles['value']),
                Paragraph(custodio, styles['value']),
                Paragraph(local, styles['label']),
                Paragraph(_fmt_datetime(rec.timestamp), styles['label']),
                Paragraph(_fmt_agent(rec.agent), styles['value']),
            ]
        )

    col_w = [0.7 * cm, 3.6 * cm, 3.0 * cm, 3.5 * cm, 3.2 * cm, 2.8 * cm]
    t = Table(table_data, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), ACCENT_BLUE),
                ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GREY_LIGHT]),
                ('GRID', (0, 0), (-1, -1), 0.5, GREY_MED),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
            ]
        )
    )
    flow = [t, Spacer(1, 0.4 * cm)]

    last = custody_records[-1]
    flow.append(Paragraph('Hash do último registo de custódia:', styles['label']))
    flow.append(Paragraph(last.record_hash or '—', styles['hash']))
    return flow


def _integrity_declaration(styles, gen_ts):
    """Rodapé de integridade partilhado pelos dois PDFs."""
    return [
        HRFlowable(width='100%', thickness=1, color=NAVY, spaceBefore=16, spaceAfter=8),
        Paragraph('DECLARAÇÃO DE INTEGRIDADE', styles['integrity_ok']),
        Paragraph(
            'Este relatório foi gerado automaticamente pela plataforma ForensiQ. '
            'Os metadados de cada item de prova são imutáveis desde o momento '
            'do registo (ISO/IEC 27037:2012). Os hashes SHA-256 acima permitem '
            'verificar a autenticidade dos metadados e da cadeia de custódia '
            'por qualquer perito independente.',
            styles['disclaimer'],
        ),
        Paragraph(
            f'ForensiQ · UC 21184 — Universidade Aberta · {gen_ts}',
            styles['footer'],
        ),
    ]


def _doc_header(story, styles, doc_title_html, subtitle_html):
    """Bloco de título do documento (logo já está no canvas — chrome).

    Apenas produz o título grande + metadata (ex.: "Item ITM-2026-00001 ·
    caso NUIPC ...") debaixo do cabeçalho permanente.
    """
    story.append(Paragraph(doc_title_html, styles['doc_title']))
    if subtitle_html:
        story.append(Paragraph(subtitle_html, styles['doc_meta']))
    story.append(HRFlowable(width='100%', thickness=0.5, color=GREY_MED, spaceAfter=8))


def _qr_verify_band(occurrence, styles):
    """Banda compacta com QR + instrução de scan (ADR-0012 Vaga 1).

    Layout: Table 2 cols [texto explicativo à esquerda | QR 2.8cm à
    direita]. O QR aponta para `/v/<short_hash>/` (vista pública
    adaptativa). Inserir após `_doc_header` em ambos os geradores.
    """
    url = _build_verify_url(occurrence)
    qr_img = _qr_flowable(url, size_cm=2.8)
    info_text = (
        '<b>Verificar talão de transporte</b><br/>'
        'Lê o QR com a câmara do telemóvel para confirmar a '
        'autenticidade. Com login, abre a vista completa da ocorrência; '
        'sem login, mostra o inventário público de integridade.'
    )
    info_para = Paragraph(info_text, styles['disclaimer'])
    tbl = Table([[info_para, qr_img]], colWidths=(12 * cm, 3 * cm))
    tbl.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('BACKGROUND', (0, 0), (-1, -1), GREY_LIGHT),
                ('BOX', (0, 0), (-1, -1), 0.5, GREY_MED),
            ]
        )
    )
    return [KeepTogether([tbl, Spacer(1, 0.3 * cm)])]


# ---------------------------------------------------------------------------
# PDF por item de prova
# ---------------------------------------------------------------------------


def _render_item_identification(evidence, styles):
    """Bloco de identificação do item principal. Devolve flowables."""
    flow = []
    flow.append(Paragraph('2. Identificação do Item de Prova', styles['section']))
    flow.append(Spacer(1, 0.2 * cm))

    rows = [
        ('Código:', evidence.code or f'#{evidence.pk}'),
        ('Tipo:', _sanitize(evidence.get_type_display())),
        ('Nº de série:', _sanitize(evidence.serial_number) or '—'),
        ('Data / Hora de apreensão:', _fmt_datetime(evidence.timestamp_seizure)),
        ('Localização GPS:', _fmt_gps(evidence.gps_lat, evidence.gps_lng)),
        ('Agente que apreendeu:', _fmt_agent(evidence.agent)),
        ('Descrição:', _sanitize(evidence.description)),
    ]
    if evidence.parent_evidence_id:
        parent = evidence.parent_evidence
        parent_label = (
            f'{parent.code or f"#{parent.pk}"} — ' f'{_sanitize(parent.get_type_display())}'
        )
        rows.insert(
            0,
            (
                'Parte integrante de:',
                parent_label,
            ),
        )
    flow.extend(_label_value_rows(rows, styles))

    flow.append(
        Paragraph(
            'Hash de integridade SHA-256 (ISO/IEC 27037):',
            styles['label'],
        )
    )
    flow.append(
        Paragraph(
            evidence.integrity_hash or '(não calculado)',
            styles['hash'],
        )
    )
    flow.append(Spacer(1, 0.3 * cm))
    return flow


def _render_sub_components(evidence, styles):
    """Sub-componentes integrantes (Evidence.sub_components).

    ISO/IEC 27037: o SIM/SD inserido num telemóvel acompanha o dispositivo
    e deve constar do mesmo relatório; a secção documenta essa inseparabilidade.
    """
    # `all()` reaproveita o prefetch_related aplicado pelas views (N12).
    # Ordenação por id em memória — lista curta.
    sub_components = sorted(evidence.sub_components.all(), key=lambda e: e.id)

    if not sub_components:
        return []

    flow = []
    flow.append(
        Paragraph(
            '3. Componentes Integrantes',
            styles['section'],
        )
    )
    flow.append(Spacer(1, 0.1 * cm))
    flow.append(
        Paragraph(
            'Itens que acompanham fisicamente o dispositivo principal '
            '(ISO/IEC 27037 — inseparabilidade). Cada componente mantém '
            'um hash próprio para verificação independente.',
            styles['disclaimer'],
        )
    )
    flow.append(Spacer(1, 0.2 * cm))

    # Sub-componentes Evidence
    for i, sub in enumerate(sub_components, start=1):
        sub_label = sub.code or f'#{sub.pk}'
        block = [
            Paragraph(
                f'3.{i}. {_sanitize(sub.get_type_display())} ({sub_label})',
                styles['subsection'],
            ),
        ]
        block.extend(
            _label_value_rows(
                [
                    ('Nº de série:', _sanitize(sub.serial_number) or '—'),
                    ('Data / Hora de apreensão:', _fmt_datetime(sub.timestamp_seizure)),
                    ('Descrição:', _sanitize(sub.description)),
                    ('Agente:', _fmt_agent(sub.agent)),
                ],
                styles,
                col_widths=(4 * cm, 13 * cm),
            )
        )
        block.append(Paragraph('Hash SHA-256:', styles['label']))
        block.append(Paragraph(sub.integrity_hash or '—', styles['hash']))
        flow.append(KeepTogether(block))

    return flow


def generate_evidence_pdf(evidence):
    """Gera o PDF de um item de prova (com sub-componentes e cadeia de custódia).

    Args:
        evidence: instância Evidence (com select_related/prefetch_related
                  recomendados na view chamadora).

    Returns:
        bytes — PDF pronto a servir como ``application/pdf``.
    """
    buffer = BytesIO()
    item_label = evidence.code or f'#{evidence.pk}'
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=HEADER_HEIGHT + 0.6 * cm,
        bottomMargin=FOOTER_HEIGHT + 0.4 * cm,
        title=f'ForensiQ — Item {item_label}',
        author='ForensiQ Platform',
        subject='Relatório Forense — ISO/IEC 27037',
    )

    styles = _build_styles()
    story = []
    gen_ts = datetime.now(UTC).strftime('%d/%m/%Y %H:%M:%S UTC')

    # Metadata exposta ao chrome (cabeçalho)
    doc.fq_header_subject = f'Cadeia de Custódia · {item_label}'
    doc.fq_header_generated = f'Gerado em {gen_ts}'

    occ = evidence.occurrence
    occ_label = occ.number or occ.code or f'#{occ.pk}'
    _doc_header(
        story,
        styles,
        f'Cadeia de Custódia — Item {item_label}',
        f'Caso {_sanitize(occ_label)} · {_sanitize(evidence.get_type_display())}',
    )

    # Banda de verificação (QR) — ADR-0012. Aponta para a ocorrência pai
    # (a vista pública agrega o caso inteiro, não só o item isolado).
    story += _qr_verify_band(occ, styles)

    # 1. Ocorrência
    story.append(Paragraph('1. Ocorrência', styles['section']))
    story.append(Spacer(1, 0.2 * cm))
    story += _label_value_rows(
        [
            ('NUIPC / Número:', occ.number or '—'),
            ('Código interno:', occ.code or '—'),
            ('Data / Hora:', _fmt_datetime(occ.date_time)),
            ('Localização GPS:', _fmt_gps(occ.gps_lat, occ.gps_lng)),
            ('Morada aproximada:', _sanitize(occ.address) or '—'),
            ('Agente responsável:', _fmt_agent(occ.agent)),
            ('Descrição:', _sanitize(occ.description)),
        ],
        styles,
    )

    # 2. Identificação do item
    story += _render_item_identification(evidence, styles)

    # 3. Componentes integrantes (sub_components)
    sub_flow = _render_sub_components(evidence, styles)
    story += sub_flow
    has_sub_section = bool(sub_flow)

    # 4. Cadeia de custódia
    section_num = 4 if has_sub_section else 3
    story.append(
        Paragraph(
            f'{section_num}. Cadeia de Custódia',
            styles['section'],
        )
    )
    story.append(Spacer(1, 0.2 * cm))
    # `all()` reaproveita o prefetch_related aplicado pela view (N12).
    # Ordenação ascendente em memória (o prefetch é -sequence; aqui
    # precisamos da ordem cronológica natural).
    custody_records = sort_custody_chain(evidence.custody_chain.all())
    story += _custody_table(custody_records, styles)

    # Declaração
    story += _integrity_declaration(styles, gen_ts)

    try:
        doc.build(story, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
        pdf_bytes = buffer.getvalue()
    finally:
        # Garantir close() do BytesIO mesmo se `doc.build` levantar
        # (audit 2026-05-18 §3 N14). `BytesIO.close()` é idempotente.
        buffer.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# PDF consolidado por ocorrência
# ---------------------------------------------------------------------------


def _current_custody_state(evidence):
    """Devolve (label sanitizado do estado legal derivado, último record).

    O estado legal é DERIVADO da sequência de eventos (ADR-0015), não uma
    coluna — o micro-fluxo materializar→ordenar→derivar vive na fonte única
    :func:`core.utils.legal_state_of` (prefetch-friendly). O label é sanitizado
    à partida porque vai sempre alimentar ``Paragraph()`` no PDF (auditoria
    2026-05-18 §3 N3).
    """
    estado, last = legal_state_of(evidence, with_last=True)
    if last is None:
        return ('—', None)
    return (_sanitize(LEGAL_STATE_LABELS.get(estado, estado)), last)


def generate_occurrence_pdf(occurrence):
    """Relatório consolidado da ocorrência.

    Contém descrição do caso, lista de todos os itens de prova (agrupados
    por raiz + sub-componentes) e o estado actual da cadeia de custódia
    de cada um.
    """
    buffer = BytesIO()
    occ_label = occurrence.number or occurrence.code or f'#{occurrence.pk}'
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=HEADER_HEIGHT + 0.6 * cm,
        bottomMargin=FOOTER_HEIGHT + 0.4 * cm,
        title=f'ForensiQ — Caso {occ_label}',
        author='ForensiQ Platform',
        subject='Resumo do processo — ISO/IEC 27037',
    )

    styles = _build_styles()
    story = []
    gen_ts = datetime.now(UTC).strftime('%d/%m/%Y %H:%M:%S UTC')

    doc.fq_header_subject = f'Resumo do Processo · Caso {occ_label}'
    doc.fq_header_generated = f'Gerado em {gen_ts}'

    _doc_header(
        story,
        styles,
        f'Resumo do Processo — Caso {_sanitize(occ_label)}',
        f'Código interno: {_sanitize(occurrence.code or "—")}',
    )

    # Banda de verificação (QR) — ADR-0012.
    story += _qr_verify_band(occurrence, styles)

    # 1. Descrição do caso
    story.append(Paragraph('1. Descrição do Caso', styles['section']))
    story.append(Spacer(1, 0.2 * cm))
    story += _label_value_rows(
        [
            ('NUIPC / Número:', occurrence.number or '—'),
            ('Código interno:', occurrence.code or '—'),
            ('Data / Hora:', _fmt_datetime(occurrence.date_time)),
            ('Localização GPS:', _fmt_gps(occurrence.gps_lat, occurrence.gps_lng)),
            ('Morada aproximada:', _sanitize(occurrence.address) or '—'),
            ('Agente responsável:', _fmt_agent(occurrence.agent)),
            ('Descrição:', _sanitize(occurrence.description)),
        ],
        styles,
    )

    # 2. Inventário de itens — `all()` reaproveita o prefetch_related
    # aplicado pela view (N12). Sort em memória (lista curta).
    evidences = sorted(occurrence.evidences.all(), key=lambda e: e.id)
    root_items = [e for e in evidences if e.parent_evidence_id is None]
    children_by_parent = {}
    for e in evidences:
        if e.parent_evidence_id:
            children_by_parent.setdefault(e.parent_evidence_id, []).append(e)

    story.append(
        Paragraph(
            f'2. Inventário de Itens de Prova ({len(evidences)})',
            styles['section'],
        )
    )
    story.append(Spacer(1, 0.2 * cm))

    if not evidences:
        story.append(
            Paragraph(
                'Nenhum item de prova registado neste caso.',
                styles['value'],
            )
        )
        story.append(Spacer(1, 0.3 * cm))
    else:
        header = [
            [
                Paragraph('#', styles['label']),
                Paragraph('Item', styles['label']),
                Paragraph('Apreensão', styles['label']),
                Paragraph('Estado actual', styles['label']),
                Paragraph('Hash', styles['label']),
            ]
        ]
        rows = list(header)
        for idx, item in enumerate(root_items, start=1):
            state_label, _ = _current_custody_state(item)
            item_label = item.code or f'#{item.pk}'
            rows.append(
                [
                    Paragraph(str(idx), styles['value']),
                    Paragraph(
                        f'<b>{item_label} · {_sanitize(item.get_type_display())}</b><br/>'
                        f'{_sanitize(item.description)[:90]}',
                        styles['value'],
                    ),
                    Paragraph(_fmt_datetime(item.timestamp_seizure), styles['label']),
                    Paragraph(state_label, styles['value']),
                    Paragraph((item.integrity_hash or '')[:16] + '…', styles['hash']),
                ]
            )
            for sub in children_by_parent.get(item.pk, []):
                sub_state, _ = _current_custody_state(sub)
                sub_label = sub.code or f'#{sub.pk}'
                rows.append(
                    [
                        Paragraph('', styles['label']),
                        Paragraph(
                            f'<i>↳ {sub_label} · {_sanitize(sub.get_type_display())}</i><br/>'
                            f'{_sanitize(sub.description)[:90]}',
                            styles['value'],
                        ),
                        Paragraph(_fmt_datetime(sub.timestamp_seizure), styles['label']),
                        Paragraph(sub_state, styles['value']),
                        Paragraph((sub.integrity_hash or '')[:16] + '…', styles['hash']),
                    ]
                )

        col_w = [0.8 * cm, 7.2 * cm, 3.5 * cm, 2.8 * cm, 2.5 * cm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ('BACKGROUND', (0, 0), (-1, 0), ACCENT_BLUE),
                    ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GREY_LIGHT]),
                    ('GRID', (0, 0), (-1, -1), 0.5, GREY_MED),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 0.4 * cm))

    # 3. Declaração
    story += _integrity_declaration(styles, gen_ts)

    try:
        doc.build(story, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
        pdf_bytes = buffer.getvalue()
    finally:
        # Garantir close() do BytesIO mesmo se `doc.build` levantar
        # (audit 2026-05-18 §3 N14). `BytesIO.close()` é idempotente.
        buffer.close()
    return pdf_bytes
