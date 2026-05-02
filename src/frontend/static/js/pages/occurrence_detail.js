'use strict';

/**
 * ForensiQ — Detalhe da ocorrência (hub central do caso).
 *
 * Carrega ocorrência + evidências raiz, custódia por evidência e mapa.
 * Sub-componentes (Evidence.parent_evidence) vêm no serializer aninhado,
 * sem round-trips adicionais.
 */

const occurrenceId = parseInt(
    document.querySelector('[data-occurrence-id]').dataset.occurrenceId,
    10,
);

const STATE_LABELS = {
    APREENDIDA:           'Apreendida',
    EM_TRANSPORTE:        'Em transporte',
    RECEBIDA_LABORATORIO: 'No laboratório',
    EM_PERICIA:           'Em perícia',
    CONCLUIDA:            'Concluída',
    DEVOLVIDA:            'Devolvida',
    DESTRUIDA:            'Destruída',
};

const CONDITION_LABELS = {
    FUNCTIONAL: 'Funcional', DAMAGED: 'Danificado', LOCKED: 'Bloqueado',
    OFF: 'Desligado',        UNKNOWN: 'Desconhecido',
};

// Mapa legado (DigitalDevice) → ícone. Mantido porque DigitalDevice coexiste
// com Evidence.sub_components enquanto não for consolidado.
const LEGACY_DEVICE_ICON = {
    SMARTPHONE: 'smartphone', TABLET: 'smartphone', LAPTOP: 'laptop',
    DESKTOP: 'laptop',        USB_DRIVE: 'hard-drive', HARD_DRIVE: 'disc',
    SIM_CARD: 'sim-card',     SD_CARD: 'sd-card', CAMERA: 'cctv',
    DRONE: 'drone',           OTHER: 'box',
};

let map = null;

// Caches partilhados pelo cardRenderer da DataTable — preenchidos no
// arranque (uma chamada por evidência) e relidos a cada render. Não
// usamos const + Object.freeze: o conteúdo é mutado quando os dados
// chegam.
let custodyByEvidence = {};
let devicesByEvidence = {};
let evidenceTable = null;

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    if (user && user.profile === 'AGENT') {
        const btnNew = document.getElementById('btn-new-evidence');
        if (btnNew) btnNew.hidden = false;
    }

    const btnPdf = document.getElementById('btn-occurrence-pdf');
    if (btnPdf) btnPdf.addEventListener('click', () => exportOccurrencePdf());

    await loadOccurrenceHub();
});

async function loadOccurrenceHub() {
    try {
        const occurrence = await API.get(
            `${CONFIG.ENDPOINTS.OCCURRENCES}${occurrenceId}/`,
        );
        renderCaseHeader(occurrence);

        const evidenceData = await API.get(CONFIG.ENDPOINTS.EVIDENCES, {
            occurrence: occurrenceId,
            page_size: 200,
        });
        const evidences = evidenceData.results || [];
        const evidenceIds = evidences.map((e) => e.id);

        const [custodyMap, devicesMap] = await Promise.all([
            loadCustodyForEvidences(evidenceIds),
            loadDevicesForEvidences(evidenceIds),
        ]);
        custodyByEvidence = custodyMap;
        devicesByEvidence = devicesMap;

        document.getElementById('evidence-count').textContent = evidences.length;
        mountEvidenceTable();
        renderCustodySummary(evidences, custodyByEvidence);
        renderDevices(evidences, devicesByEvidence);
        renderMap(occurrence, evidences);
    } catch (err) {
        console.error('Erro ao carregar ocorrência:', err);
        showCriticalError('Erro ao carregar dados. Verifique se a ocorrência existe.');
    }
}

function showCriticalError(message) {
    const container = document.getElementById('evidence-container');
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const p = document.createElement('p');
    p.className = 'text-danger';
    p.textContent = message;
    empty.appendChild(p);
    container.replaceChildren(empty);
}

async function loadCustodyForEvidences(evidenceIds) {
    const result = {};
    if (evidenceIds.length === 0) return result;
    await Promise.all(evidenceIds.map(async (id) => {
        try {
            const data = await API.get(
                `${CONFIG.ENDPOINTS.CUSTODY}evidence/${id}/timeline/`,
            );
            result[id] = Array.isArray(data) ? data : (data.results || []);
        } catch {
            result[id] = [];
        }
    }));
    return result;
}

async function loadDevicesForEvidences(evidenceIds) {
    const result = {};
    if (evidenceIds.length === 0) return result;
    await Promise.all(evidenceIds.map(async (id) => {
        try {
            const data = await API.get(CONFIG.ENDPOINTS.DEVICES, {
                evidence: id,
                page_size: 100,
            });
            result[id] = data.results || [];
        } catch {
            result[id] = [];
        }
    }));
    return result;
}

function renderCaseHeader(occ) {
    // NUIPC (ou número manual) é o identificador primário para utilizador;
    // o código interno (OCC-YYYY-NNNNN) só aparece como tag secundária.
    const primary = occ.number || occ.code || '';
    const secondary = occ.number && occ.code ? occ.code : '';
    // Page title leva o NUIPC (mais útil que "Caso" genérico — perito reconhece o NUIPC).
    document.getElementById('page-title').textContent = primary || 'Caso';
    document.getElementById('page-subtitle').textContent = secondary;
    document.getElementById('breadcrumb-title').textContent = primary;
    document.getElementById('case-number').textContent = primary;
    document.getElementById('case-description').textContent = occ.description || '—';

    const dt = new Date(occ.date_time).toLocaleString('pt-PT', {
        day: '2-digit', month: 'long', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    document.getElementById('case-datetime').textContent = dt;

    const agentEl = document.getElementById('case-agent');
    agentEl.replaceChildren();
    const strong = document.createElement('strong');
    strong.textContent = occ.agent_name || '';
    agentEl.appendChild(strong);

    const locationWrap = document.getElementById('case-location');
    const addressRow = document.getElementById('case-address-row');
    const gpsRow = document.getElementById('case-gps-row');
    const emptyRow = document.getElementById('case-location-empty');
    let hasAnyLocation = false;

    if (occ.address) {
        document.getElementById('case-address').textContent = occ.address;
        addressRow.hidden = false;
        hasAnyLocation = true;
    }
    if (occ.gps_lat && occ.gps_lon) {
        document.getElementById('case-gps').textContent =
            `${parseFloat(occ.gps_lat).toFixed(5)}, ${parseFloat(occ.gps_lon).toFixed(5)}`;
        gpsRow.hidden = false;
        hasAnyLocation = true;
    }
    if (!hasAnyLocation) {
        emptyRow.hidden = false;
    }
    locationWrap.hidden = false;
    document.getElementById('case-header').hidden = false;
}

// ---------------------------------------------------------------------------
// Mapa Leaflet — marcadores com SVG estático (sem emojis, CSP-safe)
// ---------------------------------------------------------------------------

function mapMarkerIcon({ variant }) {
    // CSP-safe: dimensões via CSSStyleDeclaration setter (não inline style attr),
    // resto via classes (.fq-map-marker / .fq-map-marker-{case,evidence}).
    // SVG construído via Icons.element (createElementNS, sem innerHTML).
    const isCase = variant === 'case';
    const size = isCase ? 32 : 24;
    const node = document.createElement('div');
    node.className = 'fq-map-marker' + (isCase ? ' fq-map-marker-case' : ' fq-map-marker-evidence');
    node.style.width = size + 'px';
    node.style.height = size + 'px';
    node.appendChild(Icons.element(isCase ? 'map-pin' : 'box', { size: isCase ? 16 : 14 }));
    return L.divIcon({
        className: '',
        html: node,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
    });
}

function buildMapPopup(title, subtitle) {
    const root = document.createElement('div');
    const s = document.createElement('strong');
    s.textContent = title;
    root.appendChild(s);
    if (subtitle) {
        root.appendChild(document.createElement('br'));
        root.appendChild(document.createTextNode(subtitle));
    }
    return root;
}

function renderMap(occ, evidences) {
    const hasOccGps = occ.gps_lat && occ.gps_lon;
    const evidencesWithGps = evidences.filter((e) => e.gps_lat && e.gps_lon);

    // Sem GPS: mapa fica escondido; a mensagem "Sem morada/coordenadas"
    // aparece em case-location-empty (renderCaseHeader).
    if (!hasOccGps && evidencesWithGps.length === 0) {
        return;
    }

    const mapEl = document.getElementById('case-map');
    mapEl.hidden = false;

    map = L.map('case-map', { center: [39.5, -8.0], zoom: 7, zoomControl: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap',
        maxZoom: 19,
    }).addTo(map);

    const markers = [];

    if (hasOccGps) {
        const m = L.marker(
            [parseFloat(occ.gps_lat), parseFloat(occ.gps_lon)],
            { icon: mapMarkerIcon({ variant: 'case' }) },
        ).addTo(map);
        m.bindPopup(buildMapPopup(occ.number, occ.address || 'Local da ocorrência'));
        markers.push(m);
    }

    evidencesWithGps.forEach((ev) => {
        const isDistinct = !hasOccGps
            || Math.abs(parseFloat(ev.gps_lat) - parseFloat(occ.gps_lat)) > 0.0001
            || Math.abs(parseFloat(ev.gps_lon) - parseFloat(occ.gps_lon)) > 0.0001;
        if (!isDistinct) return;

        const m = L.marker(
            [parseFloat(ev.gps_lat), parseFloat(ev.gps_lon)],
            { icon: mapMarkerIcon({ variant: 'evidence' }) },
        ).addTo(map);
        const popupTitle = ev.code
            ? `Item ${ev.code}`
            : (CONFIG.EVIDENCE_TYPES[ev.type] || ev.type);
        m.bindPopup(buildMapPopup(
            popupTitle,
            (ev.description || '').substring(0, 60),
        ));
        markers.push(m);
    });

    if (markers.length > 0) {
        const group = L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.3));
        if (markers.length === 1) map.setZoom(15);
    }
}

// ---------------------------------------------------------------------------
// Cartões de evidência
// ---------------------------------------------------------------------------

function makeBadge(cls, text, iconName) {
    const s = document.createElement('span');
    s.className = `badge badge-${cls}`;
    if (iconName) {
        const ic = Icons.element(iconName, { size: 12 });
        if (ic) s.appendChild(ic);
    }
    if (text) {
        const label = document.createElement('span');
        label.textContent = text;
        s.appendChild(label);
    }
    return s;
}

function buildEvidenceCard(ev, custodyRecords, devices) {
    const lastCustody = custodyRecords.length > 0
        ? custodyRecords[custodyRecords.length - 1]
        : null;
    const currentState = lastCustody ? lastCustody.new_state : null;
    const stateLabel = currentState ? STATE_LABELS[currentState] : 'Sem custódia';
    const stateClass = currentState ? `state-${currentState}` : 'state-none';
    const typeBadgeColor = CONFIG.EVIDENCE_BADGE_COLORS[ev.type] || 'default';
    const typeLabel = CONFIG.EVIDENCE_TYPES[ev.type] || ev.type;

    const dt = new Date(ev.timestamp_seizure).toLocaleString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const descFull = ev.description || '';
    const descTruncated = descFull.length > 100
        ? descFull.substring(0, 100) + '…'
        : (descFull || '—');

    const subCount = Array.isArray(ev.sub_components) ? ev.sub_components.length : 0;

    const card = document.createElement('div');
    card.className = 'evidence-card';
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => {
        window.location.href = `/evidences/${ev.id}/`;
    });

    // Cabeçalho
    const header = document.createElement('div');
    header.className = 'evidence-card-header';

    const title = document.createElement('span');
    title.className = 'evidence-card-title';
    const typeIcon = Icons.forEvidenceElement(ev.type, { size: 16 });
    if (typeIcon) title.appendChild(typeIcon);
    const titleLabel = document.createElement('span');
    const codePrefix = ev.code ? `${ev.code} · ` : '';
    titleLabel.textContent = `${codePrefix}${typeLabel}`;
    title.appendChild(titleLabel);
    header.appendChild(title);

    const stateBadge = document.createElement('span');
    stateBadge.className = `custody-badge ${stateClass}`;
    stateBadge.textContent = stateLabel;
    header.appendChild(stateBadge);
    card.appendChild(header);

    // Corpo
    const body = document.createElement('div');
    body.className = 'evidence-card-body';
    body.textContent = descTruncated;
    card.appendChild(body);

    // Footer
    const footer = document.createElement('div');
    footer.className = 'evidence-card-footer';

    const badges = document.createElement('div');
    badges.className = 'evidence-badges';
    const dateSpan = document.createElement('span');
    dateSpan.className = 'badge badge-neutral';
    dateSpan.textContent = dt;
    badges.appendChild(dateSpan);
    if (ev.gps_lat) badges.appendChild(makeBadge('success', 'GPS', 'map-pin'));
    if (ev.photo) badges.appendChild(makeBadge('success', 'Foto', 'shield'));
    if (devices.length > 0) {
        badges.appendChild(makeBadge('primary', String(devices.length), 'laptop'));
    }
    if (subCount > 0) {
        badges.appendChild(makeBadge('primary', `${subCount} sub`, 'link'));
    }
    footer.appendChild(badges);

    const actions = document.createElement('div');
    actions.className = 'evidence-actions';

    const custLink = document.createElement('a');
    custLink.href = `/evidences/${ev.id}/custody/`;
    custLink.className = 'btn btn-sm btn-ghost';
    const custIcon = Icons.element('link', { size: 14 });
    if (custIcon) custLink.appendChild(custIcon);
    const custLabel = document.createElement('span');
    custLabel.textContent = 'Custódia';
    custLink.appendChild(custLabel);
    custLink.addEventListener('click', (e) => e.stopPropagation());
    actions.appendChild(custLink);

    const pdfBtn = document.createElement('button');
    pdfBtn.type = 'button';
    pdfBtn.className = 'btn btn-sm btn-ghost';
    const pdfIcon = Icons.element('file-text', { size: 14 });
    if (pdfIcon) pdfBtn.appendChild(pdfIcon);
    const pdfLabel = document.createElement('span');
    pdfLabel.textContent = 'PDF';
    pdfBtn.appendChild(pdfLabel);
    pdfBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        exportEvidencePdf(ev.id);
    });
    actions.appendChild(pdfBtn);
    footer.appendChild(actions);
    card.appendChild(footer);

    // Chips de dispositivos legados (DigitalDevice)
    if (devices.length > 0) {
        const chipWrap = document.createElement('div');
        chipWrap.className = 'device-chip-row';
        devices.slice(0, 3).forEach((d) => {
            const chip = document.createElement('span');
            chip.className = 'device-chip';
            const chipIcon = Icons.element(
                LEGACY_DEVICE_ICON[d.type] || 'box',
                { size: 14 },
            );
            if (chipIcon) chip.appendChild(chipIcon);
            const label = [d.brand, d.model].filter(Boolean).join(' ') || d.type;
            const labelEl = document.createElement('span');
            labelEl.textContent = ` ${label}`;
            chip.appendChild(labelEl);
            chipWrap.appendChild(chip);
        });
        if (devices.length > 3) {
            const more = document.createElement('span');
            more.className = 'device-chip';
            more.textContent = `+${devices.length - 3}`;
            chipWrap.appendChild(more);
        }
        card.appendChild(chipWrap);
    }

    // Hash (integridade)
    const hashWrap = document.createElement('div');
    hashWrap.className = 'evidence-card-hash';
    const hashIcon = Icons.element('shield', { size: 12 });
    if (hashIcon) hashWrap.appendChild(hashIcon);
    const hashSpan = document.createElement('span');
    hashSpan.className = 'hash-inline';
    hashSpan.title = `SHA-256: ${ev.integrity_hash || ''}`;
    hashSpan.textContent = (ev.integrity_hash || '').substring(0, 16) + '…';
    hashWrap.appendChild(hashSpan);
    card.appendChild(hashWrap);

    return card;
}

function buildSubEvidenceCard(child) {
    // Card compacto para sub-componente (SIM, SD, etc.). Foca no essencial:
    // tipo + descrição + código/hash. Clicar abre o detalhe do filho.
    const typeLabel = CONFIG.EVIDENCE_TYPES[child.type] || child.type;
    const card = document.createElement('div');
    card.className = 'evidence-subcard';
    card.addEventListener('click', () => {
        window.location.href = `/evidences/${child.id}/`;
    });

    const title = document.createElement('span');
    title.className = 'evidence-subcard-title';
    const ic = Icons.forEvidenceElement(child.type, { size: 14 });
    if (ic) title.appendChild(ic);
    const label = document.createElement('span');
    const prefix = child.code ? `${child.code} · ` : '';
    label.textContent = `${prefix}${typeLabel}`;
    title.appendChild(label);
    card.appendChild(title);

    const body = document.createElement('span');
    body.className = 'evidence-subcard-body';
    const descFull = (child.description || '').trim();
    body.textContent = descFull.length > 60 ? descFull.substring(0, 60) + '…' : (descFull || '—');
    card.appendChild(body);

    return card;
}

function mountEvidenceTable() {
    if (evidenceTable) {
        evidenceTable.destroy();
        evidenceTable = null;
    }

    evidenceTable = DataTable.mount('#evidence-container', {
        endpoint: CONFIG.ENDPOINTS.EVIDENCES,
        defaultSort: '-timestamp_seizure',
        defaultPageSize: 50,
        rowHref: (row) => `/evidences/${row.id}/`,
        cardsContainerClass: 'evidence-grid',
        selectable: true,
        columns: [
            {
                key: 'code', label: 'Código',
                sortable: true, format: 'mono',
                width: '160px', sticky: true,
            },
            {
                key: 'type', label: 'Tipo',
                sortable: true, width: '180px',
                render: (raw) => document.createTextNode(
                    CONFIG.EVIDENCE_TYPES[raw] || raw || '—',
                ),
            },
            {
                key: 'description', label: 'Descrição',
                truncate: 90,
            },
            {
                key: 'parent_evidence_label', label: 'Pai',
                width: '160px', hideBelow: 1024,
                render: (raw) => document.createTextNode(raw || '—'),
            },
            {
                key: 'timestamp_seizure', label: 'Apreendido',
                sortable: true, format: 'date',
                width: '140px',
            },
            {
                key: 'agent_name', label: 'Agente',
                width: '160px', hideBelow: 1024,
            },
            {
                key: 'photo', label: 'Foto',
                width: '60px', align: 'center',
                render: (raw) => document.createTextNode(raw ? '✓' : '—'),
            },
            {
                key: 'gps_lat', label: 'GPS',
                width: '60px', align: 'center',
                format: 'badge-presence',
            },
        ],
        filters: [
            { key: 'type',        label: 'Tipo',          type: 'multi' },
            { key: 'date_after',  label: 'Desde',         type: 'date' },
            { key: 'date_before', label: 'Até',           type: 'date' },
            { key: 'has_gps',     label: 'Com GPS',       type: 'boolean' },
        ],
        bulkActions: [
            {
                id: 'cascade',
                label: 'Transitar selecção…',
                variant: 'primary',
                handler: cascadeTransitionPrompt,
            },
        ],
        cardRenderer: (row) => buildEvidenceCard(
            row,
            custodyByEvidence[row.id] || [],
            devicesByEvidence[row.id] || [],
        ),
        extraParams: () => ({ occurrence: occurrenceId }),
        onCount: (n) => {
            const el = document.getElementById('evidence-count');
            if (el) el.textContent = n;
        },
    });
}

async function cascadeTransitionPrompt(ids, controller) {
    if (ids.length === 0) return;
    const newState = window.prompt(
        `Transitar ${ids.length} item${ids.length !== 1 ? 's' : ''} para que estado?\n\n` +
        Object.entries(CONFIG.CUSTODY_STATES)
            .map(([k, v]) => `  ${k}  →  ${v}`)
            .join('\n'),
        'EM_TRANSPORTE',
    );
    if (!newState) return;
    if (!CONFIG.CUSTODY_STATES[newState]) {
        alert(`Estado "${newState}" não é válido.`);
        return;
    }
    try {
        await API.post(`${CONFIG.ENDPOINTS.CUSTODY}cascade/`, {
            evidence_ids: ids,
            new_state: newState,
            observations: `Transição em massa via tabela (${ids.length} itens).`,
        });
        if (typeof Toast !== 'undefined') {
            Toast.show(`${ids.length} itens transitados para ${CONFIG.CUSTODY_STATES[newState]}.`, 'success');
        }
        controller.clearSelection();
        controller.reload();
        // Recarregar custódia (estado mudou).
        const evList = controller.getState().results || [];
        const map = await loadCustodyForEvidences(evList.map((e) => e.id));
        Object.assign(custodyByEvidence, map);
        controller.refreshRender();
    } catch (err) {
        alert('Erro na transição em massa: ' + (err.message || err));
    }
}

// Mantemos a função antiga (nunca chamada agora) caso volte a ser útil.
// eslint-disable-next-line no-unused-vars
function renderEvidences(evidences, custodyMap, devicesMap) {
    const container = document.getElementById('evidence-container');
    document.getElementById('evidence-count').textContent = evidences.length;

    const childrenByParent = {};
    evidences.forEach((e) => {
        if (e.parent_evidence) {
            if (!childrenByParent[e.parent_evidence]) {
                childrenByParent[e.parent_evidence] = [];
            }
            childrenByParent[e.parent_evidence].push(e);
        }
    });

    const rootEvidences = evidences.filter((e) => !e.parent_evidence);

    if (rootEvidences.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const ic = document.createElement('div');
        ic.className = 'empty-state-icon';
        const icon = Icons.element('folder', { size: 22 });
        if (icon) ic.appendChild(icon);
        empty.appendChild(ic);
        const p = document.createElement('p');
        p.textContent = 'Sem itens registados nesta ocorrência.';
        empty.appendChild(p);
        container.replaceChildren(empty);
        return;
    }

    container.replaceChildren();
    rootEvidences.forEach((ev) => {
        const custody = custodyMap[ev.id] || [];
        const devices = devicesMap[ev.id] || [];

        const group = document.createElement('div');
        group.className = 'evidence-group';
        group.appendChild(buildEvidenceCard(ev, custody, devices));

        const children = childrenByParent[ev.id] || [];
        if (children.length > 0) {
            const subWrap = document.createElement('div');
            subWrap.className = 'evidence-sub-wrap';
            const subLabel = document.createElement('div');
            subLabel.className = 'evidence-sub-label';
            subLabel.textContent = `Componentes integrantes (${children.length})`;
            subWrap.appendChild(subLabel);
            children.forEach((child) => {
                subWrap.appendChild(buildSubEvidenceCard(child));
            });
            group.appendChild(subWrap);
        }
        container.appendChild(group);
    });
}

function buildStat(count, label, color) {
    const stat = document.createElement('div');
    stat.className = 'custody-stat';
    const c = document.createElement('div');
    c.className = 'custody-stat-count';
    if (color) c.style.color = color;
    c.textContent = count;
    stat.appendChild(c);
    const l = document.createElement('div');
    l.className = 'custody-stat-label';
    l.textContent = label;
    stat.appendChild(l);
    return stat;
}

function renderCustodySummary(evidences, custodyMap) {
    if (evidences.length === 0) return;

    const stateCounts = {};
    let withoutCustody = 0;

    evidences.forEach((ev) => {
        const records = custodyMap[ev.id] || [];
        if (records.length === 0) {
            withoutCustody++;
            return;
        }
        const lastState = records[records.length - 1].new_state;
        stateCounts[lastState] = (stateCounts[lastState] || 0) + 1;
    });

    const hasData = Object.keys(stateCounts).length > 0 || withoutCustody > 0;
    if (!hasData) return;

    const container = document.getElementById('custody-summary');
    const section = document.getElementById('custody-summary-section');
    section.hidden = false;
    container.replaceChildren();

    container.appendChild(buildStat(evidences.length, 'Total', 'var(--accent)'));

    Object.entries(stateCounts).forEach(([state, count]) => {
        container.appendChild(buildStat(count, STATE_LABELS[state] || state));
    });

    if (withoutCustody > 0) {
        container.appendChild(
            buildStat(withoutCustody, 'Sem custódia', 'var(--text-muted)'),
        );
    }
}

function buildDeviceCard(d) {
    const iconName = LEGACY_DEVICE_ICON[d.type] || 'box';
    const name = [d.brand, d.model].filter(Boolean).join(' ') || d.type;
    const condition = CONDITION_LABELS[d.condition] || d.condition;
    const conditionColor = d.condition === 'FUNCTIONAL' ? 'success'
        : d.condition === 'DAMAGED' ? 'danger'
        : d.condition === 'LOCKED' ? 'warning'
        : 'neutral';

    const card = document.createElement('div');
    card.className = 'evidence-card';
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => {
        window.location.href = `/evidences/${d.evidenceId}/`;
    });

    const header = document.createElement('div');
    header.className = 'evidence-card-header';
    const title = document.createElement('span');
    title.className = 'evidence-card-title';
    const ic = Icons.element(iconName, { size: 16 });
    if (ic) title.appendChild(ic);
    const titleLabel = document.createElement('span');
    titleLabel.textContent = ` ${name}`;
    title.appendChild(titleLabel);
    header.appendChild(title);
    header.appendChild(makeBadge(conditionColor, condition));
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'evidence-card-body';
    const parentLabel = d.evidenceCode
        ? `Item ${d.evidenceCode}`
        : (d.evidenceDesc || 'Item');
    const parts = [parentLabel];
    if (d.serial_number) parts.push(`S/N ${d.serial_number}`);
    if (d.imei) parts.push(`IMEI ${d.imei}`);
    body.textContent = parts.join(' · ');
    card.appendChild(body);

    if (d.notes) {
        const notes = document.createElement('div');
        notes.className = 'device-notes';
        notes.textContent = d.notes;
        card.appendChild(notes);
    }
    return card;
}

function renderDevices(evidences, devicesMap) {
    const allDevices = [];
    evidences.forEach((ev) => {
        (devicesMap[ev.id] || []).forEach((d) => {
            allDevices.push({
                ...d,
                evidenceId: ev.id,
                evidenceCode: ev.code,
                evidenceDesc: ev.description,
            });
        });
    });

    if (allDevices.length === 0) return;

    const section = document.getElementById('devices-section');
    const container = document.getElementById('devices-container');
    section.hidden = false;
    document.getElementById('device-count').textContent = allDevices.length;

    container.replaceChildren();
    allDevices.forEach((d) => container.appendChild(buildDeviceCard(d)));
}

// ---------------------------------------------------------------------------
// Exportação de PDF
// ---------------------------------------------------------------------------

async function exportEvidencePdf(evidenceId) {
    try {
        Toast.info('A gerar PDF…');
        const response = await fetch(
            `${CONFIG.ENDPOINTS.EVIDENCES}${evidenceId}/pdf/`,
            { credentials: 'include' },
        );
        if (!response.ok) throw new Error(`Erro ${response.status}`);

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ForensiQ_Item_${evidenceId}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        Toast.success('PDF descarregado.');
    } catch (err) {
        Toast.error('Erro ao gerar PDF.');
        console.error(err);
    }
}

async function exportOccurrencePdf() {
    try {
        Toast.info('A gerar PDF do caso…');
        const response = await fetch(
            `${CONFIG.ENDPOINTS.OCCURRENCES}${occurrenceId}/pdf/`,
            { credentials: 'include' },
        );
        if (!response.ok) throw new Error(`Erro ${response.status}`);

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ForensiQ_Caso_${String(occurrenceId).padStart(4, '0')}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        Toast.success('PDF descarregado.');
    } catch (err) {
        Toast.error('Erro ao gerar PDF.');
        console.error(err);
    }
}
