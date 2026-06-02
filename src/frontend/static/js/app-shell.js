/**
 * ForensiQ — App Shell (refactor v2)
 *
 * Geração de comportamento da casca da aplicação:
 *
 *   1. Relógio RT no header (pisca o `:` em modo respiratório).
 *   2. Máquina de estados do drawer lateral direito
 *      (closed / minimized / open), persistido em localStorage.
 *      Eventos: dispatch de `fq:drawer-state` para que componentes
 *      (mapas Leaflet, etc) possam refrescar layout.
 *   3. Destaque automático do link activo da sidebar via prefixo de URL.
 *   4. ESC fecha drawer aberto.
 *   5. Navegação móvel (<1024px): off-canvas da sidebar via hamburger,
 *      com fundo, foco preso, fecho por Esc / fundo / navegação.
 *   6. Encaminhamento das mensagens server-side para o toast.
 *
 * Sem dependências externas, vanilla. CSP-safe (sem inline handlers).
 */

(function () {
    'use strict';

    // -------------------------------------------------------------------
    // 1. Relógio RT
    // -------------------------------------------------------------------
    function startClock() {
        const el = document.getElementById('app-clock');
        if (!el) return;

        const sep = el.querySelector('.app-top__clock-sep');
        let blink = 'on';

        function tick() {
            const now = new Date();
            const hh = String(now.getHours()).padStart(2, '0');
            const mm = String(now.getMinutes()).padStart(2, '0');
            const ss = String(now.getSeconds()).padStart(2, '0');
            // Renderiza dígitos preservando o nó do separador para animação.
            // O <span> separador fornece o ':' entre horas e minutos (pisca),
            // por isso o primeiro nó não leva ':' (evitar HH::MM:SS).
            if (sep) {
                el.firstChild.nodeValue = hh;
                if (el.childNodes[2]) el.childNodes[2].nodeValue = mm + ':' + ss;
                blink = blink === 'on' ? 'off' : 'on';
                el.dataset.blink = blink;
            } else {
                el.textContent = hh + ':' + mm + ':' + ss;
            }
            el.setAttribute(
                'datetime',
                now.toISOString().slice(0, 19)
            );
        }

        tick();
        setInterval(tick, 1000);
    }

    // -------------------------------------------------------------------
    // 2. Drawer state machine
    // -------------------------------------------------------------------
    const DRAWER_KEY = 'fq-drawer-state';
    const VALID_STATES = ['closed', 'minimized', 'open'];

    function getDrawerState() {
        const stored = localStorage.getItem(DRAWER_KEY);
        return VALID_STATES.includes(stored) ? stored : 'closed';
    }

    function setDrawerState(state) {
        if (!VALID_STATES.includes(state)) return;
        const grid = document.getElementById('app-grid');
        const drawer = document.getElementById('app-drawer');
        if (!grid) return;

        grid.dataset.drawer = state;

        if (drawer) {
            if (state === 'closed') {
                drawer.hidden = true;
            } else {
                drawer.hidden = false;
            }
        }

        try { localStorage.setItem(DRAWER_KEY, state); } catch (_) { /* QuotaExceeded */ }

        window.dispatchEvent(new CustomEvent('fq:drawer-state', {
            detail: { state }
        }));
    }

    function bindDrawerActions() {
        document.addEventListener('click', function (ev) {
            const trigger = ev.target.closest('[data-drawer-action]');
            if (!trigger) return;

            const action = trigger.dataset.drawerAction;
            switch (action) {
                case 'open':      setDrawerState('open'); break;
                case 'expand':    setDrawerState('open'); break;
                case 'minimize':  setDrawerState('minimized'); break;
                case 'close':     setDrawerState('closed'); break;
                case 'toggle':    {
                    const cur = getDrawerState();
                    setDrawerState(cur === 'open' ? 'closed' : 'open');
                    break;
                }
                default: break;
            }
        });

        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && getDrawerState() === 'open') {
                // Não fecha se o foco está num input/textarea/select
                const ae = document.activeElement;
                if (ae && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) return;
                setDrawerState('closed');
                ev.stopPropagation();
            }
        });
    }

    // -------------------------------------------------------------------
    // 3. Sidebar — destaque do link activo
    // -------------------------------------------------------------------
    function highlightSidebar() {
        const links = document.querySelectorAll('[data-sidebar-link]');
        if (!links.length) return;

        const path = window.location.pathname;
        // Score: prefere o link cujo href é prefixo mais longo da URL actual.
        let bestScore = 0;
        let best = null;
        links.forEach(function (a) {
            const href = a.getAttribute('href') || '';
            if (href === '/' && path !== '/') return;
            if (path === href || path.startsWith(href)) {
                if (href.length > bestScore) {
                    bestScore = href.length;
                    best = a;
                }
            }
        });

        links.forEach(function (a) { a.removeAttribute('aria-current'); });
        if (best) best.setAttribute('aria-current', 'page');
    }

    // -------------------------------------------------------------------
    // 4. Navegação móvel — off-canvas da sidebar (<1024px)
    // -------------------------------------------------------------------
    const FOCUSABLE =
        'a[href], button:not([disabled]), input:not([disabled]), ' +
        'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function bindNavOffcanvas() {
        const toggle = document.getElementById('nav-toggle');
        const panel = document.getElementById('nav-offcanvas');
        const backdrop = document.getElementById('nav-backdrop');
        const closeBtn = document.getElementById('nav-close');
        if (!toggle || !panel) return;

        let lastFocus = null;

        function isOpen() {
            return document.body.classList.contains('nav-open');
        }

        function openNav() {
            lastFocus = document.activeElement;
            document.body.classList.add('nav-open');
            toggle.setAttribute('aria-expanded', 'true');
            if (backdrop) backdrop.hidden = false;
            // Foco para o primeiro elemento navegável do painel.
            const first = panel.querySelector(FOCUSABLE);
            if (first) first.focus();
            document.addEventListener('keydown', onKey, true);
        }

        function closeNav() {
            if (!isOpen()) return;
            document.body.classList.remove('nav-open');
            toggle.setAttribute('aria-expanded', 'false');
            if (backdrop) backdrop.hidden = true;
            document.removeEventListener('keydown', onKey, true);
            if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
        }

        function onKey(ev) {
            if (ev.key === 'Escape') {
                ev.preventDefault();
                ev.stopPropagation();
                closeNav();
                return;
            }
            if (ev.key !== 'Tab') return;
            // Foco preso dentro do painel.
            const items = Array.prototype.filter.call(
                panel.querySelectorAll(FOCUSABLE),
                function (el) { return el.offsetParent !== null; }
            );
            if (!items.length) return;
            const first = items[0];
            const last = items[items.length - 1];
            if (ev.shiftKey && document.activeElement === first) {
                ev.preventDefault();
                last.focus();
            } else if (!ev.shiftKey && document.activeElement === last) {
                ev.preventDefault();
                first.focus();
            }
        }

        toggle.addEventListener('click', function () {
            if (isOpen()) closeNav(); else openNav();
        });
        if (closeBtn) closeBtn.addEventListener('click', closeNav);
        if (backdrop) backdrop.addEventListener('click', closeNav);
        // Navegar fecha o painel.
        panel.addEventListener('click', function (ev) {
            if (ev.target.closest('[data-sidebar-link]')) closeNav();
        });
    }

    // -------------------------------------------------------------------
    // 6. Mensagens server-side -> toast
    // -------------------------------------------------------------------
    function flushServerMessages() {
        const node = document.getElementById('server-messages');
        if (!node || typeof window.Toast === 'undefined') return;

        const TYPES = { success: 'success', error: 'error', warning: 'warning', info: 'info', debug: 'info' };
        node.querySelectorAll('.server-message').forEach(function (el) {
            const text = el.dataset.text;
            if (!text) return;
            window.Toast.show(text, TYPES[el.dataset.level] || 'info');
        });
    }

    // -------------------------------------------------------------------
    // Boot
    // -------------------------------------------------------------------
    function init() {
        // Aplica estado inicial do drawer (vindo do localStorage).
        const grid = document.getElementById('app-grid');
        if (grid) {
            const initial = getDrawerState();
            grid.dataset.drawer = initial;
            const drawer = document.getElementById('app-drawer');
            if (drawer) drawer.hidden = initial === 'closed';
        }

        startClock();
        bindDrawerActions();
        bindNavOffcanvas();
        highlightSidebar();
        flushServerMessages();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expor API mínima para outros scripts (ex.: dashboard que abre drawer
    // ao clicar numa ocorrência).
    window.FQAppShell = {
        getDrawerState: getDrawerState,
        setDrawerState: setDrawerState
    };
})();
