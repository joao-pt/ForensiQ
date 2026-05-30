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
            if (sep) {
                el.firstChild.nodeValue = hh + ':';
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
    // 4. Detecção de plataforma para kbd hints
    // -------------------------------------------------------------------
    function applyPlatformHints() {
        const isMac = /Mac|iPhone|iPad|iPod/i.test(navigator.platform || '');
        if (!isMac) return;
        document.querySelectorAll('[data-kbd]').forEach(function (el) {
            const win = el.dataset.kbd;
            // Substitui "Ctrl+" por "⌘"; "Alt+" por "⌥"
            el.textContent = win
                .replace(/Ctrl\+/g, '⌘')
                .replace(/Alt\+/g, '⌥');
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
        highlightSidebar();
        applyPlatformHints();
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
