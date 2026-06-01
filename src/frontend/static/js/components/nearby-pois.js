/**
 * ForensiQ — POIs próximos para nomear o local de um evento (CSP-safe).
 *
 * Botão [data-nearby-pois] com data-lat-target / data-lng-target /
 * data-pois-target (id de um <datalist>) / data-radius. Após captura de GPS,
 * preenche o <datalist> com POIs OSM (esquadra, tribunal, laboratório…) via o
 * proxy server-side /api/nearby-pois/ (Overpass). O utilizador escolhe um ou
 * escreve livremente no input associado (location_name).
 */
(function () {
    'use strict';

    // O botão só é útil depois de haver coordenadas: arranca desativado quando
    // os campos de GPS estão vazios e é reativado pela captura (geo-capture.js).
    function hasCoords(btn) {
        var latEl = document.querySelector(btn.getAttribute('data-lat-target'));
        var lngEl = document.querySelector(btn.getAttribute('data-lng-target'));
        return !!(latEl && lngEl && latEl.value.trim() && lngEl.value.trim());
    }
    function refreshButtons() {
        var btns = document.querySelectorAll('[data-nearby-pois]');
        Array.prototype.forEach.call(btns, function (btn) {
            btn.disabled = !hasCoords(btn);
        });
    }
    refreshButtons();
    document.addEventListener('forensiq:geo-captured', refreshButtons);
    // Reavalia também na digitação manual de coordenadas (campos visíveis).
    document.addEventListener('input', refreshButtons);

    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-nearby-pois]') : null;
        if (!btn) return;
        ev.preventDefault();

        var latEl = document.querySelector(btn.getAttribute('data-lat-target'));
        var lngEl = document.querySelector(btn.getAttribute('data-lng-target'));
        var datalist = document.querySelector(btn.getAttribute('data-pois-target'));
        var status = document.querySelector('[data-nearby-pois-status]');
        if (!latEl || !lngEl || !datalist) return;

        var lat = parseFloat(latEl.value);
        var lon = parseFloat(lngEl.value);
        if (isNaN(lat) || isNaN(lon)) {
            if (status) status.textContent = 'Capture o GPS primeiro.';
            return;
        }
        var radius = parseInt(btn.getAttribute('data-radius') || '500', 10);

        btn.disabled = true;
        if (status) status.textContent = 'A carregar POIs…';
        fetch('/api/nearby-pois/?lat=' + lat + '&lon=' + lon + '&radius=' + radius,
            { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) {
                return r.json().then(function (d) { if (!r.ok) throw new Error((d && d.detail) || 'Serviço indisponível.'); return d; });
            })
            .then(function (pois) {
                datalist.innerHTML = '';
                (pois || []).forEach(function (p) {
                    var o = document.createElement('option');
                    o.value = p.nome + ' (' + p.tipo + ', ±' + p.dist_m + 'm)';
                    datalist.appendChild(o);
                });
                if (status) status.textContent = (pois && pois.length) ? (pois.length + ' POIs encontrados') : 'Sem POIs próximos';
            })
            .catch(function (e) { if (status) status.textContent = 'Falha: ' + e.message; })
            .finally(function () { btn.disabled = false; });
    });
})();
