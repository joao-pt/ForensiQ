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
import csv
from dataclasses import dataclass
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
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
    title_key: str = ''               # célula text: atributo title vindo de row.<title_key>
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
        'title_key': c.title_key,
        'filter': filters.get(c.filter.param) if c.filter else None,
    } for c in columns]


def _csv_cell(row, col):
    """Valor ACHATADO de uma célula para o CSV — regras por tipo de célula na
    fonte única (os dicts de apresentação nunca se re-exprimem nas views):
    pri→title, state→label, action→href, date→ISO; resto = valor textual."""
    from core.templatetags.grid_extras import cellattr

    v = cellattr(row, col.key)
    if v is None:
        return ''
    if col.cell == 'pri':
        return v.get('title', '') if isinstance(v, dict) else str(v)
    if col.cell == 'state':
        return v.get('label', '') if isinstance(v, dict) else str(v)
    if col.cell == 'action':
        return v.get('href', '') if isinstance(v, dict) else str(v)
    if col.cell == 'date':
        return v.isoformat() if hasattr(v, 'isoformat') else str(v)
    return str(v)


def _export_csv(request, *, qs, columns, decorate, grid_key, qs_base):
    """Export CSV da grelha FILTRADA (parecer item 18) — a MESMA queryset dos
    passos de filtragem, SEM paginação; a decoração bulk e as colunas vêm da
    própria spec (zero re-expressão). O need-to-know já está aplicado a
    montante (o chamador entrega o queryset scoped — mesmo contrato de
    ``legal_states_by_evidence``). Auditado: qualquer extração massiva fica no
    trilho (EXPORT_CSV; sem recurso único → SYSTEM + id sentinela 0 e os
    filtros ativos nos details, para re-verificação do âmbito extraído)."""
    from core.audit import log_access
    from core.models import AuditLog

    rows = list(qs)
    if decorate is not None:
        decorate(rows)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{grid_key}-export.csv"'
    writer = csv.writer(response)
    writer.writerow([c.label for c in columns])
    for row in rows:
        writer.writerow([_csv_cell(row, c) for c in columns])
    log_access(
        request=request,
        action=AuditLog.Action.EXPORT_CSV,
        resource_type=AuditLog.ResourceType.SYSTEM,
        resource_id=0,
        details={'grid': grid_key, 'rows': len(rows), 'filters': qs_base},
    )
    return response


def grid_list_response(request, *, queryset, columns, grid_key, endpoint,
                       page_template, table_label, count_noun, count_plural='',
                       sorts, default_sort, sorts_ui=(), search_fields=(),
                       search_placeholder='', decorate=None, legend=None,
                       pendency_legend=None, computed_params=None,
                       row_clickable=True, mobile_reduce=True, page_size=25,
                       lens='', empty_title='', empty_hint='',
                       empty_filtered='Nenhum resultado para os filtros aplicados.',
                       computed_filters=None, post_filter=None, extra_ctx=None,
                       csv_export=False):
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
    #    list_filters. Selects validam contra a whitelist (ColFilter.accepts —
    #    D48); um filtro derivado de TEXTO valida no próprio fn (ex.: o alvo
    #    numérico do trilho de auditoria devolve vazio a input inválido, em vez
    #    de um lookup ORM a rebentar).
    for param, fn in computed_filters.items():
        col = next(c for c in columns if c.filter and c.filter.param == param)
        value = (request.GET.get(param) or '').strip()
        ok = col.filter.accepts(value) if col.filter.kind == 'select' else bool(value)
        if ok:
            qs = fn(qs, request, value)

    # 2b) Filtros computados SEM coluna própria (ex.: ?attn= — eixo de atenção
    #     transversal): param → (whitelist, fn). O valor ativo é "pegajoso":
    #     entra em qs_base (paginação), em has_filters e num input hidden do
    #     toolbar — senão evaporava-se à primeira busca/ordenação/página.
    computed_params = computed_params or {}
    sticky_params = {}
    for param, (accepted, fn) in computed_params.items():
        value = (request.GET.get(param) or '').strip()
        if value and value in accepted:
            qs = fn(qs, request, value)
            sticky_params[param] = value

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
    #    str = um campo; tuplo/lista = sort COMPOSTO (campo + tiebreak estável,
    #    ex.: '-timestamp' + '-sequence' — sem ele a paginação baralha linhas
    #    com valores empatados entre páginas).
    sort_key = (request.GET.get('sort') or '').strip()
    if sort_key not in sorts:
        sort_key = default_sort
    sort_spec = sorts[sort_key]
    qs = qs.order_by(*((sort_spec,) if isinstance(sort_spec, str) else sort_spec))

    # Querystring base (sem 'page') — propaga TODOS os filtros na paginação e
    # no link de export (computada antes do passo 6: o export precisa dela).
    col_active = active_params(full_spec, request)
    base_params = dict(col_active)
    base_params.update(sticky_params)
    if query:
        base_params['q'] = query
    if lens:
        base_params['lens'] = lens
    if sorts_ui:
        base_params['sort'] = sort_key
    qs_base = urlencode(base_params)

    # 5b) Export CSV da grelha filtrada (opt-in por grelha): a MESMA queryset,
    #     SEM paginação — o link da UI é um <a> normal fora do contrato HTMX.
    if csv_export and (request.GET.get('export') or '').strip() == 'csv':
        return _export_csv(request, qs=qs, columns=columns, decorate=decorate,
                           grid_key=grid_key, qs_base=qs_base)

    # 6) Paginação + decoração de apresentação (rótulos, .dot, .aria_code).
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get('page'))
    if decorate is not None:
        decorate(page_obj.object_list)

    # 8) Colunas no formato do template (nome + filtro emparelhado por param).
    fbar = {f['param']: f for f in filter_bar_context(full_spec, request)}
    columns_ctx = serialize_columns(columns, fbar)

    ctx = {
        'columns': columns_ctx,
        'page_obj': page_obj,
        'total': paginator.count,
        'has_filters': bool(col_active) or bool(query) or bool(sticky_params),
        'q': query,
        'sticky_params': sticky_params,
        'urgency_legend': legend,
        # Legenda dos marcadores de pendência (val_dot/pericia_dot) — visível
        # também em desktop (--always), só nas grelhas que os mostram.
        'pendency_legend': pendency_legend,
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
        # Link do export CSV (grelhas opt-in) com os filtros ativos embebidos.
        'csv_export_url': (
            f'{endpoint}?{qs_base + "&" if qs_base else ""}export=csv'
            if csv_export else ''
        ),
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if extra_ctx:
        ctx.update(extra_ctx)

    if ctx['is_htmx']:
        return render(request, 'partials/_grid.html', ctx)
    return render(request, page_template, ctx)
