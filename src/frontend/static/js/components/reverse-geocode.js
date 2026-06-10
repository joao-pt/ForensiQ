/**
 * ForensiQ — Reverse-geocode (CSP-safe, ficheiro estático).
 *
 * Botão [data-reverse-geocode] com data-lat-target / data-lng-target /
 * data-addr-target. Após captura de GPS, resolve a morada via
 * window.ForensiQGeo.reverseGeocode (proxy server-side /api/reverse-geocode/;
 * as coordenadas nunca saem para terceiros a partir do browser — RGPD) e
 * preenche o campo de morada.
 */
(function () {
    'use strict';
    // Idempotente: handler delegado em document.body — liga UMA vez mesmo que o
    // script seja carregado globalmente (base.html) e por páginas à parte.
    if (window.__fqReverseGeocodeReady) return;
    window.__fqReverseGeocodeReady = true;
    window.FQDom.onClick('[data-reverse-geocode]', function (btn) {
        var Geo = window.ForensiQGeo;
        var addrEl = document.querySelector(btn.getAttribute('data-addr-target'));
        var status = document.querySelector('[data-reverse-geocode-status]');
        if (!Geo || !addrEl) return;

        // Esqueleto do botão de ação geo na fonte única (Geo.readTargets +
        // Geo.runAction — auditoria D72); aqui fica só o preenchimento da morada.
        var t = Geo.readTargets(btn);
        if (!t.latEl || !t.lngEl) return;
        if (isNaN(t.lat) || isNaN(t.lng)) {
            if (status) status.textContent = Geo.MSG_CAPTURE_FIRST;
            return;
        }

        Geo.runAction(btn, status, 'A resolver morada…', function () {
            return Geo.reverseGeocode(t.lat, t.lng).then(function (res) {
                addrEl.value = res.address || addrEl.value;
                if (status) status.textContent = '';
            });
        });
    });
})();
