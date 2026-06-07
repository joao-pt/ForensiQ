/**
 * ForensiQ — Helpers de DOM (FONTE ÚNICA).
 *
 * CSP-safe: ficheiro estático, sem eval/inline. Exposto como `window.FQDom`
 * (sem ES modules, para não quebrar o carregamento via <script>). Carregado em
 * base.html ANTES dos componentes de página que o usam.
 *
 * Centraliza o idioma de clique-delegado repetido nos componentes de ação
 * (geo-capture, reverse-geocode, identifier-lookup, nearby-pois): um único
 * listener em document.body que resolve o elemento de ação mais próximo via
 * `closest` — assim cobre também os fragmentos de modal injetados depois do
 * load, sem religar — e cancela o comportamento por omissão. A guarda
 * `ev.target.closest ? … : null` protege alvos sem `closest` (nós de texto,
 * document); antes estava copiada à mão em cada componente.
 *
 *   FQDom.onClick(selector, handler)  — liga um handler delegado a cliques em
 *       elementos que correspondam a `selector` (ou seus descendentes). O
 *       handler recebe (btn, ev): o elemento correspondente e o evento. O
 *       preventDefault já foi chamado; chame ev.stopPropagation() se precisar.
 */
(function () {
    'use strict';

    // Idempotente: pode ser carregado globalmente (base.html) e por páginas à
    // parte — define a API uma só vez.
    if (window.FQDom) return;

    function onClick(selector, handler) {
        document.body.addEventListener('click', function (ev) {
            var btn = ev.target.closest ? ev.target.closest(selector) : null;
            if (!btn) return;
            ev.preventDefault();
            handler(btn, ev);
        });
    }

    window.FQDom = { onClick: onClick };
})();
