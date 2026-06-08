/**
 * ForensiQ — Posicionamento do popover de filtro (CSP-safe, ficheiro estático).
 *
 * O filtro de data é um `<details class="filter-pop">` no cabeçalho da grelha.
 * O painel (`.filter-pop__panel`) seria cortado pelo `overflow` da `.gridwrap`
 * (ficava "atrás" do conteúdo/rodapé). Aqui, ao abrir, posiciona-se o painel em
 * `position: fixed` ancorado ao botão (escapa a qualquer corte) e abre-se PARA
 * CIMA se não houver espaço em baixo. Fecha ao fazer scroll, ao redimensionar a
 * janela ou ao clicar fora. Posições via CSSOM (style.*) — permitido pelo CSP.
 */
(function () {
    'use strict';
    if (window.__fqFilterPopReady) return;
    window.__fqFilterPopReady = true;

    var current = null;  // <details> aberto

    function place(details) {
        var summary = details.querySelector('summary');
        var panel = details.querySelector('.filter-pop__panel');
        if (!summary || !panel) return;
        var r = summary.getBoundingClientRect();
        panel.style.position = 'fixed';
        panel.style.left = 'auto';
        panel.style.right = 'auto';
        var size = panel.getBoundingClientRect();
        // Horizontal: alinha à esquerda do botão, sem sair pela direita.
        var left = Math.min(r.left, window.innerWidth - size.width - 8);
        panel.style.left = Math.max(8, left) + 'px';
        // Vertical: abaixo do botão; se não houver espaço, abre para cima.
        if (r.bottom + size.height + 8 > window.innerHeight && r.top - size.height - 4 > 8) {
            panel.style.top = (r.top - size.height - 4) + 'px';
        } else {
            panel.style.top = (r.bottom + 4) + 'px';
        }
    }

    function close() {
        if (current) { current.open = false; current = null; }
    }

    // O <details> dispara `toggle` ao abrir/fechar.
    document.addEventListener('toggle', function (ev) {
        var d = ev.target;
        if (!d.classList || !d.classList.contains('filter-pop')) return;
        if (d.open) {
            if (current && current !== d) current.open = false;
            current = d;
            requestAnimationFrame(function () { place(d); });
        } else if (current === d) {
            current = null;
        }
    }, true);

    // Em scroll/resize o `fixed` deixaria de alinhar com o botão → fecha.
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    document.addEventListener('click', function (ev) {
        if (current && !current.contains(ev.target)) close();
    });
})();
