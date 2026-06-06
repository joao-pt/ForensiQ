/**
 * ForensiQ — Seletor de localização no mapa (clicar → pino). CSP-safe.
 *
 * Para a criação/edição de instituições (ponto de controlo fixo): em vez de
 * digitar coordenadas, o utilizador clica no mapa e o pino fixa lat/lng nos
 * inputs-alvo. Reusa a fonte única window.FQMap (Leaflet) e o invalidateSize
 * robusto. Funciona em página completa (DOMContentLoaded) e dentro do modal de
 * ação (eventos `fq:modal-open` / `fq:modal-close`).
 *
 * Marcação:
 *   <div data-map-picker
 *        data-lat-target="#f-lat" data-lng-target="#f-lng"
 *        data-lat="38.72" data-lng="-9.14"   (opcional: posição inicial)
 *        data-zoom="7"></div>
 * Os inputs-alvo recebem a precisão de 7 casas (igual ao ledger/instituição,
 * porque a coordenada da instituição é copiada para o evento na receção).
 */
(function () {
    'use strict';

    var DEFAULT = { lat: 39.5, lng: -8.0, zoom: 6 };  // Portugal continental
    var DECIMALS = 7;
    var pickers = [];  // estado dos seletores ativos (p/ sincronizar com GPS)

    function initOne(el) {
        if (!el || el._fqPickerReady) return;
        if (typeof L === 'undefined' || !window.FQMap) return;  // Leaflet é por-página
        el._fqPickerReady = true;

        var latInput = document.querySelector(el.getAttribute('data-lat-target'));
        var lngInput = document.querySelector(el.getAttribute('data-lng-target'));

        var lat0 = parseFloat(el.getAttribute('data-lat'));
        var lng0 = parseFloat(el.getAttribute('data-lng'));
        var hasInit = !isNaN(lat0) && !isNaN(lng0);
        var zoom = parseInt(el.getAttribute('data-zoom') || '', 10);
        if (isNaN(zoom)) zoom = hasInit ? 15 : DEFAULT.zoom;

        var center = hasInit ? [lat0, lng0] : [DEFAULT.lat, DEFAULT.lng];
        var map = window.FQMap.createMap(el, { center: center, zoom: zoom });
        var marker = null;

        function place(lat, lng) {
            if (marker) marker.setLatLng([lat, lng]);
            else marker = L.marker([lat, lng]).addTo(map);
            if (latInput) latInput.value = lat.toFixed(DECIMALS);
            if (lngInput) lngInput.value = lng.toFixed(DECIMALS);
        }
        function syncFromInputs() {
            var la = parseFloat(latInput && latInput.value);
            var ln = parseFloat(lngInput && lngInput.value);
            if (!isNaN(la) && !isNaN(ln)) {
                place(la, ln);
                map.setView([la, ln], Math.max(map.getZoom(), 14));
            }
        }

        if (hasInit) place(lat0, lng0);
        map.on('click', function (ev) { place(ev.latlng.lat, ev.latlng.lng); });
        if (latInput) latInput.addEventListener('change', syncFromInputs);
        if (lngInput) lngInput.addEventListener('change', syncFromInputs);

        var rec = { el: el, map: map, sync: syncFromInputs };
        pickers.push(rec);
        el._fqPickerRec = rec;
        window.FQMap.refreshSize(map, el);
    }

    function destroyOne(el) {
        var rec = el && el._fqPickerRec;
        if (!rec) return;
        try { rec.map.remove(); } catch (e) { /* noop */ }
        if (el._fqRO) { try { el._fqRO.disconnect(); } catch (e2) { /* noop */ } el._fqRO = null; }
        pickers = pickers.filter(function (p) { return p !== rec; });
        el._fqPickerRec = null;
        el._fqPickerReady = false;
    }

    function initAll(root) {
        var scope = root || document;
        var els = scope.querySelectorAll('[data-map-picker]');
        for (var i = 0; i < els.length; i++) initOne(els[i]);
    }

    // Captura de GPS (geo-capture.js) preenche os inputs → reposiciona o(s) pino(s).
    document.addEventListener('forensiq:geo-captured', function () {
        requestAnimationFrame(function () {
            pickers.forEach(function (p) { p.sync(); });
        });
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initAll(); });
    } else {
        initAll();
    }

    document.addEventListener('fq:modal-open', function (ev) {
        initAll(ev.detail && ev.detail.root);
    });
    document.addEventListener('fq:modal-close', function (ev) {
        var root = (ev.detail && ev.detail.root) || document;
        var els = root.querySelectorAll('[data-map-picker]');
        for (var i = 0; i < els.length; i++) destroyOne(els[i]);
    });
})();
