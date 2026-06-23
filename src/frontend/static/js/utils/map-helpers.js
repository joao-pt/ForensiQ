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
    // Vista por omissão: Portugal continental (antes copiada byte-a-byte em
    // geo-field.js e map-picker.js — auditoria D98).
    var DEFAULT_VIEW = { center: [39.5, -8.0], zoom: 6 };

    /**
     * Pino ÚNICO da app (divIcon SVG, classe .fq-pin) — substitui o ícone PNG
     * por omissão do Leaflet. Motivo: em produção o STORAGES usa
     * CompressedManifestStaticFilesStorage (WhiteNoise), que põe hash no nome de
     * `marker-icon.png`; a auto-deteção do caminho do Leaflet (L.Icon.Default)
     * espera o nome literal, parte o URL e o pino aparecia como "imagem partida"
     * (em local, sem hash, funcionava). Um divIcon estilizado por CSS elimina
     * essa dependência E dá um pino na cor da marca, reativo ao tema. O SVG usa
     * classes (sem style inline) por causa da CSP estrita. Memoizado: o mesmo
     * objeto serve todos os marcadores.
     */
    var _pinIcon = null;
    function pinIcon() {
        if (_pinIcon) return _pinIcon;
        _pinIcon = L.divIcon({
            className: 'fq-pin',
            html: '<svg viewBox="0 0 24 24" class="fq-pin__svg" aria-hidden="true" focusable="false">' +
                  '<path class="fq-pin__shape" d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>' +
                  '<circle class="fq-pin__core" cx="12" cy="9" r="2.6"/></svg>',
            iconSize: [30, 30],
            iconAnchor: [15, 28],   // ponta do pino (≈ y22/24·30) sobre a coordenada
            popupAnchor: [0, -26],
            tooltipAnchor: [0, -24],
        });
        return _pinIcon;
    }

    /** Cria um mapa Leaflet com a camada OSM padrão. `opts` é passado a L.map.
     * A atribuição © OpenStreetMap é obrigatória pela licença ODbL; vive aqui
     * (fonte única) para nenhum mapa a perder. Quem a esconder (insets
     * minúsculos) tem de repor o crédito adjacente ao mapa. */
    function createMap(el, opts) {
        var map = L.map(el, opts);
        L.tileLayer(OSM_TILE_URL, {
            maxZoom: OSM_MAX_ZOOM,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        }).addTo(map);
        if (map.attributionControl) map.attributionControl.setPrefix('');
        return map;
    }

    /**
     * Desmonta um mapa criado por createMap/refreshSize: desliga o
     * ResizeObserver interno (el._fqRO — detalhe que só o FQMap deve conhecer)
     * e remove o mapa em try/catch. Quem cria oferece o desmonte (auditoria D73).
     */
    function destroy(map, el) {
        if (el && el._fqRO) {
            try { el._fqRO.disconnect(); } catch (e) { /* noop */ }
            el._fqRO = null;
        }
        if (map) { try { map.remove(); } catch (e2) { /* container já destacado */ } }
    }

    /**
     * Pino único a partir do dataset do container (data-lat/data-lng/data-label):
     * valida, centra em DEFAULT_ZOOM e cria o marker com tooltip. Devolve false
     * se as coordenadas forem inválidas (auditoria D74).
     */
    function pinFromDataset(map, el) {
        var lat = parseFloat(el.dataset.lat);
        var lng = parseFloat(el.dataset.lng);
        if (isNaN(lat) || isNaN(lng)) return false;
        map.setView([lat, lng], DEFAULT_ZOOM);
        L.marker([lat, lng], { icon: pinIcon() }).addTo(map).bindTooltip(el.dataset.label || '', { permanent: false });
        return true;
    }

    /**
     * Primitivo pin-picker (auditoria D68): clicar no mapa → pino → preencher os
     * inputs; editar os inputs → reposicionar o pino. As reações próprias de cada
     * consumidor (recentrar, morada, estado, bloqueio) entram pelos callbacks:
     *   opts: { latEl, lngEl, decimals,
     *           onPlace(lat, lng, source),  // após cada colocação ('click'|'sync'|'init'|'api')
     *           onSync(lat, lng) }          // após sync por edição manual dos inputs
     * Devolve { place(lat, lng, source?), sync() }.
     */
    function bindPinPicker(map, opts) {
        var marker = null;
        function place(lat, lng, source) {
            if (marker) marker.setLatLng([lat, lng]);
            else marker = L.marker([lat, lng], { icon: pinIcon() }).addTo(map);
            if (opts.latEl) opts.latEl.value = lat.toFixed(opts.decimals);
            if (opts.lngEl) opts.lngEl.value = lng.toFixed(opts.decimals);
            if (opts.onPlace) opts.onPlace(lat, lng, source || 'api');
        }
        function sync() {
            var la = parseFloat(opts.latEl && opts.latEl.value);
            var ln = parseFloat(opts.lngEl && opts.lngEl.value);
            if (isNaN(la) || isNaN(ln)) return;
            place(la, ln, 'sync');
            if (opts.onSync) opts.onSync(la, ln);
        }
        map.on('click', function (ev) { place(ev.latlng.lat, ev.latlng.lng, 'click'); });
        if (opts.latEl) opts.latEl.addEventListener('change', sync);
        if (opts.lngEl) opts.lngEl.addEventListener('change', sync);
        return { place: place, sync: sync };
    }

    /**
     * Reparação robusta do tamanho de um mapa Leaflet. O bug clássico é o mapa
     * arrancar num container ainda sem dimensões (swap HTMX, transição para
     * overlay fixed em mobile, banda do hero sem altura) e ficar
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
        destroy: destroy,
        pinFromDataset: pinFromDataset,
        bindPinPicker: bindPinPicker,
        pinIcon: pinIcon,
        OSM_TILE_URL: OSM_TILE_URL,
        OSM_MAX_ZOOM: OSM_MAX_ZOOM,
        DEFAULT_ZOOM: DEFAULT_ZOOM,
        DEFAULT_VIEW: DEFAULT_VIEW,
    };
})();
