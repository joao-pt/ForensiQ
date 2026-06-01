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
        sel.removeAttribute('aria-busy');
    }
    function loading(sel) {
        sel.innerHTML = '<option value="">— a carregar… —</option>';
        sel.disabled = true;
        sel.setAttribute('aria-busy', 'true');
    }
    function fill(sel, items, render) {
        sel.innerHTML = '<option value="">— selecionar —</option>';
        items.forEach(function (it) {
            var o = document.createElement('option');
            render(o, it);
            sel.appendChild(o);
        });
        sel.disabled = false;
        sel.removeAttribute('aria-busy');
    }
    function clearBadge() {
        if (badge) { badge.textContent = ''; badge.className = 'form-hint'; }
    }
    // Mensagem por estado: distingue sessão expirada (401/403) de falha de servidor.
    function statusMessage(status) {
        if (status === 401 || status === 403) return '— sessão expirada, reautentique —';
        return '— erro ao carregar —';
    }
    function getJSON(url) {
        return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) {
                if (!r.ok) {
                    var err = new Error('HTTP ' + r.status);
                    err.status = r.status;
                    throw err;
                }
                return r.json();
            });
    }

    function loadSubs(catId) {
        if (!catId) {
            reset(subSel, '— selecione a categoria —');
            reset(typeSel, '— selecione a subcategoria —');
            clearBadge();
            return Promise.resolve();
        }
        loading(subSel);
        return getJSON('/api/crime-subcategories/?categoria=' + encodeURIComponent(catId))
            .then(function (items) {
                fill(subSel, items, function (o, it) { o.value = it.id; o.textContent = it.codigo + ' — ' + it.nome; });
                reset(typeSel, '— selecione a subcategoria —');
                clearBadge();
            })
            .catch(function (e) { reset(subSel, statusMessage(e && e.status)); });
    }

    function loadTypes(subId) {
        if (!subId) {
            reset(typeSel, '— selecione a subcategoria —');
            clearBadge();
            return Promise.resolve();
        }
        loading(typeSel);
        return getJSON('/api/crime-types/?subcategoria=' + encodeURIComponent(subId))
            .then(function (items) {
                fill(typeSel, items, function (o, it) {
                    o.value = it.id;
                    o.textContent = it.codigo + ' — ' + it.descritivo;
                    if (it.is_prioritaria) o.setAttribute('data-prioritaria', '1');
                });
                clearBadge();
            })
            .catch(function (e) { reset(typeSel, statusMessage(e && e.status)); });
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
    // Se a cascata falhar a recarregar (rede/401), preserva o tipo escolhido
    // numa opção de recurso para o formulário não ficar inutilizável.
    var selCat = form.getAttribute('data-sel-cat');
    var selSub = form.getAttribute('data-sel-sub');
    var selType = form.getAttribute('data-sel-type');

    function keepChosenType() {
        if (!selType) return;
        // Garante que o tipo previamente escolhido continua selecionável e submetível,
        // mesmo que loadSubs/loadTypes não tenham repopulado os selects.
        if (!typeSel.querySelector('option[value="' + selType + '"]')) {
            var o = document.createElement('option');
            o.value = selType;
            o.textContent = 'Tipo escolhido (recuperado)';
            typeSel.appendChild(o);
        }
        typeSel.disabled = false;
        typeSel.removeAttribute('aria-busy');
        typeSel.value = selType;
        updateBadge();
    }

    if (selCat) {
        catSel.value = selCat;
        loadSubs(selCat).then(function () {
            if (!selSub) return;
            subSel.value = selSub;
            return loadTypes(selSub).then(function () {
                if (selType) { typeSel.value = selType; updateBadge(); }
            });
        }).then(function () {
            // Se algum passo falhou, o tipo escolhido pode não ter ficado selecionado.
            if (selType && typeSel.value !== selType) keepChosenType();
        }).catch(keepChosenType);
    }
})();
