"""ForensiQ — Filtros de lista por coluna (fonte ÚNICA, transversal).

Uma lista de :class:`ColFilter` descreve os filtros de uma grelha (um por coluna
filtrável). As listas (ocorrências, evidências, custódias, arquivo) declaram a
sua spec e reusam estes helpers — zero código de filtragem por página:

  * :func:`apply_col_filters`  — aplica a spec ao queryset (texto ``icontains``
    com OR opcional sobre vários campos; select EXATO validado contra as opções;
    intervalo de datas). Server-side → correto com paginação.
  * :func:`filter_bar_context` — resolve os valores atuais do GET para a barra
    (``partials/_filter_bar.html``).
  * :func:`active_params`      — pares (param, valor) ativos, para a querystring
    da paginação propagar os filtros e para o ``has_filters`` do estado vazio.

O «ao escrever filtra logo» é o HTMX (debounce) no formulário que envolve a barra.
"""
from dataclasses import dataclass

from django.db.models import Q
from django.utils.dateparse import parse_date


@dataclass
class ColFilter:
    param: str                       # nome do parâmetro GET
    label: str                       # rótulo (= a coluna que reflete)
    kind: str = 'text'               # 'text' | 'select' | 'date_range'
    field: str = ''                  # caminho ORM (text single / select / date_range)
    fields: tuple = ()               # text: OR sobre vários campos (sobrepõe `field`)
    lookup: str = 'icontains'        # text
    choices: tuple = ()              # select: iterável de (valor, rótulo)
    placeholder: str = ''


def _text_q(f, value):
    targets = f.fields or ((f.field,) if f.field else ())
    q = Q()
    for path in targets:
        q |= Q(**{f'{path}__{f.lookup}': value})
    return q


def apply_col_filters(qs, request, spec):
    """Aplica a spec ao queryset a partir dos parâmetros GET (ignora vazios)."""
    for f in spec:
        if f.kind == 'date_range':
            da = parse_date((request.GET.get(f.param + '_after') or '').strip())
            db = parse_date((request.GET.get(f.param + '_before') or '').strip())
            if da:
                qs = qs.filter(**{f'{f.field}__date__gte': da})
            if db:
                qs = qs.filter(**{f'{f.field}__date__lte': db})
        elif f.kind == 'select':
            v = (request.GET.get(f.param) or '').strip()
            # Só aplica valores que existam nas opções → evita lookups inválidos
            # (ex.: ?cat=abc) e mantém o filtro previsível.
            if v and v in {str(c[0]) for c in f.choices}:
                qs = qs.filter(**{f.field: v})
        else:  # text
            v = (request.GET.get(f.param) or '').strip()
            if v:
                qs = qs.filter(_text_q(f, v))
    return qs


def filter_bar_context(spec, request):
    """Resolve a spec + GET atual num formato simples para o template da barra."""
    out = []
    for f in spec:
        if f.kind == 'date_range':
            out.append({
                'kind': 'date_range', 'param': f.param, 'label': f.label,
                'after': (request.GET.get(f.param + '_after') or '').strip(),
                'before': (request.GET.get(f.param + '_before') or '').strip(),
            })
        elif f.kind == 'select':
            out.append({
                'kind': 'select', 'param': f.param, 'label': f.label,
                'value': (request.GET.get(f.param) or '').strip(),
                'choices': list(f.choices),
            })
        else:
            out.append({
                'kind': 'text', 'param': f.param, 'label': f.label,
                'value': (request.GET.get(f.param) or '').strip(),
                'placeholder': f.placeholder or f.label,
            })
    return out


def active_params(spec, request):
    """Dict {param: valor} dos filtros ativos (não vazios). Base da querystring
    de paginação e do indicador de «há filtros aplicados»."""
    pairs = {}
    for f in spec:
        if f.kind == 'date_range':
            for suf in ('_after', '_before'):
                v = (request.GET.get(f.param + suf) or '').strip()
                if v:
                    pairs[f.param + suf] = v
        else:
            v = (request.GET.get(f.param) or '').strip()
            if v:
                pairs[f.param] = v
    return pairs
