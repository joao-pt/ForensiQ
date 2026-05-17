/**
 * ForensiQ — Constantes partilhadas da máquina de estados da cadeia de custódia.
 *
 * Espelha o backend (`ChainOfCustody.CustodyState` e `VALID_TRANSITIONS` em
 * src/backend/core/models.py). Qualquer alteração aqui tem de ser feita também
 * lá — testes de fluxo end-to-end batem em ambos os lados.
 *
 * NOTA ESTRUTURAL: tudo encapsulado num IIFE. O único nome exposto é
 * `window.CustodyStates`. Scripts consumidores (dashboard.js,
 * custody_timeline.js, transition_modal.js) podem destructurar à vontade
 * sem risco de redeclaração global — pattern alinhado com `toast.js`.
 */

'use strict';

window.CustodyStates = (() => {

    const CUSTODY_STATE_LABELS = {
        'APREENDIDA':           'Apreendida',
        'EM_TRANSPORTE':        'Em Transporte',
        'RECEBIDA_LABORATORIO': 'Recebida no Laboratório',
        'EM_PERICIA':           'Em Perícia',
        'CONCLUIDA':            'Concluída',
        'DEVOLVIDA':            'Devolvida',
        'DESTRUIDA':            'Destruída',
    };

    const STATE_FLOW = [
        { key: 'APREENDIDA',           label: 'Apreendida' },
        { key: 'EM_TRANSPORTE',        label: 'Em Transporte' },
        { key: 'RECEBIDA_LABORATORIO', label: 'No Laboratório' },
        { key: 'EM_PERICIA',           label: 'Em Perícia' },
        { key: 'CONCLUIDA',            label: 'Concluída' },
        { key: 'DEVOLVIDA',            label: 'Devolvida' },
        { key: 'DESTRUIDA',            label: 'Destruída' },
    ];

    const VALID_TRANSITIONS = {
        '':                     ['APREENDIDA'],
        'APREENDIDA':           ['EM_TRANSPORTE'],
        'EM_TRANSPORTE':        ['RECEBIDA_LABORATORIO'],
        'RECEBIDA_LABORATORIO': ['EM_PERICIA'],
        'EM_PERICIA':           ['CONCLUIDA'],
        'CONCLUIDA':            ['DEVOLVIDA', 'DESTRUIDA'],
        'DEVOLVIDA':            [],
        'DESTRUIDA':            [],
    };

    /**
     * Calcula a intersecção dos próximos estados permitidos para vários items.
     *
     * Recebe os estados ACTUAIS de N items (com repetição permitida) e devolve
     * a lista de estados que TODOS conseguem atingir num único passo da
     * máquina. Preserva a ordem definida em STATE_FLOW.
     *
     * @param {string[]} currentStates
     * @returns {string[]}
     */
    function commonNextStates(currentStates) {
        if (!Array.isArray(currentStates) || currentStates.length === 0) return [];
        const sets = currentStates.map((s) => new Set(VALID_TRANSITIONS[s] || []));
        const first = sets[0];
        const inter = [];
        for (const candidate of first) {
            if (sets.every((set) => set.has(candidate))) inter.push(candidate);
        }
        const order = new Map(STATE_FLOW.map((s, i) => [s.key, i]));
        inter.sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99));
        return inter;
    }

    return {
        CUSTODY_STATE_LABELS,
        STATE_FLOW,
        VALID_TRANSITIONS,
        commonNextStates,
    };
})();
