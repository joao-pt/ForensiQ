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
 *        data-decimals="7"                   (injetado de settings.GPS_DECIMAL_PLACES)
 *        data-zoom="7"></div>
 * Os inputs-alvo recebem a precisão de data-decimals (igual ao ledger/instituição,
 * porque a coordenada da instituição é copiada para o evento na receção).
 */
(function () {
    'use strict';

    var pickers = [];  // estado dos seletores ativos (p/ sincronizar com GPS)

    function initOne(el) {
        if (!el || el._fqPickerReady) return;
        if (typeof L === 'undefined' || !window.FQMap) return;  // Leaflet é por-página
        el._fqPickerReady = true;

        var FQMap = window.FQMap;
        // Precisão vem do atributo (fonte: settings.GPS_DECIMAL_PLACES); o 7 é
        // só o default degradado quando o atributo falta.
        var decimals = parseInt(el.getAttribute('data-decimals') || '', 10) || 7;
        var latInput = document.querySelector(el.getAttribute('data-lat-target'));
        var lngInput = document.querySelector(el.getAttribute('data-lng-target'));

        var lat0 = parseFloat(el.getAttribute('data-lat'));
        var lng0 = parseFloat(el.getAttribute('data-lng'));
        var hasInit = !isNaN(lat0) && !isNaN(lng0);
        var zoom = parseInt(el.getAttribute('data-zoom') || '', 10);
        if (isNaN(zoom)) zoom = hasInit ? FQMap.DEFAULT_ZOOM : FQMap.DEFAULT_VIEW.zoom;

        var center = hasInit ? [lat0, lng0] : FQMap.DEFAULT_VIEW.center;
        var map = FQMap.createMap(el, { center: center, zoom: zoom });

        // Pin-picker na fonte única (FQMap.bindPinPicker); aqui só o recentrar
        // na edição manual (clicar no mapa não desloca a vista).
        var picker = FQMap.bindPinPicker(map, {
            latEl: latInput,
            lngEl: lngInput,
            decimals: decimals,
            onSync: function (la, ln) {
                map.setView([la, ln], Math.max(map.getZoom(), FQMap.DEFAULT_ZOOM));
            },
        });
        if (hasInit) picker.place(lat0, lng0, 'init');

        var rec = { el: el, map: map, sync: picker.sync };
        pickers.push(rec);
        el._fqPickerRec = rec;
        FQMap.refreshSize(map, el);
    }

    function destroyOne(el) {
        var rec = el && el._fqPickerRec;
        if (!rec) return;
        window.FQMap.destroy(rec.map, el);   // desmonte na fonte única (D73)
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
