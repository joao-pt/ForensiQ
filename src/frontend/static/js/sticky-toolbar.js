/**
 * ForensiQ — Offset dinâmico do cabeçalho das grelhas (CSP-safe).
 *
 * As listas têm uma .toolbar sticky (top:0) seguida de uma .grid cujo
 * cabeçalho (thead th) também é sticky. O cabeçalho precisa de colar
 * EXATAMENTE abaixo da toolbar; com um offset fixo (o antigo top:51px) o
 * cabeçalho sobrepunha-se à 1.ª linha sempre que a toolbar embrulhava para
 * duas linhas (telemóvel, drawer aberto, ou com mais filtros).
 *
 * Este script mede a altura real da toolbar e publica-a em --toolbar-h, que
 * a forensic.css usa em `.grid thead th { top: var(--toolbar-h, 51px) }`.
 * Atualiza no load, em resize/rotação e após swaps HTMX. No-op nas páginas
 * sem toolbar (escreve 0px). Escrita de CSS var via DOM API — permitida pela
 * CSP estrita (ao contrário de <style>/atributos style inline).
 */
(function () {
    'use strict';
    function measure() {
        var bar = document.querySelector('.toolbar');
        // offsetParent === null quando o elemento (ou um ancestral) está hidden.
        var h = (bar && bar.offsetParent !== null) ? bar.offsetHeight : 0;
        document.documentElement.style.setProperty('--toolbar-h', h + 'px');
    }
    function schedule() { requestAnimationFrame(measure); }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', schedule);
    } else {
        schedule();
    }
    window.addEventListener('resize', schedule);
    window.addEventListener('orientationchange', schedule);
    // A toolbar pode mudar de altura quando um chip de filtro aparece/desaparece
    // num swap HTMX; remede após cada troca de conteúdo.
    document.body.addEventListener('htmx:afterSwap', schedule);
})();
