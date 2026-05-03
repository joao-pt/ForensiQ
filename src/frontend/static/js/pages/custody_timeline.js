'use strict';

const evidenceId = parseInt(window.location.pathname.match(/\/evidences?\/(\d+)\//)?.[1], 10);
let currentState = null;
let allowedNextStates = [];
let subEvidences = [];  // Sub-componentes directos do item principal.

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
    '':                    ['APREENDIDA'],
    'APREENDIDA':          ['EM_TRANSPORTE'],
    'EM_TRANSPORTE':       ['RECEBIDA_LABORATORIO'],
    'RECEBIDA_LABORATORIO':['EM_PERICIA'],
    'EM_PERICIA':          ['CONCLUIDA'],
    'CONCLUIDA':           ['DEVOLVIDA', 'DESTRUIDA'],
    'DEVOLVIDA':           [],
    'DESTRUIDA':           [],
};

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    // Link "Voltar" — leva ao detalhe do ITEM, não à listagem geral.
    // Se o ID veio inválido (improvável), cai para /evidences/.
    const backBtn = document.getElementById('btn-back-evidence');
    if (backBtn) {
        backBtn.href = evidenceId ? `/evidences/${evidenceId}/` : '/evidences/';
    }

    document.getElementById('btn-new-transition').addEventListener('click', openTransitionModal);
    document.getElementById('btn-cancel-transition').addEventListener('click', closeTransitionModal);
    document.getElementById('btn-submit-transition').addEventListener('click', submitTransition);

    if (!evidenceId) {
        const container = document.getElementById('timeline-container');
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const p = document.createElement('p');
        p.className = 'text-danger';
        p.textContent = 'ID do item inválido.';
        empty.appendChild(p);
        container.replaceChildren(empty);
        return;
    }

    const user = Auth.getUser();
    await loadEvidenceAndTimeline(user);
});

function showError(container, message) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const p = document.createElement('p');
    p.className = 'text-danger';
    p.textContent = message;
    empty.appendChild(p);
    container.replaceChildren(empty);
}

async function loadEvidenceAndTimeline(user) {
    try {
        const [evidence, timelineData, subsData] = await Promise.all([
            API.get(`${CONFIG.ENDPOINTS.EVIDENCES}${evidenceId}/`),
            API.get(`${CONFIG.ENDPOINTS.CUSTODY}evidence/${evidenceId}/timeline/`),
            API.get(CONFIG.ENDPOINTS.EVIDENCES, { parent: evidenceId, page_size: 100 }),
        ]);

        renderEvidenceHeader(evidence);
        const records = Array.isArray(timelineData) ? timelineData : (timelineData.results || []);
        // Lista de sub-componentes para a cascade (só nível directo).
        subEvidences = (subsData && subsData.results) || [];
        renderStateProgress(records);
        renderTimeline(records);
        renderTransitionUI(user);

    } catch (err) {
        showError(document.getElementById('timeline-container'), 'Erro ao carregar dados. Tente novamente.');
        console.error('Erro:', err);
    }
}

function renderEvidenceHeader(evidence) {
    const header = document.getElementById('evidence-header');
    const typeLabel = (CONFIG.EVIDENCE_TYPES && CONFIG.EVIDENCE_TYPES[evidence.type]) || evidence.type;
    const dt = new Date(evidence.timestamp_seizure).toLocaleString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });

    const itemLabel = evidence.code
        ? `Item ${evidence.code}`
        : `${typeLabel}`;
    const occLabel = evidence.occurrence_number
        ? ` · Caso ${evidence.occurrence_number}`
        : '';
    document.getElementById('evidence-subtitle').textContent = itemLabel + occLabel;
    document.getElementById('evidence-description').textContent = evidence.description || '\u2014';
    document.getElementById('evidence-type').textContent = typeLabel;
    document.getElementById('evidence-timestamp').textContent = dt;
    const hashEl = document.getElementById('evidence-hash');
    hashEl.textContent = evidence.integrity_hash || '\u2014';
    hashEl.title = `SHA-256: ${evidence.integrity_hash || ''}`;
    header.hidden = false;
}

function renderStateProgress(records) {
    const container = document.getElementById('state-progress');

    const lastRecord = records.length > 0 ? records[records.length - 1] : null;
    currentState = lastRecord ? lastRecord.new_state : '';

    const mainFlow = STATE_FLOW.filter(s => s.key !== 'DESTRUIDA');
    const flow = currentState === 'DESTRUIDA'
        ? [...STATE_FLOW.filter(s => !['DEVOLVIDA','DESTRUIDA'].includes(s.key)),
           STATE_FLOW.find(s => s.key === 'DESTRUIDA')]
        : mainFlow;

    const doneKeys = new Set(records.map(r => r.new_state));

    container.replaceChildren();
    flow.forEach(step => {
        const isDone    = doneKeys.has(step.key);
        const isCurrent = step.key === currentState;
        const cls = isCurrent ? 'current' : (isDone ? 'done' : '');

        const stepEl = document.createElement('div');
        stepEl.className = `state-step ${cls}`.trim();
        const dot = document.createElement('div');
        dot.className = 'state-step-dot';
        // Ponto colorido (CSS pinta via .state-step.done/current); sem texto/emoji.
        stepEl.appendChild(dot);
        const lbl = document.createElement('div');
        lbl.className = 'state-step-label';
        lbl.textContent = step.label;
        stepEl.appendChild(lbl);
        container.appendChild(stepEl);
    });
}

function buildTimelineItem(rec, idx, stateMap) {
    const state = stateMap[rec.new_state] || { label: rec.new_state };
    const dt = new Date(rec.timestamp).toLocaleString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const agentName = rec.agent_name || `Utilizador #${rec.agent}`;

    const item = document.createElement('div');
    item.className = 'timeline-item';
    item.id = `timeline-item-${idx}`;

    const dot = document.createElement('div');
    dot.className = `timeline-dot state-${rec.new_state}`;
    dot.title = state.label;
    item.appendChild(dot);

    const card = document.createElement('div');
    card.className = 'timeline-card';

    const header = document.createElement('div');
    header.className = 'timeline-card-header';
    const stateLbl = document.createElement('span');
    stateLbl.className = 'timeline-state-label';
    stateLbl.textContent = state.label;
    header.appendChild(stateLbl);
    const dateEl = document.createElement('span');
    dateEl.className = 'timeline-date mono';
    dateEl.textContent = dt;
    header.appendChild(dateEl);
    card.appendChild(header);

    const agent = document.createElement('div');
    agent.className = 'timeline-agent';
    const agentIcon = Icons.element('user', { size: 14 });
    if (agentIcon) agent.appendChild(agentIcon);
    const agentLabel = document.createElement('span');
    agentLabel.textContent = ` ${agentName}`;
    agent.appendChild(agentLabel);
    card.appendChild(agent);

    if (rec.observations) {
        const obs = document.createElement('div');
        obs.className = 'timeline-obs';
        obs.textContent = rec.observations;
        card.appendChild(obs);
    }

    const hashLbl = document.createElement('div');
    hashLbl.className = 'hash-label';
    hashLbl.textContent = 'SHA-256 do registo';
    card.appendChild(hashLbl);

    const hash = document.createElement('div');
    hash.className = 'timeline-hash';
    hash.textContent = rec.record_hash || '\u2014';
    card.appendChild(hash);

    item.appendChild(card);
    return item;
}

function renderTimeline(records) {
    const container = document.getElementById('timeline-container');

    if (records.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const iconWrap = document.createElement('div');
        iconWrap.className = 'empty-state-icon';
        const icon = Icons.element('file-text', { size: 22 });
        if (icon) iconWrap.appendChild(icon);
        empty.appendChild(iconWrap);
        const p = document.createElement('p');
        p.textContent = 'Sem registos de custódia. Registe a primeira transição.';
        empty.appendChild(p);
        container.replaceChildren(empty);
        return;
    }

    const stateMap = Object.fromEntries(STATE_FLOW.map(s => [s.key, s]));

    const heading = document.createElement('h3');
    heading.style.margin = '0 0 16px 0';
    heading.style.fontSize = '0.9375rem';
    heading.textContent = 'Histórico de Custódia';

    const timeline = document.createElement('div');
    timeline.className = 'timeline';
    timeline.id = 'custody-timeline';
    records.forEach((rec, idx) => timeline.appendChild(buildTimelineItem(rec, idx, stateMap)));

    container.replaceChildren(heading, timeline);
}

function renderTransitionUI(user) {
    if (!user || !['AGENT', 'EXPERT'].includes(user.profile)) return;

    allowedNextStates = VALID_TRANSITIONS[currentState] || [];
    if (allowedNextStates.length === 0) return;

    const btn = document.getElementById('btn-new-transition');
    if (btn) btn.hidden = false;

    const select = document.getElementById('new-state');
    const stateMap = Object.fromEntries(STATE_FLOW.map(s => [s.key, s]));
    select.replaceChildren();
    allowedNextStates.forEach(key => {
        const s = stateMap[key] || { label: key };
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = s.label;
        select.appendChild(opt);
    });
}

function openTransitionModal() {
    const err = document.getElementById('transition-error');
    err.classList.remove('visible');
    err.textContent = '';
    document.getElementById('observations').value = '';
    renderCascadeChecklist();
    document.getElementById('transition-modal').hidden = false;
}

function closeTransitionModal() {
    document.getElementById('transition-modal').hidden = true;
}

/**
 * Renderiza checklist de sub-itens no modal de transição. Cada sub-item
 * aparece pré-marcado para a cascade; ao desmarcar mostra um aviso
 * amarelo a explicar a consequência.
 */
function renderCascadeChecklist() {
    const section = document.getElementById('cascade-section');
    const list = document.getElementById('cascade-list');
    const warn = document.getElementById('cascade-warning');
    if (!section || !list) return;

    if (!subEvidences || subEvidences.length === 0) {
        section.hidden = true;
        return;
    }
    section.hidden = false;
    warn.classList.add('hidden');
    list.replaceChildren();

    // Item principal — sempre marcado e desactivado (não dá para excluir
    // o "alvo" da própria transição).
    const mainRow = buildCascadeRow({
        id: evidenceId,
        label: 'Item principal',
        checked: true,
        disabled: true,
    });
    list.appendChild(mainRow);

    subEvidences.forEach((sub) => {
        const typeLabel = (CONFIG.EVIDENCE_TYPES && CONFIG.EVIDENCE_TYPES[sub.type]) || sub.type;
        const codePrefix = sub.code ? `${sub.code} · ` : '';
        const row = buildCascadeRow({
            id: sub.id,
            label: `${codePrefix}${typeLabel}`,
            checked: true,
            disabled: false,
        });
        list.appendChild(row);
    });

    // Listener: avisar se o utilizador desmarcar algum sub.
    list.addEventListener('change', () => {
        const anyOff = Array.from(list.querySelectorAll('input[type="checkbox"]:not(:disabled)'))
            .some((cb) => !cb.checked);
        warn.classList.toggle('hidden', !anyOff);
    });
}

function buildCascadeRow(opts) {
    const wrapper = document.createElement('label');
    wrapper.className = 'cascade-row';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = String(opts.id);
    cb.checked = opts.checked;
    cb.disabled = opts.disabled;
    const span = document.createElement('span');
    span.textContent = opts.label;
    wrapper.appendChild(cb);
    wrapper.appendChild(span);
    return wrapper;
}

async function submitTransition() {
    const btn = document.getElementById('btn-submit-transition');
    const errorEl = document.getElementById('transition-error');
    const newState = document.getElementById('new-state').value;
    const observations = document.getElementById('observations').value.trim();
    const list = document.getElementById('cascade-list');

    // Recolhe todos os IDs marcados (incluindo o principal, que está sempre).
    const selectedIds = list
        ? Array.from(list.querySelectorAll('input[type="checkbox"]:checked'))
            .map((cb) => parseInt(cb.value, 10))
            .filter((n) => Number.isFinite(n))
        : [evidenceId];
    const ids = selectedIds.length > 0 ? selectedIds : [evidenceId];

    btn.disabled = true;
    btn.textContent = 'A registar…';
    errorEl.classList.remove('visible');

    try {
        // Sempre via cascade — endpoint é seguro mesmo com 1 evidência só
        // (transação atómica + auditoria por registo).
        await API.post(CONFIG.ENDPOINTS.CUSTODY + 'cascade/', {
            evidence_ids: ids,
            new_state: newState,
            observations,
        });

        closeTransitionModal();
        const n = ids.length;
        Toast.success(n === 1
            ? 'Transição registada com sucesso.'
            : `Transição aplicada a ${n} itens.`);
        const user = Auth.getUser();
        await loadEvidenceAndTimeline(user);

    } catch (err) {
        // Endpoint cascade devolve { evidence_id, evidence_code, error }
        // se uma transição específica falhar.
        let msg = 'Erro ao registar transição.';
        if (err && err.data) {
            if (err.data.evidence_code && err.data.error) {
                const errorDetail = typeof err.data.error === 'object'
                    ? Object.values(err.data.error).flat().join('; ')
                    : err.data.error;
                msg = `Falhou em ${err.data.evidence_code}: ${errorDetail}`;
            } else if (err.data.detail) {
                msg = err.data.detail;
            } else if (err.data.new_state) {
                msg = err.data.new_state[0] || msg;
            }
        }
        errorEl.textContent = msg;
        errorEl.classList.add('visible');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Confirmar';
    }
}
