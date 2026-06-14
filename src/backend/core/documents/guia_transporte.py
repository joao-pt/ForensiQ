"""
ForensiQ — Guia de transporte (PDF) de uma REMESSA.

A guia é o manifesto que acompanha fisicamente a prova quando ela se MOVE de um
ponto de controlo ao seguinte (ADR-0012): NÃO é prova juridicamente auto-contida
nem entra na cadeia de custódia — é um documento operacional, re-gerado a partir do
ledger e verificável pelo QR. Responde a o-quê / de-onde→para-onde / quem / quando /
em-que-estado: REMESSA (origem→destino, portador, remetente, receção), ITENS (só
identificadores inequívocos + selo), PROCESSO (mínimo) e PERCURSO físico por item.
Identidade de DOCUMENTO (monocromática, condensada), distinta da interface da app.

:func:`generate_guia_transporte` gera o PDF de uma :class:`core.models.GuiaTransporte`
(a remessa criada no encaminhamento em lote).
"""

from __future__ import annotations

from core.documents.builder import DocumentBuilder, fmt_agent, fmt_datetime, sanitize
from core.evidence_field_config import display_fields_for, fields_by_type
from core.policy.event_states import CERTIFIED_ACT_EVENTS, EventType
from core.qr_verify import verify_url_for_guia
from core.utils import current_seal_of, sort_custody_chain


def _masthead(doc, *, ref, qr_url):
    """Topo: tipo de documento + nº da guia + QR pequeno (topo-direito) que aponta à
    verificação da remessa (``/v/g/<hash>/``), com a ligação legível por baixo
    (entrada manual se o QR estiver ilegível — ADR-0012)."""
    short = qr_url.split('://', 1)[-1].rstrip('/')
    return doc.masthead(
        doc_type='GUIA DE TRANSPORTE',
        subtitle=f'Nº {sanitize(ref)} · ISO/IEC 27037',
        qr_url=qr_url,
        qr_caption=f'Verifique em<br/>{sanitize(short)}',
    )


def _identity_inline(item, catalog):
    """Identificadores INEQUÍVOCOS de um item numa linha condensada (rótulo valor · …):
    marca/modelo/série + IMEI/VIN/… do tipo (só ``is_identifier``; sem metadados)."""
    bits = [
        f'{f["label"]} {f["value"]}'
        for f in display_fields_for(item, catalog, identifiers_only=True)
    ]
    if item.serial_number:
        bits.append(f'Série {item.serial_number}')
    return ' · '.join(bits)


def _institution_label(inst):
    return inst.short_label if inst else ''


def _portador_label(rec):
    """Nome + matrícula do portador (snapshot do evento — entra na cadeia de hash)."""
    nome = ' '.join(p for p in (rec.bearer_nome, rec.bearer_apelido) if p).strip()
    if not nome:
        return '—'
    return f'{nome} · {rec.bearer_matricula}' if rec.bearer_matricula else nome


def _physical_events(item):
    """Eventos FÍSICOS do ledger por ordem (saltam-se os atos certificados —
    validação/despacho — que não deslocam a prova)."""
    eventos = sort_custody_chain(item.custody_chain.all())
    return [e for e in eventos if e.event_type not in CERTIFIED_ACT_EVENTS]


def _step_label(rec):
    """Ponto do percurso: instituição (sigla), senão local, senão o tipo de evento."""
    inst = _institution_label(rec.custodian_institution)
    if inst:
        return inst
    loc = ' · '.join(p for p in (rec.location_name, rec.storage_location) if p)
    return loc or rec.get_event_type_display()


def _rececao_after(item, anchor):
    """RECEPCAO_CUSTODIA do item depois do encaminhamento ``anchor`` (None se ainda
    em trânsito) — é a confirmação de entrega no destino."""
    for ev in sort_custody_chain(item.custody_chain.all()):
        if ev.sequence > anchor.sequence and ev.event_type == EventType.RECEPCAO_CUSTODIA:
            return ev
    return None


def _remessa_pairs(anchor, item):
    """De/Para/Enviado/Portador/Remetente da remessa ancorada no encaminhamento
    ``anchor`` (+ receção, se já entregue). O selo é por-item — vai em cada item."""
    phys = _physical_events(item)
    idx = next((k for k, e in enumerate(phys) if e.pk == anchor.pk), None)
    origem = _step_label(phys[idx - 1]) if (idx is not None and idx > 0) else 'Local da apreensão'
    pairs = [
        ('De', origem),
        ('Para', _institution_label(anchor.custodian_institution) or '—'),
        ('Enviado', fmt_datetime(anchor.timestamp)),
        ('Portador', _portador_label(anchor)),
        ('Remetente', fmt_agent(anchor.relinquished_by or anchor.agent)),
    ]
    rec = _rececao_after(item, anchor)
    if rec:
        pairs.append(('Recebido por', sanitize(rec.receiver_nome) or fmt_agent(rec.agent)))
        pairs.append(('Receção', fmt_datetime(rec.timestamp)))
    return pairs


def _itens_block(doc, itens, catalog):
    """Itens transportados (só identificadores + selo) + subitens integrantes."""
    out = []
    for item in itens:
        out.append(
            doc.paragraph(
                f'<b>{sanitize(item.display_code)}</b> · {sanitize(item.get_type_display())}',
                'cell',
            )
        )
        bits = []
        ident = _identity_inline(item, catalog)
        if ident:
            bits.append(ident)
        selo = current_seal_of(item)
        if selo:
            bits.append(f'Selo {selo}')
        if bits:
            out.append(doc.paragraph(sanitize(' · '.join(bits)), 'subitem'))
        for sub in sorted(item.sub_components.all(), key=lambda e: e.id):
            line = f'» <b>{sanitize(sub.display_code)}</b> · {sanitize(sub.get_type_display())}'
            sid = _identity_inline(sub, catalog)
            if sid:
                line += f' — {sanitize(sid)}'
            out.append(doc.paragraph(line, 'subitem'))
    out.append(doc.spacer(0.1))
    return out


def _processo_line(occ):
    """Contexto MÍNIMO do processo numa linha: NUIPC · crime · prioridade."""
    crime = sanitize(occ.crime_type.descritivo) if occ.crime_type_id else '—'
    return (
        f'<b>NUIPC</b> {sanitize(occ.number or "—")} · {crime} · '
        f'{sanitize(occ.get_priority_display())}'
    )


def _percurso_line(item):
    """Percurso FÍSICO condensado: sequência de pontos por onde a prova passou,
    sem repetir o mesmo ponto seguido (encaminhar→receber no mesmo destino = 1 ponto)."""
    phys = _physical_events(item)
    if not phys:
        return '—'
    steps = []
    for ev in phys:
        lbl = sanitize(_step_label(ev))
        if not steps or steps[-1] != lbl:
            steps.append(lbl)
    if phys[-1].event_type == EventType.ENCAMINHAMENTO_CUSTODIA:
        steps[-1] = f'<i>(em trânsito)</i> {steps[-1]}'
    return ' → '.join(steps)


def generate_guia_transporte(guia):
    """Guia de transporte (PDF) de uma REMESSA (:class:`core.models.GuiaTransporte`):
    de→para, portador, lote de itens (só identificadores + selo), processo e percurso
    por item. Re-gerada sempre a partir dos eventos do ledger (ADR-0012)."""
    from django.db.models import Prefetch

    from core.models import ChainOfCustody

    custody_qs = ChainOfCustody.objects.select_related('custodian_institution', 'agent').order_by(
        '-sequence'
    )
    events = list(
        guia.events.select_related(
            'evidence',
            'evidence__occurrence',
            'evidence__occurrence__crime_type',
            'custodian_institution',
            'relinquished_by',
            'agent',
        )
        .prefetch_related(
            Prefetch('evidence__custody_chain', queryset=custody_qs),
            'evidence__sub_components',
        )
        .order_by('evidence_id')
    )
    anchor = events[0]
    items = [e.evidence for e in events]
    occ = anchor.evidence.occurrence
    catalog = fields_by_type()

    doc = DocumentBuilder(
        title=f'ForensiQ — Guia de transporte {guia.code}',
        doc_subject='Guia de transporte — remessa',
        footer_ref=guia.code,
    )
    doc.add(_masthead(doc, ref=guia.code, qr_url=verify_url_for_guia(guia.id)))

    doc.section('Remessa')
    doc.add(doc.kv_grid(_remessa_pairs(anchor, anchor.evidence), ncols=2))

    doc.section(f'Itens transportados ({len(items)})')
    doc.add(_itens_block(doc, items, catalog))

    doc.section('Processo')
    doc.add(doc.paragraph(_processo_line(occ), 'cell'), doc.spacer(0.15))

    doc.section('Percurso')
    doc.add(
        [
            doc.paragraph(f'<b>{sanitize(it.display_code)}</b> {_percurso_line(it)}', 'cell')
            for it in items
        ]
    )

    return doc.render()
