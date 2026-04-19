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
    profileInfo.replaceChildren();
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

/**
 * Carrega estatísticas agregadas do endpoint `/api/stats/dashboard/` da
 * Wave 2c. Se estiver indisponível (503 ou falha de rede), recai para
 * `/api/stats/` legacy e, em último caso, mostra "—" nos números.
 */
async function loadStats() {
    var grid = document.getElementById('stats-grid');
    var breakdown = document.getElementById('evidences-breakdown');

    if (grid) grid.setAttribute('aria-busy', 'true');

    var data = await fetchDashboardStats();

    if (!data) {
        setStat('stat-occurrences', '—');
        setStat('stat-evidences', '—');
        setStat('stat-devices', '—');
        setStat('stat-custody', '—');
        setStatSub('stat-occurrences-sub', 'indisponível');
        setStatSub('stat-evidences-sub', 'indisponível');
        setStatSub('stat-devices-sub', 'indisponível');
        setStatSub('stat-custody-sub', 'indisponível');
        renderBreakdown({});
        if (grid) grid.setAttribute('aria-busy', 'false');
        return;
    }

    // Novo shape (Wave 2c)
    //   total_occurrences, open_occurrences, total_evidences,
    //   evidences_by_type, custodies_in_transit
    // Legacy shape (fallback):
    //   occurrences, evidences, devices, custody_records,
    //   evidence_by_type, custody_by_state
    var occTotal = pickNumber(data.total_occurrences, data.occurrences);
    var occOpen = pickNumber(data.open_occurrences, null);
    var evTotal = pickNumber(data.total_evidences, data.evidences);
    var devTotal = pickNumber(data.total_devices, data.devices);
    var inTransit = pickNumber(data.custodies_in_transit,
                               (data.custody_by_state || {}).EM_TRANSPORTE);
    var byType = data.evidences_by_type || data.evidence_by_type || {};

    setStat('stat-occurrences', occTotal);
    setStat('stat-evidences', evTotal);
    setStat('stat-devices', devTotal);
    setStat('stat-custody', inTransit);

    if (occOpen !== null && occOpen !== undefined) {
        setStatSub('stat-occurrences-sub', occOpen + ' em aberto');
    }
    setStatSub('stat-custody-sub', 'em trânsito');

    renderBreakdown(byType);

    if (grid) grid.setAttribute('aria-busy', 'false');
    if (breakdown) breakdown.setAttribute('aria-busy', 'false');
}

async function fetchDashboardStats() {
    // 1. Tenta o endpoint novo agregado (Wave 2c)
    try {
        var r = await fetch(CONFIG.ENDPOINTS.STATS_DASHBOARD, { credentials: 'include' });
        if (r.ok) return await r.json();
        if (r.status === 503) {
            console.warn('Serviço de estatísticas temporariamente indisponível.');
            return null;
        }
        // 404 → provavelmente Wave 2c ainda não aterrou; tenta legacy
    } catch (err) {
        console.warn('Falha ao contactar /api/stats/dashboard/:', err);
    }

    // 2. Fallback para endpoint legacy
    try {
        var r2 = await fetch(CONFIG.ENDPOINTS.STATS_LEGACY, { credentials: 'include' });
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

function setStat(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setStatSub(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text || '';
}

function renderBreakdown(byType) {
    var chart = document.getElementById('evidences-type-chart');
    if (!chart) return;
    chart.replaceChildren();

    var entries = Object.keys(byType || {}).map(function (k) {
        return { type: k, count: Number(byType[k]) || 0 };
    }).filter(function (e) { return e.count > 0; });

    if (entries.length === 0) {
        var empty = document.createElement('p');
        empty.className = 'text-muted';
        empty.textContent = 'Sem evidências registadas.';
        chart.appendChild(empty);
        return;
    }

    entries.sort(function (a, b) { return b.count - a.count; });
    var max = entries[0].count || 1;

    entries.forEach(function (e) {
        var row = document.createElement('div');
        row.className = 'type-row';
        row.setAttribute('role', 'listitem');

        var label = document.createElement('div');
        label.className = 'type-row-label';
        var icon = document.createElement('span');
        icon.className = 'type-row-icon';
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = CONFIG.EVIDENCE_ICONS[e.type] || '•';
        var name = document.createElement('span');
        name.textContent = CONFIG.EVIDENCE_TYPES[e.type] || e.type;
        label.appendChild(icon);
        label.appendChild(name);

        var barWrap = document.createElement('div');
        barWrap.className = 'type-row-bar';
        var bar = document.createElement('div');
        bar.className = 'type-row-bar-fill';
        bar.style.width = Math.max(2, (e.count / max) * 100) + '%';
        barWrap.appendChild(bar);

        var val = document.createElement('div');
        val.className = 'type-row-count mono';
        val.textContent = String(e.count);

        row.appendChild(label);
        row.appendChild(barWrap);
        row.appendChild(val);
        chart.appendChild(row);
    });
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
    var snippet = (occ.description || '').substring(0, 80);
    desc.textContent = (occ.description || '').length > 80 ? snippet + '...' : snippet;
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
