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
    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-reverse-geocode]') : null;
        if (!btn) return;
        ev.preventDefault();

        var Geo = window.ForensiQGeo;
        var latEl = document.querySelector(btn.getAttribute('data-lat-target'));
        var lngEl = document.querySelector(btn.getAttribute('data-lng-target'));
        var addrEl = document.querySelector(btn.getAttribute('data-addr-target'));
        var status = document.querySelector('[data-reverse-geocode-status]');
        if (!latEl || !lngEl || !addrEl || !Geo) return;

        var lat = parseFloat(latEl.value);
        var lon = parseFloat(lngEl.value);
        if (isNaN(lat) || isNaN(lon)) {
            if (status) status.textContent = 'Capture o GPS primeiro.';
            return;
        }

        btn.disabled = true;
        if (status) status.textContent = 'A resolver morada…';
        Geo.reverseGeocode(lat, lon)
            .then(function (res) {
                addrEl.value = res.address || addrEl.value;
                if (status) status.textContent = '';
            })
            .catch(function (e) { if (status) status.textContent = 'Falha: ' + e.message; })
            .finally(function () { btn.disabled = false; });
    });
})();
