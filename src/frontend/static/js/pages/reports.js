'use strict';

/**
 * ForensiQ — Relatórios PDF (/relatorios/).
 *
 * Lista evidências com botão "Gerar PDF" que abre /api/evidences/<id>/pdf/
 * numa nova tab (o browser faz download ou mostra, conforme o Content-Type).
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

let currentPage = 1;
let searchTimeout = null;

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    document.getElementById('search-input').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentPage = 1;
            loadEvidences(e.target.value.trim());
        }, 400);
    });

    loadEvidences();
});

async function loadEvidences(search = '') {
    const container = document.getElementById('reports-list');
    container.replaceChildren(renderLoading());

    try {
        const params = { page: currentPage, page_size: 20 };
        if (search) params.search = search;

        const data = await API.get(CONFIG.ENDPOINTS.EVIDENCES, params);
        const evidences = data.results || [];

        if (evidences.length === 0) {
            container.replaceChildren(renderEmpty(search));
            document.getElementById('pagination').classList.add('hidden');
            return;
        }

        container.replaceChildren();
        evidences.forEach(ev => container.appendChild(renderReportRow(ev)));
        renderPagination(data);
    } catch (err) {
        container.replaceChildren(renderError());
    }
}

function renderReportRow(ev) {
    const typeLabel = CONFIG.EVIDENCE_TYPES[ev.type] || ev.type;

    const row = document.createElement('div');
    row.className = 'list-item';

    const content = document.createElement('div');
    content.className = 'list-item-content';

    const head = document.createElement('div');
    head.className = 'list-item-title flex items-center gap-2';
    const id = document.createElement('span');
    id.className = 'mono';
    id.textContent = '#' + ev.id;
    head.appendChild(id);
    const badge = document.createElement('span');
    badge.className = 'badge badge-accent';
    badge.textContent = typeLabel;
    head.appendChild(badge);
    content.appendChild(head);

    const desc = document.createElement('span');
    desc.className = 'list-item-subtitle';
    const full = (ev.description || '').trim();
    desc.textContent = full.length > 100 ? full.substring(0, 100) + '…' : full;
    content.appendChild(desc);

    const meta = document.createElement('span');
    meta.className = 'list-item-subtitle text-subtle';
    meta.textContent = `Ocorrência #${ev.occurrence || '—'} · ${formatDate(ev.timestamp_seizure)}`;
    content.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'report-item-actions';

    const btnPdf = document.createElement('a');
    btnPdf.className = 'btn btn-primary btn-sm';
    btnPdf.href = `${CONFIG.ENDPOINTS.EVIDENCES}${ev.id}/pdf/`;
    btnPdf.target = '_blank';
    btnPdf.rel = 'noopener';
    btnPdf.appendChild(pdfIcon());
    btnPdf.appendChild(document.createTextNode(' Gerar PDF'));
    actions.appendChild(btnPdf);

    const btnView = document.createElement('a');
    btnView.className = 'btn btn-ghost btn-sm';
    btnView.href = `/evidences/${ev.id}/`;
    btnView.textContent = 'Abrir';
    actions.appendChild(btnView);

    row.appendChild(content);
    row.appendChild(actions);
    return row;
}

function pdfIcon() {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    const p1 = document.createElementNS(SVG_NS, 'path');
    p1.setAttribute('d', 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z');
    const p2 = document.createElementNS(SVG_NS, 'path');
    p2.setAttribute('d', 'M14 2v6h6');
    s.appendChild(p1);
    s.appendChild(p2);
    return s;
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    return d.toLocaleDateString('pt-PT', {
        day: '2-digit', month: 'short',
        hour: '2-digit', minute: '2-digit',
    });
}

function renderLoading() {
    const wrap = document.createElement('div');
    wrap.className = 'loading-overlay';
    const sp = document.createElement('span');
    sp.className = 'spinner';
    const t = document.createElement('span');
    t.textContent = 'A carregar itens';
    wrap.appendChild(sp);
    wrap.appendChild(t);
    return wrap;
}

function renderEmpty(search) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';
    const t = document.createElement('div');
    t.className = 'empty-state-title';
    t.textContent = search ? `Sem resultados para "${search}"` : 'Sem itens para reportar';
    wrap.appendChild(t);
    const p = document.createElement('p');
    p.textContent = search
        ? 'Tenta outro termo.'
        : 'Quando forem registados itens, poderás gerar relatórios aqui.';
    wrap.appendChild(p);
    return wrap;
}

function renderError() {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';
    const t = document.createElement('div');
    t.className = 'empty-state-title text-danger';
    t.textContent = 'Erro ao carregar itens';
    wrap.appendChild(t);
    const p = document.createElement('p');
    p.textContent = 'Verifica a ligação e tenta recarregar.';
    wrap.appendChild(p);
    return wrap;
}

function renderPagination(data) {
    const container = document.getElementById('pagination');
    if (!data.next && !data.previous) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    container.replaceChildren();

    const prev = document.createElement('button');
    prev.className = 'btn btn-ghost btn-sm';
    prev.textContent = '← Anterior';
    prev.disabled = !data.previous;
    prev.addEventListener('click', () => changePage(-1));

    const label = document.createElement('span');
    label.className = 'text-muted text-sm';
    label.textContent = `Página ${currentPage}`;

    const next = document.createElement('button');
    next.className = 'btn btn-ghost btn-sm';
    next.textContent = 'Seguinte →';
    next.disabled = !data.next;
    next.addEventListener('click', () => changePage(1));

    container.appendChild(prev);
    container.appendChild(label);
    container.appendChild(next);
}

function changePage(delta) {
    currentPage += delta;
    const search = document.getElementById('search-input').value.trim();
    loadEvidences(search);
    window.scrollTo(0, 0);
}
