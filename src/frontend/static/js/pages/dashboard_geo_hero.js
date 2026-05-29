'use strict';

/**
 * ForensiQ — Dashboard Geo Hero
 *
 * Inicializa o hero de 3 colunas do dashboard:
 *   1. Cadeia vertical (7 tiles, populadas com counts do endpoint stats)
 *   2. Mapa continental (Leaflet + OSM tiles, fitBounds Portugal)
 *   3. Insets Madeira/Açores (não-arrastáveis) + CTA "Nova ocorrência"
 *
 * As tiles de cadeia substituem o `custody-flow-card` da v1 (a função
 * legacy `renderCustodyFlow` em dashboard.js fica inerte por ausência
 * de DOM nodes — defesa em profundidade).
 *
 * IIFE para não poluir global scope (cumpre tests_frontend_js_namespace).
 */

(() => {

if (!window.L || typeof L.map !== 'function') {
    console.warn('[geo-hero] Leaflet não está carregado.');
    return;
}

const { STATE_FLOW } = window.CustodyStates || { STATE_FLOW: [] };

const BOUNDS = {
    continental: [[36.95, -9.55], [42.15, -6.18]],
    madeira:     [[32.40, -17.40], [33.10, -16.50]],
    acores:      [[36.85, -31.40], [39.85, -24.70]],
};

const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

let mapContinental = null;
let mapMadeira = null;
let mapAcores = null;
let markersLayer = null;

document.addEventListener('DOMContentLoaded', async function () {
    if (!document.getElementById('geo-hero')) return;
    if (!window.Auth || !(await Auth.requireAuth())) return;

    initMaps();
    populateCustody();
    loadOccurrenceMarkers();
    bindCta();

    // Refrescar layout do mapa quando o drawer abre/fecha (CSS grid mexe na largura)
    window.addEventListener('fq:drawer-state', invalidateMapsSoon);
    window.addEventListener('resize', invalidateMapsSoon);
});

// -----------------------------------------------------------------
// Mapas
// -----------------------------------------------------------------
function initMaps() {
    const elCont = document.getElementById('geo-hero-map-continental');
    const elMad  = document.getElementById('geo-hero-map-madeira');
    const elAco  = document.getElementById('geo-hero-map-acores');
    if (!elCont || !elMad || !elAco) return;

    mapContinental = L.map(elCont, {
        zoomControl: true,
        attributionControl: false,
    });
    L.tileLayer(TILE_URL, { maxZoom: 12, minZoom: 5, attribution: TILE_ATTR })
        .addTo(mapContinental);
    mapContinental.fitBounds(BOUNDS.continental);
    markersLayer = L.layerGroup().addTo(mapContinental);

    mapMadeira = makeInsetMap(elMad, BOUNDS.madeira);
    mapAcores  = makeInsetMap(elAco, BOUNDS.acores);
}

function makeInsetMap(el, bounds) {
    const m = L.map(el, {
        zoomControl: false,
        attributionControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        keyboard: false,
        touchZoom: false,
    });
    L.tileLayer(TILE_URL, { maxZoom: 12, minZoom: 5, attribution: TILE_ATTR })
        .addTo(m);
    m.fitBounds(bounds);
    return m;
}

let invalidateTimer = null;
function invalidateMapsSoon() {
    if (invalidateTimer) clearTimeout(invalidateTimer);
    invalidateTimer = setTimeout(function () {
        [mapContinental, mapMadeira, mapAcores].forEach(function (m) {
            if (m && typeof m.invalidateSize === 'function') m.invalidateSize();
        });
    }, 220);
}

// -----------------------------------------------------------------
// Tiles da cadeia (counts)
// -----------------------------------------------------------------
async function populateCustody() {
    const container = document.getElementById('cs-tiles');
    if (!container) return;

    // Render skeleton com os 7 estados (counts a "—" até chegar a resposta)
    container.replaceChildren();
    STATE_FLOW.forEach(function (s) {
        container.appendChild(buildTile(s, '—', null));
    });

    let data;
    try {
        data = await fetchStats();
    } catch (err) {
        console.warn('[geo-hero] Falha ao obter stats:', err);
        return;
    }
    if (!data) return;

    const byState = data.evidences_by_current_state || data.custody_by_state || {};

    container.replaceChildren();
    STATE_FLOW.forEach(function (s) {
        const count = Number(byState[s.key]) || 0;
        container.appendChild(buildTile(s, String(count), null));
    });
}

function buildTile(state, valueText, delta) {
    const tile = document.createElement('a');
    tile.className = 'cs-tile';
    tile.dataset.state = state.key;
    tile.href = '/evidences/?state=' + state.key;
    tile.setAttribute(
        'aria-label',
        state.label + ': ' + valueText + ' itens — abrir lista filtrada'
    );

    const num = document.createElement('span');
    num.className = 'cs-tile__num';
    num.textContent = valueText;

    const label = document.createElement('span');
    label.className = 'cs-tile__label';
    label.textContent = state.label;

    const deltaEl = document.createElement('span');
    deltaEl.className = 'cs-tile__delta';
    if (delta && typeof delta.value === 'number') {
        deltaEl.dataset.trend = delta.value > 0 ? 'up' : delta.value < 0 ? 'down' : 'flat';
        deltaEl.textContent = (delta.value > 0 ? '+' : '') + delta.value;
    } else {
        deltaEl.dataset.trend = 'flat';
        deltaEl.textContent = '·';
    }

    const spark = buildSparkline(valueText === '—' ? 0 : Number(valueText));

    tile.appendChild(num);
    tile.appendChild(label);
    tile.appendChild(deltaEl);
    tile.appendChild(spark);

    return tile;
}

function buildSparkline(count) {
    // Placeholder visual: linha levemente ondulada cuja amplitude reflecte o count.
    // Real time-series chega quando o endpoint stats expuser histograma 24h.
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('class', 'cs-tile__spark');
    svg.setAttribute('viewBox', '0 0 80 14');
    svg.setAttribute('preserveAspectRatio', 'none');

    const amplitude = Math.min(6, Math.max(1, Math.log(count + 1) * 1.5));
    const points = [];
    for (let i = 0; i <= 10; i++) {
        const x = (i / 10) * 80;
        const phase = (i + (count % 7)) * 0.85;
        const y = 7 + Math.sin(phase) * amplitude * 0.6;
        points.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    const poly = document.createElementNS(svgNS, 'polyline');
    poly.setAttribute('fill', 'none');
    poly.setAttribute('stroke', 'currentColor');
    poly.setAttribute('stroke-width', '1');
    poly.setAttribute('stroke-linejoin', 'round');
    poly.setAttribute('points', points.join(' '));

    svg.appendChild(poly);
    return svg;
}

// -----------------------------------------------------------------
// Marcadores no mapa continental
// -----------------------------------------------------------------
async function loadOccurrenceMarkers() {
    if (!markersLayer || !window.API) return;

    let resp;
    try {
        resp = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 100 });
    } catch (err) {
        console.warn('[geo-hero] Falha ao carregar ocorrências:', err);
        return;
    }

    const items = (resp && resp.results) || [];
    items.forEach(function (occ) {
        const lat = Number(occ.latitude);
        const lng = Number(occ.longitude);
        if (Number.isNaN(lat) || Number.isNaN(lng)) return;
        L.marker([lat, lng], { icon: makeMarkerIcon() })
            .bindTooltip(occ.number || ('Ocorrência #' + occ.id))
            .addTo(markersLayer);
    });
}

function makeMarkerIcon() {
    return L.divIcon({
        className: 'fq-geohero-marker',
        html: '<span class="fq-geohero-marker__dot"></span>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
    });
}

// -----------------------------------------------------------------
// CTA "Nova ocorrência"
// -----------------------------------------------------------------
function bindCta() {
    const btn = document.querySelector('.geo-hero__cta .btn-new-occ');
    if (!btn) return;

    // Esconder se o utilizador não for AGENT (alinhado com policy actual)
    const user = window.Auth && Auth.getUser();
    if (user && user.profile !== 'AGENT') {
        btn.parentElement.hidden = true;
    }

    document.addEventListener('keydown', function (ev) {
        if ((ev.ctrlKey || ev.metaKey) && ev.key && ev.key.toLowerCase() === 'n') {
            const ae = document.activeElement;
            if (ae && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) return;
            ev.preventDefault();
            btn.click();
        }
    });
}

// -----------------------------------------------------------------
// Stats fetch (replica do dashboard.js para isolamento)
// -----------------------------------------------------------------
async function fetchStats() {
    try {
        const r = await fetch(CONFIG.ENDPOINTS.STATS_DASHBOARD, { credentials: 'include' });
        if (r.ok) return await r.json();
    } catch (_) { /* swallow */ }
    try {
        const r2 = await fetch(CONFIG.ENDPOINTS.STATS_LEGACY, { credentials: 'include' });
        if (r2.ok) return await r2.json();
    } catch (_) { /* swallow */ }
    return null;
}

})();
