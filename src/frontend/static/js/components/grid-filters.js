/**
 * ForensiQ — Painel de filtros no telemóvel (CSP-safe, ficheiro estático).
 *
 * No telemóvel a grelha de ocorrências reduz-se a 4 colunas e a linha de filtros
 * por coluna (no <thead>) esconde-se; o botão "Filtros" (data-filters-toggle), que
 * vive na toolbar FORA do alvo de swap do HTMX, alterna o atributo
 * `data-filters-open` no <form class="grid-form"> e o CSS revela a linha de filtros
 * como painel empilhado. Como o atributo fica no form (não trocado) e o listener é
 * delegado no document, o estado SOBREVIVE aos swaps da grelha. Sem estilo inline,
 * sem eval — só toggleAttribute/aria (permitido pelo CSP).
 */
(function () {
    'use strict';
    if (window.__fqGridFiltersReady) return;
    window.__fqGridFiltersReady = true;

    document.addEventListener('click', function (ev) {
        var btn = ev.target.closest('[data-filters-toggle]');
        if (!btn) return;
        var form = btn.closest('.grid-form');
        if (!form) return;
        ev.preventDefault();
        var open = form.toggleAttribute('data-filters-open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
})();
