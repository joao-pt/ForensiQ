'use strict';

/**
 * ForensiQ — Lista de custódias.
 *
 * Obtém as transições visíveis ao utilizador (a filtragem por perfil é
 * aplicada no backend em /api/custody/) e apresenta-as numa tabela com
 * pesquisa client-side e paginação simples.
 */

var currentPage = 1;
var searchTimeout = null;

document.addEventListener('DOMContentLoaded', async function () {
    var authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    // Logout e user-menu são cuidados por user-menu.js (carregado no base.html).

    var searchInput = document.getElementById('custody-search');
    searchInput.addEventListener('input', function (e) {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(function () {
            currentPage = 1;
            loadCustodies(e.target.value.trim());
        }, 400);
    });

    loadCustodies();
});

async function loadCustodies(search) {
    var wrapper = document.getElementById('custody-table-wrapper');
    var tbody = document.getElementById('custody-tbody');
    var countEl = document.getElementById('custody-count');

    wrapper.setAttribute('aria-busy', 'true');
    tbody.replaceChildren(buildLoadingRow(6));

    try {
        var params = { page: currentPage, page_size: 25 };
        if (search) params.search = search;

        var data = await API.get(CONFIG.ENDPOINTS.CUSTODY, params);
        var records = data.results || [];
        var total = data.count || 0;

        countEl.textContent = total + (total === 1 ? ' transição' : ' transições');

        tbody.replaceChildren();
        if (records.length === 0) {
            tbody.appendChild(buildEmptyRow(search
                ? 'Sem resultados para "' + search + '".'
                : 'Sem transições registadas.'));
        } else {
            records.forEach(function (rec) { tbody.appendChild(buildRow(rec)); });
        }

        renderPagination(data);
    } catch (err) {
        console.error('Erro ao carregar custódias:', err);
        tbody.replaceChildren(buildEmptyRow('Erro ao carregar custódias. Tente novamente.', true));
        Toast.show('Erro ao carregar custódias.', 'error');
    } finally {
        wrapper.setAttribute('aria-busy', 'false');
    }
}

function buildLoadingRow(span) {
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.colSpan = span;
    td.className = 'text-center text-muted';
    var wrap = document.createElement('div');
    wrap.className = 'loading-overlay';
    var sp = document.createElement('span');
    sp.className = 'spinner';
    wrap.appendChild(sp);
    td.appendChild(wrap);
    tr.appendChild(td);
    return tr;
}

function buildEmptyRow(message, danger) {
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.colSpan = 6;
    td.className = 'text-center text-muted';
    if (danger) td.classList.add('text-danger');
    td.textContent = message;
    tr.appendChild(td);
    return tr;
}

function buildRow(rec) {
    var tr = document.createElement('tr');

    // Evidência — preferir o código humano (ITM-2026-XXXXX); fallback "#id".
    var evTd = document.createElement('td');
    if (rec.evidence) {
        var a = document.createElement('a');
        a.href = '/evidences/' + rec.evidence + '/';
        a.className = 'link mono';
        a.textContent = rec.evidence_code || ('#' + rec.evidence);
        evTd.appendChild(a);
    } else {
        evTd.textContent = '—';
    }
    tr.appendChild(evTd);

    // Estado anterior — usa label legível em vez do enum (RECEBIDA_LABORATORIO → "No laboratório")
    var fromTd = document.createElement('td');
    if (rec.previous_state) {
        var fromLabel = (CONFIG.CUSTODY_STATES && CONFIG.CUSTODY_STATES[rec.previous_state])
            || rec.previous_state;
        fromTd.textContent = fromLabel;
    } else {
        fromTd.textContent = '—';
    }
    tr.appendChild(fromTd);

    // Custodiante — nome completo do agente (não o ID).
    var toTd = document.createElement('td');
    toTd.textContent = rec.agent_name || '—';
    tr.appendChild(toTd);

    // Estado — usa state-pill (cores coerentes com timeline)
    var stTd = document.createElement('td');
    if (rec.new_state) {
        var pill = document.createElement('span');
        pill.className = 'state-pill state-' + rec.new_state;
        pill.textContent = CONFIG.CUSTODY_STATES[rec.new_state] || rec.new_state;
        stTd.appendChild(pill);
    } else {
        stTd.textContent = '—';
    }
    tr.appendChild(stTd);

    // Data/hora
    var dtTd = document.createElement('td');
    dtTd.className = 'mono';
    if (rec.timestamp) {
        var d = new Date(rec.timestamp);
        dtTd.textContent = d.toLocaleDateString('pt-PT', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } else {
        dtTd.textContent = '—';
    }
    tr.appendChild(dtTd);

    // Link para timeline
    var actionsTd = document.createElement('td');
    actionsTd.className = 'text-right';
    if (rec.evidence) {
        var link = document.createElement('a');
        link.href = '/evidences/' + rec.evidence + '/custody/';
        link.className = 'btn btn-sm btn-ghost';
        link.textContent = 'Ver timeline';
        actionsTd.appendChild(link);
    }
    tr.appendChild(actionsTd);

    return tr;
}

function formatAgent(agent) {
    if (!agent) return '';
    if (typeof agent === 'string' || typeof agent === 'number') return String(agent);
    return agent.full_name || agent.username || agent.email || '';
}

function renderPagination(data) {
    var container = document.getElementById('custody-pagination');
    if (!data.next && !data.previous) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    container.replaceChildren();

    var prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'btn btn-sm btn-ghost';
    prev.textContent = '← Anterior';
    prev.disabled = !data.previous;
    prev.addEventListener('click', function () { changePage(-1); });

    var label = document.createElement('span');
    label.className = 'text-muted text-sm';
    label.textContent = 'Página ' + currentPage;

    var next = document.createElement('button');
    next.type = 'button';
    next.className = 'btn btn-sm btn-ghost';
    next.textContent = 'Seguinte →';
    next.disabled = !data.next;
    next.addEventListener('click', function () { changePage(1); });

    container.appendChild(prev);
    container.appendChild(label);
    container.appendChild(next);
}

function changePage(delta) {
    currentPage += delta;
    var search = document.getElementById('custody-search').value.trim();
    loadCustodies(search);
    window.scrollTo(0, 0);
}
