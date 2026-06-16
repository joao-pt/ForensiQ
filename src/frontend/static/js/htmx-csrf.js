/**
 * ForensiQ — CSRF para pedidos HTMX.
 *
 * Sob a CSP estrita (sem unsafe-inline) o token CSRF não pode ser injetado
 * por <script> inline em cada fragmento. Este ficheiro regista um listener
 * `htmx:configRequest` que adiciona o header `X-CSRFToken` a TODOS os
 * pedidos HTMX, lendo o token do cookie `csrftoken` (mesmo critério usado
 * em auth.js para os pedidos `fetch`). Cobre qualquer fragmento HTMX
 * mutante — presente (o form modal de _modal_form_open.html) ou futuro —
 * sem depender de cada form embeber o campo `csrfmiddlewaretoken`.
 *
 * Vive em _grid_scripts.html, logo a seguir ao htmx.min.js (fonte ÚNICA do
 * runtime HTMX). IIFE puro — zero bindings de topo (teste estrutural
 * tests_frontend_js_namespace.py).
 */
(() => {
    'use strict';

    function csrfToken() {
        const row = document.cookie.split('; ').find(r => r.startsWith('csrftoken='));
        return row ? row.split('=')[1] : '';
    }

    // htmx:configRequest borbulha até ao document; o detail.headers é o objeto
    // mutável de headers a enviar. GET/HEAD não passam pela verificação CSRF do
    // Django — mandar o header nesses casos é inócuo, por isso não filtramos.
    document.addEventListener('htmx:configRequest', (evt) => {
        evt.detail.headers['X-CSRFToken'] = csrfToken();
    });
})();
