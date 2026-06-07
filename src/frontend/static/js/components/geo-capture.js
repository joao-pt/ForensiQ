/**
 * ForensiQ — Captura de GPS (CSP-safe, ficheiro estático).
 *
 * Botão [data-geo-capture] com:
 *   data-lat-target / data-lng-target : seletores dos inputs a preencher
 *   data-acc-target                   : (opcional) input para a precisão em metros
 *   data-decimals                     : casas decimais (AGENTE 3 ~110m / PERITO 4 ~11m)
 *   data-high-accuracy="false"        : (opcional) força arranque em baixa precisão
 * Mostra a precisão num elemento [data-geo-acc] e sinaliza ±>50m (lab).
 *
 * Delega em window.ForensiQGeo.getPosition (módulo geo.js), que trata os
 * códigos de erro de forma distinta e recai para baixa precisão no desktop.
 */
(function () {
    'use strict';
    // Idempotente: handler delegado em document.body — liga UMA vez mesmo que o
    // script seja carregado globalmente (base.html) e por páginas à parte, para
    // não duplicar a captura de GPS por clique.
    if (window.__fqGeoCaptureReady) return;
    window.__fqGeoCaptureReady = true;
    window.FQDom.onClick('[data-geo-capture]', function (btn) {
        var Geo = window.ForensiQGeo;
        // Resolve o indicador de precisão relativamente ao botão clicado: cada
        // bloco de geolocalização (.form-inline) tem o seu próprio [data-geo-acc].
        // Fallback global para layouts que não embrulhem o botão num .form-inline.
        var scope = btn.closest('.form-inline');
        var acc = (scope && scope.querySelector('[data-geo-acc]')) || document.querySelector('[data-geo-acc]');
        if (!Geo) { if (acc) acc.textContent = 'Geolocalização indisponível.'; return; }

        var latEl = document.querySelector(btn.getAttribute('data-lat-target'));
        var lngEl = document.querySelector(btn.getAttribute('data-lng-target'));
        var accTargetSel = btn.getAttribute('data-acc-target');
        var accEl = accTargetSel ? document.querySelector(accTargetSel) : null;
        var dec = parseInt(btn.getAttribute('data-decimals') || '5', 10);

        btn.disabled = true;
        if (acc) { acc.textContent = 'A localizar…'; acc.classList.remove('geo-acc--flag', 'geo-acc--error'); }

        Geo.getPosition({ highAccuracy: btn.getAttribute('data-high-accuracy') !== 'false' })
            .then(function (pos) {
                if (latEl) latEl.value = pos.coords.latitude.toFixed(dec);
                if (lngEl) lngEl.value = pos.coords.longitude.toFixed(dec);
                var m = Math.round(pos.coords.accuracy);
                // A precisão só é persistida em páginas de MOVIMENTO de custódia
                // (campo gps_accuracy_m do evento); na génese da prova é só informativa.
                if (accEl) accEl.value = m;
                if (acc) {
                    acc.textContent = '±' + m + ' m';
                    acc.classList.toggle('geo-acc--flag', m > 50);
                }
                // Sinaliza a captura para componentes dependentes (ex.: POIs próximos),
                // que só funcionam depois de haver coordenadas.
                document.dispatchEvent(new CustomEvent('forensiq:geo-captured', {
                    detail: {
                        latTarget: btn.getAttribute('data-lat-target'),
                        lngTarget: btn.getAttribute('data-lng-target')
                    }
                }));
            })
            .catch(function (err) {
                if (acc) { acc.textContent = Geo.errorMessage(err); acc.classList.add('geo-acc--error'); }
            })
            .finally(function () { btn.disabled = false; });
    });
})();
