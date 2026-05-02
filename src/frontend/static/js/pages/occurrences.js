'use strict';

/**
 * ForensiQ — Lista de ocorrências (cards em mobile, tabela densa em desktop).
 *
 * O renderer é escolhido pelo componente `DataTable` (viewport / localStorage
 * `fq:listmode`). A função ``renderRow`` continua a construir o card legacy —
 * é passada como ``cardRenderer`` para preservar mobile-first sem refactor.
 *
 * O painel "Mapa" continua a ser servido pela mesma instância via tabs.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

let searchTimeout = null;
let allOccurrences = [];
let leafletMap = null;
let mapInitialized = false;
let currentView = 'list';
let currentStateFilter = null;
let dataTable = null;

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    if (user && user.profile !== 'AGENT') {
        const btnNew = document.getElementById('btn-new-occurrence');
        if (btnNew) btnNew.style.display = 'none';
    }

    setupTabs();

    const urlParams = new URLSearchParams(window.location.search);
    currentStateFilter = urlParams.get('state');
    renderStateFilterChip();

    mountDataTable();
    setupSearch();
    setupSidebarFilters();
    loadAllOccurrencesForMap();
});

// ----------------------------------------------------------
// DataTable mount
// ----------------------------------------------------------
function mountDataTable() {
    dataTable = DataTable.mount('#occurrences-list', {
        endpoint: CONFIG.ENDPOINTS.OCCURRENCES,
        defaultSort: '-date_time',
        defaultPageSize: DataTable.effectiveRenderer() === 'cards' ? 20 : 50,
        rowHref: (row) => `/occurrences/${row.id}/`,
        columns: [
            {
                key: 'number', label: 'NUIPC',
                sortable: true, format: 'mono',
                width: '160px', sticky: true,
            },
            {
                key: 'description', label: 'Descrição',
                truncate: 90,
            },
            {
                key: 'address', label: 'Morada',
                truncate: 50, hideBelow: 1024,
            },
            {
                key: 'date_time', label: 'Data',
                sortable: true, format: 'date',
                width: '140px',
            },
            {
                key: 'agent.username', label: 'Agente',
                width: '140px', hideBelow: 1024,
            },
            {
                key: 'gps_lat', label: 'GPS',
                format: 'badge-presence', width: '60px', align: 'center',
            },
        ],
        filters: [
            { key: 'date_after',  label: 'Desde', type: 'date' },
            { key: 'date_before', label: 'Até',   type: 'date' },
            { key: 'has_gps',     label: 'Com GPS', type: 'boolean' },
        ],
        cardRenderer: (row) => renderRow(row),
        extraParams: () => (currentStateFilter ? { state: currentStateFilter } : {}),
        onCount: (n) => {
            const countEl = document.getElementById('occurrences-count');
            if (countEl && currentView === 'list') {
                countEl.textContent = `${n} ocorrência${n !== 1 ? 's' : ''}`;
            }
        },
    });

    // Inicializar inputs da sidebar a partir da URL.
    const urlParams = new URLSearchParams(window.location.search);
    const da = document.getElementById('filter-date-after');
    const db = document.getElementById('filter-date-before');
    const hg = document.getElementById('filter-has-gps');
    if (da && urlParams.has('date_after')) da.value = urlParams.get('date_after');
    if (db && urlParams.has('date_before')) db.value = urlParams.get('date_before');
    if (hg && urlParams.has('has_gps')) hg.checked = urlParams.get('has_gps') === 'true';
}

function setupSearch() {
    const input = document.getElementById('search-input');
    if (!input) return;

    // Pré-popular a partir da URL.
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

    if (clear) {
        clear.addEventListener('click', () => {
            if (da) da.value = '';
            if (db) db.value = '';
            if (hg) hg.checked = false;
            if (!dataTable) return;
            dataTable.setFilter('date_after', '');
            dataTable.setFilter('date_before', '');
            dataTable.setFilter('has_gps', '');
        });
    }
}

function renderStateFilterChip() {
    if (!currentStateFilter) return;
    const countEl = document.getElementById('occurrences-count');
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
        window.location.href = '/occurrences/';
    });
    chip.appendChild(clear);
    countEl.appendChild(chip);
}

// ----------------------------------------------------------
// Segmented control Lista / Mapa — ARIA tabs pattern com roving tabindex
// (audit #18). Teclado: ← → muda tab, Home / End saltam para extremos.
// ----------------------------------------------------------
function setupTabs() {
    const tabList = document.getElementById('tab-list');
    const tabMap  = document.getElementById('tab-map');
    const tabs    = [tabList, tabMap];

    tabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            activateTab(tab);
        });
        tab.addEventListener('keydown', (e) => {
            let target = null;
            const idx = tabs.indexOf(tab);
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                target = tabs[(idx + 1) % tabs.length];
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                target = tabs[(idx - 1 + tabs.length) % tabs.length];
            } else if (e.key === 'Home') {
                target = tabs[0];
            } else if (e.key === 'End') {
                target = tabs[tabs.length - 1];
            }
            if (target) {
                e.preventDefault();
                target.focus();
                activateTab(target);
            }
        });
    });

    updateRovingFocus(tabList);
}

function updateRovingFocus(activeTab) {
    ['tab-list', 'tab-map'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.tabIndex = el === activeTab ? 0 : -1;
    });
}

function activateTab(tab) {
    const view = tab.id === 'tab-map' ? 'map' : 'list';
    updateRovingFocus(tab);
    switchView(view);
}

function switchView(view) {
    currentView = view;
    const panelList = document.getElementById('panel-list');
    const panelMap  = document.getElementById('panel-map');
    const tabList   = document.getElementById('tab-list');
    const tabMap    = document.getElementById('tab-map');

    if (view === 'map') {
        panelList.hidden = true;
        panelMap.hidden  = false;
        tabList.classList.remove('active');
        tabList.setAttribute('aria-selected', 'false');
        tabMap.classList.add('active');
        tabMap.setAttribute('aria-selected', 'true');

        if (!mapInitialized) {
            initMap();
            setTimeout(() => leafletMap.invalidateSize(), 150);
        } else {
            leafletMap.invalidateSize();
        }
    } else {
        panelList.hidden = false;
        panelMap.hidden  = true;
        tabList.classList.add('active');
        tabList.setAttribute('aria-selected', 'true');
        tabMap.classList.remove('active');
        tabMap.setAttribute('aria-selected', 'false');
    }
}

// ----------------------------------------------------------
// Mapa Leaflet
// ----------------------------------------------------------
function initMap() {
    mapInitialized = true;

    leafletMap = L.map('map-container', {
        center: [39.5, -8.0],
        zoom: 7,
        zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
    }).addTo(leafletMap);

    if (allOccurrences.length > 0) addMarkersToMap(allOccurrences);
}

async function loadAllOccurrencesForMap() {
    try {
        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 100 });
        allOccurrences = data.results || [];
        if (mapInitialized) addMarkersToMap(allOccurrences);
    } catch (err) {
        console.error('Erro ao carregar ocorrências para mapa:', err);
    }
}

function makeMarkerIcon() {
    return L.divIcon({
        className: 'fq-marker',
        html: '<span class="status-dot accent fq-marker-dot"></span>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
    });
}

function buildPopupNode(occ) {
    const dt = new Date(occ.date_time).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
    });
    const full = occ.description || '';

    const root = document.createElement('div');

    const num = document.createElement('strong');
    num.textContent = occ.number;
    root.appendChild(num);

    const desc = document.createElement('div');
    desc.className = 'popup-desc';
    desc.textContent = full.length > 80 ? `${full.substring(0, 80)}…` : full;
    root.appendChild(desc);

    if (occ.address) {
        const addr = document.createElement('div');
        addr.className = 'popup-date';
        addr.textContent = occ.address;
        root.appendChild(addr);
    }

    const date = document.createElement('div');
    date.className = 'popup-date';
    date.textContent = dt;
    root.appendChild(date);

    const link = document.createElement('a');
    link.href = `/occurrences/${occ.id}/`;
    link.textContent = 'Abrir caso →';
    root.appendChild(link);

    return root;
}

function addMarkersToMap(occurrences) {
    if (!leafletMap) return;

    const icon = makeMarkerIcon();
    const bounds = [];
    let added = 0;

    occurrences.forEach(occ => {
        if (!occ.gps_lat || !occ.gps_lon) return;
        const lat = parseFloat(occ.gps_lat);
        const lon = parseFloat(occ.gps_lon);
        if (isNaN(lat) || isNaN(lon)) return;

        L.marker([lat, lon], { icon })
            .bindPopup(buildPopupNode(occ), { maxWidth: 260 })
            .addTo(leafletMap);

        bounds.push([lat, lon]);
        added++;
    });

    if (bounds.length > 0) {
        leafletMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
    }

    if (currentView === 'map') {
        const countEl = document.getElementById('occurrences-count');
        if (countEl) {
            countEl.textContent = `${added} de ${occurrences.length} com GPS`;
        }
    }
}

// ----------------------------------------------------------
// Card renderer (modo mobile / fq:listmode=cards) — preserva o layout
// .list-item original. Usado pelo DataTable para mobile-first.
// ----------------------------------------------------------
function renderRow(occ) {
    const hasGps = !!(occ.gps_lat && occ.gps_lon);

    const row = document.createElement('a');
    row.className = 'list-item';
    row.href = `/occurrences/${occ.id}/`;

    const content = document.createElement('div');
    content.className = 'list-item-content';

    const head = document.createElement('div');
    head.className = 'list-item-title mono-tab flex items-center gap-2';
    const num = document.createElement('span');
    num.textContent = occ.number;
    head.appendChild(num);
    if (hasGps) {
        const badge = document.createElement('span');
        badge.className = 'badge badge-success';
        badge.title = 'GPS registado';
        badge.textContent = 'GPS';
        head.appendChild(badge);
    }
    content.appendChild(head);

    const subtitle = document.createElement('span');
    subtitle.className = 'list-item-subtitle';
    const desc = (occ.description || '').trim();
    subtitle.textContent = desc.length > 120 ? desc.substring(0, 120) + '…' : desc;
    content.appendChild(subtitle);

    if (occ.address) {
        const addr = document.createElement('span');
        addr.className = 'list-item-subtitle text-subtle';
        addr.textContent = occ.address;
        content.appendChild(addr);
    }

    const meta = document.createElement('span');
    meta.className = 'list-item-meta mono-tab';
    meta.textContent = formatDate(occ.date_time);

    row.appendChild(content);
    row.appendChild(meta);
    row.appendChild(chevron());
    return row;
}

function chevron() {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('class', 'list-item-chevron');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8');
    s.setAttribute('aria-hidden', 'true');
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', 'm9 18 6-6-6-6');
    p.setAttribute('stroke-linecap', 'round');
    p.setAttribute('stroke-linejoin', 'round');
    s.appendChild(p);
    return s;
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    return d.toLocaleDateString('pt-PT', {
        day: '2-digit', month: 'short',
        hour: '2-digit', minute: '2-digit',
    });
}
