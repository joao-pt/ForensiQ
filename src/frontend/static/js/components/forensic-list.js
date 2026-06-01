/**
 * ForensiQ — Comportamento partilhado das páginas de lista forense
 * (server-rendered + HTMX). CSP-safe: ficheiro estático, sem eval/inline.
 *
 *  - Clicar/Enter numa linha [data-row] → HTMX carrega o detalhe em
 *    #app-drawer-body; aqui abrimos o drawer (FQAppShell), marcamos a linha
 *    activa e inicializamos o mini-mapa Leaflet (#drawer-map).
 *  - O mapa antigo é destruído ANTES do swap (htmx:beforeSwap) para evitar
 *    estado órfão do Leaflet (2.º mapa não aparecia).
 *  - Modo Cadeia: se #drawer-map tiver data-chain (JSON de pontos), desenha
 *    polyline tracejada amber + pins por evento (timeline de custódia).
 *  - Navegação por teclado na grelha (↑/↓/Enter/Espaço) e botões de copiar.
 */
(function () {
    'use strict';
    var drawerMap = null;
    var lastTrigger = null;   // linha que abriu o drawer (para restaurar foco)

    // Lê um token de cor do tema (--accent / --state-*) via getComputedStyle,
    // para os marcadores Leaflet acompanharem dia/noite em vez de hex fixo.
    // O fallback cobre o caso de o CSS ainda não ter resolvido a variável.
    function token(name, fallback) {
        try {
            var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
            return v || fallback;
        } catch (e) {
            return fallback;
        }
    }

    document.body.addEventListener('htmx:beforeSwap', function (ev) {
        if (ev.target && ev.target.id === 'app-drawer-body') destroyDrawerMap();
    });
    document.body.addEventListener('htmx:afterSwap', function (ev) {
        if (!ev.target || ev.target.id !== 'app-drawer-body') return;
        if (window.FQAppShell) window.FQAppShell.setDrawerState('open');
        markSelected(ev.detail);
        rememberTrigger(ev.detail);
        clearGridBusy();
        updateDrawerTitle(ev.target);
        initDrawerMap();
        focusDrawer();
    });

    // Indicador de carregamento: ao disparar um pedido HTMX a partir de uma
    // linha da grelha, marca a grelha como ocupada (aria-busy + classe de
    // estilo) até o swap chegar.
    document.body.addEventListener('htmx:beforeRequest', function (ev) {
        var row = ev.target;
        if (!row || !row.matches || !row.matches('[data-row]')) return;
        markGridBusy(true);
    });
    document.body.addEventListener('htmx:afterRequest', function (ev) {
        var row = ev.target;
        if (row && row.matches && row.matches('[data-row]')) markGridBusy(false);
    });

    // As três grelhas clicáveis (ocorrências, itens, custódia).
    function busyGrids() {
        return document.querySelectorAll('.grid--clickable');
    }
    function markGridBusy(on) {
        busyGrids().forEach(function (g) {
            if (on) { g.setAttribute('aria-busy', 'true'); g.classList.add('htmx-request'); }
            else { g.removeAttribute('aria-busy'); g.classList.remove('htmx-request'); }
        });
    }
    function clearGridBusy() { markGridBusy(false); }

    // Reflecte o fragmento recém-trocado no título do drawer. O fragmento
    // pode declará-lo em [data-drawer-title]; caso contrário usa-se o código
    // (.dd__code), que é o identificador forense que rotula o painel. Não se
    // recorre a cabeçalhos internos (ex.: "Descrição") para não rotular mal.
    function updateDrawerTitle(body) {
        var title = document.getElementById('app-drawer-title');
        if (!title) return;
        var src = body.querySelector('[data-drawer-title]');
        var text = src ? src.getAttribute('data-drawer-title') : '';
        if (!text) {
            var code = body.querySelector('.dd__code');
            if (code) text = code.textContent.trim();
        }
        if (text) title.textContent = text;
    }

    // Acessibilidade do drawer: ao abrir, lembra a linha que o despoletou,
    // move o foco para dentro do painel e prende-o (trap) até fechar; ao
    // fechar, devolve o foco à linha de origem.
    function drawerEl() { return document.getElementById('app-drawer'); }

    // Guarda a linha que abriu o drawer (clique de rato ou teclado) para
    // lhe devolver o foco ao fechar — detail.requestConfig.elt é fiável em
    // ambos os casos, ao contrário de document.activeElement no clique.
    function rememberTrigger(detail) {
        var row = detail && detail.requestConfig && detail.requestConfig.elt;
        if (row && row.matches && row.matches('[data-row]')) lastTrigger = row;
    }

    var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]),' +
        ' select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    // Elementos focáveis e realmente visíveis, excluindo descendentes de
    // contentores aria-hidden (ex.: o rail de ícones do drawer).
    function focusables(root) {
        return Array.prototype.slice.call(root.querySelectorAll(FOCUSABLE))
            .filter(function (n) {
                return n.offsetParent !== null && !n.closest('[aria-hidden="true"]');
            });
    }

    function focusDrawer() {
        var drawer = drawerEl();
        if (!drawer) return;
        // Padrão de diálogo: focar o cabeçalho do painel (anuncia o título via
        // aria-labelledby) e só depois prender o Tab nos focáveis reais.
        var head = drawer.querySelector('[data-drawer-head]');
        if (head) {
            head.focus();
        } else {
            var nodes = focusables(drawer);
            if (nodes.length) nodes[0].focus();
        }
        document.addEventListener('keydown', trapFocus, true);
    }

    function trapFocus(ev) {
        if (ev.key !== 'Tab') return;
        var drawer = drawerEl();
        if (!drawer || drawer.hidden) { document.removeEventListener('keydown', trapFocus, true); return; }
        var nodes = focusables(drawer);
        if (!nodes.length) return;
        var first = nodes[0], last = nodes[nodes.length - 1];
        if (ev.shiftKey && document.activeElement === first) {
            ev.preventDefault(); last.focus();
        } else if (!ev.shiftKey && document.activeElement === last) {
            ev.preventDefault(); first.focus();
        }
    }

    // Ao fechar o drawer (Esc / botão), liberta o trap e devolve o foco.
    window.addEventListener('fq:drawer-state', function (ev) {
        var state = ev.detail && ev.detail.state;
        if (state === 'closed') {
            document.removeEventListener('keydown', trapFocus, true);
            if (lastTrigger && document.contains(lastTrigger)) {
                lastTrigger.focus();
                lastTrigger = null;
            }
        }
    });

    // Reparação robusta do tamanho de um mapa Leaflet. O bug clássico é o mapa
    // arrancar num container ainda sem dimensões (drawer a abrir, swap HTMX,
    // transição para overlay fixed em mobile, banda do hero sem altura) e ficar
    // cinzento. Em vez de depender de um único invalidateSize com timing frágil,
    // disparamos em três momentos: já a seguir ao layout (duplo rAF), quando o
    // mapa fica pronto (whenReady) e sempre que o container muda de dimensões
    // (ResizeObserver) — cobrindo todos os casos acima.
    function refreshMapSize(map, el) {
        if (!map || !el) return;
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { try { map.invalidateSize(); } catch (e) { /* removido */ } });
        });
        map.whenReady(function () { try { map.invalidateSize(); } catch (e) { /* removido */ } });
        if (typeof ResizeObserver !== 'undefined' && !el._fqRO) {
            var ro = new ResizeObserver(function () {
                if (el.clientWidth > 0 && el.clientHeight > 0) {
                    try { map.invalidateSize(); } catch (e) { /* removido */ }
                }
            });
            ro.observe(el);
            el._fqRO = ro;
        }
    }

    function destroyDrawerMap() {
        if (!drawerMap) return;
        var dm = document.getElementById('drawer-map');
        if (dm && dm._fqRO) { dm._fqRO.disconnect(); dm._fqRO = null; }
        try { drawerMap.remove(); } catch (e) { /* container já destacado */ }
        drawerMap = null;
    }

    function markSelected(detail) {
        var row = detail && detail.requestConfig && detail.requestConfig.elt;
        document.querySelectorAll('[data-row][aria-selected="true"]').forEach(function (r) {
            r.removeAttribute('aria-selected');
        });
        if (row && row.matches && row.matches('[data-row]')) row.setAttribute('aria-selected', 'true');
    }

    function initDrawerMap() {
        var el = document.getElementById('drawer-map');
        if (!el || typeof L === 'undefined') return;
        var lat = parseFloat(el.dataset.lat);
        var lng = parseFloat(el.dataset.lng);
        destroyDrawerMap();
        drawerMap = L.map(el, { zoomControl: true, attributionControl: false });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(drawerMap);

        var drewChain = renderChain(el);
        if (!drewChain) {
            if (isNaN(lat) || isNaN(lng)) { destroyDrawerMap(); return; }
            drawerMap.setView([lat, lng], 15);
            L.marker([lat, lng]).addTo(drawerMap).bindTooltip(el.dataset.label || '', { permanent: false });
        }
        refreshMapSize(drawerMap, el);
    }

    // Modo Cadeia — desenha o trajeto a partir de #drawer-map[data-chain].
    function renderChain(el) { return drawChainOn(drawerMap, el.dataset.chain); }

    // Desenha uma cadeia (polyline tracejada amber + pins por evento) num mapa.
    function drawChainOn(map, raw) {
        if (!raw || !map) return false;
        var pts;
        try { pts = JSON.parse(raw); } catch (e) { return false; }
        if (!pts || !pts.length) return false;
        var amber = token('--accent', '#F6AD55');
        var latlngs = [];
        pts.forEach(function (p) {
            var la = parseFloat(p.lat), ln = parseFloat(p.lng);
            if (isNaN(la) || isNaN(ln)) return;
            latlngs.push([la, ln]);
            L.circleMarker([la, ln], { radius: 5, color: amber, weight: 2, fillColor: amber, fillOpacity: 0.85 })
                .addTo(map).bindTooltip(p.label || '', { permanent: false });
        });
        if (!latlngs.length) return false;
        if (latlngs.length > 1) {
            L.polyline(latlngs, { color: amber, weight: 2, dashArray: '5,6', opacity: 0.9 }).addTo(map);
            map.fitBounds(latlngs, { padding: [26, 26] });
        } else {
            map.setView(latlngs[0], 15);
        }
        return true;
    }

    // Pontos de prioridade (cor classifica) — usado no mapa panorâmico do hero.
    // As cores vêm dos tokens de estado para terem variante de tema claro:
    //   prioridade alta → vermelho (destruída), média → âmbar (em transporte),
    //   normal → azul (apreendida).
    function priColors() {
        return {
            1: token('--state-destruida', '#F87171'),
            2: token('--state-em-transporte', '#F59E0B'),
            0: token('--state-apreendida', '#60A5FA'),
        };
    }
    function drawPoints(map, raw) {
        if (!raw) return false;
        var pts;
        try { pts = JSON.parse(raw); } catch (e) { return false; }
        if (!pts || !pts.length) return false;
        var colors = priColors();
        pts.forEach(function (p) {
            var la = parseFloat(p.lat), ln = parseFloat(p.lng);
            if (isNaN(la) || isNaN(ln)) return;
            var col = colors[p.pri] || colors[0];
            L.circleMarker([la, ln], { radius: 5, color: col, weight: 2, fillColor: col, fillOpacity: 0.7 })
                .addTo(map).bindTooltip(p.label || '', { permanent: false });
        });
        return true;
    }
    function parseBounds(raw) {
        if (!raw) return null;
        try { var b = JSON.parse(raw); return (b && b.length === 2) ? b : null; } catch (e) { return null; }
    }

    // Mapas estáticos embebidos ([data-static-map]): pin único (data-lat/lng),
    // cadeia (data-chain), ou conjunto de pontos (data-points) com bounds fixos
    // (data-bounds) e opcionalmente sem interação (data-fixed, para insets).
    function initStaticMaps() {
        if (typeof L === 'undefined') return;
        document.querySelectorAll('[data-static-map]').forEach(function (el) {
            if (el._fqMap) return;
            var fixed = el.hasAttribute('data-fixed');
            var opts = { attributionControl: false, zoomControl: !fixed };
            if (fixed) {
                opts.dragging = false; opts.scrollWheelZoom = false; opts.doubleClickZoom = false;
                opts.boxZoom = false; opts.keyboard = false; opts.touchZoom = false; opts.tap = false;
            }
            var m = L.map(el, opts);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(m);
            el._fqMap = m;

            var bounds = parseBounds(el.dataset.bounds);
            var drewPoints = drawPoints(m, el.dataset.points);
            var drewChain = !drewPoints && drawChainOn(m, el.dataset.chain);

            if (bounds) {
                m.fitBounds(bounds);
            } else if (!drewPoints && !drewChain) {
                var lat = parseFloat(el.dataset.lat), lng = parseFloat(el.dataset.lng);
                if (isNaN(lat) || isNaN(lng)) { m.remove(); el._fqMap = null; return; }
                m.setView([lat, lng], 15);
                L.marker([lat, lng]).addTo(m).bindTooltip(el.dataset.label || '', { permanent: false });
            }
            refreshMapSize(m, el);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initStaticMaps);
    else initStaticMaps();

    // Abrir um <details> alvo quando a página é aberta com âncora (ex.: o
    // formulário de registo de evento via "#custody-register").
    function openHashTarget() {
        if (!location.hash) return;
        var t = null;
        try { t = document.querySelector(location.hash); } catch (e) { return; }
        if (t && t.tagName === 'DETAILS') { t.open = true; t.scrollIntoView(); }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', openHashTarget);
    else openHashTarget();
    window.addEventListener('hashchange', openHashTarget);

    window.addEventListener('fq:drawer-state', function () {
        if (drawerMap) setTimeout(function () { if (drawerMap) drawerMap.invalidateSize(); }, 280);
    });

    document.body.addEventListener('keydown', function (ev) {
        var cur = document.activeElement;
        if (!cur || !cur.matches || !cur.matches('[data-row]')) return;
        var rows = Array.prototype.slice.call(document.querySelectorAll('[data-row]'));
        var i = rows.indexOf(cur);
        if (ev.key === 'ArrowDown') { ev.preventDefault(); if (rows[i + 1]) rows[i + 1].focus(); }
        else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (rows[i - 1]) rows[i - 1].focus(); }
        else if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); cur.click(); }
    });

    function flashCopied(btn) {
        btn.classList.add('is-copied');
        setTimeout(function () { btn.classList.remove('is-copied'); }, 1200);
    }

    // Fallback para contexto não-seguro (ex.: /v/<hash>/ servido por HTTP),
    // onde navigator.clipboard é undefined. Sem ele, copiar o hash — a ação
    // central da verificação pública — falhava em silêncio.
    function legacyCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.className = 'visually-hidden';
        document.body.appendChild(ta);
        ta.select();
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        document.body.removeChild(ta);
        return ok;
    }

    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-copy]') : null;
        if (!btn) return;
        ev.preventDefault();
        ev.stopPropagation();
        var val = btn.getAttribute('data-copy');
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(val).then(function () {
                flashCopied(btn);
            }, function () {
                if (legacyCopy(val)) flashCopied(btn);
            });
        } else if (legacyCopy(val)) {
            flashCopied(btn);
        }
    });
})();
