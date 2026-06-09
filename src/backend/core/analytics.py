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
    SEIZURE_GENESIS_EVENTS,
    TERMINAL_EVENTS,
    TERMINAL_LEGAL_STATES,
    EventType,
)

# Janelas temporais oferecidas no seletor (dias). 30 é o defeito.
WINDOW_CHOICES = (7, 30, 90, 365)
DEFAULT_WINDOW_DAYS = 30

# "Concluído" para efeitos de fluxo = disposição final do item — o mesmo critério
# do Arquivo (restituída / perdida a favor do Estado / destruída).
DISPOSAL_EVENTS = (
    EventType.RESTITUICAO,
    EventType.DESTRUICAO,
    EventType.PERDA_FAVOR_ESTADO,
)
VALIDATION_DEADLINE = timedelta(hours=settings.VALIDATION_DEADLINE_HOURS)


def resolve_window(raw):
    """Valida ``?days=`` contra as janelas oferecidas; cai no defeito (30)."""
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return days if days in WINDOW_CHOICES else DEFAULT_WINDOW_DAYS


def state_distribution(states_by_ev):
    """Distribuição do ESTADO ATUAL dos itens (stock), separando ativo/terminal.

    ``states_by_ev`` = ``{evidence_id: estado}`` produzido por
    ``frontend_views._legal_states_by_evidence`` (a fonte única do estado legal
    derivado) — passa-se já calculado para não duplicar a derivação aqui.
    """
    counts = {k: 0 for k in LEGAL_STATE_LABELS}
    for st in states_by_ev.values():
        if st in counts:
            counts[st] += 1
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


def throughput(occ_qs, evd_qs, cus_qs, since):
    """Fluxo por semana desde ``since``: processos abertos, itens registados e
    itens concluídos (disposição final). Séries alinhadas por semana (TruncWeek).
    """

    def weekly(qs, field):
        rows = (
            qs.filter(**{field + '__gte': since})
            .annotate(w=TruncWeek(field))
            .values('w')
            .annotate(n=Count('id'))
            .order_by('w')
        )
        return {r['w'].date(): r['n'] for r in rows if r['w']}

    opened = weekly(occ_qs, 'date_time')
    registered = weekly(evd_qs, 'timestamp_seizure')
    concluded = weekly(cus_qs.filter(event_type__in=DISPOSAL_EVENTS), 'timestamp')

    weeks = sorted(set(opened) | set(registered) | set(concluded))
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
    (último evento → agora, só para itens ainda não terminais).
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

    open_secs = [
        (now - ts).total_seconds()
        for et, ts in last_by_ev.values()
        if ts is not None and et not in TERMINAL_EVENTS
    ]
    avg_h = (sum(closed_secs) / len(closed_secs) / 3600) if closed_secs else 0
    longest_open_h = (max(open_secs) / 3600) if open_secs else 0
    return {
        'avg_dwell_hours': round(avg_h, 1),
        'intervals': len(closed_secs),
        'longest_open_hours': round(longest_open_h, 1),
        'open_items': len(open_secs),
    }


def aging_sla(evd_qs, cus_qs, now=None):
    """Prazos & atenção: validações de apreensão em atraso e prova em trânsito.

    - **Validações em atraso**: itens com génese de APREENSÃO há mais de 72h
      (``VALIDATION_DEADLINE``, CPP art. 178.º/6) SEM evento de validação no ledger.
    - **Em trânsito por receber**: ``ProvaEmTransito`` (handoff em dois tempos) por
      confirmar, restringido ao universo de itens visível, e a paragem mais antiga.
    """
    now = now or timezone.now()
    seized = set(
        cus_qs.filter(
            event_type__in=SEIZURE_GENESIS_EVENTS,
            timestamp__lt=now - VALIDATION_DEADLINE,
        ).values_list('evidence_id', flat=True)
    )
    validated = set(
        cus_qs.filter(event_type=EventType.VALIDACAO_APREENSAO).values_list(
            'evidence_id', flat=True
        )
    )
    validations_overdue = len(seized - validated)

    in_transit = ProvaEmTransito.objects.filter(
        evidence__in=evd_qs, acknowledged_at__isnull=True
    )
    in_transit_count = in_transit.count()
    oldest = in_transit.order_by('created_at').values_list('created_at', flat=True).first()
    oldest_h = round((now - oldest).total_seconds() / 3600, 1) if oldest else 0
    return {
        'validations_overdue': validations_overdue,
        'in_transit': in_transit_count,
        'oldest_transit_hours': oldest_h,
        'deadline_hours': settings.VALIDATION_DEADLINE_HOURS,
    }
