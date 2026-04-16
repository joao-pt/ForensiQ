'use strict';

const evidenceId = parseInt(window.location.pathname.match(/\/evidence\/(\d+)\//)?.[1], 10);
let currentState = null;
let allowedNextStates = [];

const STATE_FLOW = [
    { key: 'APREENDIDA',           label: 'Apreendida',         icon: '\u{1F512}' },
    { key: 'EM_TRANSPORTE',        label: 'Em Transporte',      icon: '\u{1F690}' },
    { key: 'RECEBIDA_LABORATORIO', label: 'No Laboratório',     icon: '\u{1F3DB}\uFE0F' },
    { key: 'EM_PERICIA',           label: 'Em Perícia',         icon: '\u{1F52C}' },
    { key: 'CONCLUIDA',            label: 'Concluída',          icon: '\u2705' },
    { key: 'DEVOLVIDA',            label: 'Devolvida',          icon: '\u21A9\uFE0F' },
    { key: 'DESTRUIDA',            label: 'Destruída',          icon: '\u{1F5D1}\uFE0F' },
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

    const user = Auth.getUser();
    if (user) {
        document.getElementById('navbar-user').textContent = user.first_name || user.username;
    }
    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    document.getElementById('btn-new-transition').addEventListener('click', openTransitionModal);
    document.getElementById('btn-cancel-transition').addEventListener('click', closeTransitionModal);
    document.getElementById('btn-submit-transition').addEventListener('click', submitTransition);

    if (!evidenceId) {
        const container = document.getElementById('timeline-container');
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const p = document.createElement('p');
        p.className = 'text-danger';
        p.textContent = 'ID de evidência inválido.';
        empty.appendChild(p);
        container.replaceChildren(empty);
        return;
    }

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
        const [evidence, timelineData] = await Promise.all([
            API.get(`${CONFIG.ENDPOINTS.EVIDENCES}${evidenceId}/`),
            API.get(`${CONFIG.ENDPOINTS.CUSTODY}evidence/${evidenceId}/timeline/`),
        ]);

        renderEvidenceHeader(evidence);
        const records = Array.isArray(timelineData) ? timelineData : (timelineData.results || []);
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
    const typeMap = {
        DIGITAL_DEVICE:  'Dispositivo Digital',
        DOCUMENT:        'Documento',
        STORAGE_MEDIA:   'Suporte de Armazenamento',
        PHOTO:           'Fotografia',
        OTHER:           'Outro',
    };
    const dt = new Date(evidence.timestamp_seizure).toLocaleString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });

    document.getElementById('evidence-subtitle').textContent = `Evidência #${evidence.id}`;
    document.getElementById('evidence-description').textContent = evidence.description || '\u2014';
    document.getElementById('evidence-type').textContent = typeMap[evidence.type] || evidence.type;
    document.getElementById('evidence-timestamp').textContent = dt;
    const hashEl = document.getElementById('evidence-hash');
    hashEl.textContent = evidence.integrity_hash || '\u2014';
    hashEl.title = `SHA-256: ${evidence.integrity_hash || ''}`;
    header.style.display = '';
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
        dot.textContent = step.icon;
        stepEl.appendChild(dot);
        const lbl = document.createElement('div');
        lbl.className = 'state-step-label';
        lbl.textContent = step.label;
        stepEl.appendChild(lbl);
        container.appendChild(stepEl);
    });
}

function buildTimelineItem(rec, idx, stateMap) {
    const state = stateMap[rec.new_state] || { label: rec.new_state, icon: '\u25CF' };
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
    dot.textContent = state.icon;
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
    dateEl.className = 'timeline-date';
    dateEl.textContent = `\u{1F551} ${dt}`;
    header.appendChild(dateEl);
    card.appendChild(header);

    const agent = document.createElement('div');
    agent.className = 'timeline-agent';
    agent.textContent = `\u{1F464} ${agentName}`;
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
        const icon = document.createElement('div');
        icon.className = 'empty-state-icon';
        icon.textContent = '\u{1F4CB}';
        empty.appendChild(icon);
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
    if (!user || user.profile !== 'AGENT') return;

    allowedNextStates = VALID_TRANSITIONS[currentState] || [];
    if (allowedNextStates.length === 0) return;

    const container = document.getElementById('new-transition-container');
    container.style.display = '';

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
    document.getElementById('transition-error').style.display = 'none';
    document.getElementById('observations').value = '';
    document.getElementById('transition-modal').classList.add('open');
}

function closeTransitionModal() {
    document.getElementById('transition-modal').classList.remove('open');
}

async function submitTransition() {
    const btn = document.getElementById('btn-submit-transition');
    const errorEl = document.getElementById('transition-error');
    const newState = document.getElementById('new-state').value;
    const observations = document.getElementById('observations').value.trim();

    btn.disabled = true;
    btn.textContent = 'A registar...';
    errorEl.style.display = 'none';

    try {
        await API.post(CONFIG.ENDPOINTS.CUSTODY, {
            evidence: evidenceId,
            new_state: newState,
            observations,
        });

        closeTransitionModal();
        Toast.success('Transição registada com sucesso.');
        const user = Auth.getUser();
        await loadEvidenceAndTimeline(user);

    } catch (err) {
        const msg = err?.detail || err?.new_state?.[0] || 'Erro ao registar transição.';
        errorEl.textContent = msg;
        errorEl.style.display = '';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Confirmar';
    }
}
