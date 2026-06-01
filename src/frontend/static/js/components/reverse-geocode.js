/**
 * ForensiQ — Reverse-geocode (CSP-safe, ficheiro estático).
 *
 * Botão [data-reverse-geocode] com data-lat-target / data-lng-target /
 * data-addr-target. Após captura de GPS, resolve a morada via o proxy
 * server-side /api/reverse-geocode/ (Nominatim; as coordenadas nunca saem
 * para terceiros a partir do browser — RGPD) e preenche o campo de morada.
 */
(function () {
    'use strict';
    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-reverse-geocode]') : null;
        if (!btn) return;
        ev.preventDefault();

        var latEl = document.querySelector(btn.getAttribute('data-lat-target'));
        var lngEl = document.querySelector(btn.getAttribute('data-lng-target'));
        var addrEl = document.querySelector(btn.getAttribute('data-addr-target'));
        var status = document.querySelector('[data-reverse-geocode-status]');
        if (!latEl || !lngEl || !addrEl) return;

        var lat = parseFloat(latEl.value);
        var lon = parseFloat(lngEl.value);
        if (isNaN(lat) || isNaN(lon)) {
            if (status) status.textContent = 'Capture o GPS primeiro.';
            return;
        }

        btn.disabled = true;
        if (status) status.textContent = 'A resolver morada…';
        fetch('/api/reverse-geocode/?lat=' + lat + '&lon=' + lon,
            { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) {
                return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || 'Serviço indisponível.'); return d; });
            })
            .then(function (d) {
                var a = d.address || {};
                var parts = [a.road, a.house_number, a.city, a.country].filter(function (x) { return x; });
                addrEl.value = parts.join(', ') || d.display_name || addrEl.value;
                if (status) status.textContent = '';
            })
            .catch(function (e) { if (status) status.textContent = 'Falha: ' + e.message; })
            .finally(function () { btn.disabled = false; });
    });
})();
