/**
 * ForensiQ — Seletor de crime em cascata N1>N2>N3 (occurrences_new).
 * CSP-safe: ficheiro estático, sem eval/inline. fetch com cookie JWT.
 *
 * Categoria (N1, server-rendered) → Subcategoria (N2, /api/crime-subcategories/)
 * → Tipo (N3, /api/crime-types/, com flag is_prioritaria). Ao escolher o tipo,
 * mostra a pré-visualização do badge de prioridade (P1 se derivada da lei).
 * A derivação final é sempre confirmada no servidor (Occurrence._aplicar_prioridade).
 */
(function () {
    'use strict';

    var form = document.querySelector('[data-crime-cascade]');
    if (!form) return;
    var catSel = form.querySelector('[data-crime-cat]');
    var subSel = form.querySelector('[data-crime-sub]');
    var typeSel = form.querySelector('[data-crime-type]');
    var badge = form.querySelector('[data-crime-priority]');
    if (!catSel || !subSel || !typeSel) return;

    function reset(sel, placeholder) {
        sel.innerHTML = '<option value="">' + placeholder + '</option>';
        sel.disabled = true;
    }
    function fill(sel, items, render) {
        sel.innerHTML = '<option value="">— selecionar —</option>';
        items.forEach(function (it) {
            var o = document.createElement('option');
            render(o, it);
            sel.appendChild(o);
        });
        sel.disabled = false;
    }
    function clearBadge() {
        if (badge) { badge.textContent = ''; badge.className = 'form-hint'; }
    }
    function getJSON(url) {
        return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) { return r.json(); });
    }

    function loadSubs(catId) {
        if (!catId) {
            reset(subSel, '— selecione a categoria —');
            reset(typeSel, '— selecione a subcategoria —');
            clearBadge();
            return Promise.resolve();
        }
        return getJSON('/api/crime-subcategories/?categoria=' + encodeURIComponent(catId))
            .then(function (items) {
                fill(subSel, items, function (o, it) { o.value = it.id; o.textContent = it.codigo + ' — ' + it.nome; });
                reset(typeSel, '— selecione a subcategoria —');
                clearBadge();
            })
            .catch(function () { reset(subSel, '— erro ao carregar —'); });
    }

    function loadTypes(subId) {
        if (!subId) {
            reset(typeSel, '— selecione a subcategoria —');
            clearBadge();
            return Promise.resolve();
        }
        return getJSON('/api/crime-types/?subcategoria=' + encodeURIComponent(subId))
            .then(function (items) {
                fill(typeSel, items, function (o, it) {
                    o.value = it.id;
                    o.textContent = it.codigo + ' — ' + it.descritivo;
                    if (it.is_prioritaria) o.setAttribute('data-prioritaria', '1');
                });
                clearBadge();
            })
            .catch(function () { reset(typeSel, '— erro ao carregar —'); });
    }

    function updateBadge() {
        if (!badge) return;
        var opt = typeSel.options[typeSel.selectedIndex];
        if (opt && opt.getAttribute('data-prioritaria') === '1') {
            badge.textContent = 'P1 · Prioritária (derivada da lei)';
            badge.className = 'form-hint pri-hint--p1';
        } else if (typeSel.value) {
            badge.textContent = 'Sem prioridade pela lei — pode elevar manualmente abaixo.';
            badge.className = 'form-hint';
        } else {
            clearBadge();
        }
    }

    catSel.addEventListener('change', function () { loadSubs(catSel.value); });
    subSel.addEventListener('change', function () { loadTypes(subSel.value); });
    typeSel.addEventListener('change', updateBadge);

    // Pré-seleção após re-render por erro de validação (mantém o crime escolhido).
    var selCat = form.getAttribute('data-sel-cat');
    var selSub = form.getAttribute('data-sel-sub');
    var selType = form.getAttribute('data-sel-type');
    if (selCat) {
        catSel.value = selCat;
        loadSubs(selCat).then(function () {
            if (!selSub) return;
            subSel.value = selSub;
            return loadTypes(selSub).then(function () {
                if (selType) { typeSel.value = selType; updateBadge(); }
            });
        });
    }
})();
