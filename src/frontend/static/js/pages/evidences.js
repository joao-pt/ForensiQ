'use strict';

/**
 * ForensiQ — Lista de itens de prova (cards mobile, tabela densa desktop).
 *
 * O renderer é decidido pelo componente DataTable. ``renderEvidenceItem``
 * continua a desenhar o card legado e é passado como ``cardRenderer``
 * (preserva mobile-first sem tocar na lógica de badges/photo/GPS).
 */

let searchTimeout = null;
let currentStateFilter = null;
let dataTable = null;

// Fallback local — preenchido preferencialmente via CONFIG.EVIDENCE_BADGE_COLORS
const TYPE_COLORS = {
    'MOBILE_DEVICE': 'blue',
    'COMPUTER': 'blue',
    'STORAGE_MEDIA': 'green',
    'VEHICLE': 'red',
    'OTHER_DIGITAL': 'default',
};

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    if (user && user.profile !== 'AGENT') {
        const btnNew = document.getElementById('btn-new-evidence');
        if (btnNew) btnNew.hidden = true;
        const fab = document.querySelector('.fab');
        if (fab) fab.hidden = true;
    }

    const params = new URLSearchParams(window.location.search);
    currentStateFilter = params.get('state');
    renderStateFilterChip();

    populateTypeFilter();
    mountDataTable();
    setupSearch();
    setupSidebarFilters();
});

function mountDataTable() {
    dataTable = DataTable.mount('#evidences-list', {
        endpoint: CONFIG.ENDPOINTS.EVIDENCES,
        defaultSort: '-timestamp_seizure',
        defaultPageSize: DataTable.effectiveRenderer() === 'cards' ? 20 : 50,
        rowHref: (row) => `/evidences/${row.id}/`,
        columns: [
            {
                key: 'code', label: 'Código',
                sortable: true, format: 'mono',
                width: '160px', sticky: true,
            },
            {
                key: 'type', label: 'Tipo',
                sortable: true, width: '180px',
                render: (raw) => {
                    const span = document.createElement('span');
                    span.textContent = CONFIG.EVIDENCE_TYPES[raw] || raw || '—';
                    return span;
                },
            },
            {
                key: 'description', label: 'Descrição',
                truncate: 90,
            },
            {
                key: 'occurrence_number', label: 'NUIPC',
                format: 'mono', width: '160px', hideBelow: 1024,
            },
            {
                key: 'timestamp_seizure', label: 'Apreendido',
                sortable: true, format: 'date',
                width: '140px',
            },
            {
                key: 'photo', label: 'Foto',
                width: '60px', align: 'center',
                render: (raw) => document.createTextNode(raw ? '✓' : '—'),
            },
            {
                key: 'gps_lat', label: 'GPS',
                width: '60px', align: 'center',
                format: 'badge-presence',
            },
        ],
        filters: [
            { key: 'type',        label: 'Tipo',          type: 'multi' },
            { key: 'date_after',  label: 'Desde',         type: 'date' },
            { key: 'date_before', label: 'Até',           type: 'date' },
            { key: 'has_gps',     label: 'Com GPS',       type: 'boolean' },
        ],
        cardRenderer: (row) => renderEvidenceItem(row),
        extraParams: () => (currentStateFilter ? { state: currentStateFilter } : {}),
        onCount: (n) => {
            const countEl = document.getElementById('evidences-count');
            if (countEl) countEl.textContent = `${n} ${n === 1 ? 'item' : 'itens'}`;
            const live = document.getElementById('results-announce');
            if (live) live.textContent = `${n} resultado${n !== 1 ? 's' : ''} após filtragem`;
            refreshExportLink();
        },
    });

    // Pré-popular inputs da sidebar a partir da URL.
    const urlParams = new URLSearchParams(window.location.search);
    const da = document.getElementById('filter-date-after');
    const db = document.getElementById('filter-date-before');
    const hg = document.getElementById('filter-has-gps');
    if (da && urlParams.has('date_after')) da.value = urlParams.get('date_after');
    if (db && urlParams.has('date_before')) db.value = urlParams.get('date_before');
    if (hg && urlParams.has('has_gps')) hg.checked = urlParams.get('has_gps') === 'true';
    // Pré-marcar tipos seleccionados.
    const selectedTypes = urlParams.getAll('type');
    selectedTypes.forEach((t) => {
        const cb = document.querySelector(`#filter-type-list input[value="${CSS.escape(t)}"]`);
        if (cb) cb.checked = true;
    });
}

function populateTypeFilter() {
    const list = document.getElementById('filter-type-list');
    if (!list) return;
    list.replaceChildren();
    const types = CONFIG.EVIDENCE_TYPES || {};
    Object.entries(types).forEach(([key, label]) => {
        const wrap = document.createElement('label');
        wrap.className = 'form-checkbox';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = key;
        cb.dataset.role = 'filter-type';
        wrap.appendChild(cb);
        wrap.appendChild(document.createTextNode(' ' + label));
        list.appendChild(wrap);
    });
}

function setupSearch() {
    const input = document.getElementById('search-input');
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
    const hg = document.getElementById('filter-has-gps');
    const clear = document.getElementById('filter-clear');

    if (da) da.addEventListener('change', () => dataTable && dataTable.setFilter('date_after', da.value || ''));
    if (db) db.addEventListener('change', () => dataTable && dataTable.setFilter('date_before', db.value || ''));
    if (hg) hg.addEventListener('change', () => dataTable && dataTable.setFilter('has_gps', hg.checked ? 'true' : ''));

    document.querySelectorAll('#filter-type-list input[data-role="filter-type"]').forEach((cb) => {
        cb.addEventListener('change', () => {
            const checked = Array.from(
                document.querySelectorAll('#filter-type-list input[data-role="filter-type"]:checked')
            ).map((el) => el.value);
            if (dataTable) dataTable.setFilter('type', checked);
        });
    });

    if (clear) {
        clear.addEventListener('click', () => {
            if (da) da.value = '';
            if (db) db.value = '';
            if (hg) hg.checked = false;
            document.querySelectorAll('#filter-type-list input').forEach((cb) => { cb.checked = false; });
            if (!dataTable) return;
            dataTable.setFilter('date_after', '');
            dataTable.setFilter('date_before', '');
            dataTable.setFilter('has_gps', '');
            dataTable.setFilter('type', []);
        });
    }
}

function refreshExportLink() {
    const btn = document.getElementById('btn-export-csv');
    if (!btn) return;
    const params = new URLSearchParams(window.location.search);
    params.delete('page');
    params.delete('page_size');
    const qs = params.toString();
    btn.href = qs ? `/api/evidences/csv/?${qs}` : '/api/evidences/csv/';
}

function renderStateFilterChip() {
    if (!currentStateFilter) return;
    const countEl = document.getElementById('evidences-count');
    if (!countEl) return;

    const stateLabels = {
        'APREENDIDA': 'Apreendido',
        'EM_TRANSPORTE': 'Em trânsito',
        'RECEBIDA_LABORATORIO': 'Recebido no laboratório',
        'EM_PERICIA': 'Em perícia',
        'CONCLUIDA': 'Concluído',
        'DEVOLVIDA': 'Devolvido',
        'DESTRUIDA': 'Destruído',
    };
    const label = stateLabels[currentStateFilter] || currentStateFilter;

    const chip = document.createElement('span');
    chip.className = 'badge badge-info ml-2';
    chip.textContent = `Filtrado: ${label}`;
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'btn-icon-inline';
    clear.setAttribute('aria-label', 'Limpar filtro');
    clear.textContent = ' ✕';
    clear.addEventListener('click', () => {
        window.location.href = '/evidences/';
    });
    chip.appendChild(clear);
    countEl.appendChild(chip);
}

// ----------------------------------------------------------
// Card renderer (modo mobile / fq:listmode=cards)
// ----------------------------------------------------------
function renderEvidenceItem(ev) {
    const date = new Date(ev.timestamp_seizure).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const typeName = CONFIG.EVIDENCE_TYPES[ev.type] || ev.type;
    const color = (CONFIG.EVIDENCE_BADGE_COLORS && CONFIG.EVIDENCE_BADGE_COLORS[ev.type])
        || TYPE_COLORS[ev.type]
        || 'default';

    const row = document.createElement('a');
    row.className = 'list-item evidences-row';
    row.href = `/evidences/${ev.id}/`;

    const left = document.createElement('div');
    left.className = 'evidences-row-left';

    const badges = document.createElement('div');
    badges.className = 'evidences-row-badges';

    const typeBadge = document.createElement('span');
    typeBadge.className = `badge badge-${color}`;
    const typeIcon = Icons.forEvidenceElement(ev.type, { size: 12 });
    if (typeIcon) typeBadge.appendChild(typeIcon);
    const typeLabel = document.createElement('span');
    typeLabel.textContent = typeName;
    typeBadge.appendChild(typeLabel);
    badges.appendChild(typeBadge);

    if (ev.parent_evidence) {
        const sub = document.createElement('span');
        sub.className = 'badge badge-default';
        const parentLabel = ev.parent_evidence_label || `Item ${ev.parent_evidence}`;
        sub.title = 'Componente integrante de ' + parentLabel;
        const truncated = parentLabel.length > 30
            ? parentLabel.substring(0, 30) + '…'
            : parentLabel;
        sub.textContent = `↳ ${truncated}`;
        badges.appendChild(sub);
    }

    if (ev.photo) {
        const b = document.createElement('span');
        b.className = 'badge badge-success';
        b.title = 'Com fotografia';
        b.setAttribute('aria-label', 'Com fotografia');
        const ic = Icons.element('shield', { size: 12 });
        if (ic) b.appendChild(ic);
        badges.appendChild(b);
    }
    if (ev.gps_lat && ev.gps_lon) {
        const b = document.createElement('span');
        b.className = 'badge badge-success';
        b.title = 'Com GPS';
        b.setAttribute('aria-label', 'Com GPS');
        const ic = Icons.element('map-pin', { size: 12 });
        if (ic) b.appendChild(ic);
        badges.appendChild(b);
    }

    const idTag = document.createElement('small');
    idTag.className = 'text-muted mono';
    idTag.textContent = ev.code || '';
    if (ev.code) badges.appendChild(idTag);

    left.appendChild(badges);

    const desc = document.createElement('div');
    desc.className = 'mt-4 evidences-row-desc';
    const fullDesc = ev.description || '';
    desc.textContent = fullDesc.length > 80 ? `${fullDesc.substring(0, 80)}…` : fullDesc;
    left.appendChild(desc);

    const occLine = document.createElement('div');
    occLine.className = 'text-muted evidences-row-meta';
    const nuipc = ev.occurrence_number || ev.occurrence_code || '—';
    occLine.textContent = `Caso: ${nuipc}`;
    left.appendChild(occLine);

    const right = document.createElement('div');
    right.className = 'evidences-row-right';

    const dateEl = document.createElement('div');
    dateEl.className = 'text-muted evidences-row-date';
    dateEl.textContent = date;
    right.appendChild(dateEl);

    const arrow = Icons.element('chevron-right', { size: 16 });
    if (arrow) {
        arrow.classList.add('evidences-row-chevron');
        right.appendChild(arrow);
    }

    row.appendChild(left);
    row.appendChild(right);
    return row;
}
