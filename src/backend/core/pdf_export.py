"""
ForensiQ — Módulo de exportação de relatório de evidência para PDF.

Gera um relatório forense em PDF para uma evidência, incluindo:
- Informações da ocorrência
- Metadados da evidência (tipo, descrição, GPS, timestamp, hash SHA-256)
- Dispositivos digitais associados
- Cadeia de custódia completa
- Declaração de integridade

Conformidade: ISO/IEC 27037:2012 — preservação e integridade de prova digital.
Implementado com ReportLab (PDF puro, sem dependências externas de browser).
"""

from datetime import datetime, timezone as dt_timezone
from io import BytesIO
import html as _html

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ---------------------------------------------------------------------------
# Sanitização de texto — Proteção contra injeção de HTML/XML
# ---------------------------------------------------------------------------

def _sanitize(text):
    """Remove tags HTML e escapa caracteres especiais para ReportLab."""
    if not text:
        return ''
    text = _html.escape(str(text))
    # Remover caracteres de controlo (manter \n e \t)
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\t')
    return text


# ---------------------------------------------------------------------------
# Paleta de cores ForensiQ (consistente com CSS mobile-first)
# ---------------------------------------------------------------------------
BLUE_DARK = colors.HexColor('#0d47a1')
BLUE_MID = colors.HexColor('#1565c0')
BLUE_LIGHT = colors.HexColor('#e3f2fd')
GREEN_OK = colors.HexColor('#2e7d32')
ORANGE_WARN = colors.HexColor('#e65100')
GREY_LIGHT = colors.HexColor('#f5f5f5')
GREY_MED = colors.HexColor('#e0e0e0')
BLACK = colors.black
WHITE = colors.white


# ---------------------------------------------------------------------------
# Estilos tipográficos
# ---------------------------------------------------------------------------

def _build_styles():
    """Cria e devolve o dicionário de estilos para o relatório."""
    base = getSampleStyleSheet()

    styles = {
        'title': ParagraphStyle(
            'FQTitle',
            parent=base['Title'],
            fontSize=18,
            textColor=BLUE_DARK,
            spaceAfter=4,
            alignment=TA_CENTER,
        ),
        'subtitle': ParagraphStyle(
            'FQSubtitle',
            parent=base['Normal'],
            fontSize=10,
            textColor=colors.grey,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        'section': ParagraphStyle(
            'FQSection',
            parent=base['Heading2'],
            fontSize=12,
            textColor=WHITE,
            backColor=BLUE_DARK,
            spaceBefore=12,
            spaceAfter=6,
            leftIndent=-6,
            rightIndent=-6,
            borderPad=4,
        ),
        'label': ParagraphStyle(
            'FQLabel',
            parent=base['Normal'],
            fontSize=8,
            textColor=colors.grey,
            spaceAfter=1,
        ),
        'value': ParagraphStyle(
            'FQValue',
            parent=base['Normal'],
            fontSize=10,
            textColor=BLACK,
            spaceAfter=6,
        ),
        'hash': ParagraphStyle(
            'FQHash',
            parent=base['Code'],
            fontSize=7,
            textColor=GREEN_OK,
            fontName='Courier',
            spaceAfter=6,
            leftIndent=6,
        ),
        'footer': ParagraphStyle(
            'FQFooter',
            parent=base['Normal'],
            fontSize=7,
            textColor=colors.grey,
            alignment=TA_CENTER,
        ),
        'integrity_ok': ParagraphStyle(
            'FQIntegrity',
            parent=base['Normal'],
            fontSize=9,
            textColor=GREEN_OK,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
    }
    return styles


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def _fmt_datetime(dt):
    """Formata datetime para string legível em PT."""
    if dt is None:
        return '—'
    if hasattr(dt, 'strftime'):
        return dt.strftime('%d/%m/%Y %H:%M:%S UTC')
    return str(dt)


def _fmt_gps(lat, lon):
    """Formata coordenadas GPS."""
    if lat is None or lon is None:
        return 'Não disponível'
    return f'{float(lat):.6f}°N, {float(lon):.6f}°E'


def _label_value_rows(pairs, styles, col_widths=(5 * cm, 12 * cm)):
    """
    Cria uma tabela de duas colunas (Rótulo | Valor) para metadados.
    Retorna uma lista de flowables.
    """
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


# ---------------------------------------------------------------------------
# Construção do PDF
# ---------------------------------------------------------------------------

def generate_evidence_pdf(evidence):
    """
    Gera um relatório forense PDF para uma evidência.

    Args:
        evidence: instância do modelo Evidence (com relações pré-carregadas)

    Returns:
        bytes — conteúdo do PDF gerado

    Conformidade ISO/IEC 27037:
        - Hash SHA-256 dos metadados registado no relatório
        - Timestamp da geração do relatório (UTC)
        - Cadeia de custódia completa incluída
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
        title=f'ForensiQ — Relatório de Evidência #{evidence.pk}',
        author='ForensiQ Platform',
        subject='Relatório Forense Digital — ISO/IEC 27037',
    )

    styles = _build_styles()
    story = []
    gen_ts = datetime.now(dt_timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')

    # ── Cabeçalho ────────────────────────────────────────────────────────────
    story.append(Paragraph('ForensiQ', styles['title']))
    story.append(Paragraph(
        'Plataforma Modular de Gestão de Prova Digital',
        styles['subtitle'],
    ))
    story.append(HRFlowable(
        width='100%', thickness=2, color=BLUE_DARK, spaceAfter=8,
    ))
    story.append(Paragraph(
        f'<b>RELATÓRIO DE EVIDÊNCIA DIGITAL</b>&nbsp;&nbsp;'
        f'Nº {evidence.pk:04d}',
        ParagraphStyle('FQDocTitle', parent=styles['value'],
                       fontSize=13, textColor=BLUE_DARK, spaceAfter=4,
                       alignment=TA_CENTER),
    ))
    story.append(Paragraph(
        f'Gerado em: {gen_ts}',
        styles['subtitle'],
    ))
    story.append(HRFlowable(
        width='100%', thickness=0.5, color=GREY_MED, spaceAfter=12,
    ))

    # ── Ocorrência ───────────────────────────────────────────────────────────
    occ = evidence.occurrence
    story.append(Paragraph('1. Ocorrência', styles['section']))
    story.append(Spacer(1, 0.2 * cm))
    story += _label_value_rows([
        ('Número:', occ.number),
        ('Data / Hora:', _fmt_datetime(occ.date_time)),
        ('Localização GPS:', _fmt_gps(occ.gps_lat, occ.gps_lon)),
        ('Morada aproximada:', _sanitize(occ.address) or '—'),
        ('Agente responsável:', _sanitize(occ.agent.get_full_name() or occ.agent.username)),
        ('Descrição:', _sanitize(occ.description)),
    ], styles)

    # ── Evidência ────────────────────────────────────────────────────────────
    story.append(Paragraph('2. Dados da Evidência', styles['section']))
    story.append(Spacer(1, 0.2 * cm))
    story += _label_value_rows([
        ('ID da evidência:', f'#{evidence.pk}'),
        ('Tipo:', evidence.get_type_display()),
        ('Número de série:', _sanitize(evidence.serial_number) or '—'),
        ('Data / Hora de apreensão:', _fmt_datetime(evidence.timestamp_seizure)),
        ('Localização GPS (apreensão):', _fmt_gps(evidence.gps_lat, evidence.gps_lon)),
        ('Agente que apreendeu:', _sanitize(evidence.agent.get_full_name() or evidence.agent.username)),
        ('Descrição:', _sanitize(evidence.description)),
    ], styles)

    story.append(Paragraph('Hash de Integridade SHA-256 (ISO/IEC 27037):', styles['label']))
    story.append(Paragraph(evidence.integrity_hash or '(não calculado)', styles['hash']))
    story.append(Spacer(1, 0.3 * cm))

    # ── Dispositivos Digitais ────────────────────────────────────────────────
    devices = list(evidence.digital_devices.all())
    if devices:
        story.append(Paragraph('3. Dispositivos Digitais', styles['section']))
        story.append(Spacer(1, 0.2 * cm))
        for i, dev in enumerate(devices, start=1):
            story.append(Paragraph(f'Dispositivo {i}:', styles['label']))
            story += _label_value_rows([
                ('Tipo:', dev.get_type_display()),
                ('Marca / Modelo:', f'{_sanitize(dev.brand) or "—"} / {_sanitize(dev.model) or "—"}'),
                ('Estado:', dev.get_condition_display()),
                ('IMEI:', _sanitize(dev.imei) or '—'),
                ('Número de série:', _sanitize(dev.serial_number) or '—'),
                ('Observações:', _sanitize(dev.notes) or '—'),
            ], styles)
    else:
        story.append(Paragraph('3. Dispositivos Digitais', styles['section']))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph('Nenhum dispositivo digital registado.', styles['value']))
        story.append(Spacer(1, 0.3 * cm))

    # ── Cadeia de Custódia ───────────────────────────────────────────────────
    custody_records = list(
        evidence.custody_chain.select_related('agent').order_by('sequence')
    )
    section_num = 4
    story.append(Paragraph(f'{section_num}. Cadeia de Custódia', styles['section']))
    story.append(Spacer(1, 0.2 * cm))

    if custody_records:
        # Cabeçalho da tabela
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
                Paragraph(
                    _sanitize(rec.agent.get_full_name() or rec.agent.username),
                    styles['value'],
                ),
                Paragraph(_sanitize(rec.observations) or '—', styles['label']),
            ])

        col_w = [0.8 * cm, 5.5 * cm, 3.8 * cm, 3.2 * cm, 3.5 * cm]
        t = Table(table_data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BLUE_MID),
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

        # Hash do último registo
        last = custody_records[-1]
        story.append(Paragraph(
            f'Hash do último registo de custódia:',
            styles['label'],
        ))
        story.append(Paragraph(last.record_hash or '—', styles['hash']))
    else:
        story.append(Paragraph(
            'Nenhum registo de cadeia de custódia encontrado.',
            styles['value'],
        ))
        story.append(Spacer(1, 0.3 * cm))

    # ── Declaração de Integridade ────────────────────────────────────────────
    story.append(HRFlowable(
        width='100%', thickness=1, color=BLUE_DARK, spaceBefore=16, spaceAfter=8,
    ))
    story.append(Paragraph(
        '✓  DECLARAÇÃO DE INTEGRIDADE',
        styles['integrity_ok'],
    ))
    story.append(Paragraph(
        'Este relatório foi gerado automaticamente pela plataforma ForensiQ. '
        'Os metadados da evidência são imutáveis desde o momento do registo '
        '(conforme ISO/IEC 27037:2012). O hash SHA-256 acima permite verificar '
        'a autenticidade dos metadados registados.',
        ParagraphStyle('FQDisclaimer', parent=styles['footer'],
                       fontSize=8, alignment=TA_LEFT,
                       spaceAfter=4),
    ))
    story.append(Paragraph(
        f'ForensiQ Platform · UC 21184 — Universidade Aberta · {gen_ts}',
        styles['footer'],
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
