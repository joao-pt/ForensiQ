/**
 * ForensiQ — Modal de AÇÃO (<dialog> nativo central). CSP-safe.
 *
 * Modelo de interação "ação-in-place" (Fase 7): ações de propósito único
 * (criar instituição, encaminhar prova, …) abrem num <dialog> central SOBRE a
 * página atual, sem trocar de janela — para o utilizador não se perder. O
 * DETALHE read-only não tem painel próprio: as linhas navegam para a página.
 *
 * Fluxo (progressive enhancement sobre o HTMX):
 *   1. Um gatilho [data-modal-open] tem hx-get="…?modal=1" e
 *      hx-target="#app-modal-body". O HTMX carrega o fragmento do formulário
 *      para o corpo do modal.
 *   2. Ao terminar o swap para #app-modal-body abrimos o <dialog> (showModal),
 *      pomos o título (data-modal-title do gatilho), focamos o 1.º campo e
 *      disparamos `fq:modal-open` para os componentes do fragmento (map-picker,
 *      geo, …) se iniciarem.
 *   3. O formulário submete via hx-post para o mesmo endpoint. Em erro de
 *      validação (400/422) o servidor devolve o fragmento com os erros e nós
 *      deixamos o HTMX trocar mesmo assim (por omissão não troca respostas de
 *      erro) — o status fica honesto no servidor e os erros aparecem no modal.
 *      Em sucesso o servidor responde 204 + cabeçalho HX-Redirect e o HTMX navega.
 *   4. [data-modal-close] (ou Esc — nativo do <dialog>, ou clique no fundo)
 *      fecha; ao fechar disparamos `fq:modal-close`, limpamos o corpo e
 *      devolvemos o foco ao gatilho.
 *
 * Inerte se o HTMX não estiver presente na página (os eventos nunca disparam).
 * Sem dependências; sem inline handlers (CSP estrita).
 */
(function () {
    'use strict';

    var dialog = document.getElementById('app-modal');
    if (!dialog) return;

    var body = document.getElementById('app-modal-body');
    var titleEl = document.getElementById('app-modal-title');
    var lastTrigger = null;

    // Deriva o contrato HTMX dos gatilhos (auditoria D61): no markup fica só
    // href + data-modal-open + data-modal-title; o hx-get com ?modal=1, o
    // target #app-modal-body e o swap vivem AQUI — fonte única do contrato.
    function wireTriggers(root) {
        if (typeof htmx === 'undefined') return;
        var scope = (root && root.querySelectorAll) ? root : document;
        var els = scope.querySelectorAll('[data-modal-open]:not([hx-get])');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var href = el.getAttribute('href');
            if (!href) continue;
            el.setAttribute('hx-get', href + (href.indexOf('?') >= 0 ? '&' : '?') + 'modal=1');
            el.setAttribute('hx-target', '#app-modal-body');
            el.setAttribute('hx-swap', 'innerHTML');
            htmx.process(el);
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { wireTriggers(); });
    } else {
        wireTriggers();
    }
    // Gatilhos que cheguem por swap HTMX (fragmentos de grelha, etc.).
    document.body.addEventListener('htmx:afterSwap', function (ev) {
        wireTriggers(ev.detail && ev.detail.target);
    });

    function openModal(title) {
        if (titleEl) titleEl.textContent = title || 'Ação';
        // Abre + foco via FQDialog (plumbing partilhada). Em re-render com erros
        // (POST inválido troca o fragmento para o modal) foca o 1.º campo inválido
        // — senão o resumo de erros gerais, senão o 1.º campo. O modal é dono do
        // seu foco, por isso os formulários no modal não precisam do form-error-focus.js.
        FQDialog.open(dialog, function () {
            if (!body) return null;
            var target = body.querySelector('[aria-invalid="true"]');
            if (!target) {
                var alertEl = body.querySelector('[role="alert"]');
                if (alertEl) {
                    if (!alertEl.hasAttribute('tabindex')) alertEl.setAttribute('tabindex', '-1');
                    target = alertEl;
                }
            }
            if (!target) {
                target = body.querySelector(
                    'input:not([type=hidden]):not([disabled]),select:not([disabled]),textarea:not([disabled])'
                );
            }
            // Fragmento READ-ONLY (consulta, sem campos): foca a primeira ação
            // do próprio fragmento por desenho — sem isto o showModal() nativo
            // focava o primeiro focável do <dialog> (o X do cabeçalho), um
            // destino por acidente que mudaria com o markup partilhado.
            if (!target) {
                target = body.querySelector('a[href], button:not([data-modal-close])')
                    || body.querySelector('button');
            }
            return target;
        });
        // Sinaliza para componentes que vivem dentro do fragmento (mapas, …).
        document.dispatchEvent(new CustomEvent('fq:modal-open', { detail: { root: body } }));
    }

    function closeModal() {
        FQDialog.close(dialog);
    }

    // Captura o gatilho (título + foco a restaurar) antes do pedido.
    document.body.addEventListener('htmx:beforeRequest', function (ev) {
        var elt = ev.detail && ev.detail.elt;
        var trig = elt && elt.closest && elt.closest('[data-modal-open]');
        if (trig) lastTrigger = trig;
    });

    // Erros de validação (4xx) ao alvo do modal: deixa o HTMX trocar mesmo assim.
    document.body.addEventListener('htmx:beforeSwap', function (ev) {
        var t = ev.detail && ev.detail.target;
        if (t && t.id === 'app-modal-body') {
            var s = ev.detail.xhr ? ev.detail.xhr.status : 0;
            if (s === 400 || s === 422) {
                ev.detail.shouldSwap = true;
                ev.detail.isError = false;
            }
        }
    });

    // Após carregar o fragmento para o corpo do modal, abre.
    document.body.addEventListener('htmx:afterSwap', function (ev) {
        var t = ev.detail && ev.detail.target;
        if (!t || t.id !== 'app-modal-body') return;
        var inFragment = body.querySelector('[data-modal-title]');
        var title = (lastTrigger && lastTrigger.getAttribute('data-modal-title'))
            || (inFragment && inFragment.getAttribute('data-modal-title'))
            || 'Ação';
        openModal(title);
    });

    // Fecho por botão.
    document.addEventListener('click', function (ev) {
        var closer = ev.target.closest && ev.target.closest('[data-modal-close]');
        if (closer) { ev.preventDefault(); closeModal(); }
    });

    // Clique no fundo (backdrop do <dialog> nativo) fecha — via plumbing partilhada.
    FQDialog.bindBackdropClose(dialog);

    // Limpeza ao fechar (Esc nativo, botão, fundo ou close()).
    dialog.addEventListener('close', function () {
        document.dispatchEvent(new CustomEvent('fq:modal-close', { detail: { root: body } }));
        if (body) body.innerHTML = '';
        if (lastTrigger && typeof lastTrigger.focus === 'function') {
            try { lastTrigger.focus(); } catch (e) { /* noop */ }
        }
        lastTrigger = null;
    });

    // API mínima para outros scripts.
    window.FQModal = { open: openModal, close: closeModal };
})();
