/**
 * ForensiQ — Helpers de fetch JSON (FONTE ÚNICA).
 *
 * CSP-safe: ficheiro estático, sem eval/inline. Exposto como `window.FQFetch`
 * (sem ES modules, para não quebrar o carregamento via <script>). Carregado em
 * base.html ANTES dos componentes (geo.js, crime-cascade.js, identifier-lookup.js)
 * que o usam.
 *
 * Centraliza o pedido GET same-origin (cookie JWT) a pedir JSON, antes repetido
 * em geo.js (jsonFetch), crime-cascade.js (getJSON) e identifier-lookup.js
 * (lookups IMEI/VIN) — cada um com o seu tratamento de erro ligeiramente diferente.
 *
 *   FQFetch.requestJSON(url) -> Promise<{ ok, status, data }>  (nunca rejeita por
 *       status HTTP; data=null se o corpo não for JSON. Para quem ramifica por
 *       código, ex.: 503/429.)
 *   FQFetch.getJSON(url)     -> Promise<data>  (rejeita em !ok com um Error a
 *       carregar `.status` (código HTTP) e `.detail` (campo detail do corpo).)
 */
(function () {
    'use strict';

    // Idempotente: pode ser carregado globalmente (base.html) e por páginas à
    // parte — define a API uma só vez.
    if (window.FQFetch) return;

    function requestJSON(url) {
        return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) {
                return r.json()
                    .then(function (data) { return { ok: r.ok, status: r.status, data: data }; })
                    .catch(function () { return { ok: r.ok, status: r.status, data: null }; });
            });
    }

    function getJSON(url) {
        return requestJSON(url).then(function (res) {
            if (!res.ok) {
                var detail = res.data && res.data.detail;
                var err = new Error(detail || ('HTTP ' + res.status));
                err.status = res.status;
                err.detail = detail;
                throw err;
            }
            return res.data;
        });
    }

    window.FQFetch = { requestJSON: requestJSON, getJSON: getJSON };
})();
