'use strict';

document.addEventListener('DOMContentLoaded', async function () {
    var authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    var user = Auth.getUser();
    initDashboard(user);
    loadStats();
    loadRecentOccurrences();

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    document.querySelectorAll('[data-nav]').forEach(function (el) {
        el.addEventListener('click', function () {
            window.location.href = el.dataset.nav;
        });
    });
});

function initDashboard(user) {
    if (!user) return;

    var navbarUser = document.getElementById('navbar-user');
    if (navbarUser) navbarUser.textContent = user.first_name || user.username;

    var greeting = document.getElementById('greeting');
    var hour = new Date().getHours();
    var salutation = 'Bom dia';
    if (hour >= 13 && hour < 20) salutation = 'Boa tarde';
    else if (hour >= 20 || hour < 6) salutation = 'Boa noite';
    greeting.textContent = salutation + ', ' + (user.first_name || user.username);

    var profileInfo = document.getElementById('profile-info');
    var profileLabel = CONFIG.PROFILES[user.profile] || user.profile;
    profileInfo.innerHTML = '';
    var badge = document.createElement('span');
    badge.className = 'greeting-badge';
    badge.textContent = profileLabel;
    profileInfo.appendChild(badge);

    if (user.profile === 'AGENT') {
        document.getElementById('agent-actions').classList.remove('hidden');
    } else if (user.profile === 'EXPERT') {
        document.getElementById('expert-actions').classList.remove('hidden');
    }
}

async function loadStats() {
    try {
        var results = await Promise.all([
            API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 1 }),
            API.get(CONFIG.ENDPOINTS.EVIDENCES, { page_size: 1 }),
            API.get(CONFIG.ENDPOINTS.DEVICES, { page_size: 1 }),
            API.get(CONFIG.ENDPOINTS.CUSTODY, { page_size: 1 })
        ]);

        setStat('stat-occurrences', results[0].count || 0);
        setStat('stat-evidences', results[1].count || 0);
        setStat('stat-devices', results[2].count || 0);
        setStat('stat-custody', results[3].count || 0);
    } catch (err) {
        console.error('Erro ao carregar estatísticas:', err);
        setStat('stat-occurrences', '—');
        setStat('stat-evidences', '—');
        setStat('stat-devices', '—');
        setStat('stat-custody', '—');
    }
}

function setStat(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

async function loadRecentOccurrences() {
    var container = document.getElementById('recent-occurrences');

    try {
        var data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 5 });
        var occurrences = data.results || [];

        container.replaceChildren();

        if (occurrences.length === 0) {
            container.appendChild(buildEmptyState('\uD83D\uDCCB', 'Sem ocorrências registadas.'));
            return;
        }

        occurrences.forEach(function (occ) {
            container.appendChild(buildOccurrenceRow(occ));
        });
    } catch (err) {
        container.replaceChildren();
        var empty = buildEmptyState(null, 'Erro ao carregar ocorrências.');
        var p = empty.querySelector('p');
        if (p) p.classList.add('text-danger');
        container.appendChild(empty);
        console.error('Erro:', err);
    }
}

function buildOccurrenceRow(occ) {
    var date = new Date(occ.date_time).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });

    var row = document.createElement('div');
    row.className = 'list-item';
    row.style.cursor = 'pointer';
    row.addEventListener('click', function () {
        window.location.href = '/occurrences/' + occ.id + '/';
    });

    var left = document.createElement('div');
    left.style.flex = '1';

    var num = document.createElement('strong');
    num.textContent = occ.number;
    left.appendChild(num);

    var desc = document.createElement('div');
    desc.className = 'text-muted';
    desc.style.fontSize = '0.8125rem';
    var snippet = occ.description.substring(0, 80);
    desc.textContent = occ.description.length > 80 ? snippet + '...' : snippet;
    left.appendChild(desc);

    var right = document.createElement('div');
    right.className = 'text-muted mono';
    right.style.fontSize = '0.75rem';
    right.style.whiteSpace = 'nowrap';
    right.textContent = date;

    row.appendChild(left);
    row.appendChild(right);
    return row;
}

function buildEmptyState(icon, message) {
    var wrapper = document.createElement('div');
    wrapper.className = 'empty-state';
    if (icon) {
        var ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        ic.textContent = icon;
        wrapper.appendChild(ic);
    }
    var p = document.createElement('p');
    p.textContent = message;
    wrapper.appendChild(p);
    return wrapper;
}
