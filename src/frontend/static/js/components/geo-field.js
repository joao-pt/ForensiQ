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

    var DEFAULT = { lat: 39.5, lng: -8.0, zoom: 6 };  // Portugal continental

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
        var map = null, marker = null;
        var addrTouched = false;  // o utilizador editou a morada → não atropelar

        if (addrEl) addrEl.addEventListener('input', function () { addrTouched = true; });

        function setStatus(text, kind) {
            if (!statusEl) return;
            statusEl.textContent = text || '';
            statusEl.className = 'geo-field__status' + (kind ? ' geo-field__status--' + kind : '');
        }

        function place(lat, lng) {
            if (map) {
                if (marker) marker.setLatLng([lat, lng]);
                else marker = L.marker([lat, lng]).addTo(map);
                map.setView([lat, lng], Math.max(map.getZoom(), 15));
            }
            if (latEl) latEl.value = lat.toFixed(dec);
            if (lngEl) lngEl.value = lng.toFixed(dec);
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
            var la0 = parseFloat(latEl && latEl.value), ln0 = parseFloat(lngEl && lngEl.value);
            var has0 = !isNaN(la0) && !isNaN(ln0);
            map = window.FQMap.createMap(mapEl, {
                center: has0 ? [la0, ln0] : [DEFAULT.lat, DEFAULT.lng],
                zoom: has0 ? 15 : DEFAULT.zoom,
                zoomControl: true,
            });
            if (has0) place(la0, ln0);
            map.on('click', function (ev) {
                place(ev.latlng.lat, ev.latlng.lng);
                lockCoords(true);
                if (accEl) accEl.value = '';   // já não é a precisão do GPS
                setStatus('Localização escolhida no mapa.', 'ok');
                reverse(ev.latlng.lat, ev.latlng.lng);
            });
            window.FQMap.refreshSize(map, mapEl);
        } else if (mapEl) {
            mapEl.hidden = true;  // sem Leaflet: esconde o mapa, mantém o resto
        }

        function locate() {
            if (!Geo) { setStatus('Geolocalização indisponível neste dispositivo.', 'error'); return; }
            setStatus('A localizar…', 'busy');
            if (locateBtn) locateBtn.disabled = true;
            Geo.getPosition({ highAccuracy: true })
                .then(function (pos) {
                    var lat = pos.coords.latitude, lng = pos.coords.longitude;
                    place(lat, lng);
                    lockCoords(true);
                    var m = Math.round(pos.coords.accuracy);
                    if (accEl) accEl.value = m;
                    if (m > flagM) {
                        setStatus('Localização obtida (±' + m + ' m — pouco precisa; ajuste no mapa se necessário).', 'flag');
                    } else {
                        setStatus('Localização obtida (±' + m + ' m). Ajuste no mapa se o facto ocorreu noutro ponto.', 'ok');
                    }
                    reverse(lat, lng);
                })
                .catch(function (err) {
                    setStatus(Geo.errorMessage(err) + ' Clique no mapa ou escreva as coordenadas.', 'error');
                })
                .finally(function () { if (locateBtn) locateBtn.disabled = false; });
        }

        if (locateBtn) locateBtn.addEventListener('click', locate);

        // Edição manual das coordenadas → reposiciona o pino e resolve a morada.
        function syncFromInputs() {
            var la = parseFloat(latEl && latEl.value), ln = parseFloat(lngEl && lngEl.value);
            if (isNaN(la) || isNaN(ln)) return;
            place(la, ln);
            if (accEl) accEl.value = '';
            reverse(la, ln);
        }
        if (latEl) latEl.addEventListener('change', syncFromInputs);
        if (lngEl) lngEl.addEventListener('change', syncFromInputs);

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
})();
