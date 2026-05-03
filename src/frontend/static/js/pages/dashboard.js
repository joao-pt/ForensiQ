'use strict';

/**
 * ForensiQ — Dashboard.
 *
 * Hero: Cadeia de custódia (river bar + cards clicáveis por estado).
 * Acções rápidas (full width) + Últimas ocorrências em baixo.
 * Distribuição por tipo de item migrou para /stats/.
 */

const STATE_FLOW = [
    { key: 'APREENDIDA',           label: 'Apreendida' },
    { key: 'EM_TRANSPORTE',        label: 'Em transporte' },
    { key: 'RECEBIDA_LABORATORIO', label: 'No laboratório' },
    { key: 'EM_PERICIA',           label: 'Em perícia' },
    { key: 'CONCLUIDA',            label: 'Concluída' },
    { key: 'DEVOLVIDA',            label: 'Devolvida' },
    { key: 'DESTRUIDA',            label: 'Destruída' },
];

document.addEventListener('DOMContentLoaded', async function () {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    initDashboard(user);
    loadStats();
    loadRecentOccurrences();

    document.querySelectorAll('[data-nav]').forEach(function (el) {
        el.addEventListener('click', function () {
            window.location.href = el.dataset.nav;
        });
    });
});

function initDashboard(user) {
    if (!user) return;

    const greeting = document.getElementById('greeting');
    const hour = new Date().getHours();
    let salutation = 'Bom dia';
    if (hour >= 13 && hour < 20) salutation = 'Boa tarde';
    else if (hour >= 20 || hour < 6) salutation = 'Boa noite';
    greeting.textContent = salutation + ', ' + (user.first_name || user.username);

    const profileInfo = document.getElementById('profile-info');
    const profileLabel = CONFIG.PROFILES[user.profile] || user.profile;
    profileInfo.replaceChildren();
    profileInfo.textContent = profileLabel;

    if (user.profile === 'AGENT') {
        document.getElementById('agent-actions').classList.remove('hidden');
    } else if (user.profile === 'EXPERT') {
        document.getElementById('expert-actions').classList.remove('hidden');
    }
}

async function loadStats() {
    const flowCard = document.getElementById('custody-flow');
    if (flowCard) flowCard.setAttribute('aria-busy', 'true');

    const data = await fetchDashboardStats();

    if (!data) {
        renderCustodyFlow({ total: 0, byState: {}, withoutCustody: 0, error: true });
        if (flowCard) flowCard.setAttribute('aria-busy', 'false');
        return;
    }

    const total = pickNumber(data.total_evidences, data.evidences);
    const byState = data.evidences_by_current_state
        || data.custody_by_state          // fallback ao endpoint legado
        || {};
    const withoutCustody = pickNumber(data.evidences_without_custody, 0);

    renderCustodyFlow({ total, byState, withoutCustody });
    if (flowCard) flowCard.setAttribute('aria-busy', 'false');
}

async function fetchDashboardStats() {
    try {
        const r = await fetch(CONFIG.ENDPOINTS.STATS_DASHBOARD, { credentials: 'include' });
        if (r.ok) return await r.json();
        if (r.status === 503) {
            console.warn('Serviço de estatísticas temporariamente indisponível.');
            return null;
        }
    } catch (err) {
        console.warn('Falha ao contactar /api/stats/dashboard/:', err);
    }
    try {
        const r2 = await fetch(CONFIG.ENDPOINTS.STATS_LEGACY, { credentials: 'include' });
        if (r2.ok) return await r2.json();
    } catch (err2) {
        console.error('Falha também em /api/stats/:', err2);
    }
    return null;
}

function pickNumber(a, b) {
    if (typeof a === 'number') return a;
    if (typeof b === 'number') return b;
    return 0;
}

/**
 * Renderiza a "river bar" + cards clicáveis por estado.
 *
 * - River: 7 segmentos com flex proporcional ao count. Estados a 0
 *   recebem um sliver com hatching (8px) para denunciar a sua presença.
 * - Cards: count grande + label + percentagem; click navega para
 *   /evidences/?state=<KEY> (já filtrável pelo backend).
 */
function renderCustodyFlow({ total, byState, withoutCustody, error }) {
    const totalEl = document.getElementById('custody-flow-total-num');
    const river = document.getElementById('custody-river');
    const states = document.getElementById('custody-flow-states');
    if (!totalEl || !river || !states) return;

    const totalCovered = STATE_FLOW.reduce(
        (acc, s) => acc + (Number(byState[s.key]) || 0), 0,
    );
    const totalShown = total || (totalCovered + (withoutCustody || 0));

    totalEl.textContent = error ? '—' : String(totalShown);

    river.replaceChildren();
    states.replaceChildren();

    if (error) {
        const msg = document.createElement('p');
        msg.className = 'text-muted';
        msg.style.padding = 'var(--sp-3)';
        msg.textContent = 'Não foi possível carregar a distribuição de custódia.';
        states.appendChild(msg);
        return;
    }

    const denominator = totalCovered || 1;

    STATE_FLOW.forEach((s) => {
        const count = Number(byState[s.key]) || 0;
        const pct = totalCovered > 0 ? (count / denominator) * 100 : 0;

        // River segment.
        const seg = document.createElement('div');
        seg.className = 'custody-river-segment' + (count === 0 ? ' is-empty' : '');
        seg.dataset.state = s.key;
        seg.style.flex = count > 0 ? `${count} 1 0` : '';
        seg.style.background = count > 0 ? `var(--state-${s.key.toLowerCase().replace(/_/g, '-')})` : '';
        seg.title = `${s.label}: ${count} ${count === 1 ? 'item' : 'itens'}`;
        river.appendChild(seg);

        // Card.
        const card = document.createElement('a');
        card.className = 'flow-state-card' + (count === 0 ? ' is-empty' : '');
        card.dataset.state = s.key;
        card.href = `/evidences/?state=${s.key}`;
        card.setAttribute('role', 'listitem');
        card.setAttribute('aria-label',
            `${s.label}: ${count} ${count === 1 ? 'item' : 'itens'} — abrir lista filtrada`);

        const countEl = document.createElement('div');
        countEl.className = 'flow-state-count';
        countEl.textContent = String(count);

        const labelEl = document.createElement('div');
        labelEl.className = 'flow-state-label';
        labelEl.textContent = s.label;

        const pctEl = document.createElement('div');
        pctEl.className = 'flow-state-pct';
        pctEl.textContent = totalCovered > 0
            ? `${pct.toFixed(0)}%`
            : '—';

        card.appendChild(countEl);
        card.appendChild(labelEl);
        card.appendChild(pctEl);
        states.appendChild(card);
    });
}

async function loadRecentOccurrences() {
    const container = document.getElementById('recent-occurrences');

    try {
        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 5 });
        const occurrences = data.results || [];

        container.replaceChildren();

        if (occurrences.length === 0) {
            container.appendChild(buildEmptyState('folder', 'Sem ocorrências registadas.'));
            return;
        }

        occurrences.forEach(function (occ) {
            container.appendChild(buildOccurrenceRow(occ));
        });
    } catch (err) {
        container.replaceChildren();
        const empty = buildEmptyState(null, 'Erro ao carregar ocorrências.');
        const p = empty.querySelector('p');
        if (p) p.classList.add('text-danger');
        container.appendChild(empty);
        console.error('Erro:', err);
    }
}

function buildOccurrenceRow(occ) {
    const date = new Date(occ.date_time).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });

    const row = document.createElement('a');
    row.className = 'list-item';
    row.href = '/occurrences/' + occ.id + '/';

    const content = document.createElement('div');
    content.className = 'list-item-content';

    const num = document.createElement('div');
    num.className = 'list-item-title';
    num.textContent = occ.number;
    content.appendChild(num);

    const desc = document.createElement('div');
    desc.className = 'list-item-subtitle';
    const snippet = (occ.description || '').substring(0, 80);
    desc.textContent = (occ.description || '').length > 80 ? snippet + '...' : snippet;
    content.appendChild(desc);

    if (occ.address) {
        const addr = document.createElement('div');
        addr.className = 'list-item-subtitle text-subtle';
        addr.textContent = occ.address;
        content.appendChild(addr);
    }

    const right = document.createElement('div');
    right.className = 'list-item-meta mono';
    right.textContent = date;

    row.appendChild(content);
    row.appendChild(right);

    const chev = Icons.element('chevron-right', { size: 16 });
    if (chev) {
        chev.classList.add('list-item-chevron');
        row.appendChild(chev);
    }

    return row;
}

function buildEmptyState(iconName, message) {
    const wrapper = document.createElement('div');
    wrapper.className = 'empty-state';
    if (iconName) {
        const ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        const svgIcon = Icons.element(iconName, { size: 22 });
        if (svgIcon) ic.appendChild(svgIcon);
        wrapper.appendChild(ic);
    }
    const p = document.createElement('p');
    p.textContent = message;
    wrapper.appendChild(p);
    return wrapper;
}
