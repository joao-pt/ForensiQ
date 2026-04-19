'use strict';

/**
 * ForensiQ — Estatísticas (/estatisticas/).
 *
 * Consome /api/stats/. Renderiza KPIs totais e dois bar charts:
 * evidências por tipo + custódia por estado. AGENT vê só os seus;
 * staff/EXPERT veem totais globais (filtro é server-side).
 */

const EVIDENCE_BAR_COLORS = {
    DIGITAL_DEVICE: '',          // accent (default)
    STORAGE_MEDIA:  'info',
    DOCUMENT:       'warning',
    PHOTO:          'success',
    OTHER:          'neutral',
};

const CUSTODY_BAR_COLORS = {
    APREENDIDA:           'info',
    EM_TRANSPORTE:        'warning',
    RECEBIDA_LABORATORIO: '',
    EM_PERICIA:           '',
    CONCLUIDA:            'success',
    DEVOLVIDA:            'neutral',
    DESTRUIDA:            'danger',
};

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    const scope = document.getElementById('stats-scope');
    if (user) {
        const isScopedAgent = user.profile === 'AGENT' && !user.is_staff;
        scope.textContent = isScopedAgent
            ? 'Apenas ocorrências em que estás como agente responsável.'
            : 'Visão global da plataforma.';
    }

    try {
        const data = await API.get('/api/stats/');
        renderTotals(data);
        renderEvidenceByType(data.evidence_by_type || {});
        renderCustodyByState(data.custody_by_state || {});
    } catch (err) {
        scope.textContent = 'Erro ao carregar estatísticas.';
        scope.classList.add('text-danger');
    }
});

function renderTotals(data) {
    setText('kpi-occurrences', data.occurrences ?? 0);
    setText('kpi-evidences',   data.evidences ?? 0);
    setText('kpi-devices',     data.devices ?? 0);
    setText('kpi-custody',     data.custody_records ?? 0);
}

function renderEvidenceByType(map) {
    const container = document.getElementById('chart-evidence-type');
    renderBarChart(container, map, CONFIG.EVIDENCE_TYPES, EVIDENCE_BAR_COLORS);
}

function renderCustodyByState(map) {
    const container = document.getElementById('chart-custody-state');
    renderBarChart(container, map, CONFIG.CUSTODY_STATES, CUSTODY_BAR_COLORS);
}

function renderBarChart(container, data, labelsMap, colorMap) {
    container.replaceChildren();

    const entries = Object.entries(data).filter(([, n]) => n > 0);
    if (entries.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const t = document.createElement('div');
        t.className = 'empty-state-title';
        t.textContent = 'Sem dados';
        const p = document.createElement('p');
        p.textContent = 'Ainda não há registos nesta categoria.';
        empty.appendChild(t);
        empty.appendChild(p);
        container.appendChild(empty);
        return;
    }

    const max = Math.max(...entries.map(([, n]) => n));

    entries
        .sort((a, b) => b[1] - a[1])
        .forEach(([key, count]) => {
            const row = document.createElement('div');
            row.className = 'bar-row';

            const label = document.createElement('span');
            label.className = 'bar-label';
            label.textContent = labelsMap[key] || key;
            row.appendChild(label);

            const countEl = document.createElement('span');
            countEl.className = 'bar-count';
            countEl.textContent = count;
            row.appendChild(countEl);

            const track = document.createElement('div');
            track.className = 'bar-track';
            const fill = document.createElement('div');
            fill.className = 'bar-fill';
            const color = colorMap[key];
            if (color) fill.classList.add(color);
            fill.style.width = `${Math.round((count / max) * 100)}%`;
            track.appendChild(fill);
            row.appendChild(track);

            container.appendChild(row);
        });
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
}
