'use strict';

let currentPage = 1;
let searchTimeout = null;

// Fallback local — será preferencialmente preenchido via
// CONFIG.EVIDENCE_BADGE_COLORS / CONFIG.EVIDENCE_ICONS (18 tipos, Wave 2a)
const TYPE_COLORS = {
    'MOBILE_DEVICE': 'blue',
    'COMPUTER': 'blue',
    'STORAGE_MEDIA': 'green',
    'VEHICLE': 'red',
    'OTHER_DIGITAL': 'default',
};

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    if (user && user.profile !== 'AGENT') {
        const btnNew = document.getElementById('btn-new-evidence');
        if (btnNew) btnNew.style.display = 'none';
        const fab = document.querySelector('.fab');
        if (fab) fab.style.display = 'none';
    }

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
    const sp = document.createElement('span');
    sp.className = 'spinner';
    wrap.appendChild(sp);
    return wrap;
}

function buildEmpty(message, opts = {}) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';

    if (opts.icon) {
        const ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        const svgIcon = Icons.element(opts.icon, { size: 22 });
        if (svgIcon) ic.appendChild(svgIcon);
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
        countEl.textContent = `${total} ${total === 1 ? 'item' : 'itens'}`;

        if (evidences.length === 0) {
            const message = search
                ? `Sem resultados para "${search}".`
                : 'Sem itens registados.';
            const opts = { icon: 'search' };
            const user = Auth.getUser();
            if (!search && user && user.profile === 'AGENT') {
                const a = document.createElement('a');
                a.href = '/evidences/new/';
                a.className = 'btn btn-primary mt-16';
                a.id = 'btn-empty-new';
                a.textContent = 'Registar primeiro item';
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
        container.replaceChildren(buildEmpty('Erro ao carregar itens. Tente novamente.', { danger: true }));
        console.error('Erro:', err);
    }
}

function renderEvidenceItem(ev) {
    const date = new Date(ev.timestamp_seizure).toLocaleDateString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const typeName = CONFIG.EVIDENCE_TYPES[ev.type] || ev.type;
    const color = (CONFIG.EVIDENCE_BADGE_COLORS && CONFIG.EVIDENCE_BADGE_COLORS[ev.type])
        || TYPE_COLORS[ev.type]
        || 'default';

    const row = document.createElement('div');
    row.className = 'list-item';
    row.style.cursor = 'pointer';
    // Rota canónica: /evidences/<id>/ (normalizada na Wave 2d).
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
    const typeIcon = Icons.forEvidenceElement(ev.type, { size: 12 });
    if (typeIcon) typeBadge.appendChild(typeIcon);
    const typeLabel = document.createElement('span');
    typeLabel.textContent = typeName;
    typeBadge.appendChild(typeLabel);
    badges.appendChild(typeBadge);

    // Badge adicional para sub-componentes — mostra o nome/código do pai,
    // nunca o ID cru (ISO/IEC 27037: cadeia deve ser legível).
    if (ev.parent_evidence) {
        const sub = document.createElement('span');
        sub.className = 'badge badge-default';
        const parentLabel = ev.parent_evidence_label || `Item ${ev.parent_evidence}`;
        sub.title = 'Componente integrante de ' + parentLabel;
        const truncated = parentLabel.length > 30
            ? parentLabel.substring(0, 30) + '…'
            : parentLabel;
        sub.textContent = `↳ ${truncated}`;
        badges.appendChild(sub);
    }

    if (ev.photo) {
        const b = document.createElement('span');
        b.className = 'badge badge-success';
        b.title = 'Com fotografia';
        b.setAttribute('aria-label', 'Com fotografia');
        const ic = Icons.element('shield', { size: 12 });
        if (ic) b.appendChild(ic);
        badges.appendChild(b);
    }
    if (ev.gps_lat && ev.gps_lon) {
        const b = document.createElement('span');
        b.className = 'badge badge-success';
        b.title = 'Com GPS';
        b.setAttribute('aria-label', 'Com GPS');
        const ic = Icons.element('map-pin', { size: 12 });
        if (ic) b.appendChild(ic);
        badges.appendChild(b);
    }

    const idTag = document.createElement('small');
    idTag.className = 'text-muted mono';
    idTag.textContent = ev.code || '';
    if (ev.code) badges.appendChild(idTag);

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
    const nuipc = ev.occurrence_number || ev.occurrence_code || '—';
    occLine.textContent = `Caso: ${nuipc}`;
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
