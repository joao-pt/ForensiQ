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

    // Reflecte o fragmento recém-trocado no título do drawer: usa o código
    // (.dd__code), o identificador forense que rotula o painel. Não se recorre a
    // cabeçalhos internos (ex.: "Descrição") para não rotular mal.
    function updateDrawerTitle(body) {
        var title = document.getElementById('app-drawer-title');
        if (!title) return;
        var code = body.querySelector('.dd__code');
        if (code && code.textContent.trim()) title.textContent = code.textContent.trim();
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

    // refreshMapSize / init de mapa Leaflet: fonte única em FQMap (utils/map-helpers.js).

    function destroyDrawerMap() {
        if (!drawerMap) return;
        FQMap.destroy(drawerMap, document.getElementById('drawer-map'));
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
        if (!el) return;
        // Leaflet em falta: antes falhava em SILÊNCIO (aba sem mapa, sem pista).
        // O runtime vem do _grid_scripts (fonte única), por isso isto só dispara
        // se uma página contornar esse include — agora avisa e mostra estado honesto.
        if (typeof L === 'undefined') {
            el.classList.add('dd__map--unavailable');
            el.textContent = 'Mapa indisponível.';
            if (window.console && console.warn) {
                console.warn('[ForensiQ] drawer-map: Leaflet (L) não carregado nesta página.');
            }
            return;
        }
        destroyDrawerMap();
        drawerMap = FQMap.createMap(el, { zoomControl: true, attributionControl: false });

        // Cadeia se houver trajeto; senão, pino único pela fonte única (D74).
        if (!renderChain(el) && !FQMap.pinFromDataset(drawerMap, el)) {
            destroyDrawerMap();
            return;
        }
        FQMap.refreshSize(drawerMap, el);
    }

    // Modo Cadeia — desenha o trajeto a partir de #drawer-map[data-chain].
    function renderChain(el) { return drawChainOn(drawerMap, el.dataset.chain); }

    // Desenha uma cadeia de custódia num mapa: o trajeto (linha âmbar tracejada
    // sobre um casing escuro, para contrastar em qualquer tile) e marcadores
    // NUMERADOS por ordem de passagem — a origem (1) e a localização ATUAL (N)
    // ficam destacadas. A ordem dos eventos vem do servidor (antigo→recente).
    function drawChainOn(map, raw) {
        if (!raw || !map) return false;
        var pts;
        try { pts = JSON.parse(raw); } catch (e) { return false; }
        if (!pts || !pts.length) return false;
        var amber = token('--accent', '#F6AD55');

        // Pontos válidos, preservando a ordem.
        var valid = [];
        pts.forEach(function (p) {
            var la = parseFloat(p.lat), ln = parseFloat(p.lng);
            if (isNaN(la) || isNaN(ln)) return;
            valid.push({ ll: [la, ln], label: p.label || '' });
        });
        if (!valid.length) return false;
        var latlngs = valid.map(function (v) { return v.ll; });

        // Trajeto: casing escuro por baixo + linha âmbar tracejada por cima.
        if (latlngs.length > 1) {
            L.polyline(latlngs, { color: '#11151c', weight: 7, opacity: 0.45,
                lineJoin: 'round', lineCap: 'round' }).addTo(map);
            L.polyline(latlngs, { color: amber, weight: 3.5, opacity: 0.95,
                dashArray: '8,7', lineJoin: 'round', lineCap: 'round' }).addTo(map);
        }

        // Marcadores numerados (1 = origem; N = localização atual, maior).
        var last = valid.length - 1;
        valid.forEach(function (v, i) {
            var role = (i === 0 ? ' fq-chain-pin--first' : '')
                     + (i === last ? ' fq-chain-pin--current' : '');
            var size = (i === last) ? 34 : 26;
            var icon = L.divIcon({
                className: 'fq-chain-pin' + role,
                html: '<span class="fq-chain-pin__num">' + (i + 1) + '</span>',
                iconSize: [size, size],
                iconAnchor: [size / 2, size / 2],
            });
            L.marker(v.ll, { icon: icon, riseOnHover: true })
                .addTo(map)
                .bindTooltip(v.label, { permanent: false, direction: 'top', offset: [0, -size / 2] });
        });

        if (latlngs.length > 1) map.fitBounds(latlngs, { padding: [34, 34] });
        else map.setView(latlngs[0], FQMap.DEFAULT_ZOOM);
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

    // Conta os pontos de um payload [data-points] (silencioso em caso de erro).
    function countPoints(raw) {
        if (!raw) return 0;
        try { var p = JSON.parse(raw); return (p && p.length) ? p.length : 0; } catch (e) { return 0; }
    }

    // Acessibilidade dos mapas fixos (insets/hero): são imagens, não aplicações.
    // Força role=img e anexa um resumo textual ('N ocorrências') via
    // aria-describedby, dando a quem usa leitor de ecrã a informação que os
    // tooltips Leaflet (só hover/foco) não oferecem num mapa não-focável.
    function describeFixedMap(el) {
        el.setAttribute('role', 'img');
        el.removeAttribute('aria-haspopup');
        var n = countPoints(el.dataset.points);
        var noun = n === 1 ? 'ocorrência' : 'ocorrências';
        var summary = n + ' ' + noun + ' neste mapa';
        var descId = (el.id || 'fqmap-' + Math.random().toString(36).slice(2, 8)) + '-desc';
        var desc = document.getElementById(descId);
        if (!desc) {
            desc = document.createElement('span');
            desc.id = descId;
            desc.className = 'visually-hidden';
            el.appendChild(desc);
        }
        desc.textContent = summary;
        el.setAttribute('aria-describedby', descId);
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
            var m = FQMap.createMap(el, opts);
            el._fqMap = m;

            var bounds = parseBounds(el.dataset.bounds);
            var drewPoints = drawPoints(m, el.dataset.points);
            var drewChain = !drewPoints && drawChainOn(m, el.dataset.chain);

            // Mapas fixos são figuras, não widgets: garante role=img (o template
            // já o declara, isto cobre fragmentos antigos) e um resumo textual
            // do nº de pontos via aria-describedby, já que os pins/tooltips
            // Leaflet são inacessíveis num mapa não-focável.
            if (fixed) describeFixedMap(el);

            if (bounds) {
                m.fitBounds(bounds);
            } else if (!drewPoints && !drewChain && !FQMap.pinFromDataset(m, el)) {
                // Pino único pela fonte única (D74); sem coordenadas válidas
                // não há nada para mostrar.
                FQMap.destroy(m, el);
                el._fqMap = null;
                return;
            }
            FQMap.refreshSize(m, el);
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

    // Copiar para a área de transferência. NÃO usa FQDom.onClick (utils/dom-helpers):
    // este ficheiro corre também na página pública de verificação (public_verify.html),
    // que é autónoma e não carrega os helpers de base.html; e o handler precisa de
    // stopPropagation para o clique no botão não abrir o drawer da linha.
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
