"""ForensiQ — Gerador ÚNICO de grelhas de lista (fonte única transversal).

Uma lista declara as suas COLUNAS (:class:`GridColumn`) + dados; este módulo faz
TODO o resto — filtros por coluna (reusa :mod:`core.list_filters`), busca
transversal, ordenação, paginação, decoração e montagem do contexto que os
parciais ``partials/_grid*.html`` consomem. O MESMO gerador serve ocorrências,
arquivo, evidências, custódias, instituições e relatórios: muda só a spec.

Desktop: cabeçalho de 2 linhas (nomes + filtros por coluna), larguras fixas por
classe utilitária ``grid__col--wN`` (CSP-safe, sem estilo inline). Telemóvel: a
grelha reduz às colunas marcadas (resto ``col-reduce-hide``), bolinha de urgência
+ legenda + só a busca global (regras em ``forensic.css``).
"""
from dataclasses import dataclass
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from core.list_filters import (
    ColFilter,
    active_params,
    apply_col_filters,
    filter_bar_context,
)


@dataclass
class GridColumn:
    """Uma coluna da grelha: como se renderiza a célula + (opcional) o seu filtro.

    Só muda isto por tabela; tudo o resto vem do gerador. ``css`` leva apenas
    modificadores responsivos/de texto (``col-reduce-hide``/``col-hide-sm``/
    ``col-hide-md``/``mono``/``grid__ellipsis``/``grid__muted``) — NUNCA largura
    (essa vem de ``width`` → classe) nem a classe estrutural do tipo de célula
    (``grid__code``/``grid__pri`` são adicionadas pelo ``_grid_cell.html``).
    """
    key: str                          # atributo da linha com o valor (caminho com ponto ok)
    label: str                        # nome da coluna (cabeçalho)
    cell: str = 'text'                # text | code | num | pri | state | date | action
    css: str = ''                     # modificadores responsivos/texto
    width: int = 0                    # % no desktop (>0 OBRIGATÓRIO → classe grid__col--wN)
    time: bool = False                # célula date: acrescenta <span grid__cell-time> H:i
    link_key: str = ''                # envolve o valor em <a href=row.<link_key>>
    suffix: str = ''                  # literal após o valor (ex.: hash '…')
    geo: bool = False                 # célula text: prefixa ícone GPS se row.gps_lat
    dot: bool = False                 # coluna hospedeira da bolinha de urgência
    val_flag: bool = False            # sufixa o marcador de validação pendente (row.val_dot)
    filter: ColFilter | None = None


def serialize_columns(columns, filters=None):
    """Spec de colunas → formato que os parciais consomem (_col_names/_grid_cell).

    ``filters`` é o dict param→contexto do filter_bar (só nas listas completas;
    painéis read-only passam None e escondem a linha de filtros no parcial).
    Fonte única da serialização — usada por :func:`grid_list_response` e pelos
    painéis que incluem ``_grid.html`` diretamente (ex.: dashboard).
    """
    filters = filters or {}
    return [{
        'key': c.key, 'label': c.label, 'css': c.css, 'width': c.width,
        'cell': c.cell, 'time': c.time, 'link_key': c.link_key,
        'suffix': c.suffix, 'geo': c.geo, 'dot': c.dot, 'val_flag': c.val_flag,
        'filter': filters.get(c.filter.param) if c.filter else None,
    } for c in columns]


def grid_list_response(request, *, queryset, columns, grid_key, endpoint,
                       page_template, table_label, count_noun, count_plural='',
                       sorts, default_sort, sorts_ui=(), search_fields=(),
                       search_placeholder='', decorate=None, legend=None,
                       row_clickable=True, mobile_reduce=True, page_size=25,
                       lens='', empty_title='', empty_hint='',
                       empty_filtered='Nenhum resultado para os filtros aplicados.',
                       computed_filters=None, post_filter=None, extra_ctx=None):
    """Resposta de uma lista server-rendered + HTMX a partir da spec de colunas.

    Em pedidos HTMX devolve só o fragmento ``partials/_grid.html`` (com a contagem
    out-of-band); senão a ``page_template`` (casca que inclui ``_grid_toolbar``).
    """
    # Guarda de dev: table-layout:fixed lê as larguras da 1.ª linha do <thead>;
    # uma coluna sem largura colapsaria/absorveria o resto silenciosamente.
    missing = [c.key for c in columns if not c.width]
    if missing:
        raise ValueError(f'GridColumn sem width (>0) obrigatório: {missing}')

    computed_filters = computed_filters or {}
    field_spec = [c.filter for c in columns
                  if c.filter and c.filter.param not in computed_filters]
    full_spec = [c.filter for c in columns if c.filter]

    # 1) Filtros por coluna baseados em campos (reusa list_filters, validado).
    qs = apply_col_filters(queryset, request, field_spec)

    # 2) Filtros DERIVADOS (estado legal, is_active) — única extensão ao
    #    list_filters; whitelist no predicado único (ColFilter.accepts — D48).
    for param, fn in computed_filters.items():
        col = next(c for c in columns if c.filter and c.filter.param == param)
        value = (request.GET.get(param) or '').strip()
        if col.filter.accepts(value):
            qs = fn(qs, request, value)

    # 3) Busca transversal (OR icontains sobre vários campos) — o que permite
    #    encolher a grelha no telemóvel (menos colunas, mas encontra tudo).
    query = (request.GET.get('q') or '').strip()
    if query and search_fields:
        cond = Q()
        for path in search_fields:
            cond |= Q(**{f'{path}__icontains': query})
        qs = qs.filter(cond)

    # 4) Pós-filtro específico da lista (ex.: divisão arquivado/ativo).
    if post_filter is not None:
        qs = post_filter(qs, request)

    # 5) Ordenação (lista branca → impede campos arbitrários por query param).
    sort_key = (request.GET.get('sort') or '').strip()
    if sort_key not in sorts:
        sort_key = default_sort
    qs = qs.order_by(sorts[sort_key])

    # 6) Paginação + decoração de apresentação (rótulos, .dot, .aria_code).
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page'))
    if decorate is not None:
        decorate(page_obj.object_list)

    # 7) Querystring base (sem 'page') para a paginação propagar TODOS os filtros.
    col_active = active_params(full_spec, request)
    base_params = dict(col_active)
    if query:
        base_params['q'] = query
    if lens:
        base_params['lens'] = lens
    if sorts_ui:
        base_params['sort'] = sort_key
    qs_base = urlencode(base_params)

    # 8) Colunas no formato do template (nome + filtro emparelhado por param).
    fbar = {f['param']: f for f in filter_bar_context(full_spec, request)}
    columns_ctx = serialize_columns(columns, fbar)

    ctx = {
        'columns': columns_ctx,
        'page_obj': page_obj,
        'total': paginator.count,
        'has_filters': bool(col_active) or bool(query),
        'q': query,
        'urgency_legend': legend,
        'sort': sort_key,
        'sorts_ui': list(sorts_ui),
        'qs_base': qs_base,
        'lens': lens,
        'endpoint': endpoint,
        'grid_id': f'{grid_key}-grid',
        'table_id': f'{grid_key}-table',
        'count_id': f'{grid_key}-count',
        'busy_id': f'{grid_key}-busy',
        # Consumido pela casca única grid_page.html (auditoria D52) — as páginas
        # deixam de hard-codar ids (o OOB swap do _grid exige id == count_id).
        'title_id': f'{grid_key}-title',
        'count_noun': count_noun,
        'count_plural': count_plural,
        'row_clickable': row_clickable,
        'mobile_reduce': mobile_reduce,
        'search_placeholder': search_placeholder,
        'table_label': table_label,
        'empty_title': empty_title,
        'empty_hint': empty_hint,
        'empty_filtered': empty_filtered,
        'selected_id': request.GET.get('selected') or '',
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if extra_ctx:
        ctx.update(extra_ctx)

    if ctx['is_htmx']:
        return render(request, 'partials/_grid.html', ctx)
    return render(request, page_template, ctx)
