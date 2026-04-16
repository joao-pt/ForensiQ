'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    initDashboard(user);
    loadStats();
    loadRecentOccurrences();

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    document.querySelectorAll('[data-nav]').forEach(el => {
        el.addEventListener('click', () => {
            window.location.href = el.dataset.nav;
        });
    });
});

function initDashboard(user) {
    if (!user) return;

    const navbarUser = document.getElementById('navbar-user');
    navbarUser.textContent = user.first_name || user.username;

    const greeting = document.getElementById('greeting');
    const hour = new Date().getHours();
    let salutation = 'Bom dia';
    if (hour >= 13 && hour < 20) salutation = 'Boa tarde';
    else if (hour >= 20 || hour < 6) salutation = 'Boa noite';

    greeting.textContent = `${salutation}, ${user.first_name || user.username}`;

    const profileInfo = document.getElementById('profile-info');
    profileInfo.textContent = CONFIG.PROFILES[user.profile] || user.profile;

    if (user.profile === 'AGENT') {
        document.getElementById('agent-actions').classList.remove('hidden');
    } else if (user.profile === 'EXPERT') {
        document.getElementById('expert-actions').classList.remove('hidden');
    }
}

async function loadStats() {
    try {
        const [occurrences, evidences, devices, custody] = await Promise.all([
            API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 1 }),
            API.get(CONFIG.ENDPOINTS.EVIDENCES, { page_size: 1 }),
            API.get(CONFIG.ENDPOINTS.DEVICES, { page_size: 1 }),
            API.get(CONFIG.ENDPOINTS.CUSTODY, { page_size: 1 }),
        ]);

        document.getElementById('stat-occurrences').textContent = occurrences.count || 0;
        document.getElementById('stat-evidences').textContent = evidences.count || 0;
        document.getElementById('stat-devices').textContent = devices.count || 0;
        document.getElementById('stat-custody').textContent = custody.count || 0;
    } catch (err) {
        console.error('Erro ao carregar estatísticas:', err);
    }
}

async function loadRecentOccurrences() {
    const container = document.getElementById('recent-occurrences');

    try {
        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 5 });
        const occurrences = data.results || [];

        container.replaceChildren();

        if (occurrences.length === 0) {
            container.appendChild(buildEmptyState('\u{1F4CB}', 'Sem ocorrências registadas.'));
            return;
        }

        occurrences.forEach(occ => container.appendChild(buildOccurrenceRow(occ)));
    } catch (err) {
        container.replaceChildren();
        const empty = buildEmptyState(null, 'Erro ao carregar ocorrências.');
        empty.querySelector('p').classList.add('text-danger');
        container.appendChild(empty);
        console.error('Erro:', err);
    }
}

function buildOccurrenceRow(occ) {
    const date = new Date(occ.date_time).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });

    const row = document.createElement('div');
    row.className = 'list-item';
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => {
        window.location.href = `/occurrences/${occ.id}/`;
    });

    const left = document.createElement('div');
    left.style.flex = '1';

    const num = document.createElement('strong');
    num.textContent = occ.number;
    left.appendChild(num);

    const desc = document.createElement('div');
    desc.className = 'text-muted';
    desc.style.fontSize = '0.8125rem';
    const snippet = occ.description.substring(0, 80);
    desc.textContent = occ.description.length > 80 ? `${snippet}...` : snippet;
    left.appendChild(desc);

    const right = document.createElement('div');
    right.className = 'text-muted';
    right.style.fontSize = '0.75rem';
    right.style.whiteSpace = 'nowrap';
    right.textContent = date;

    row.appendChild(left);
    row.appendChild(right);
    return row;
}

function buildEmptyState(icon, message) {
    const wrapper = document.createElement('div');
    wrapper.className = 'empty-state';
    if (icon) {
        const ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        ic.textContent = icon;
        wrapper.appendChild(ic);
    }
    const p = document.createElement('p');
    p.textContent = message;
    wrapper.appendChild(p);
    return wrapper;
}
