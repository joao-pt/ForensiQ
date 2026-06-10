/**
 * ForensiQ — Módulo de geolocalização partilhado (CSP-safe, ficheiro estático).
 *
 * Expõe window.ForensiQGeo com três funções baseadas em Promise, para que
 * captura de GPS, geocodificação inversa e POIs deixem de ser três scripts
 * isolados e passem a chamar uma fonte única e robusta:
 *
 *   ForensiQGeo.getPosition(opts)      -> Promise<GeolocationPosition>
 *   ForensiQGeo.reverseGeocode(lat,lon)-> Promise<{ address, raw }>
 *   ForensiQGeo.searchPOI(lat,lon,r)   -> Promise<Array<POI>>
 *   ForensiQGeo.errorMessage(err)      -> string PT-PT
 *
 * getPosition trata os três códigos de GeolocationPositionError de forma
 * distinta (1 permissão, 2 indisponível, 3 timeout) — ao contrário do código
 * anterior, que deitava fora o erro — e usa uma estratégia de dois passos:
 * tenta alta precisão com timeout curto e, se esgotar/indisponível, recai
 * para baixa precisão (fix de rede/IP, leitura recente aceite). É isto que
 * resolve o caso do PC fixo sem GPS, onde enableHighAccuracy:true + maximumAge:0
 * faziam timeout silencioso mesmo com a permissão concedida.
 *
 * As coordenadas nunca saem para terceiros a partir do browser: reverseGeocode
 * e searchPOI batem nos proxies server-side /api/reverse-geocode/ e
 * /api/nearby-pois/ (requisito RGPD).
 */
(function () {
    'use strict';

    // Idempotente: o módulo pode ser carregado globalmente (base.html) e ainda
    // por páginas que o incluem à parte — define a API uma só vez.
    if (window.ForensiQGeo) return;

    var Geo = {};

    // Limiar de sinalização da precisão (m) — FALLBACK único do lado JS; o
    // valor canónico vem de settings.GPS_ACCURACY_FLAG_M via data-acc-flag-m.
    Geo.ACC_FLAG_M = 50;

    // Mensagem única dos botões de ação geo que exigem coordenadas prévias.
    Geo.MSG_CAPTURE_FIRST = 'Capture o GPS primeiro.';

    /**
     * Resolve os inputs-alvo de um elemento com data-lat-target/data-lng-target
     * e devolve { latEl, lngEl, lat, lng } (lat/lng em float, NaN se vazio) —
     * esqueleto único dos botões de ação geo (auditoria D72).
     */
    Geo.readTargets = function (el) {
        var latEl = document.querySelector(el.getAttribute('data-lat-target') || '');
        var lngEl = document.querySelector(el.getAttribute('data-lng-target') || '');
        return {
            latEl: latEl,
            lngEl: lngEl,
            lat: latEl ? parseFloat(latEl.value) : NaN,
            lng: lngEl ? parseFloat(lngEl.value) : NaN,
        };
    };

    /**
     * Corre uma ação geo com o funil único disable→busy→catch('Falha: …')→
     * re-enable (auditoria D72). ``promiseFn`` devolve a Promise da ação; o
     * sucesso (texto/render próprios) fica no consumidor.
     */
    Geo.runAction = function (btn, statusEl, busyText, promiseFn) {
        btn.disabled = true;
        if (statusEl) statusEl.textContent = busyText || '';
        return promiseFn()
            .catch(function (e) { if (statusEl) statusEl.textContent = 'Falha: ' + e.message; })
            .finally(function () { btn.disabled = false; });
    };

    /**
     * Captura a posição E preenche os campos — o fluxo «decimals → fill →
     * precisão → flag» numa fonte única (auditoria D71). opts: { latEl, lngEl,
     * accEl, decimals, flagM, highAccuracy }. Resolve para
     * { lat, lng, m, flagged }; a APRESENTAÇÃO (status/classe) fica no consumidor.
     */
    Geo.captureToFields = function (opts) {
        return Geo.getPosition({ highAccuracy: opts.highAccuracy !== false })
            .then(function (pos) {
                var lat = pos.coords.latitude;
                var lng = pos.coords.longitude;
                var dec = (opts.decimals == null ? 5 : opts.decimals);
                if (opts.latEl) opts.latEl.value = lat.toFixed(dec);
                if (opts.lngEl) opts.lngEl.value = lng.toFixed(dec);
                var m = Math.round(pos.coords.accuracy);
                if (opts.accEl) opts.accEl.value = m;
                return { lat: lat, lng: lng, m: m, flagged: m > (opts.flagM || Geo.ACC_FLAG_M) };
            });
    };

    /** Mensagem PT-PT para um GeolocationPositionError (ou Error genérico). */
    function errorMessage(err) {
        if (!err) return 'Falha ao obter a localização.';
        switch (err.code) {
            case 1: return 'Permissão de localização negada — autorize-a no browser.';
            case 2: return 'Sem sinal de posição — num PC fixo, use o telemóvel ou introduza as coordenadas manualmente.';
            case 3: return 'Tempo de localização esgotado — tente novamente.';
            default: return err.message || 'Falha ao obter a localização.';
        }
    }
    Geo.errorMessage = errorMessage;

    /**
     * Obtém a posição atual. opts:
     *   highAccuracy   (bool, def. true)  — 1.ª tentativa em alta precisão
     *   timeout        (ms, def. 8000)    — timeout da 1.ª tentativa
     *   maximumAge     (ms, def. 0)       — idade máx. do fix da 1.ª tentativa
     *   fallbackTimeout(ms, def. 15000)   — timeout do fallback de baixa precisão
     *   fallbackMaxAge (ms, def. 60000)   — idade máx. aceite no fallback
     * Rejeita com o GeolocationPositionError completo (code + message).
     */
    Geo.getPosition = function (opts) {
        opts = opts || {};
        return new Promise(function (resolve, reject) {
            if (!navigator.geolocation) {
                var ns = new Error('GPS não suportado neste dispositivo.');
                ns.code = 0;
                reject(ns);
                return;
            }
            // navigator.geolocation só existe em contexto seguro (HTTPS/localhost);
            // se a app for servida por IP em HTTP, a API é rejeitada pelo browser.
            if (typeof window !== 'undefined' && window.isSecureContext === false) {
                var se = new Error('A geolocalização exige uma ligação segura (HTTPS).');
                se.code = -1;
                reject(se);
                return;
            }

            function attempt(highAccuracy, timeout, maximumAge, isFallback) {
                navigator.geolocation.getCurrentPosition(
                    resolve,
                    function (err) {
                        // Na 1.ª tentativa, timeout (3) ou indisponível (2) recaem
                        // uma vez para baixa precisão (rede/IP, fix em cache aceite).
                        if (!isFallback && (err.code === 3 || err.code === 2)) {
                            attempt(false, opts.fallbackTimeout || 15000, opts.fallbackMaxAge || 60000, true);
                        } else {
                            reject(err);
                        }
                    },
                    { enableHighAccuracy: highAccuracy, timeout: timeout, maximumAge: maximumAge }
                );
            }

            if (opts.highAccuracy === false) {
                attempt(false, opts.timeout || 15000, opts.maximumAge != null ? opts.maximumAge : 30000, true);
            } else {
                attempt(true, opts.timeout || 8000, opts.maximumAge != null ? opts.maximumAge : 0, false);
            }
        });
    };

    // GET JSON same-origin → window.FQFetch.getJSON (fonte única; carregado em
    // base.html antes deste módulo). reverseGeocode/searchPOI só correm a pedido,
    // pelo que FQFetch está sempre definido quando são chamados.

    /**
     * Geocodificação inversa via proxy server-side. Devolve a morada composta
     * (rua, nº, localidade, país) e o payload em bruto.
     */
    Geo.reverseGeocode = function (lat, lon) {
        return window.FQFetch.getJSON('/api/reverse-geocode/?lat=' + encodeURIComponent(lat) + '&lon=' + encodeURIComponent(lon))
            .then(function (d) {
                var a = (d && d.address) || {};
                var parts = [a.road, a.house_number, a.city, a.country].filter(function (x) { return x; });
                return { address: parts.join(', ') || (d && d.display_name) || '', raw: d };
            });
    };

    /** POIs OSM próximos via proxy server-side. Devolve sempre um array. */
    Geo.searchPOI = function (lat, lon, radius) {
        radius = radius || 500;
        return window.FQFetch.getJSON('/api/nearby-pois/?lat=' + encodeURIComponent(lat) +
            '&lon=' + encodeURIComponent(lon) + '&radius=' + encodeURIComponent(radius))
            .then(function (pois) { return pois || []; });
    };

    window.ForensiQGeo = Geo;
})();
