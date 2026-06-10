/**
 * ForensiQ — Campo de localização auto-localizado (CSP-safe, ficheiro estático).
 *
 * Fonte ÚNICA da experiência "onde": um `[data-geo-field]` que mostra o mapa
 * logo carregado, pede a posição ao abrir (sem o utilizador clicar), larga o
 * pino, preenche lat/lng (+ precisão) e resolve a morada — tudo sobre o motor
 * já central `window.ForensiQGeo` (geo.js) e o `window.FQMap` (map-helpers.js).
 *
 * Estados: "A localizar…", sucesso com ±precisão (avisa se pior que o limiar
 * data-acc-flag-m, def. ForensiQGeo.ACC_FLAG_M), ou erro/sem
 * permissão com a mensagem PT-PT do ForensiQGeo. Em qualquer caso o utilizador
 * pode clicar no mapa para colocar/mover o pino ou escrever as coordenadas —
 * e há um botão de recurso "Usar a minha localização".
 *
 * Marcação (ver partials/_geo_field.html):
 *   <div data-geo-field
 *        data-lat-target="#f-lat" data-lng-target="#f-lng"
 *        data-addr-target="#f-addr" data-reverse="true"   (opcional)
 *        data-acc-target="#f-acc"                          (opcional)
 *        data-decimals="3" data-autolocate="true">
 *     <div data-geo-field-map></div>
 *     <button data-geo-field-locate>…</button>
 *     <span data-geo-field-status></span>
 *     … inputs lat/lng/morada …
 *   </div>
 *
 * Reutilizável: AGENTE usa 3 casas (~110 m), o ponto fixo (instituição) pode
 * usar data-autolocate="false" (só clicar no mapa). Degrada com elegância: sem
 * Leaflet (ex.: modal numa página sem mapa) esconde o mapa mas continua a
 * auto-localizar e a preencher os campos. Corre no load e em `fq:modal-open`.
 */
(function () {
    'use strict';
    if (window.__fqGeoFieldReady) return;
    window.__fqGeoFieldReady = true;

    function initOne(el) {
        if (!el || el._fqGeoFieldReady) return;
        el._fqGeoFieldReady = true;

        var dec = parseInt(el.getAttribute('data-decimals') || '5', 10);
        var autolocate = el.getAttribute('data-autolocate') !== 'false';
        var doReverse = el.getAttribute('data-reverse') === 'true';

        var latEl = document.querySelector(el.getAttribute('data-lat-target') || '');
        var lngEl = document.querySelector(el.getAttribute('data-lng-target') || '');
        var addrSel = el.getAttribute('data-addr-target');
        var addrEl = addrSel ? document.querySelector(addrSel) : null;
        var accSel = el.getAttribute('data-acc-target');
        var accEl = accSel ? document.querySelector(accSel) : null;

        var mapEl = el.querySelector('[data-geo-field-map]');
        var statusEl = el.querySelector('[data-geo-field-status]');
        var locateBtn = el.querySelector('[data-geo-field-locate]');

        var Geo = window.ForensiQGeo;
        var flagM = parseInt(el.getAttribute('data-acc-flag-m') || '', 10)
            || (Geo && Geo.ACC_FLAG_M) || 50;
        var map = null, picker = null;
        var addrTouched = false;  // o utilizador editou a morada → não atropelar

        if (addrEl) addrEl.addEventListener('input', function () { addrTouched = true; });

        function setStatus(text, kind) {
            if (!statusEl) return;
            statusEl.textContent = text || '';
            statusEl.className = 'geo-field__status' + (kind ? ' geo-field__status--' + kind : '');
        }

        function place(lat, lng) {
            // Com mapa: pino + inputs via primitivo único (FQMap.bindPinPicker);
            // sem Leaflet nesta página: só os inputs.
            if (picker) {
                picker.place(lat, lng);
            } else {
                if (latEl) latEl.value = lat.toFixed(dec);
                if (lngEl) lngEl.value = lng.toFixed(dec);
            }
        }

        // Coordenadas vindas de GPS/mapa são autoritativas → bloqueiam-se para
        // edição livre (evita erros de digitação); o ajuste fino faz-se clicando
        // no mapa. A morada NÃO bloqueia (pode acrescentar-se o andar, etc.).
        // readonly (não disabled): o campo continua a ser submetido.
        function lockCoords(locked) {
            [latEl, lngEl].forEach(function (el) {
                if (!el) return;
                if (locked) el.setAttribute('readonly', '');
                else el.removeAttribute('readonly');
            });
        }

        function reverse(lat, lng) {
            if (!doReverse || !addrEl || !Geo) return;
            if (addrTouched && addrEl.value.trim()) return;  // respeita edição manual
            Geo.reverseGeocode(lat, lng)
                .then(function (res) { if (res.address && !addrTouched) addrEl.value = res.address; })
                .catch(function () { /* a morada é conveniência: falha em silêncio */ });
        }

        // --- Mapa (só se o Leaflet estiver presente nesta página) ---
        if (mapEl && typeof L !== 'undefined' && window.FQMap) {
            var FQMap = window.FQMap;
            var la0 = parseFloat(latEl && latEl.value), ln0 = parseFloat(lngEl && lngEl.value);
            var has0 = !isNaN(la0) && !isNaN(ln0);
            map = FQMap.createMap(mapEl, {
                center: has0 ? [la0, ln0] : FQMap.DEFAULT_VIEW.center,
                zoom: has0 ? FQMap.DEFAULT_ZOOM : FQMap.DEFAULT_VIEW.zoom,
                zoomControl: true,
            });
            el._fqGeoMap = map;   // para o teardown em fq:modal-close
            // Pin-picker na fonte única; as reações próprias deste campo
            // (recentrar sempre, bloquear/limpar/estado/morada) ficam nos callbacks.
            picker = FQMap.bindPinPicker(map, {
                latEl: latEl,
                lngEl: lngEl,
                decimals: dec,
                onPlace: function (lat, lng, source) {
                    map.setView([lat, lng], Math.max(map.getZoom(), FQMap.DEFAULT_ZOOM));
                    if (source === 'click') {
                        lockCoords(true);
                        if (accEl) accEl.value = '';   // já não é a precisão do GPS
                        setStatus('Localização escolhida no mapa.', 'ok');
                        reverse(lat, lng);
                    }
                },
                onSync: function (la, ln) {
                    if (accEl) accEl.value = '';
                    reverse(la, ln);
                },
            });
            if (has0) picker.place(la0, ln0, 'init');
            FQMap.refreshSize(map, mapEl);
        } else if (mapEl) {
            mapEl.hidden = true;  // sem Leaflet: esconde o mapa, mantém o resto
        }

        function locate() {
            if (!Geo) { setStatus('Geolocalização indisponível neste dispositivo.', 'error'); return; }
            setStatus('A localizar…', 'busy');
            if (locateBtn) locateBtn.disabled = true;
            // Captura + preenchimento + limiar na fonte única (Geo.captureToFields);
            // aqui fica só o pino/recentrar e a apresentação do estado.
            Geo.captureToFields({
                latEl: latEl, lngEl: lngEl, accEl: accEl,
                decimals: dec, flagM: flagM, highAccuracy: true,
            })
                .then(function (r) {
                    place(r.lat, r.lng);
                    lockCoords(true);
                    if (r.flagged) {
                        setStatus('Localização obtida (±' + r.m + ' m — pouco precisa; ajuste no mapa se necessário).', 'flag');
                    } else {
                        setStatus('Localização obtida (±' + r.m + ' m). Ajuste no mapa se o facto ocorreu noutro ponto.', 'ok');
                    }
                    reverse(r.lat, r.lng);
                })
                .catch(function (err) {
                    setStatus(Geo.errorMessage(err) + ' Clique no mapa ou escreva as coordenadas.', 'error');
                })
                .finally(function () { if (locateBtn) locateBtn.disabled = false; });
        }

        if (locateBtn) locateBtn.addEventListener('click', locate);

        // Edição manual SEM mapa nesta página: o pin-picker (que normalmente faz
        // o sync) não existe — mantém-se a limpeza da precisão + morada.
        if (!picker) {
            var manualSync = function () {
                var la = parseFloat(latEl && latEl.value), ln = parseFloat(lngEl && lngEl.value);
                if (isNaN(la) || isNaN(ln)) return;
                if (accEl) accEl.value = '';
                reverse(la, ln);
            };
            if (latEl) latEl.addEventListener('change', manualSync);
            if (lngEl) lngEl.addEventListener('change', manualSync);
        }

        // Auto-localiza ao abrir — mas nunca atropela coordenadas já presentes
        // (ex.: re-render após erro de validação preserva o que o utilizador pôs).
        var hasCoords = !!(latEl && lngEl && latEl.value && lngEl.value);
        if (hasCoords) {
            lockCoords(true);   // coordenadas já fixadas (ex.: re-render após erro)
            setStatus('Coordenadas preenchidas — ajuste no mapa se necessário.', 'ok');
        } else if (autolocate) {
            locate();
        } else {
            setStatus('Clique no mapa para marcar a localização.', '');
        }
    }

    function initAll(root) {
        var scope = root || document;
        var els = scope.querySelectorAll('[data-geo-field]');
        for (var i = 0; i < els.length; i++) initOne(els[i]);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initAll(); });
    } else {
        initAll();
    }
    // Modal ação-in-place: o fragmento é injetado depois do load.
    document.addEventListener('fq:modal-open', function (ev) {
        initAll(ev.detail && ev.detail.root);
    });
    // Teardown do mapa ao fechar o modal (antes fugia — auditoria D73): o
    // desmonte vive na fonte única FQMap.destroy.
    document.addEventListener('fq:modal-close', function (ev) {
        if (!window.FQMap) return;
        var root = (ev.detail && ev.detail.root) || document;
        var els = root.querySelectorAll('[data-geo-field]');
        for (var i = 0; i < els.length; i++) {
            if (els[i]._fqGeoMap) {
                window.FQMap.destroy(els[i]._fqGeoMap, els[i].querySelector('[data-geo-field-map]'));
                els[i]._fqGeoMap = null;
                els[i]._fqGeoFieldReady = false;
            }
        }
    });
})();
