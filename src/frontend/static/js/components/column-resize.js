/**
 * ForensiQ — Colunas redimensionáveis (CSP-safe, ficheiro estático).
 *
 * Para qualquer `<table class="grid--resizable">`: acrescenta uma pega no bordo
 * direito de cada coluna; arrastar define a largura via `style.width` (CSSOM —
 * permitido pelo CSP, ao contrário de um estilo inline no HTML). A largura é
 * persistida em localStorage por (id da tabela × índice de coluna) e reaplicada
 * no arranque e depois de cada swap HTMX (a grelha é re-renderizada nos filtros/
 * paginação). Exige `table-layout: fixed` (ver forensic.css).
 *
 * Reutilizável: marca qualquer grelha com `grid--resizable` e dá-lhe um `id`.
 */
(function () {
    'use strict';
    if (window.__fqColResizeReady) return;
    window.__fqColResizeReady = true;

    function key(table) { return 'fq-colw-' + (table.id || 'grid'); }

    function saved(table) {
        try { return JSON.parse(localStorage.getItem(key(table)) || '{}'); }
        catch (e) { return {}; }
    }
    function persist(table, widths) {
        try { localStorage.setItem(key(table), JSON.stringify(widths)); }
        catch (e) { /* quota / modo privado — ignora */ }
    }

    function headerCells(table) {
        var head = table.tHead && table.tHead.rows[0];
        return head ? Array.prototype.slice.call(head.cells) : [];
    }

    function applySaved(table) {
        var w = saved(table);
        headerCells(table).forEach(function (th, i) {
            if (w[i]) th.style.width = w[i] + 'px';
        });
    }

    function attach(table) {
        if (table._fqResize) { applySaved(table); return; }
        table._fqResize = true;
        headerCells(table).forEach(function (th, i) {
            var handle = document.createElement('span');
            handle.className = 'col-resize';
            handle.setAttribute('aria-hidden', 'true');
            th.appendChild(handle);
            handle.addEventListener('pointerdown', function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                var startX = ev.clientX;
                var startW = th.getBoundingClientRect().width;
                handle.classList.add('col-resize--active');
                function move(e) {
                    th.style.width = Math.max(48, Math.round(startW + (e.clientX - startX))) + 'px';
                }
                function up() {
                    document.removeEventListener('pointermove', move);
                    document.removeEventListener('pointerup', up);
                    handle.classList.remove('col-resize--active');
                    var widths = saved(table);
                    widths[i] = Math.round(th.getBoundingClientRect().width);
                    persist(table, widths);
                }
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', up);
            });
        });
        applySaved(table);
    }

    function initAll() {
        var tables = document.querySelectorAll('table.grid--resizable');
        for (var i = 0; i < tables.length; i++) attach(tables[i]);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
    // Após um swap HTMX a grelha é nova → religa as pegas e reaplica larguras.
    document.body.addEventListener('htmx:afterSwap', initAll);
})();
