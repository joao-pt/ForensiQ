/**
 * ForensiQ — Filtro do selector de pai pela ocorrência escolhida (CSP-safe).
 *
 * No registo de item (/evidences/new/), o selector «Sub-componente de» traz
 * todos os candidatos do âmbito do utilizador, cada opção anotada com
 * data-occurrence. Ao escolher a ocorrência (#f-occ), escondem-se os
 * candidatos de outros processos — pendurar um filho na ocorrência errada
 * era o risco apontado no parecer §6.
 *
 * Progressive enhancement: sem JS a lista fica completa e a guarda «mesma
 * ocorrência» do serializer/clean() continua a valer no POST. No fluxo
 * encadeado (?parent=) não há selects — este script não encontra os ids e
 * sai cedo.
 */
(function () {
    'use strict';

    var occ = document.getElementById('f-occ');
    var parent = document.getElementById('f-parent');
    if (!occ || !parent) return;

    function sync() {
        var val = occ.value;
        for (var i = 0; i < parent.options.length; i += 1) {
            var opt = parent.options[i];
            var owner = opt.getAttribute('data-occurrence');
            if (!owner) continue; // «— nenhum (item raiz) —»
            var hide = Boolean(val) && owner !== val;
            opt.hidden = hide;
            opt.disabled = hide;
            if (hide && opt.selected) parent.value = '';
        }
    }

    occ.addEventListener('change', sync);
    sync();
})();
