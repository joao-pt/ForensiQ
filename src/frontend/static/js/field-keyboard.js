/**
 * ForensiQ — Barra de ações que respeita o teclado virtual no terreno (CSP-safe).
 *
 * Só atua em páginas com `.form-actions--sticky` (formulários de captura). Usa a
 * Visual Viewport API (cross-browser) para medir a sobreposição do teclado e
 * publica-a em `--kb`, que a CSS usa para levantar a barra de ações acima do
 * teclado. Em browsers que encolhem o layout (Chrome com
 * `interactive-widget=resizes-content`) a sobreposição ≈ 0 e a barra sticky
 * `bottom:0` já fica acima do teclado; em iOS, onde o teclado sobrepõe sem
 * encolher o layout, `--kb` levanta-a. Ao focar um campo, garante que fica
 * visível (o `scrollIntoView` nativo não conhece a altura do teclado, por isso
 * corre depois de o relayout assentar).
 */
(function () {
    'use strict';
    if (!document.querySelector('.form-actions--sticky')) return;

    var vv = window.visualViewport;
    if (vv) {
        var update = function () {
            var overlap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
            document.documentElement.style.setProperty('--kb', overlap + 'px');
        };
        vv.addEventListener('resize', update);
        vv.addEventListener('scroll', update);
        update();
    }

    document.addEventListener('focusin', function (ev) {
        var t = ev.target;
        if (!t || !t.matches || !t.matches('input, textarea, select')) return;
        setTimeout(function () {
            try { t.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { /* no-op */ }
        }, 80);
    });
})();
