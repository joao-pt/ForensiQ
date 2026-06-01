/**
 * ForensiQ — Captura de GPS (CSP-safe, ficheiro estático).
 *
 * Botão [data-geo-capture] com:
 *   data-lat-target / data-lng-target : seletores dos inputs a preencher
 *   data-decimals                     : casas decimais (AGENTE 3 ~110m / PERITO 4 ~11m)
 * Mostra a precisão num elemento [data-geo-acc] e sinaliza ±>50m (lab).
 * navigator.geolocation exige HTTPS (ou localhost).
 */
(function () {
    'use strict';
    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-geo-capture]') : null;
        if (!btn) return;
        ev.preventDefault();
        var acc = document.querySelector('[data-geo-acc]');
        if (!navigator.geolocation) { if (acc) acc.textContent = 'GPS não suportado'; return; }

        var latEl = document.querySelector(btn.getAttribute('data-lat-target'));
        var lngEl = document.querySelector(btn.getAttribute('data-lng-target'));
        var accTargetSel = btn.getAttribute('data-acc-target');
        var accEl = accTargetSel ? document.querySelector(accTargetSel) : null;
        var dec = parseInt(btn.getAttribute('data-decimals') || '5', 10);
        btn.disabled = true;
        if (acc) acc.textContent = 'A localizar…';

        navigator.geolocation.getCurrentPosition(
            function (pos) {
                if (latEl) latEl.value = pos.coords.latitude.toFixed(dec);
                if (lngEl) lngEl.value = pos.coords.longitude.toFixed(dec);
                var m = Math.round(pos.coords.accuracy);
                if (accEl) accEl.value = m;  // precisão persistida (gps_accuracy_m)
                if (acc) {
                    acc.textContent = '±' + m + ' m';
                    acc.classList.toggle('geo-acc--flag', m > 50);
                }
                btn.disabled = false;
            },
            function () {
                if (acc) acc.textContent = 'GPS indisponível';
                btn.disabled = false;
            },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    });
})();
