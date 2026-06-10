/**
 * ForensiQ — POIs próximos para nomear o local de um evento (CSP-safe).
 *
 * Botão [data-nearby-pois] com:
 *   data-lat-target / data-lng-target : seletores dos inputs de coordenadas
 *   data-input-target                 : input location_name a preencher na escolha
 *   data-pois-list-target             : container onde renderizar o picker (botões)
 *   data-pois-target                  : (fallback) <datalist> a preencher
 *   data-radius                       : raio em metros (def. 500)
 *
 * Após captura de GPS, obtém POIs OSM via window.ForensiQGeo.searchPOI (proxy
 * server-side /api/nearby-pois/). Renderiza uma lista de botões SELECIONÁVEIS
 * (fiável em telemóvel, ao contrário do <datalist>, que muitos browsers móveis
 * não deixam escolher); a escolha escreve no input location_name. O <datalist>
 * é mantido como fallback progressivo onde existir.
 */
(function () {
    'use strict';

    function q(sel) { return sel ? document.querySelector(sel) : null; }

    // O botão só é útil depois de haver coordenadas: arranca desativado quando
    // os campos de GPS estão vazios e é reativado pela captura (geo-capture.js)
    // ou pela digitação manual.
    function hasCoords(btn) {
        var latEl = q(btn.getAttribute('data-lat-target'));
        var lngEl = q(btn.getAttribute('data-lng-target'));
        return !!(latEl && lngEl && latEl.value.trim() && lngEl.value.trim());
    }
    function refreshButtons() {
        Array.prototype.forEach.call(document.querySelectorAll('[data-nearby-pois]'), function (btn) {
            btn.disabled = !hasCoords(btn);
        });
    }
    refreshButtons();
    document.addEventListener('forensiq:geo-captured', refreshButtons);
    document.addEventListener('input', refreshButtons);

    function renderPicker(listEl, inputEl, datalist, pois) {
        // Fallback progressivo: <datalist> para quem o suporta (desktop).
        if (datalist) {
            datalist.innerHTML = '';
            pois.forEach(function (p) {
                var o = document.createElement('option');
                o.value = p.nome + ' (' + p.tipo + ', ±' + p.dist_m + 'm)';
                datalist.appendChild(o);
            });
        }
        if (!listEl) return;
        listEl.innerHTML = '';
        if (!pois.length) { listEl.hidden = true; return; }
        pois.forEach(function (p) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'poi-chip';
            b.setAttribute('aria-pressed', 'false');
            var name = document.createElement('span');
            name.className = 'poi-chip__name';
            name.textContent = p.nome;
            var meta = document.createElement('span');
            meta.className = 'poi-chip__meta mono';
            meta.textContent = p.tipo + ' · ±' + p.dist_m + 'm';
            b.appendChild(name);
            b.appendChild(meta);
            b.addEventListener('click', function () {
                if (inputEl) {
                    inputEl.value = p.nome;
                    inputEl.dispatchEvent(new Event('change', { bubbles: true }));
                }
                Array.prototype.forEach.call(listEl.querySelectorAll('.poi-chip[aria-pressed="true"]'), function (c) {
                    c.setAttribute('aria-pressed', 'false');
                });
                b.setAttribute('aria-pressed', 'true');
            });
            listEl.appendChild(b);
        });
        listEl.hidden = false;
    }

    window.FQDom.onClick('[data-nearby-pois]', function (btn) {
        var Geo = window.ForensiQGeo;
        var datalist = q(btn.getAttribute('data-pois-target'));
        var listEl = q(btn.getAttribute('data-pois-list-target'));
        var inputEl = q(btn.getAttribute('data-input-target'));
        var status = document.querySelector('[data-nearby-pois-status]');
        if (!Geo) return;

        // Esqueleto do botão de ação geo na fonte única (Geo.readTargets +
        // Geo.runAction — auditoria D72); aqui fica só o render do picker.
        var t = Geo.readTargets(btn);
        if (!t.latEl || !t.lngEl) return;
        if (isNaN(t.lat) || isNaN(t.lng)) {
            if (status) status.textContent = Geo.MSG_CAPTURE_FIRST;
            return;
        }
        var radius = parseInt(btn.getAttribute('data-radius') || '500', 10);

        Geo.runAction(btn, status, 'A carregar POIs…', function () {
            return Geo.searchPOI(t.lat, t.lng, radius).then(function (pois) {
                renderPicker(listEl, inputEl, datalist, pois);
                if (status) status.textContent = pois.length ? (pois.length + ' POIs encontrados') : 'Sem POIs próximos';
            });
        });
    });
})();
