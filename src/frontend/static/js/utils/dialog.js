/**
 * ForensiQ — Plumbing partilhada de <dialog> nativo central (CSP-safe).
 *
 * Fonte ÚNICA do "abrir / fechar / clique-no-fundo" usada tanto pelo modal de
 * AÇÃO (modal-action.js) como pela confirmação de fim de sessão (user-menu.js).
 * Antes cada um reimplementava o mesmo showModal()/close()/backdrop — agora
 * partilham este helper. A centragem e o ::backdrop vivem no CSS
 * (.app-modal / .confirm-dialog, base partilhada). Sem dependências externas
 * nem handlers inline (CSP estrita).
 */
(function () {
    'use strict';

    function open(dialog, getFocus) {
        if (!dialog) return;
        if (typeof dialog.showModal === 'function') {
            if (!dialog.open) dialog.showModal();
        } else {
            dialog.setAttribute('open', '');  // recurso p/ navegadores muito antigos
        }
        // Foco depois do paint (deixa o navegador montar o top-layer primeiro).
        // getFocus() devolve o elemento a focar — calculado tarde porque o
        // conteúdo do modal pode ter sido injetado por HTMX no mesmo instante.
        requestAnimationFrame(function () {
            var target = typeof getFocus === 'function' ? getFocus() : null;
            if (target && typeof target.focus === 'function') {
                try { target.focus(); } catch (e) { /* noop */ }
            }
        });
    }

    function close(dialog) {
        if (!dialog) return;
        if (dialog.open && typeof dialog.close === 'function') dialog.close();
        else dialog.removeAttribute('open');
    }

    // Clique no fundo do <dialog> nativo (o target é o próprio <dialog>) fecha.
    // Idempotente: liga uma só vez por elemento.
    function bindBackdropClose(dialog) {
        if (!dialog || dialog.__fqBackdrop) return;
        dialog.__fqBackdrop = true;
        dialog.addEventListener('click', function (ev) {
            if (ev.target === dialog) close(dialog);
        });
    }

    window.FQDialog = { open: open, close: close, bindBackdropClose: bindBackdropClose };
})();
