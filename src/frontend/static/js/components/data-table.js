/**
 * ForensiQ — DataTable component (modo tabela densa em desktop).
 *
 * Convive com o renderer de cards actual (mobile-first). O modo é
 * escolhido por viewport e pode ser sobreposto via localStorage
 * (`fq:listmode = auto|cards|table`). URLs como source of truth para
 * sort/filter/page (history.replaceState).
 *
 * Uso:
 *
 *   const dt = DataTable.mount('#occurrences-table', {
 *     endpoint: CONFIG.ENDPOINTS.OCCURRENCES,
 *     defaultSort: '-date_time',
 *     defaultPageSize: 50,
 *     rowHref: (row) => `/occurrences/${row.id}/`,
 *     columns: [
 *       { key: 'number', label: 'NUIPC', sortable: true, format: 'mono', width: '180px', sticky: true },
 *       { key: 'description', label: 'Descrição', truncate: 80 },
 *       { key: 'date_time', label: 'Data', sortable: true, format: 'date', width: '140px' },
 *       { key: 'agent.username', label: 'Agente', width: '140px', hideBelow: 1024 },
 *     ],
 *     filters: [
 *       { key: 'date_after',  label: 'Desde', type: 'date' },
 *       { key: 'date_before', label: 'Até',   type: 'date' },
 *       { key: 'has_gps',     label: 'Com GPS', type: 'boolean' },
 *     ],
 *     cardRenderer: (row) => renderRow(row),  // legacy mobile renderer
 *     extraParams: () => ({ state: currentStateFilter || undefined }),
 *     onCount: (n) => updateCountLabel(n),
 *   });
 *
 *   // Eventos externos (ex: search input partilhado entre cards e tabela):
 *   dt.setSearch('NUIPC-123');
 */

'use strict';

const DataTable = (function () {
    const MODE_KEY = 'fq:listmode';      // valores: auto|cards|table
    const MODE_VALID = new Set(['auto', 'cards', 'table']);
    const TABLE_BREAKPOINT = 768;        // px — limite cards/tabela em modo auto
    const SVG_NS = 'http://www.w3.org/2000/svg';

    function getMode() {
        const m = localStorage.getItem(MODE_KEY);
        return MODE_VALID.has(m) ? m : 'auto';
    }

    function setMode(mode) {
        if (!MODE_VALID.has(mode)) return;
        localStorage.setItem(MODE_KEY, mode);
    }

    function effectiveRenderer() {
        const mode = getMode();
        if (mode === 'cards' || mode === 'table') return mode;
        return (window.innerWidth || 0) >= TABLE_BREAKPOINT ? 'table' : 'cards';
    }

    // --------------------------------------------------------------
    // Helpers
    // --------------------------------------------------------------

    function getNested(obj, path) {
        if (!obj || !path) return undefined;
        return path.split('.').reduce((acc, k) => (acc == null ? acc : acc[k]), obj);
    }

    function formatValue(value, fmt) {
        if (value == null || value === '') return '—';
        switch (fmt) {
            case 'date':
                return formatDate(value);
            case 'datetime':
                return formatDateTime(value);
            case 'mono':
                return String(value);
            case 'badge-presence':
                return value ? '✓' : '—';
            default:
                return String(value);
        }
    }

    function formatDate(iso) {
        const d = new Date(iso);
        if (isNaN(d)) return '—';
        return d.toLocaleDateString('pt-PT', {
            day: '2-digit', month: 'short', year: 'numeric',
        });
    }

    function formatDateTime(iso) {
        const d = new Date(iso);
        if (isNaN(d)) return '—';
        return d.toLocaleString('pt-PT', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    }

    function truncate(s, max) {
        if (s == null) return '';
        const str = String(s);
        return str.length > max ? `${str.substring(0, max)}…` : str;
    }

    function chevronSvg() {
        const s = document.createElementNS(SVG_NS, 'svg');
        s.setAttribute('class', 'data-table-sort-icon');
        s.setAttribute('viewBox', '0 0 24 24');
        s.setAttribute('fill', 'none');
        s.setAttribute('stroke', 'currentColor');
        s.setAttribute('stroke-width', '2');
        s.setAttribute('aria-hidden', 'true');
        const p = document.createElementNS(SVG_NS, 'path');
        p.setAttribute('d', 'M6 9l6 6 6-6');
        p.setAttribute('stroke-linecap', 'round');
        p.setAttribute('stroke-linejoin', 'round');
        s.appendChild(p);
        return s;
    }

    // Coluna activa de sort: "-date_time" → { key: 'date_time', dir: 'desc' }.
    function parseOrdering(ordering) {
        if (!ordering) return { key: '', dir: '' };
        if (ordering.startsWith('-')) return { key: ordering.substring(1), dir: 'desc' };
        return { key: ordering, dir: 'asc' };
    }

    // Cicla sort: nenhum → asc → desc → volta a defaultSort.
    function nextSort(currentOrdering, columnKey, defaultSort) {
        const cur = parseOrdering(currentOrdering);
        if (cur.key !== columnKey) return columnKey;          // asc
        if (cur.dir === 'asc') return `-${columnKey}`;        // desc
        return defaultSort || '';                              // limpa
    }

    // --------------------------------------------------------------
    // URL <-> state sync
    // --------------------------------------------------------------

    function readStateFromUrl(state, schema) {
        const params = new URLSearchParams(window.location.search);
        if (params.has('page')) {
            const n = parseInt(params.get('page'), 10);
            if (Number.isFinite(n) && n > 0) state.page = n;
        }
        if (params.has('page_size')) {
            const n = parseInt(params.get('page_size'), 10);
            if (Number.isFinite(n) && n > 0) state.page_size = Math.min(n, 100);
        }
        if (params.has('ordering')) state.ordering = params.get('ordering');
        if (params.has('search')) state.search = params.get('search');
        (schema.filters || []).forEach((f) => {
            if (params.has(f.key)) {
                const all = params.getAll(f.key);
                state.filters[f.key] = all.length > 1 ? all : all[0];
            }
        });
    }

    function writeStateToUrl(state, schema, extra) {
        const params = new URLSearchParams();
        if (state.page > 1) params.set('page', String(state.page));
        if (state.page_size) params.set('page_size', String(state.page_size));
        if (state.ordering) params.set('ordering', state.ordering);
        if (state.search) params.set('search', state.search);
        (schema.filters || []).forEach((f) => {
            const v = state.filters[f.key];
            if (v == null || v === '' || (Array.isArray(v) && v.length === 0)) return;
            if (Array.isArray(v)) {
                v.forEach((vv) => params.append(f.key, vv));
            } else {
                params.set(f.key, String(v));
            }
        });
        // Parâmetros externos (ex: ?state=APREENDIDA vindo do dashboard) também
        // ficam na URL — bookmarkable e shareable.
        Object.entries(extra || {}).forEach(([k, v]) => {
            if (v == null || v === '') return;
            params.set(k, String(v));
        });
        const qs = params.toString();
        const next = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
        window.history.replaceState(null, '', next);
    }

    // --------------------------------------------------------------
    // Mount
    // --------------------------------------------------------------

    function mount(container, schema) {
        const root = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        if (!root) {
            console.error('[DataTable] container não encontrado:', container);
            return null;
        }

        const state = {
            page: 1,
            page_size: schema.defaultPageSize || 50,
            ordering: schema.defaultSort || '',
            search: '',
            filters: {},
            total: 0,
            results: [],
            requestSeq: 0,
            renderer: effectiveRenderer(),
        };

        readStateFromUrl(state, schema);

        // Marca o renderer escolhido no DOM para CSS (responsive guard).
        root.classList.add('data-table-host');
        root.dataset.renderer = state.renderer;

        // Listener de redimensionamento — só relevante em modo "auto".
        let resizeTimer = null;
        const onResize = () => {
            if (getMode() !== 'auto') return;
            window.clearTimeout(resizeTimer);
            resizeTimer = window.setTimeout(() => {
                const next = effectiveRenderer();
                if (next !== state.renderer) {
                    state.renderer = next;
                    root.dataset.renderer = next;
                    render();
                }
            }, 150);
        };
        window.addEventListener('resize', onResize);

        // popstate — utilizador carrega "back" do browser.
        const onPopState = () => {
            // Reset state e relê a URL.
            state.page = 1;
            state.page_size = schema.defaultPageSize || 50;
            state.ordering = schema.defaultSort || '';
            state.search = '';
            state.filters = {};
            readStateFromUrl(state, schema);
            fetchAndRender();
        };
        window.addEventListener('popstate', onPopState);

        // --------------------------------------------------------
        // Fetch
        // --------------------------------------------------------

        async function fetchAndRender() {
            const seq = ++state.requestSeq;
            renderLoading();
            const params = {
                page: state.page,
                page_size: state.page_size,
            };
            if (state.ordering) params.ordering = state.ordering;
            if (state.search) params.search = state.search;
            Object.entries(state.filters).forEach(([k, v]) => {
                if (v == null || v === '') return;
                params[k] = Array.isArray(v) ? v.join(',') : v;
            });
            const extra = typeof schema.extraParams === 'function'
                ? (schema.extraParams() || {}) : {};
            Object.entries(extra).forEach(([k, v]) => {
                if (v != null && v !== '') params[k] = v;
            });

            try {
                const data = await API.get(schema.endpoint, params);
                if (seq !== state.requestSeq) return; // stale
                state.results = data.results || [];
                state.total = data.count || 0;
                state.next = data.next;
                state.previous = data.previous;
                writeStateToUrl(state, schema, extra);
                if (typeof schema.onCount === 'function') {
                    schema.onCount(state.total);
                }
                render();
            } catch (err) {
                if (seq !== state.requestSeq) return;
                renderError(err);
            }
        }

        // --------------------------------------------------------
        // Render — entry point
        // --------------------------------------------------------

        function render() {
            if (state.renderer === 'cards') {
                renderCards();
            } else {
                renderTable();
            }
        }

        function renderLoading() {
            root.replaceChildren();
            const skel = document.createElement('div');
            skel.className = 'data-table-skeleton';
            skel.setAttribute('aria-busy', 'true');
            for (let i = 0; i < 3; i++) {
                const line = document.createElement('div');
                line.className = 'data-table-skeleton-row';
                skel.appendChild(line);
            }
            root.appendChild(skel);
        }

        function renderError(err) {
            root.replaceChildren();
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            const title = document.createElement('div');
            title.className = 'empty-state-title text-danger';
            title.textContent = 'Erro ao carregar';
            const p = document.createElement('p');
            p.textContent = (err && err.message) || 'Verifica a ligação e tenta recarregar.';
            empty.appendChild(title);
            empty.appendChild(p);
            root.appendChild(empty);
        }

        function renderEmpty() {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            const title = document.createElement('div');
            title.className = 'empty-state-title';
            title.textContent = state.search
                ? `Sem resultados para "${state.search}"`
                : 'Sem registos';
            const p = document.createElement('p');
            p.textContent = state.search
                ? 'Tenta outro termo de pesquisa.'
                : 'A listagem está vazia.';
            empty.appendChild(title);
            empty.appendChild(p);
            return empty;
        }

        // --------------------------------------------------------
        // Cards (mobile / override)
        // --------------------------------------------------------

        function renderCards() {
            root.replaceChildren();
            if (state.results.length === 0) {
                root.appendChild(renderEmpty());
                return;
            }
            const list = document.createElement('div');
            list.className = 'list';
            const cardRenderer = schema.cardRenderer || defaultCardRenderer;
            state.results.forEach((row) => {
                const node = cardRenderer(row, schema);
                if (node) list.appendChild(node);
            });
            root.appendChild(list);
            root.appendChild(renderPagination());
        }

        function defaultCardRenderer(row) {
            const a = document.createElement('a');
            a.className = 'list-item';
            a.href = schema.rowHref ? schema.rowHref(row) : '#';
            const content = document.createElement('div');
            content.className = 'list-item-content';
            const title = document.createElement('span');
            title.className = 'list-item-title';
            const firstCol = (schema.columns || [])[0];
            title.textContent = firstCol ? formatValue(getNested(row, firstCol.key), firstCol.format) : (row.id || '');
            content.appendChild(title);
            a.appendChild(content);
            return a;
        }

        // --------------------------------------------------------
        // Table (desktop)
        // --------------------------------------------------------

        function renderTable() {
            root.replaceChildren();

            const wrap = document.createElement('div');
            wrap.className = 'data-table-wrap card p-0';

            const table = document.createElement('table');
            table.className = 'data-table';
            table.setAttribute('role', 'table');

            table.appendChild(buildThead());
            table.appendChild(buildTbody());

            wrap.appendChild(table);
            root.appendChild(wrap);
            root.appendChild(renderPagination());
        }

        function buildThead() {
            const thead = document.createElement('thead');
            const tr = document.createElement('tr');
            const cur = parseOrdering(state.ordering);
            (schema.columns || []).forEach((col) => {
                const th = document.createElement('th');
                th.scope = 'col';
                if (col.width) th.style.width = col.width;
                if (col.sticky) th.classList.add('data-table-sticky-col');
                if (col.hideBelow) th.dataset.hideBelow = String(col.hideBelow);
                if (col.align) th.style.textAlign = col.align;

                if (col.sortable) {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'data-table-sort-btn';
                    btn.textContent = col.label;
                    btn.appendChild(chevronSvg());

                    if (cur.key === col.key) {
                        th.setAttribute('aria-sort', cur.dir === 'asc' ? 'ascending' : 'descending');
                        btn.classList.add('is-active');
                        if (cur.dir === 'desc') btn.classList.add('is-desc');
                    } else {
                        th.setAttribute('aria-sort', 'none');
                    }

                    btn.addEventListener('click', () => {
                        state.ordering = nextSort(state.ordering, col.key, schema.defaultSort);
                        state.page = 1;
                        fetchAndRender();
                    });
                    th.appendChild(btn);
                } else {
                    th.textContent = col.label;
                }
                tr.appendChild(th);
            });
            thead.appendChild(tr);
            return thead;
        }

        function buildTbody() {
            const tbody = document.createElement('tbody');
            if (state.results.length === 0) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = (schema.columns || []).length || 1;
                td.appendChild(renderEmpty());
                tr.appendChild(td);
                tbody.appendChild(tr);
                return tbody;
            }
            state.results.forEach((row) => {
                const tr = document.createElement('tr');
                tr.className = 'data-table-row';
                const href = schema.rowHref ? schema.rowHref(row) : null;
                if (href) {
                    tr.tabIndex = 0;
                    tr.role = 'link';
                    tr.dataset.href = href;
                    tr.addEventListener('click', (e) => {
                        // Não navegar quando o utilizador carrega num link interno
                        // (ex: chip de filtro futuro). Só linhas-inteiras.
                        if (e.target.closest('a, button')) return;
                        window.location.assign(href);
                    });
                    tr.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            window.location.assign(href);
                        }
                    });
                }
                (schema.columns || []).forEach((col) => {
                    const td = document.createElement('td');
                    if (col.sticky) td.classList.add('data-table-sticky-col');
                    if (col.hideBelow) td.dataset.hideBelow = String(col.hideBelow);
                    if (col.align) td.style.textAlign = col.align;
                    if (col.format === 'mono') td.classList.add('mono-tab');

                    const raw = getNested(row, col.key);
                    let text;
                    if (typeof col.render === 'function') {
                        const node = col.render(raw, row);
                        if (node instanceof Node) {
                            td.appendChild(node);
                        } else {
                            td.textContent = String(node ?? '—');
                        }
                    } else if (col.truncate) {
                        text = truncate(formatValue(raw, col.format), col.truncate);
                        td.textContent = text;
                        if (typeof raw === 'string' && raw.length > col.truncate) {
                            td.title = raw;
                        }
                    } else {
                        text = formatValue(raw, col.format);
                        td.textContent = text;
                    }
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
            return tbody;
        }

        // --------------------------------------------------------
        // Paginação (cards e tabela partilham)
        // --------------------------------------------------------

        function renderPagination() {
            const bar = document.createElement('div');
            bar.className = 'data-table-pagination';

            const totalPages = Math.max(1, Math.ceil(state.total / state.page_size));
            const from = state.total === 0 ? 0 : (state.page - 1) * state.page_size + 1;
            const to = Math.min(state.total, state.page * state.page_size);

            const info = document.createElement('span');
            info.className = 'data-table-pagination-info text-muted text-sm';
            info.textContent = state.total === 0
                ? '0 registos'
                : `${from}-${to} de ${state.total}`;

            const prev = document.createElement('button');
            prev.type = 'button';
            prev.className = 'btn btn-ghost btn-sm';
            prev.textContent = '← Anterior';
            prev.disabled = !state.previous;
            prev.addEventListener('click', () => {
                if (state.page > 1) {
                    state.page -= 1;
                    fetchAndRender();
                }
            });

            const pageLabel = document.createElement('span');
            pageLabel.className = 'data-table-pagination-page text-sm';
            pageLabel.textContent = `Página ${state.page} de ${totalPages}`;

            const next = document.createElement('button');
            next.type = 'button';
            next.className = 'btn btn-ghost btn-sm';
            next.textContent = 'Seguinte →';
            next.disabled = !state.next;
            next.addEventListener('click', () => {
                state.page += 1;
                fetchAndRender();
            });

            // Page-size selector — só em tabela (cards estão fixos a 20).
            if (state.renderer === 'table' && schema.pageSizeOptions !== false) {
                const sizes = schema.pageSizeOptions || [20, 50, 100];
                const sel = document.createElement('select');
                sel.className = 'form-input data-table-pagination-size';
                sel.setAttribute('aria-label', 'Itens por página');
                sizes.forEach((n) => {
                    const opt = document.createElement('option');
                    opt.value = String(n);
                    opt.textContent = `${n} / pág.`;
                    if (n === state.page_size) opt.selected = true;
                    sel.appendChild(opt);
                });
                sel.addEventListener('change', () => {
                    state.page_size = parseInt(sel.value, 10) || 50;
                    state.page = 1;
                    fetchAndRender();
                });
                bar.appendChild(sel);
            }

            bar.appendChild(prev);
            bar.appendChild(pageLabel);
            bar.appendChild(next);
            bar.appendChild(info);
            return bar;
        }

        // --------------------------------------------------------
        // API pública do controlador
        // --------------------------------------------------------

        function setSearch(value) {
            const v = (value || '').trim();
            if (v === state.search) return;
            state.search = v;
            state.page = 1;
            fetchAndRender();
        }

        function setFilter(key, value) {
            state.filters[key] = value;
            state.page = 1;
            fetchAndRender();
        }

        function reload() {
            fetchAndRender();
        }

        function destroy() {
            window.removeEventListener('resize', onResize);
            window.removeEventListener('popstate', onPopState);
            root.replaceChildren();
            root.classList.remove('data-table-host');
            delete root.dataset.renderer;
        }

        // Arranque
        fetchAndRender();

        return {
            setSearch,
            setFilter,
            reload,
            destroy,
            getState: () => ({ ...state }),
        };
    }

    return { mount, getMode, setMode, effectiveRenderer };
})();
