"""
ForensiQ — Métricas de FLUXO do painel de estatísticas (fonte ÚNICA dos cálculos
temporais).

Substitui as contagens cumulativas point-in-time do /stats/ (que não diziam
*quando*, *de quê* nem *filtrado por quê*) por quatro leituras honestas:

  * **estado atual (stock)** — distribuição do estado legal DERIVADO dos itens,
    separando ativo de terminal (reaproveita ``derive_legal_state`` via o dict já
    calculado pela view, sem reinventar);
  * **fluxo no período (throughput)** — processos abertos, itens registados e
    itens concluídos por semana, dentro de uma janela temporal;
  * **prazos & atenção (SLA)** — validações de apreensão em atraso (CPP art.
    178.º/6, 72h) e prova em trânsito por receber;
  * **dwell time da custódia** — quanto tempo um item fica sob um custódio entre
    eventos consecutivos do ledger, e a paragem atual mais longa.

Todo o cálculo de durações entre eventos vive AQUI — nenhuma página o duplica.
Funções puras de leitura (sem efeitos), recebem os querysets já restringidos à
lente ativa. O vocabulário processual vem de ``core.policy.event_states``.
"""


from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.db.models.functions import TruncWeek
from django.utils import timezone

from .labels import LEGAL_STATE_CSS, LEGAL_STATE_LABELS
from .models import ProvaEmTransito
from .policy.event_states import (
    DISPOSAL_EVENTS,
    LEGAL_STATES,
    SEIZURE_GENESIS_EVENTS,
    TERMINAL_LEGAL_STATES,
    VALIDATION_DEADLINE,
    VALIDATION_DEADLINE_WARNING,
    EventType,
    derive_legal_state,
    pericia_deadline,
    validation_status,
)

# Janelas temporais oferecidas no seletor (dias). 30 é o defeito.
WINDOW_CHOICES = (7, 30, 90, 365)
DEFAULT_WINDOW_DAYS = 30

# "Concluído" para efeitos de fluxo = disposição final do item — o mesmo critério
# do Arquivo. DISPOSAL_EVENTS/VALIDATION_DEADLINE: fonte única em core.policy
# (auditoria D50) — importados acima.


def resolve_window(raw):
    """Valida ``?days=`` contra as janelas oferecidas; cai no defeito (30)."""
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return days if days in WINDOW_CHOICES else DEFAULT_WINDOW_DAYS


def legal_states_by_evidence(custody_qs, *, with_events=False, related=()):
    """``{evidence_id: estado_legal_derivado}`` numa ÚNICA query (WI-E).

    Fonte única do agrupamento ledger→estado: agrupa os eventos do ledger
    (âmbito *need-to-know*/lente JÁ imposto pelo chamador) por ``evidence_id``
    — uma só passagem, suportada pelo índice ``coc_ev_seq_idx`` — e deriva o
    estado uma vez por item com a função pura :func:`derive_legal_state`.
    Consumida pelo frontend, pela API, pelos filtros e pelo intake; nenhuma
    camada re-implementa o agrupamento.

    ``with_events=True`` devolve ``(states, eventos_por_evidencia)`` para os
    consumidores que também precisam dos registos agrupados (ex.: o intake lê o
    destino do último encaminhamento) sem repetir a passagem; ``related``
    acrescenta ``select_related`` nesse modo (no modo leve usa-se ``only`` com
    os campos mínimos da derivação).
    """
    qs = custody_qs.select_related(None).order_by('evidence_id', 'sequence')
    if with_events:
        if related:
            qs = qs.select_related(*related)
    else:
        qs = qs.only('evidence_id', 'event_type', 'custodian_type', 'sequence')
    eventos = {}
    for rec in qs:
        eventos.setdefault(rec.evidence_id, []).append(rec)
    states = {ev_id: derive_legal_state(evs) for ev_id, evs in eventos.items()}
    return (states, eventos) if with_events else states


def validation_statuses_by_evidence(custody_qs, now=None):
    """Estatuto de VALIDAÇÃO por evidência (eixo ortogonal ao estado de custódia
    — CPP art. 178.º/6), em LOTE: agrupa o ledger visível por ``evidence_id``
    numa só passagem e aplica a função pura :func:`validation_status` uma vez
    por item. Espelho de :func:`legal_states_by_evidence` para o outro eixo —
    nenhuma camada re-implementa o agrupamento. ``None`` = não aplicável."""
    now = now or timezone.now()
    qs = (
        custody_qs.select_related(None)
        .order_by('evidence_id', 'sequence')
        .only('evidence_id', 'event_type', 'sequence', 'timestamp')
    )
    eventos = {}
    for rec in qs:
        eventos.setdefault(rec.evidence_id, []).append(rec)
    return {ev_id: validation_status(evs, now) for ev_id, evs in eventos.items()}


def pericia_deadlines_by_evidence(custody_qs, now=None):
    """Prazo da perícia ordenada por evidência (data-limite + estatuto, derivados
    do último despacho — CPP art. 154.º; hv4), em LOTE: agrupa o ledger visível
    por ``evidence_id`` numa só passagem e aplica a função pura
    :func:`pericia_deadline` uma vez por item. Espelho de
    :func:`validation_statuses_by_evidence` para o eixo do despacho — nenhuma
    camada re-implementa o agrupamento. ``None`` = não aplicável."""
    now = now or timezone.now()
    qs = (
        custody_qs.select_related(None)
        .order_by('evidence_id', 'sequence')
        .only(
            'evidence_id', 'event_type', 'sequence', 'timestamp',
            'act_declared_at', 'act_deadline_days',
        )
    )
    eventos = {}
    for rec in qs:
        eventos.setdefault(rec.evidence_id, []).append(rec)
    return {ev_id: pericia_deadline(evs, now) for ev_id, evs in eventos.items()}


def state_counts(states_by_ev):
    """Contagem por estado legal derivado com TODOS os estados (zeros incluídos),
    por ordem canónica. Fonte única do loop de contagem (stock)."""
    counts = {state: 0 for state in sorted(LEGAL_STATES)}
    for st in states_by_ev.values():
        if st in counts:
            counts[st] += 1
    return counts


def state_distribution(states_by_ev):
    """Distribuição do ESTADO ATUAL dos itens (stock), separando ativo/terminal.

    ``states_by_ev`` = ``{evidence_id: estado}`` produzido por
    :func:`legal_states_by_evidence` — passa-se já calculado para a view poder
    partilhar o mesmo dict com outros cálculos do request.
    """
    counts = state_counts(states_by_ev)
    rows = [
        {
            'key': k,
            'label': LEGAL_STATE_LABELS[k],
            'css': LEGAL_STATE_CSS.get(k, 'muted'),
            'n': counts[k],
            'terminal': k in TERMINAL_LEGAL_STATES,
        }
        for k in LEGAL_STATE_LABELS
        if counts[k]
    ]
    rows.sort(key=lambda r: r['n'], reverse=True)
    active = sum(n for k, n in counts.items() if k not in TERMINAL_LEGAL_STATES)
    concluded = sum(n for k, n in counts.items() if k in TERMINAL_LEGAL_STATES)
    return {
        'rows': rows,
        'active': active,
        'concluded': concluded,
        'total': active + concluded,
        'peak': max(counts.values(), default=0),
    }


def bucket_counts(qs, field, since, trunc=TruncWeek):
    """Contagem por balde temporal: ``filter(field>=since) → annotate(trunc) →
    Count``, devolvendo ``{data: n}``. Fonte única da pipeline de séries — a
    granularidade (``TruncWeek``/``TruncDate``…) é parâmetro, não uma segunda
    implementação."""
    rows = (
        qs.filter(**{field + '__gte': since})
        .annotate(b=trunc(field))
        .values('b')
        .annotate(n=Count('id'))
        .order_by('b')
    )
    # TruncWeek devolve datetime aware (em UTC na ligação PG) — reduzir ao dia
    # EM HORA LOCAL: um .date() cru dava DOMINGO no horário de verão (segunda
    # 00:00 local = domingo 23:00 UTC) e desalinhava o eixo semanal canónico.
    # TruncDate já devolve date.
    return {
        (timezone.localtime(r['b']).date() if hasattr(r['b'], 'date') else r['b']): r['n']
        for r in rows
        if r['b']
    }


def throughput(occ_qs, evd_qs, cus_qs, since):
    """Fluxo por semana desde ``since``: processos abertos, itens registados e
    itens concluídos (disposição final). Séries alinhadas por semana (TruncWeek).

    «Abertas» conta por data de REGISTO (``created_at`` — decisão UX n.º 5):
    coerência com o título «Fluxo» e com as outras séries, que também são
    datas de atos (apreensão, disposição), não dos factos. O eixo semanal é
    CONTÍNUO de ``since`` até agora — semanas sem eventos entram a ZERO
    (buracos silenciosos liam-se como semanas inexistentes).
    """
    opened = bucket_counts(occ_qs, 'created_at', since)
    registered = bucket_counts(evd_qs, 'timestamp_seizure', since)
    concluded = bucket_counts(
        cus_qs.filter(event_type__in=DISPOSAL_EVENTS), 'timestamp', since
    )

    # Eixo canónico de segundas-feiras em HORA LOCAL — a mesma redução de
    # bucket_counts, senão os baldes desalinhavam ±1 dia (DST/meia-noite).
    start = timezone.localtime(since).date()
    start -= timedelta(days=start.weekday())
    end = timezone.localdate()
    end -= timedelta(days=end.weekday())
    weeks, w = [], start
    while w <= end:
        weeks.append(w)
        w += timedelta(days=7)
    series = [
        {
            'week': w,
            'opened': opened.get(w, 0),
            'registered': registered.get(w, 0),
            'concluded': concluded.get(w, 0),
        }
        for w in weeks
    ]
    peak = max((max(s['opened'], s['registered'], s['concluded']) for s in series), default=0)
    return {
        'series': series,
        'opened': sum(opened.values()),
        'registered': sum(registered.values()),
        'concluded': sum(concluded.values()),
        'peak': peak,
    }


def custody_dwell(cus_qs, now=None):
    """Dwell time da custódia a partir do ledger restringido à lente.

    Dwell = horas que um item esteve sob um custódio ANTES do evento seguinte
    (diferença entre eventos consecutivos por evidência, ordenados por sequence).
    Devolve a média global das paragens fechadas e a paragem ATUAL mais longa
    (último evento → agora, só para itens sem disposição final — DISPOSAL_EVENTS
    — como ÚLTIMO evento; um evento posterior à perda reabre a paragem, tal
    como reabre o prazo da perícia). A paragem máxima vem IDENTIFICADA
    (``longest_open_evidence_id``/``longest_open_code``) — número re-derivável
    → devolve o id, como o ``aging_sla`` — e com o flag ``longest_open_warn``
    calculado contra ``CUSTODY_DWELL_WARNING_HOURS`` (settings; lido em runtime
    para os testes poderem usar ``override_settings``).
    """
    now = now or timezone.now()
    rows = (
        cus_qs.select_related(None)
        .order_by('evidence_id', 'sequence')
        .values_list('evidence_id', 'event_type', 'timestamp')
    )
    closed_secs = []          # durações entre dois eventos consecutivos
    last_by_ev = {}           # evidence_id -> (event_type, timestamp) do último evento
    prev_ev, prev_ts = None, None
    for ev_id, et, ts in rows:
        if ev_id == prev_ev and prev_ts is not None and ts is not None:
            closed_secs.append((ts - prev_ts).total_seconds())
        prev_ev, prev_ts = ev_id, ts
        last_by_ev[ev_id] = (et, ts)

    open_stops = [
        ((now - ts).total_seconds(), ev_id)
        for ev_id, (et, ts) in last_by_ev.items()
        if ts is not None and et not in DISPOSAL_EVENTS
    ]
    avg_h = (sum(closed_secs) / len(closed_secs) / 3600) if closed_secs else 0
    # max() sobre tuplos desempata pelo ev_id maior — determinístico mas
    # arbitrário; identifica-se UM item mesmo com paragens empatadas.
    longest_secs, longest_ev = max(open_stops) if open_stops else (0, None)
    longest_open_h = longest_secs / 3600
    # Code por query DIRIGIDA sobre cus_qs (a lente preserva o need-to-know);
    # nunca um JOIN de evidence__code em todas as linhas do ledger.
    longest_code = (
        cus_qs.filter(evidence_id=longest_ev)
        .values_list('evidence__code', flat=True).first()
        if longest_ev is not None else None
    )
    warn_hours = settings.CUSTODY_DWELL_WARNING_HOURS
    return {
        'avg_dwell_hours': round(avg_h, 1),
        'intervals': len(closed_secs),
        'longest_open_hours': round(longest_open_h, 1),
        'longest_open_evidence_id': longest_ev,
        'longest_open_code': longest_code,
        'longest_open_warn': longest_open_h >= warn_hours,
        'dwell_warn_hours': warn_hours,
        'open_items': len(open_stops),
    }


def aging_sla(evd_qs, cus_qs, now=None):
    """Prazos & atenção: validações em atraso, prova em trânsito e prazos de perícia.

    - **Validações em atraso**: itens com génese de APREENSÃO há mais de 72h
      (``VALIDATION_DEADLINE``, CPP art. 178.º/6) SEM evento de validação no ledger.
    - **Validações a vencer**: idem, mas com a génese a ≤
      ``VALIDATION_DEADLINE_WARNING`` do prazo (eixo PREVENTIVO; disjunto do
      «em atraso» — gte/lt na fronteira).
    - **Em trânsito por receber**: ``ProvaEmTransito`` (handoff em dois tempos) por
      confirmar, restringido ao universo de itens visível, e a paragem mais antiga.
    - **Prazos de perícia**: itens com despacho cuja data-limite (data declarada
      + prazo em dias, hv4 — :func:`pericia_deadlines_by_evidence`) já venceu
      ou vence em ≤ ``PERICIA_DEADLINE_WARNING_DAYS`` dias sem CONCLUSAO_PERICIA.

    Devolve também os IDS de evidência de cada conjunto (``overdue_ids``/
    ``validation_due_ids``/``transit_ids``/``pericia_overdue_ids``/
    ``pericia_due_ids``): os números do painel têm de ser RE-DERIVÁVEIS — quem
    clica num prazo vê exatamente os itens que o contam, não um conjunto
    parecido (princípio de re-verificabilidade).
    """
    now = now or timezone.now()
    seized = set(
        cus_qs.filter(
            event_type__in=SEIZURE_GENESIS_EVENTS,
            timestamp__lt=now - VALIDATION_DEADLINE,
        ).values_list('evidence_id', flat=True)
    )
    # Janela preventiva [prazo-aviso, prazo[: gte/lt espelham o lt estrito do
    # «em atraso» — um item na fronteira nunca conta duas vezes nem desaparece.
    due_seized = set(
        cus_qs.filter(
            event_type__in=SEIZURE_GENESIS_EVENTS,
            timestamp__gte=now - VALIDATION_DEADLINE,
            timestamp__lt=now - (VALIDATION_DEADLINE - VALIDATION_DEADLINE_WARNING),
        ).values_list('evidence_id', flat=True)
    )
    validated = set(
        cus_qs.filter(event_type=EventType.VALIDACAO_APREENSAO).values_list(
            'evidence_id', flat=True
        )
    )
    # Disposição final (restituída/destruída/perdida) extingue a exigência de
    # validação pendente — mesmo critério de validation_status (core.policy).
    closed = set(
        cus_qs.filter(event_type__in=DISPOSAL_EVENTS).values_list(
            'evidence_id', flat=True
        )
    )
    overdue_ids = seized - validated - closed
    validation_due_ids = due_seized - validated - closed

    in_transit = ProvaEmTransito.objects.filter(
        evidence__in=evd_qs, acknowledged_at__isnull=True
    )
    transit_ids = set(in_transit.values_list('evidence_id', flat=True))
    oldest = in_transit.order_by('created_at').values_list('created_at', flat=True).first()
    oldest_h = round((now - oldest).total_seconds() / 3600, 1) if oldest else 0

    # Prazo da perícia ordenada (despacho + dias, hv4) — mesma derivação em
    # lote dos badges/marcadores, para o número do painel bater com as linhas.
    deadlines = pericia_deadlines_by_evidence(cus_qs, now)
    pericia_overdue_ids = {
        ev for ev, d in deadlines.items() if d and d['status'] == 'vencida'
    }
    pericia_due_ids = {
        ev for ev, d in deadlines.items() if d and d['status'] == 'a_vencer'
    }
    return {
        'validations_overdue': len(overdue_ids),
        'overdue_ids': overdue_ids,
        'validations_due': len(validation_due_ids),
        'validation_due_ids': validation_due_ids,
        'validation_warning_hours': settings.VALIDATION_DEADLINE_WARNING_HOURS,
        'in_transit': len(transit_ids),
        'transit_ids': transit_ids,
        'oldest_transit_hours': oldest_h,
        'deadline_hours': settings.VALIDATION_DEADLINE_HOURS,
        'pericias_overdue': len(pericia_overdue_ids),
        'pericia_overdue_ids': pericia_overdue_ids,
        'pericias_due': len(pericia_due_ids),
        'pericia_due_ids': pericia_due_ids,
        'pericia_warning_days': settings.PERICIA_DEADLINE_WARNING_DAYS,
    }
