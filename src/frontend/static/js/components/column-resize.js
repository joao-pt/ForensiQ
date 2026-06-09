/**
 * ForensiQ — Colunas redimensionáveis (CSP-safe, ficheiro estático).
 *
 * Para qualquer `<table class="grid--resizable">` com `table-layout: fixed`:
 * acrescenta uma pega no bordo direito de cada coluna. Ao arrastar, CONGELA
 * todas as colunas na largura atual (px) e faz crescer SÓ a coluna arrastada
 * e a tabela pelo mesmo delta — assim as outras colunas NÃO se mexem e, quando
 * a tabela passa a largura do contentor, aparece a barra horizontal (a `.gridwrap`
 * tem `overflow-x: auto`; some quando tudo cabe). As larguras (colunas + tabela)
 * persistem em localStorage e reaplicam-se no arranque e após cada swap HTMX.
 *
 * Larguras via `style.width` (CSSOM) — permitido pelo CSP, ao contrário de um
 * estilo inline no HTML. Reutilizável: marca a grelha com `grid--resizable` + id.
 */
(function () {
    'use strict';
    if (window.__fqColResizeReady) return;
    window.__fqColResizeReady = true;

    function key(table) { return 'fq-colw-' + (table.id || 'grid'); }
    function saved(table) {
        try { return JSON.parse(localStorage.getItem(key(table)) || 'null'); }
        catch (e) { return null; }
    }
    function persist(table, data) {
        try { localStorage.setItem(key(table), JSON.stringify(data)); }
        catch (e) { /* quota / modo privado — ignora */ }
    }
    function headerCells(table) {
        var head = table.tHead && table.tHead.rows[0];
        return head ? Array.prototype.slice.call(head.cells) : [];
    }

    // Reaplica larguras guardadas (entra em "modo manual": px fixos + tabela px).
    function applySaved(table) {
        var data = saved(table);
        if (!data || !data.cols) return;
        var cells = headerCells(table);
        data.cols.forEach(function (w, i) { if (cells[i] && w) cells[i].style.width = w + 'px'; });
        if (data.table) table.style.width = data.table + 'px';
    }

    // Congela todas as colunas e a tabela na largura atual (px), antes de arrastar.
    function freeze(table) {
        headerCells(table).forEach(function (c) {
            c.style.width = Math.round(c.getBoundingClientRect().width) + 'px';
        });
        table.style.width = Math.round(table.getBoundingClientRect().width) + 'px';
    }

    function snapshot(table) {
        return {
            cols: headerCells(table).map(function (c) { return Math.round(c.getBoundingClientRect().width); }),
            table: Math.round(table.getBoundingClientRect().width),
        };
    }

    function attach(table) {
        if (table._fqResize) { applySaved(table); return; }
        table._fqResize = true;
        headerCells(table).forEach(function (th) {
            var handle = document.createElement('span');
            handle.className = 'col-resize';
            handle.setAttribute('aria-hidden', 'true');
            th.appendChild(handle);
            handle.addEventListener('pointerdown', function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                freeze(table);                       // outras colunas ficam fixas
                var startX = ev.clientX;
                var startW = th.getBoundingClientRect().width;
                var startTableW = table.getBoundingClientRect().width;
                handle.classList.add('col-resize--active');
                function move(e) {
                    var newW = Math.max(48, startW + (e.clientX - startX));
                    var delta = newW - startW;
                    th.style.width = newW + 'px';
                    table.style.width = (startTableW + delta) + 'px';  // tabela cresce com a coluna
                }
                function up() {
                    document.removeEventListener('pointermove', move);
                    document.removeEventListener('pointerup', up);
                    handle.classList.remove('col-resize--active');
                    persist(table, snapshot(table));
                }
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', up);
            });
        });
        applySaved(table);
    }

    function isMobile() {
        return !!(window.matchMedia && window.matchMedia('(max-width: 767px)').matches);
    }
    // Ao toque o resize não faz sentido; e as larguras px do desktop (style inline)
    // venceriam o CSS mobile (4 colunas) → há que LIMPÁ-LAS ao cruzar o breakpoint.
    function clearInline(table) {
        headerCells(table).forEach(function (c) { c.style.width = ''; });
        table.style.width = '';
    }

    function initAll() {
        var tables = document.querySelectorAll('table.grid--resizable');
        var mobile = isMobile();
        for (var i = 0; i < tables.length; i++) {
            if (mobile) clearInline(tables[i]);   // sem resize ao toque + sem larguras a vazar
            else attach(tables[i]);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
    document.body.addEventListener('htmx:afterSwap', initAll);  // grelha nova → religa + reaplica
    // Cruzar o breakpoint: em desktop reaplica larguras guardadas; em mobile limpa-as.
    if (window.matchMedia) {
        var mq = window.matchMedia('(max-width: 767px)');
        if (mq.addEventListener) mq.addEventListener('change', initAll);
        else if (mq.addListener) mq.addListener(initAll);
    }
})();
