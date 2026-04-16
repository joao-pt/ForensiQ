'use strict';

let currentPage = 1;
let searchTimeout = null;
let allOccurrences = [];
let leafletMap = null;
let mapInitialized = false;
let currentView = 'list';

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    if (user) {
        document.getElementById('navbar-user').textContent = user.first_name || user.username;
        if (user.profile !== 'AGENT') {
            const btnNew = document.getElementById('btn-new-occurrence');
            if (btnNew) btnNew.style.display = 'none';
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    document.getElementById('tab-list').addEventListener('click', () => switchView('list'));
    document.getElementById('tab-map').addEventListener('click', () => switchView('map'));

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

function switchView(view) {
    currentView = view;
    const panelList = document.getElementById('panel-list');
    const panelMap  = document.getElementById('panel-map');
    const tabList   = document.getElementById('tab-list');
    const tabMap    = document.getElementById('tab-map');

    if (view === 'map') {
        panelList.style.display = 'none';
        panelMap.style.display  = '';
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
        panelList.style.display = '';
        panelMap.style.display  = 'none';
        tabList.classList.add('active');
        tabList.setAttribute('aria-selected', 'true');
        tabMap.classList.remove('active');
        tabMap.setAttribute('aria-selected', 'false');
    }
}

function initMap() {
    mapInitialized = true;

    leafletMap = L.map('map-container', {
        center: [39.5, -8.0],
        zoom: 7,
        zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
    }).addTo(leafletMap);

    if (allOccurrences.length > 0) {
        addMarkersToMap(allOccurrences);
    }
}

async function loadAllOccurrencesForMap() {
    try {
        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 200 });
        allOccurrences = data.results || [];

        if (mapInitialized) {
            addMarkersToMap(allOccurrences);
        }
    } catch (err) {
        console.error('Erro ao carregar ocorrências para mapa:', err);
    }
}

function buildMarkerDot() {
    const dot = document.createElement('div');
    dot.style.width = '14px';
    dot.style.height = '14px';
    dot.style.background = '#1565c0';
    dot.style.border = '2px solid #fff';
    dot.style.borderRadius = '50%';
    dot.style.boxShadow = '0 1px 4px rgba(0,0,0,0.4)';
    return dot.outerHTML;
}

function buildPopupNode(occ) {
    const dt = new Date(occ.date_time).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
    });
    const fullDesc = occ.description || '';
    const desc = fullDesc.substring(0, 80);

    const root = document.createElement('div');

    const num = document.createElement('strong');
    num.textContent = occ.number;
    root.appendChild(num);

    const descEl = document.createElement('div');
    descEl.className = 'popup-desc';
    descEl.textContent = fullDesc.length > 80 ? `${desc}…` : desc;
    root.appendChild(descEl);

    if (occ.address) {
        const addr = document.createElement('div');
        addr.className = 'popup-date';
        addr.textContent = `\u{1F4CC} ${occ.address}`;
        root.appendChild(addr);
    }

    const dateEl = document.createElement('div');
    dateEl.className = 'popup-date';
    dateEl.textContent = `\u{1F551} ${dt}`;
    root.appendChild(dateEl);

    const link = document.createElement('a');
    link.href = `/occurrences/${occ.id}/`;
    link.textContent = 'Ver detalhes →';
    root.appendChild(link);

    return root;
}

function addMarkersToMap(occurrences) {
    if (!leafletMap) return;

    const iconWithGps = L.divIcon({
        html: buildMarkerDot(),
        className: '',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
    });

    const bounds = [];
    let markersAdded = 0;

    occurrences.forEach(occ => {
        if (!occ.gps_lat || !occ.gps_lon) return;

        const lat = parseFloat(occ.gps_lat);
        const lon = parseFloat(occ.gps_lon);
        if (isNaN(lat) || isNaN(lon)) return;

        const marker = L.marker([lat, lon], { icon: iconWithGps })
            .bindPopup(buildPopupNode(occ), { maxWidth: 260 });

        marker.addTo(leafletMap);
        bounds.push([lat, lon]);
        markersAdded++;
    });

    if (bounds.length > 0) {
        leafletMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
    }

    const total = occurrences.length;
    const countEl = document.getElementById('occurrences-count');
    if (countEl && currentView === 'map') {
        countEl.textContent = `${markersAdded} de ${total} ocorrência${total !== 1 ? 's' : ''} com GPS`;
    }
}

function buildLoading() {
    const wrap = document.createElement('div');
    wrap.className = 'loading-overlay';
    const sp = document.createElement('div');
    sp.className = 'spinner spinner-dark';
    wrap.appendChild(sp);
    return wrap;
}

function buildEmpty(message, opts = {}) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';
    if (opts.icon) {
        const ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        ic.textContent = opts.icon;
        wrap.appendChild(ic);
    }
    const p = document.createElement('p');
    p.textContent = message;
    if (opts.danger) p.classList.add('text-danger');
    wrap.appendChild(p);
    if (opts.action) wrap.appendChild(opts.action);
    return wrap;
}

async function loadOccurrences(search = '') {
    const container = document.getElementById('occurrences-list');
    const countEl = document.getElementById('occurrences-count');

    container.replaceChildren(buildLoading());

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
            const message = search
                ? `Sem resultados para "${search}".`
                : 'Sem ocorrências registadas.';
            const opts = { icon: '\u{1F4CB}' };
            if (!search) {
                const a = document.createElement('a');
                a.href = '/occurrences/new/';
                a.className = 'btn btn-primary mt-16';
                a.textContent = 'Registar primeira ocorrência';
                opts.action = a;
            }
            container.replaceChildren(buildEmpty(message, opts));
            document.getElementById('pagination').classList.add('hidden');
            return;
        }

        container.replaceChildren();
        occurrences.forEach(occ => container.appendChild(renderOccurrenceItem(occ)));
        renderPagination(data);

    } catch (err) {
        container.replaceChildren(buildEmpty('Erro ao carregar ocorrências. Tente novamente.', { danger: true }));
        console.error('Erro:', err);
    }
}

function renderOccurrenceItem(occ) {
    const date = new Date(occ.date_time).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const hasGps = occ.gps_lat && occ.gps_lon;
    const fullDesc = occ.description || '';

    const row = document.createElement('div');
    row.className = 'list-item';
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => {
        window.location.href = `/occurrences/${occ.id}/`;
    });

    const left = document.createElement('div');
    left.style.flex = '1';
    left.style.minWidth = '0';

    const head = document.createElement('div');
    head.style.display = 'flex';
    head.style.alignItems = 'center';
    head.style.gap = '8px';
    head.style.flexWrap = 'wrap';

    const num = document.createElement('strong');
    num.textContent = occ.number;
    head.appendChild(num);

    if (hasGps) {
        const badge = document.createElement('span');
        badge.className = 'badge badge-success';
        badge.title = 'GPS disponível';
        badge.textContent = '\u{1F4CD} GPS';
        head.appendChild(badge);
    }
    left.appendChild(head);

    const desc = document.createElement('div');
    desc.className = 'text-muted mt-4';
    desc.style.fontSize = '0.8125rem';
    desc.style.overflow = 'hidden';
    desc.style.textOverflow = 'ellipsis';
    desc.style.whiteSpace = 'nowrap';
    desc.textContent = fullDesc.length > 100 ? `${fullDesc.substring(0, 100)}...` : fullDesc;
    left.appendChild(desc);

    if (occ.address) {
        const addr = document.createElement('div');
        addr.className = 'text-muted';
        addr.style.fontSize = '0.75rem';
        addr.textContent = `\u{1F4CC} ${occ.address}`;
        left.appendChild(addr);
    }

    const right = document.createElement('div');
    right.style.textAlign = 'right';
    right.style.flexShrink = '0';
    right.style.marginLeft = '12px';

    const dateEl = document.createElement('div');
    dateEl.className = 'text-muted';
    dateEl.style.fontSize = '0.75rem';
    dateEl.style.whiteSpace = 'nowrap';
    dateEl.textContent = date;
    right.appendChild(dateEl);

    const arrow = document.createElement('div');
    arrow.className = 'text-muted';
    arrow.style.fontSize = '0.75rem';
    arrow.textContent = '>';
    right.appendChild(arrow);

    row.appendChild(left);
    row.appendChild(right);
    return row;
}

function renderPagination(data) {
    const container = document.getElementById('pagination');
    if (!data.next && !data.previous) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');
    container.replaceChildren();

    const prev = document.createElement('button');
    prev.className = 'btn btn-outline';
    prev.textContent = '← Anterior';
    prev.disabled = !data.previous;
    if (!data.previous) prev.classList.add('disabled');
    prev.addEventListener('click', () => changePage(-1));

    const label = document.createElement('span');
    label.className = 'text-muted';
    label.style.fontSize = '0.875rem';
    label.textContent = `Página ${currentPage}`;

    const next = document.createElement('button');
    next.className = 'btn btn-outline';
    next.textContent = 'Seguinte →';
    next.disabled = !data.next;
    if (!data.next) next.classList.add('disabled');
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
