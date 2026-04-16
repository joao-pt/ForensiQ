'use strict';

let currentPage = 1;
let searchTimeout = null;

const TYPE_COLORS = {
    'DIGITAL_DEVICE': 'blue',
    'DOCUMENT': 'orange',
    'STORAGE_MEDIA': 'green',
    'PHOTO': 'red',
    'OTHER': 'default',
};

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    if (user) {
        document.getElementById('navbar-user').textContent = user.first_name || user.username;
        if (user.profile !== 'AGENT') {
            const btnNew = document.getElementById('btn-new-evidence');
            if (btnNew) btnNew.style.display = 'none';
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    document.getElementById('search-input').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentPage = 1;
            loadEvidences(e.target.value.trim());
        }, 400);
    });

    loadEvidences();
});

function buildLoading() {
    const wrap = document.createElement('div');
    wrap.className = 'loading-overlay';
    const sp = document.createElement('div');
    sp.className = 'spinner spinner-dark';
    wrap.appendChild(sp);
    return wrap;
}

function buildEmpty(message, opts = {}) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';

    if (opts.icon) {
        const ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        ic.textContent = opts.icon;
        wrap.appendChild(ic);
    }

    const p = document.createElement('p');
    p.textContent = message;
    if (opts.danger) p.classList.add('text-danger');
    wrap.appendChild(p);

    if (opts.action) {
        wrap.appendChild(opts.action);
    }
    return wrap;
}

async function loadEvidences(search = '') {
    const container = document.getElementById('evidences-list');
    const countEl = document.getElementById('evidences-count');

    container.replaceChildren(buildLoading());

    try {
        const params = { page: currentPage, page_size: 20 };
        if (search) params.search = search;

        const data = await API.get(CONFIG.ENDPOINTS.EVIDENCES, params);
        const evidences = data.results || [];

        const total = data.count || 0;
        countEl.textContent = `${total} evidência${total !== 1 ? 's' : ''}`;

        if (evidences.length === 0) {
            const message = search
                ? `Sem resultados para "${search}".`
                : 'Sem evidências registadas.';
            const opts = { icon: '\u{1F50E}' };
            const user = Auth.getUser();
            if (!search && user && user.profile === 'AGENT') {
                const a = document.createElement('a');
                a.href = '/evidences/new/';
                a.className = 'btn btn-primary mt-16';
                a.id = 'btn-empty-new';
                a.textContent = 'Registar primeira evidência';
                opts.action = a;
            }
            container.replaceChildren(buildEmpty(message, opts));
            document.getElementById('pagination').classList.add('hidden');
            return;
        }

        container.replaceChildren();
        evidences.forEach(ev => container.appendChild(renderEvidenceItem(ev)));
        renderPagination(data);

    } catch (err) {
        container.replaceChildren(buildEmpty('Erro ao carregar evidências. Tente novamente.', { danger: true }));
        console.error('Erro:', err);
    }
}

function renderEvidenceItem(ev) {
    const date = new Date(ev.timestamp_seizure).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const typeName = CONFIG.EVIDENCE_TYPES[ev.type] || ev.type;
    const color = TYPE_COLORS[ev.type] || 'default';

    const row = document.createElement('div');
    row.className = 'list-item';
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => {
        window.location.href = `/evidences/${ev.id}/`;
    });

    const left = document.createElement('div');
    left.style.flex = '1';
    left.style.minWidth = '0';

    const badges = document.createElement('div');
    badges.style.display = 'flex';
    badges.style.alignItems = 'center';
    badges.style.gap = '8px';
    badges.style.flexWrap = 'wrap';

    const typeBadge = document.createElement('span');
    typeBadge.className = `badge badge-${color}`;
    typeBadge.textContent = typeName;
    badges.appendChild(typeBadge);

    if (ev.photo) {
        const b = document.createElement('span');
        b.className = 'badge badge-success';
        b.textContent = '\u{1F4F7}';
        badges.appendChild(b);
    }
    if (ev.gps_lat && ev.gps_lon) {
        const b = document.createElement('span');
        b.className = 'badge badge-success';
        b.textContent = '\u{1F4CD}';
        badges.appendChild(b);
    }

    const idTag = document.createElement('small');
    idTag.className = 'text-muted';
    idTag.textContent = `#${ev.id}`;
    badges.appendChild(idTag);

    left.appendChild(badges);

    const desc = document.createElement('div');
    desc.className = 'mt-4';
    desc.style.fontWeight = '500';
    desc.style.overflow = 'hidden';
    desc.style.textOverflow = 'ellipsis';
    desc.style.whiteSpace = 'nowrap';
    const fullDesc = ev.description || '';
    desc.textContent = fullDesc.length > 80 ? `${fullDesc.substring(0, 80)}...` : fullDesc;
    left.appendChild(desc);

    const occLine = document.createElement('div');
    occLine.className = 'text-muted';
    occLine.style.fontSize = '0.75rem';
    occLine.textContent = `Ocorrência: ${ev.occurrence ? ev.occurrence : '—'}`;
    left.appendChild(occLine);

    const right = document.createElement('div');
    right.style.textAlign = 'right';
    right.style.flexShrink = '0';
    right.style.marginLeft = '12px';

    const dateEl = document.createElement('div');
    dateEl.className = 'text-muted';
    dateEl.style.fontSize = '0.75rem';
    dateEl.style.whiteSpace = 'nowrap';
    dateEl.textContent = date;
    right.appendChild(dateEl);

    const arrow = document.createElement('div');
    arrow.className = 'text-muted';
    arrow.style.fontSize = '0.75rem';
    arrow.textContent = '>';
    right.appendChild(arrow);

    row.appendChild(left);
    row.appendChild(right);
    return row;
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
    prev.className = 'btn btn-outline';
    prev.textContent = '← Anterior';
    prev.disabled = !data.previous;
    if (!data.previous) prev.classList.add('disabled');
    prev.addEventListener('click', () => changePage(-1));

    const label = document.createElement('span');
    label.className = 'text-muted';
    label.style.fontSize = '0.875rem';
    label.textContent = `Página ${currentPage}`;

    const next = document.createElement('button');
    next.className = 'btn btn-outline';
    next.textContent = 'Seguinte →';
    next.disabled = !data.next;
    if (!data.next) next.classList.add('disabled');
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
