'use strict';

/**
 * ForensiQ — Lista de ocorrências (lista + mapa).
 *
 * Usa as primitives de .list-item do design system. Mapa Leaflet com
 * markers e popups tokenizados.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

let currentPage = 1;
let searchTimeout = null;
let allOccurrences = [];
let leafletMap = null;
let mapInitialized = false;
let currentView = 'list';

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    if (user && user.profile !== 'AGENT') {
        const btnNew = document.getElementById('btn-new-occurrence');
        if (btnNew) btnNew.style.display = 'none';
    }

    setupTabs();

    document.getElementById('search-input').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentPage = 1;
            loadOccurrences(e.target.value.trim());
        }, 400);
    });

    loadOccurrences();
    loadAllOccurrencesForMap();
});

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

    // Estado inicial de tabindex (roving)
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
        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 200 });
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
// Lista
// ----------------------------------------------------------
async function loadOccurrences(search = '') {
    const container = document.getElementById('occurrences-list');
    const countEl   = document.getElementById('occurrences-count');

    container.replaceChildren(renderLoading());

    try {
        const params = { page: currentPage, page_size: 20 };
        if (search) params.search = search;

        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, params);
        const occurrences = data.results || [];
        const total = data.count || 0;

        if (currentView === 'list') {
            countEl.textContent = `${total} ocorrência${total !== 1 ? 's' : ''}`;
        }

        if (occurrences.length === 0) {
            container.replaceChildren(renderEmpty(search));
            document.getElementById('pagination').classList.add('hidden');
            return;
        }

        container.replaceChildren();
        occurrences.forEach(occ => container.appendChild(renderRow(occ)));
        renderPagination(data);

    } catch (err) {
        container.replaceChildren(renderError());
    }
}

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

function renderLoading() {
    const wrap = document.createElement('div');
    wrap.className = 'loading-overlay';
    const sp = document.createElement('span');
    sp.className = 'spinner';
    const txt = document.createElement('span');
    txt.textContent = 'A carregar ocorrências';
    wrap.appendChild(sp);
    wrap.appendChild(txt);
    return wrap;
}

function renderEmpty(search) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';

    const title = document.createElement('div');
    title.className = 'empty-state-title';
    title.textContent = search ? `Sem resultados para "${search}"` : 'Sem ocorrências';
    wrap.appendChild(title);

    const p = document.createElement('p');
    p.textContent = search
        ? 'Tenta outro termo de pesquisa.'
        : 'Começa por registar a primeira ocorrência.';
    wrap.appendChild(p);

    if (!search) {
        const a = document.createElement('a');
        a.href = '/occurrences/new/';
        a.className = 'btn btn-primary mt-3';
        a.textContent = 'Registar ocorrência';
        wrap.appendChild(a);
    }
    return wrap;
}

function renderError() {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';
    const title = document.createElement('div');
    title.className = 'empty-state-title text-danger';
    title.textContent = 'Erro ao carregar ocorrências';
    wrap.appendChild(title);
    const p = document.createElement('p');
    p.textContent = 'Verifica a ligação e tenta recarregar.';
    wrap.appendChild(p);
    return wrap;
}

// ----------------------------------------------------------
// Paginação
// ----------------------------------------------------------
function renderPagination(data) {
    const container = document.getElementById('pagination');
    if (!data.next && !data.previous) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');
    container.replaceChildren();

    const prev = document.createElement('button');
    prev.className = 'btn btn-ghost btn-sm';
    prev.textContent = '← Anterior';
    prev.disabled = !data.previous;
    prev.addEventListener('click', () => changePage(-1));

    const label = document.createElement('span');
    label.className = 'text-muted text-sm';
    label.textContent = `Página ${currentPage}`;

    const next = document.createElement('button');
    next.className = 'btn btn-ghost btn-sm';
    next.textContent = 'Seguinte →';
    next.disabled = !data.next;
    next.addEventListener('click', () => changePage(1));

    container.appendChild(prev);
    container.appendChild(label);
    container.appendChild(next);
}

function changePage(delta) {
    currentPage += delta;
    const search = document.getElementById('search-input').value.trim();
    loadOccurrences(search);
    window.scrollTo(0, 0);
}
