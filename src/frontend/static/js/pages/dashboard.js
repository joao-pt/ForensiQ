'use strict';

document.addEventListener('DOMContentLoaded', async function () {
    var authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    var user = Auth.getUser();
    initDashboard(user);
    loadStats();
    loadRecentOccurrences();

    // Logout e user-menu são cuidados por user-menu.js (carregado no base.html).

    document.querySelectorAll('[data-nav]').forEach(function (el) {
        el.addEventListener('click', function () {
            window.location.href = el.dataset.nav;
        });
    });
});

function initDashboard(user) {
    if (!user) return;

    var greeting = document.getElementById('greeting');
    var hour = new Date().getHours();
    var salutation = 'Bom dia';
    if (hour >= 13 && hour < 20) salutation = 'Boa tarde';
    else if (hour >= 20 || hour < 6) salutation = 'Boa noite';
    greeting.textContent = salutation + ', ' + (user.first_name || user.username);

    var profileInfo = document.getElementById('profile-info');
    var profileLabel = CONFIG.PROFILES[user.profile] || user.profile;
    profileInfo.replaceChildren();
    profileInfo.textContent = profileLabel;

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
        setStat('stat-analysis', '—');
        setStat('stat-custody', '—');
        setStatSub('stat-occurrences-sub', 'indisponível');
        setStatSub('stat-evidences-sub', 'indisponível');
        setStatSub('stat-analysis-sub', 'indisponível');
        setStatSub('stat-custody-sub', 'indisponível');
        renderBreakdown({});
        if (grid) grid.setAttribute('aria-busy', 'false');
        return;
    }

    // Novo shape (Wave 2c+):
    //   total_occurrences, open_occurrences, total_evidences,
    //   evidences_by_type, custodies_in_transit, evidences_in_analysis
    // O legado "devices"/"total_devices" foi descontinuado em favor da
    // taxonomia Evidence (sub_components) — agora mostramos "Em perícia".
    var occTotal = pickNumber(data.total_occurrences, data.occurrences);
    var occOpen = pickNumber(data.open_occurrences, null);
    var evTotal = pickNumber(data.total_evidences, data.evidences);
    var inAnalysis = pickNumber(data.evidences_in_analysis,
                                (data.custody_by_state || {}).EM_PERICIA);
    var inTransit = pickNumber(data.custodies_in_transit,
                               (data.custody_by_state || {}).EM_TRANSPORTE);
    var byType = data.evidences_by_type || data.evidence_by_type || {};

    setStat('stat-occurrences', occTotal);
    setStat('stat-evidences', evTotal);
    setStat('stat-analysis', inAnalysis);
    setStat('stat-custody', inTransit);

    if (occOpen !== null && occOpen !== undefined) {
        setStatSub('stat-occurrences-sub', occOpen + ' em aberto');
    }

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
        empty.textContent = 'Sem itens registados.';
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
        var svgIcon = Icons.forEvidenceElement(e.type, { size: 16 });
        if (svgIcon) icon.appendChild(svgIcon);
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
            container.appendChild(buildEmptyState('folder', 'Sem ocorrências registadas.'));
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

    var row = document.createElement('a');
    row.className = 'list-item';
    row.href = '/occurrences/' + occ.id + '/';

    var content = document.createElement('div');
    content.className = 'list-item-content';

    var num = document.createElement('div');
    num.className = 'list-item-title';
    num.textContent = occ.number;
    content.appendChild(num);

    var desc = document.createElement('div');
    desc.className = 'list-item-subtitle';
    var snippet = (occ.description || '').substring(0, 80);
    desc.textContent = (occ.description || '').length > 80 ? snippet + '...' : snippet;
    content.appendChild(desc);

    if (occ.address) {
        var addr = document.createElement('div');
        addr.className = 'list-item-subtitle text-subtle';
        addr.textContent = occ.address;
        content.appendChild(addr);
    }

    var right = document.createElement('div');
    right.className = 'list-item-meta mono';
    right.textContent = date;

    row.appendChild(content);
    row.appendChild(right);

    // Chevron — alinha o estilo das linhas com as listagens /occurrences/
    // e /evidences/ (que já mostram chevron à direita).
    var chev = Icons.element('chevron-right', { size: 16 });
    if (chev) {
        chev.classList.add('list-item-chevron');
        row.appendChild(chev);
    }

    return row;
}

function buildEmptyState(iconName, message) {
    var wrapper = document.createElement('div');
    wrapper.className = 'empty-state';
    if (iconName) {
        var ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        var svgIcon = Icons.element(iconName, { size: 22 });
        if (svgIcon) ic.appendChild(svgIcon);
        wrapper.appendChild(ic);
    }
    var p = document.createElement('p');
    p.textContent = message;
    wrapper.appendChild(p);
    return wrapper;
}
