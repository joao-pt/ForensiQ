'use strict';

/**
 * ForensiQ — Lista global de transições da cadeia de custódia.
 *
 * Modo cards (mobile) / tabela (desktop) gerido pelo componente DataTable.
 * Quando aplicado um filtro, o botão "Exportar CSV" reflecte os mesmos
 * filtros (URL é a fonte de verdade — o link tem download attr e
 * recebe o querystring actualizado em ``onCount``).
 */

let searchTimeout = null;
let dataTable = null;

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    populateStateFilter();
    mountDataTable();
    setupSearch();
    setupSidebarFilters();
    refreshExportLink();
});

function mountDataTable() {
    dataTable = DataTable.mount('#custody-list', {
        endpoint: CONFIG.ENDPOINTS.CUSTODY,
        defaultSort: '-timestamp',                 // mais recentes primeiro
        defaultPageSize: DataTable.effectiveRenderer() === 'cards' ? 20 : 50,
        rowHref: (row) => row.evidence
            ? `/evidences/${row.evidence}/custody/`
            : null,
        columns: [
            {
                key: 'code', label: 'Código',
                sortable: true, format: 'mono',
                width: '160px', sticky: true,
            },
            {
                key: 'evidence_code', label: 'Item',
                format: 'mono', width: '160px',
                render: (raw, row) => {
                    if (!row.evidence) return document.createTextNode(raw || '—');
                    const a = document.createElement('a');
                    a.href = `/evidences/${row.evidence}/`;
                    a.className = 'link mono';
                    a.textContent = raw || `#${row.evidence}`;
                    return a;
                },
            },
            {
                key: 'previous_state', label: 'De',
                hideBelow: 1024,
                render: (raw) => document.createTextNode(
                    raw ? (CONFIG.CUSTODY_STATES[raw] || raw) : '—',
                ),
            },
            {
                key: 'new_state', label: 'Para',
                sortable: true, width: '160px',
                render: (raw) => {
                    if (!raw) return document.createTextNode('—');
                    const pill = document.createElement('span');
                    pill.className = `state-pill state-${raw}`;
                    pill.textContent = CONFIG.CUSTODY_STATES[raw] || raw;
                    return pill;
                },
            },
            {
                key: 'agent_name', label: 'Custodiante',
                width: '160px', hideBelow: 1024,
            },
            {
                key: 'timestamp', label: 'Data/hora',
                sortable: true, format: 'datetime',
                width: '160px',
            },
        ],
        filters: [
            { key: 'new_state',   label: 'Estado', type: 'multi' },
            { key: 'date_after',  label: 'Desde',  type: 'date' },
            { key: 'date_before', label: 'Até',    type: 'date' },
        ],
        cardRenderer: (row) => renderCustodyCard(row),
        onCount: (n) => {
            const countEl = document.getElementById('custody-count');
            if (countEl) countEl.textContent = `${n} ${n === 1 ? 'transição' : 'transições'}`;
            const live = document.getElementById('results-announce');
            if (live) live.textContent = `${n} resultado${n !== 1 ? 's' : ''} após filtragem`;
            refreshExportLink();
        },
    });

    // Pré-popular inputs da sidebar a partir da URL.
    const urlParams = new URLSearchParams(window.location.search);
    const da = document.getElementById('filter-date-after');
    const db = document.getElementById('filter-date-before');
    if (da && urlParams.has('date_after')) da.value = urlParams.get('date_after');
    if (db && urlParams.has('date_before')) db.value = urlParams.get('date_before');
    urlParams.getAll('new_state').forEach((s) => {
        const cb = document.querySelector(`#filter-state-list input[value="${CSS.escape(s)}"]`);
        if (cb) cb.checked = true;
    });
}

function populateStateFilter() {
    const list = document.getElementById('filter-state-list');
    if (!list) return;
    list.replaceChildren();
    Object.entries(CONFIG.CUSTODY_STATES || {}).forEach(([key, label]) => {
        const wrap = document.createElement('label');
        wrap.className = 'form-checkbox';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = key;
        cb.dataset.role = 'filter-state';
        wrap.appendChild(cb);
        wrap.appendChild(document.createTextNode(' ' + label));
        list.appendChild(wrap);
    });
}

function setupSearch() {
    const input = document.getElementById('custody-search');
    if (!input) return;
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('search')) input.value = urlParams.get('search');
    input.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            if (dataTable) dataTable.setSearch(e.target.value.trim());
        }, 400);
    });
}

function setupSidebarFilters() {
    const da = document.getElementById('filter-date-after');
    const db = document.getElementById('filter-date-before');
    const clear = document.getElementById('filter-clear');

    if (da) da.addEventListener('change', () => dataTable && dataTable.setFilter('date_after', da.value || ''));
    if (db) db.addEventListener('change', () => dataTable && dataTable.setFilter('date_before', db.value || ''));

    document.querySelectorAll('#filter-state-list input[data-role="filter-state"]').forEach((cb) => {
        cb.addEventListener('change', () => {
            const checked = Array.from(
                document.querySelectorAll('#filter-state-list input[data-role="filter-state"]:checked')
            ).map((el) => el.value);
            if (dataTable) dataTable.setFilter('new_state', checked);
        });
    });

    if (clear) {
        clear.addEventListener('click', () => {
            if (da) da.value = '';
            if (db) db.value = '';
            document.querySelectorAll('#filter-state-list input').forEach((cb) => { cb.checked = false; });
            if (!dataTable) return;
            dataTable.setFilter('date_after', '');
            dataTable.setFilter('date_before', '');
            dataTable.setFilter('new_state', []);
        });
    }
}

/**
 * O href do botão "Exportar CSV" reflecte sempre o querystring actual,
 * para que o ficheiro descarregado corresponda ao que o utilizador vê.
 * Excluímos parâmetros internos de paginação (``page``, ``page_size``).
 */
function refreshExportLink() {
    const btn = document.getElementById('btn-export-csv');
    if (!btn) return;
    const params = new URLSearchParams(window.location.search);
    params.delete('page');
    params.delete('page_size');
    const qs = params.toString();
    btn.href = qs ? `/api/custody/csv/?${qs}` : '/api/custody/csv/';
}

function renderCustodyCard(rec) {
    const card = document.createElement('a');
    card.className = 'list-item';
    card.href = rec.evidence ? `/evidences/${rec.evidence}/custody/` : '#';

    const content = document.createElement('div');
    content.className = 'list-item-content';

    const head = document.createElement('div');
    head.className = 'list-item-title flex items-center gap-2';
    const code = document.createElement('span');
    code.className = 'mono-tab';
    code.textContent = rec.code || '—';
    head.appendChild(code);
    if (rec.new_state) {
        const pill = document.createElement('span');
        pill.className = `state-pill state-${rec.new_state}`;
        pill.textContent = CONFIG.CUSTODY_STATES[rec.new_state] || rec.new_state;
        head.appendChild(pill);
    }
    content.appendChild(head);

    if (rec.evidence_code) {
        const sub = document.createElement('span');
        sub.className = 'list-item-subtitle mono';
        sub.textContent = rec.evidence_code;
        content.appendChild(sub);
    }

    if (rec.agent_name) {
        const agent = document.createElement('span');
        agent.className = 'list-item-subtitle text-subtle';
        agent.textContent = rec.agent_name;
        content.appendChild(agent);
    }

    const meta = document.createElement('span');
    meta.className = 'list-item-meta mono-tab';
    if (rec.timestamp) {
        const d = new Date(rec.timestamp);
        meta.textContent = d.toLocaleDateString('pt-PT', {
            day: '2-digit', month: '2-digit',
            hour: '2-digit', minute: '2-digit',
        });
    }
    card.appendChild(content);
    card.appendChild(meta);
    return card;
}
