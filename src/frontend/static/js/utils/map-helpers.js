/**
 * ForensiQ — Helpers de mapa Leaflet (FONTE ÚNICA).
 *
 * CSP-safe: ficheiro estático, sem eval/inline. Exposto como `window.FQMap` (sem
 * ES modules, para não quebrar o carregamento via <script>). Carregado em
 * base.html ANTES dos componentes (forensic-list.js, map-picker.js, …) que o usam.
 *
 * Centraliza a inicialização repetida (`L.map` + camada de tiles OSM) e o padrão
 * robusto de `invalidateSize` (duplo rAF + whenReady + ResizeObserver), antes
 * duplicados em forensic-list.js. NÃO toca em `L` no load — só dentro das funções,
 * pelo que pode carregar antes do Leaflet (que é por-página).
 */
(function () {
    'use strict';

    var OSM_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    var OSM_MAX_ZOOM = 19;
    var DEFAULT_ZOOM = 15;

    /** Cria um mapa Leaflet com a camada OSM padrão. `opts` é passado a L.map. */
    function createMap(el, opts) {
        var map = L.map(el, opts);
        L.tileLayer(OSM_TILE_URL, { maxZoom: OSM_MAX_ZOOM }).addTo(map);
        return map;
    }

    /**
     * Reparação robusta do tamanho de um mapa Leaflet. O bug clássico é o mapa
     * arrancar num container ainda sem dimensões (drawer a abrir, swap HTMX,
     * transição para overlay fixed em mobile, banda do hero sem altura) e ficar
     * cinzento. Em vez de um único invalidateSize com timing frágil, dispara em
     * três momentos: já a seguir ao layout (duplo rAF), quando o mapa fica pronto
     * (whenReady) e sempre que o container muda de dimensões (ResizeObserver).
     */
    function refreshSize(map, el) {
        if (!map || !el) return;
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { try { map.invalidateSize(); } catch (e) { /* noop */ } });
        });
        map.whenReady(function () { try { map.invalidateSize(); } catch (e) { /* noop */ } });
        if (typeof ResizeObserver !== 'undefined' && !el._fqRO) {
            var ro = new ResizeObserver(function () {
                if (el.clientWidth > 0 && el.clientHeight > 0) {
                    try { map.invalidateSize(); } catch (e) { /* noop */ }
                }
            });
            ro.observe(el);
            el._fqRO = ro;
        }
    }

    window.FQMap = {
        createMap: createMap,
        refreshSize: refreshSize,
        OSM_TILE_URL: OSM_TILE_URL,
        OSM_MAX_ZOOM: OSM_MAX_ZOOM,
        DEFAULT_ZOOM: DEFAULT_ZOOM,
    };
})();
