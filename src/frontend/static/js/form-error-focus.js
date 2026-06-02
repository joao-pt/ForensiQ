/**
 * ForensiQ — Foco no primeiro erro de formulário após re-render (CSP-safe).
 *
 * Quando o servidor reapresenta um formulário com erros de validação, a página
 * volta ao topo e, num formulário longo, o primeiro campo inválido pode ficar
 * fora do ecrã — sem qualquer indicação de onde corrigir, sobretudo em mobile.
 *
 * Ao carregar, este script:
 *   1. procura o primeiro controlo com [aria-invalid="true"], foca-o e
 *      desloca-o para o centro do ecrã (scrollIntoView);
 *   2. se não houver erro por campo mas existir um resumo de erros gerais
 *      ([role="alert"] no topo), torna-o focável (tabindex=-1) e foca-o, para
 *      o leitor de ecrã o anunciar e o utilizador ver onde está o problema.
 *
 * Sem dependências; carregado no extra_js dos formulários de terreno.
 */
(function () {
    'use strict';

    function focusFirstError() {
        var field = document.querySelector('[aria-invalid="true"]');
        if (field) {
            try { field.focus({ preventScroll: true }); } catch (e) { field.focus(); }
            try { field.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e2) { /* no-op */ }
            return;
        }

        var summary = document.querySelector('[role="alert"]');
        if (summary) {
            if (!summary.hasAttribute('tabindex')) summary.setAttribute('tabindex', '-1');
            try { summary.focus({ preventScroll: true }); } catch (e3) { summary.focus(); }
            try { summary.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e4) { /* no-op */ }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', focusFirstError);
    } else {
        focusFirstError();
    }
})();
