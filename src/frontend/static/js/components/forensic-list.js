/**
 * ForensiQ — Comportamento partilhado das páginas de lista forense
 * (server-rendered + HTMX). CSP-safe: ficheiro estático, sem eval/inline.
 *
 *  - Clicar/Enter numa linha [data-row] → HTMX carrega o detalhe em
 *    #app-drawer-body; aqui abrimos o drawer (FQAppShell), marcamos a linha
 *    activa e inicializamos o mini-mapa Leaflet (#drawer-map).
 *  - O mapa antigo é destruído ANTES do swap (htmx:beforeSwap) para evitar
 *    estado órfão do Leaflet (2.º mapa não aparecia).
 *  - Modo Cadeia: se #drawer-map tiver data-chain (JSON de pontos), desenha
 *    polyline tracejada amber + pins por evento (timeline de custódia).
 *  - Navegação por teclado na grelha (↑/↓/Enter/Espaço) e botões de copiar.
 */
(function () {
    'use strict';
    var drawerMap = null;

    document.body.addEventListener('htmx:beforeSwap', function (ev) {
        if (ev.target && ev.target.id === 'app-drawer-body') destroyDrawerMap();
    });
    document.body.addEventListener('htmx:afterSwap', function (ev) {
        if (!ev.target || ev.target.id !== 'app-drawer-body') return;
        if (window.FQAppShell) window.FQAppShell.setDrawerState('open');
        markSelected(ev.detail);
        initDrawerMap();
    });

    function destroyDrawerMap() {
        if (!drawerMap) return;
        try { drawerMap.remove(); } catch (e) { /* container já destacado */ }
        drawerMap = null;
    }

    function markSelected(detail) {
        var row = detail && detail.requestConfig && detail.requestConfig.elt;
        document.querySelectorAll('[data-row][aria-selected="true"]').forEach(function (r) {
            r.removeAttribute('aria-selected');
        });
        if (row && row.matches && row.matches('[data-row]')) row.setAttribute('aria-selected', 'true');
    }

    function initDrawerMap() {
        var el = document.getElementById('drawer-map');
        if (!el || typeof L === 'undefined') return;
        var lat = parseFloat(el.dataset.lat);
        var lng = parseFloat(el.dataset.lng);
        destroyDrawerMap();
        drawerMap = L.map(el, { zoomControl: true, attributionControl: false });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(drawerMap);

        var drewChain = renderChain(el);
        if (!drewChain) {
            if (isNaN(lat) || isNaN(lng)) { destroyDrawerMap(); return; }
            drawerMap.setView([lat, lng], 15);
            L.marker([lat, lng]).addTo(drawerMap).bindTooltip(el.dataset.label || '', { permanent: false });
        }
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { if (drawerMap) drawerMap.invalidateSize(); });
        });
    }

    // Modo Cadeia — desenha o trajeto a partir de #drawer-map[data-chain].
    function renderChain(el) { return drawChainOn(drawerMap, el.dataset.chain); }

    // Desenha uma cadeia (polyline tracejada amber + pins por evento) num mapa.
    function drawChainOn(map, raw) {
        if (!raw || !map) return false;
        var pts;
        try { pts = JSON.parse(raw); } catch (e) { return false; }
        if (!pts || !pts.length) return false;
        var latlngs = [];
        pts.forEach(function (p) {
            var la = parseFloat(p.lat), ln = parseFloat(p.lng);
            if (isNaN(la) || isNaN(ln)) return;
            latlngs.push([la, ln]);
            L.circleMarker([la, ln], { radius: 5, color: '#F6AD55', weight: 2, fillColor: '#F6AD55', fillOpacity: 0.85 })
                .addTo(map).bindTooltip(p.label || '', { permanent: false });
        });
        if (!latlngs.length) return false;
        if (latlngs.length > 1) {
            L.polyline(latlngs, { color: '#F6AD55', weight: 2, dashArray: '5,6', opacity: 0.9 }).addTo(map);
            map.fitBounds(latlngs, { padding: [26, 26] });
        } else {
            map.setView(latlngs[0], 15);
        }
        return true;
    }

    // Pontos de prioridade (cor classifica) — usado no mapa panorâmico do hero.
    var PRI_COLORS = { 1: '#F87171', 2: '#F59E0B', 0: '#60A5FA' };
    function drawPoints(map, raw) {
        if (!raw) return false;
        var pts;
        try { pts = JSON.parse(raw); } catch (e) { return false; }
        if (!pts || !pts.length) return false;
        pts.forEach(function (p) {
            var la = parseFloat(p.lat), ln = parseFloat(p.lng);
            if (isNaN(la) || isNaN(ln)) return;
            var col = PRI_COLORS[p.pri] || PRI_COLORS[0];
            L.circleMarker([la, ln], { radius: 5, color: col, weight: 2, fillColor: col, fillOpacity: 0.7 })
                .addTo(map).bindTooltip(p.label || '', { permanent: false });
        });
        return true;
    }
    function parseBounds(raw) {
        if (!raw) return null;
        try { var b = JSON.parse(raw); return (b && b.length === 2) ? b : null; } catch (e) { return null; }
    }

    // Mapas estáticos embebidos ([data-static-map]): pin único (data-lat/lng),
    // cadeia (data-chain), ou conjunto de pontos (data-points) com bounds fixos
    // (data-bounds) e opcionalmente sem interação (data-fixed, para insets).
    function initStaticMaps() {
        if (typeof L === 'undefined') return;
        document.querySelectorAll('[data-static-map]').forEach(function (el) {
            if (el._fqMap) return;
            var fixed = el.hasAttribute('data-fixed');
            var opts = { attributionControl: false, zoomControl: !fixed };
            if (fixed) {
                opts.dragging = false; opts.scrollWheelZoom = false; opts.doubleClickZoom = false;
                opts.boxZoom = false; opts.keyboard = false; opts.touchZoom = false; opts.tap = false;
            }
            var m = L.map(el, opts);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(m);
            el._fqMap = m;

            var bounds = parseBounds(el.dataset.bounds);
            var drewPoints = drawPoints(m, el.dataset.points);
            var drewChain = !drewPoints && drawChainOn(m, el.dataset.chain);

            if (bounds) {
                m.fitBounds(bounds);
            } else if (!drewPoints && !drewChain) {
                var lat = parseFloat(el.dataset.lat), lng = parseFloat(el.dataset.lng);
                if (isNaN(lat) || isNaN(lng)) { m.remove(); el._fqMap = null; return; }
                m.setView([lat, lng], 15);
                L.marker([lat, lng]).addTo(m).bindTooltip(el.dataset.label || '', { permanent: false });
            }
            setTimeout(function () { m.invalidateSize(); }, 60);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initStaticMaps);
    else initStaticMaps();

    // Abrir um <details> alvo quando a página é aberta com âncora (ex.: o
    // formulário de registo de evento via "#custody-register").
    function openHashTarget() {
        if (!location.hash) return;
        var t = null;
        try { t = document.querySelector(location.hash); } catch (e) { return; }
        if (t && t.tagName === 'DETAILS') { t.open = true; t.scrollIntoView(); }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', openHashTarget);
    else openHashTarget();
    window.addEventListener('hashchange', openHashTarget);

    window.addEventListener('fq:drawer-state', function () {
        if (drawerMap) setTimeout(function () { if (drawerMap) drawerMap.invalidateSize(); }, 280);
    });

    document.body.addEventListener('keydown', function (ev) {
        var cur = document.activeElement;
        if (!cur || !cur.matches || !cur.matches('[data-row]')) return;
        var rows = Array.prototype.slice.call(document.querySelectorAll('[data-row]'));
        var i = rows.indexOf(cur);
        if (ev.key === 'ArrowDown') { ev.preventDefault(); if (rows[i + 1]) rows[i + 1].focus(); }
        else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (rows[i - 1]) rows[i - 1].focus(); }
        else if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); cur.click(); }
    });

    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-copy]') : null;
        if (!btn) return;
        ev.preventDefault();
        ev.stopPropagation();
        var val = btn.getAttribute('data-copy');
        if (!navigator.clipboard) return;
        navigator.clipboard.writeText(val).then(function () {
            btn.classList.add('is-copied');
            setTimeout(function () { btn.classList.remove('is-copied'); }, 1200);
        });
    });
})();
