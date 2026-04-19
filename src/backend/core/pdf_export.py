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

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
# Paleta (alinhada ao design system do frontend — logo usa teal/navy)
# ---------------------------------------------------------------------------
NAVY = colors.HexColor('#0F1115')          # preto-azulado da marca
BRAND_TEAL = colors.HexColor('#2DD4BF')    # teal do anel
BRAND_LIGHT = colors.HexColor('#E6E8EC')   # cinzento-claro do anel oposto
ACCENT_BLUE = colors.HexColor('#1565c0')   # cabeçalhos de tabela
GREEN_OK = colors.HexColor('#0F766E')      # verde-forense para OK
GREY_LIGHT = colors.HexColor('#F5F5F5')
GREY_MED = colors.HexColor('#E0E0E0')
GREY_DARK = colors.HexColor('#6B7280')
WHITE = colors.white
BLACK = colors.black

# Margens e geometria do cabeçalho/rodapé (em pontos — 1 cm ≈ 28.35 pt)
HEADER_HEIGHT = 2.2 * cm    # área reservada para logo + rule
FOOTER_HEIGHT = 1.2 * cm    # rodapé com página X / total
LOGO_BOX_SIZE = 0.9 * cm    # diâmetro do círculo exterior do logo


# ---------------------------------------------------------------------------
# Estilos tipográficos (partilhados pelos dois geradores)
# ---------------------------------------------------------------------------

def _build_styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'FQTitle', parent=base['Title'],
            fontSize=16, textColor=NAVY, spaceAfter=2, alignment=TA_LEFT,
            fontName='Helvetica-Bold',
        ),
        'subtitle': ParagraphStyle(
            'FQSubtitle', parent=base['Normal'],
            fontSize=9, textColor=GREY_DARK, alignment=TA_LEFT, spaceAfter=10,
        ),
        'doc_title': ParagraphStyle(
            'FQDocTitle', parent=base['Normal'],
            fontSize=13, textColor=NAVY, alignment=TA_LEFT, spaceAfter=2,
            fontName='Helvetica-Bold',
        ),
        'doc_meta': ParagraphStyle(
            'FQDocMeta', parent=base['Normal'],
            fontSize=9, textColor=GREY_DARK, alignment=TA_LEFT, spaceAfter=12,
        ),
        'section': ParagraphStyle(
            'FQSection', parent=base['Heading2'],
            fontSize=11, textColor=WHITE, backColor=NAVY,
            spaceBefore=10, spaceAfter=4,
            leftIndent=-6, rightIndent=-6, borderPad=5,
            fontName='Helvetica-Bold',
        ),
        'subsection': ParagraphStyle(
            'FQSubSection', parent=base['Heading3'],
            fontSize=10.5, textColor=NAVY,
            spaceBefore=8, spaceAfter=3,
            fontName='Helvetica-Bold',
        ),
        'label': ParagraphStyle(
            'FQLabel', parent=base['Normal'],
            fontSize=8, textColor=GREY_DARK, spaceAfter=1,
            fontName='Helvetica-Bold',
        ),
        'value': ParagraphStyle(
            'FQValue', parent=base['Normal'],
            fontSize=10, textColor=BLACK, spaceAfter=4,
        ),
        'hash': ParagraphStyle(
            'FQHash', parent=base['Code'],
            fontSize=7, textColor=GREEN_OK, fontName='Courier',
            spaceAfter=4, leftIndent=4,
        ),
        'footer': ParagraphStyle(
            'FQFooter', parent=base['Normal'],
            fontSize=7, textColor=GREY_DARK, alignment=TA_CENTER,
        ),
        'integrity_ok': ParagraphStyle(
            'FQIntegrity', parent=base['Normal'],
            fontSize=10, textColor=GREEN_OK,
            alignment=TA_CENTER, spaceAfter=4, fontName='Helvetica-Bold',
        ),
        'disclaimer': ParagraphStyle(
            'FQDisclaimer', parent=base['Normal'],
            fontSize=8, alignment=TA_LEFT, spaceAfter=4, textColor=GREY_DARK,
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
        left, FOOTER_HEIGHT - 0.05 * cm,
        'ForensiQ · UC 21184 Universidade Aberta · Gerado automaticamente',
    )
    canvas.drawRightString(
        right_edge, FOOTER_HEIGHT - 0.05 * cm,
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


def _fmt_gps(lat, lon):
    if lat is None or lon is None:
        return 'Não disponível'
    return f'{float(lat):.6f}°N, {float(lon):.6f}°E'


def _fmt_agent(user):
    return _sanitize(user.get_full_name() or user.username)


def _label_value_rows(pairs, styles, col_widths=(5 * cm, 12 * cm)):
    """Tabela duas colunas (rótulo | valor)."""
    data = []
    for label, value in pairs:
        data.append([
            Paragraph(label, styles['label']),
            Paragraph(str(value) if value else '—', styles['value']),
        ])
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (0, -1), GREY_LIGHT),
        ('GRID', (0, 0), (-1, -1), 0.5, GREY_MED),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return [t, Spacer(1, 0.3 * cm)]


def _custody_table(custody_records, styles):
    """Tabela de transições. Devolve lista de flowables."""
    if not custody_records:
        return [Paragraph(
            'Nenhum registo de cadeia de custódia.',
            styles['value'],
        ), Spacer(1, 0.3 * cm)]

    table_data = [[
        Paragraph('#', styles['label']),
        Paragraph('Transição', styles['label']),
        Paragraph('Data/Hora', styles['label']),
        Paragraph('Agente', styles['label']),
        Paragraph('Observações', styles['label']),
    ]]
    for idx, rec in enumerate(custody_records, start=1):
        prev = rec.get_previous_state_display() if rec.previous_state else '(início)'
        new = rec.get_new_state_display()
        table_data.append([
            Paragraph(str(idx), styles['value']),
            Paragraph(f'{prev} → {new}', styles['value']),
            Paragraph(_fmt_datetime(rec.timestamp), styles['label']),
            Paragraph(_fmt_agent(rec.agent), styles['value']),
            Paragraph(_sanitize(rec.observations) or '—', styles['label']),
        ])

    col_w = [0.8 * cm, 5.5 * cm, 3.8 * cm, 3.2 * cm, 3.5 * cm]
    t = Table(table_data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
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
    ]))
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
        ('Tipo:', evidence.get_type_display()),
        ('Nº de série:', _sanitize(evidence.serial_number) or '—'),
        ('Data / Hora de apreensão:', _fmt_datetime(evidence.timestamp_seizure)),
        ('Localização GPS:', _fmt_gps(evidence.gps_lat, evidence.gps_lon)),
        ('Agente que apreendeu:', _fmt_agent(evidence.agent)),
        ('Descrição:', _sanitize(evidence.description)),
    ]
    if evidence.parent_evidence_id:
        parent = evidence.parent_evidence
        parent_label = (
            f'{parent.code or f"#{parent.pk}"} — '
            f'{_sanitize(parent.get_type_display())}'
        )
        rows.insert(0, (
            'Parte integrante de:',
            parent_label,
        ))
    flow.extend(_label_value_rows(rows, styles))

    flow.append(Paragraph(
        'Hash de integridade SHA-256 (ISO/IEC 27037):', styles['label'],
    ))
    flow.append(Paragraph(
        evidence.integrity_hash or '(não calculado)', styles['hash'],
    ))
    flow.append(Spacer(1, 0.3 * cm))
    return flow


def _render_sub_components(evidence, styles):
    """Sub-componentes integrantes (Evidence.sub_components) + DigitalDevice legado.

    ISO/IEC 27037: o SIM/SD inserido num telemóvel acompanha o dispositivo
    e deve constar do mesmo relatório; a secção documenta essa inseparabilidade.
    """
    sub_components = list(evidence.sub_components.select_related('agent').order_by('id'))
    legacy_devices = list(evidence.digital_devices.all())

    if not sub_components and not legacy_devices:
        return []

    flow = []
    flow.append(Paragraph(
        '3. Componentes Integrantes',
        styles['section'],
    ))
    flow.append(Spacer(1, 0.1 * cm))
    flow.append(Paragraph(
        'Itens que acompanham fisicamente o dispositivo principal '
        '(ISO/IEC 27037 — inseparabilidade). Cada componente mantém '
        'um hash próprio para verificação independente.',
        styles['disclaimer'],
    ))
    flow.append(Spacer(1, 0.2 * cm))

    # Sub-componentes Evidence
    for i, sub in enumerate(sub_components, start=1):
        sub_label = sub.code or f'#{sub.pk}'
        block = [
            Paragraph(
                f'3.{i}. {sub.get_type_display()} ({sub_label})',
                styles['subsection'],
            ),
        ]
        block.extend(_label_value_rows([
            ('Nº de série:', _sanitize(sub.serial_number) or '—'),
            ('Data / Hora de apreensão:', _fmt_datetime(sub.timestamp_seizure)),
            ('Descrição:', _sanitize(sub.description)),
            ('Agente:', _fmt_agent(sub.agent)),
        ], styles, col_widths=(4 * cm, 13 * cm)))
        block.append(Paragraph('Hash SHA-256:', styles['label']))
        block.append(Paragraph(sub.integrity_hash or '—', styles['hash']))
        flow.append(KeepTogether(block))

    # DigitalDevice legado (mantemos por compatibilidade com registos anteriores
    # à Wave 2a; podem ser consolidados numa migração futura).
    if legacy_devices:
        start = len(sub_components) + 1
        for j, dev in enumerate(legacy_devices, start=start):
            block = [
                Paragraph(
                    f'3.{j}. {dev.get_type_display()} (dispositivo legado)',
                    styles['subsection'],
                ),
            ]
            block.extend(_label_value_rows([
                ('Marca:', _sanitize(dev.brand) or '—'),
                ('Nome comercial:', _sanitize(dev.commercial_name) or '—'),
                ('Modelo (SKU):', _sanitize(dev.model) or '—'),
                ('Estado:', dev.get_condition_display()),
                ('IMEI:', _sanitize(dev.imei) or '—'),
                ('Nº de série:', _sanitize(dev.serial_number) or '—'),
                ('Observações:', _sanitize(dev.notes) or '—'),
            ], styles, col_widths=(4 * cm, 13 * cm)))
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
        leftMargin=2 * cm, rightMargin=2 * cm,
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
        story, styles,
        f'Cadeia de Custódia — Item {item_label}',
        f'Caso {_sanitize(occ_label)} · {_sanitize(evidence.get_type_display())}',
    )

    # 1. Ocorrência
    story.append(Paragraph('1. Ocorrência', styles['section']))
    story.append(Spacer(1, 0.2 * cm))
    story += _label_value_rows([
        ('NUIPC / Número:', occ.number or '—'),
        ('Código interno:', occ.code or '—'),
        ('Data / Hora:', _fmt_datetime(occ.date_time)),
        ('Localização GPS:', _fmt_gps(occ.gps_lat, occ.gps_lon)),
        ('Morada aproximada:', _sanitize(occ.address) or '—'),
        ('Agente responsável:', _fmt_agent(occ.agent)),
        ('Descrição:', _sanitize(occ.description)),
    ], styles)

    # 2. Identificação do item
    story += _render_item_identification(evidence, styles)

    # 3. Componentes integrantes (sub_components + DigitalDevice legado)
    sub_flow = _render_sub_components(evidence, styles)
    story += sub_flow
    has_sub_section = bool(sub_flow)

    # 4. Cadeia de custódia
    section_num = 4 if has_sub_section else 3
    story.append(Paragraph(
        f'{section_num}. Cadeia de Custódia', styles['section'],
    ))
    story.append(Spacer(1, 0.2 * cm))
    custody_records = list(
        evidence.custody_chain.select_related('agent').order_by('sequence')
    )
    story += _custody_table(custody_records, styles)

    # Declaração
    story += _integrity_declaration(styles, gen_ts)

    doc.build(story, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# PDF consolidado por ocorrência
# ---------------------------------------------------------------------------

def _current_custody_state(evidence):
    """Devolve (label, record) do estado actual de custódia. ``None`` se não há."""
    last = evidence.custody_chain.order_by('-sequence').first()
    if last is None:
        return ('—', None)
    return (last.get_new_state_display(), last)


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
        leftMargin=2 * cm, rightMargin=2 * cm,
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
        story, styles,
        f'Resumo do Processo — Caso {_sanitize(occ_label)}',
        f'Código interno: {_sanitize(occurrence.code or "—")}',
    )

    # 1. Descrição do caso
    story.append(Paragraph('1. Descrição do Caso', styles['section']))
    story.append(Spacer(1, 0.2 * cm))
    story += _label_value_rows([
        ('NUIPC / Número:', occurrence.number or '—'),
        ('Código interno:', occurrence.code or '—'),
        ('Data / Hora:', _fmt_datetime(occurrence.date_time)),
        ('Localização GPS:', _fmt_gps(occurrence.gps_lat, occurrence.gps_lon)),
        ('Morada aproximada:', _sanitize(occurrence.address) or '—'),
        ('Agente responsável:', _fmt_agent(occurrence.agent)),
        ('Descrição:', _sanitize(occurrence.description)),
    ], styles)

    # 2. Inventário de itens
    evidences = list(
        occurrence.evidences
        .select_related('agent', 'parent_evidence')
        .prefetch_related('sub_components', 'custody_chain')
        .order_by('id')
    )
    root_items = [e for e in evidences if e.parent_evidence_id is None]
    children_by_parent = {}
    for e in evidences:
        if e.parent_evidence_id:
            children_by_parent.setdefault(e.parent_evidence_id, []).append(e)

    story.append(Paragraph(
        f'2. Inventário de Itens de Prova ({len(evidences)})', styles['section'],
    ))
    story.append(Spacer(1, 0.2 * cm))

    if not evidences:
        story.append(Paragraph(
            'Nenhum item de prova registado neste caso.', styles['value'],
        ))
        story.append(Spacer(1, 0.3 * cm))
    else:
        header = [[
            Paragraph('#', styles['label']),
            Paragraph('Item', styles['label']),
            Paragraph('Apreensão', styles['label']),
            Paragraph('Estado actual', styles['label']),
            Paragraph('Hash', styles['label']),
        ]]
        rows = list(header)
        for idx, item in enumerate(root_items, start=1):
            state_label, _ = _current_custody_state(item)
            item_label = item.code or f'#{item.pk}'
            rows.append([
                Paragraph(str(idx), styles['value']),
                Paragraph(
                    f'<b>{item_label} · {_sanitize(item.get_type_display())}</b><br/>'
                    f'{_sanitize(item.description)[:90]}',
                    styles['value'],
                ),
                Paragraph(_fmt_datetime(item.timestamp_seizure), styles['label']),
                Paragraph(state_label, styles['value']),
                Paragraph((item.integrity_hash or '')[:16] + '…', styles['hash']),
            ])
            for sub in children_by_parent.get(item.pk, []):
                sub_state, _ = _current_custody_state(sub)
                sub_label = sub.code or f'#{sub.pk}'
                rows.append([
                    Paragraph('', styles['label']),
                    Paragraph(
                        f'<i>↳ {sub_label} · {_sanitize(sub.get_type_display())}</i><br/>'
                        f'{_sanitize(sub.description)[:90]}',
                        styles['value'],
                    ),
                    Paragraph(_fmt_datetime(sub.timestamp_seizure), styles['label']),
                    Paragraph(sub_state, styles['value']),
                    Paragraph((sub.integrity_hash or '')[:16] + '…', styles['hash']),
                ])

        col_w = [0.8 * cm, 7.2 * cm, 3.5 * cm, 2.8 * cm, 2.5 * cm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
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
        ]))
        story.append(t)
        story.append(Spacer(1, 0.4 * cm))

    # 3. Dispositivos digitais legados agregados
    legacy = []
    for e in evidences:
        for d in e.digital_devices.all():
            legacy.append((e, d))
    if legacy:
        story.append(Paragraph(
            f'3. Dispositivos Digitais Associados ({len(legacy)})', styles['section'],
        ))
        story.append(Spacer(1, 0.2 * cm))
        for ev_owner, dev in legacy:
            owner_label = ev_owner.code or f'#{ev_owner.pk}'
            # Identidade do dispositivo: prefere "Marca Nome (SKU)";
            # cai para "Marca Modelo" quando não há nome comercial.
            brand = _sanitize(dev.brand) or '—'
            commercial = _sanitize(dev.commercial_name)
            sku = _sanitize(dev.model)
            if commercial and sku:
                identity = f'{brand} {commercial} ({sku})'
            elif commercial:
                identity = f'{brand} {commercial}'
            elif sku:
                identity = f'{brand} {sku}'
            else:
                identity = brand
            story.append(Paragraph(
                f'Item {owner_label} · {dev.get_type_display()} · {identity}',
                styles['value'],
            ))

    # 4. Declaração
    story += _integrity_declaration(styles, gen_ts)

    doc.build(story, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
