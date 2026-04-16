'use strict';

const occurrenceId = parseInt(
    document.querySelector('[data-occurrence-id]').dataset.occurrenceId,
    10
);

const TYPE_LABELS = {
    DIGITAL_DEVICE: 'Dispositivo Digital',
    DOCUMENT:       'Documento',
    STORAGE_MEDIA:  'Suporte de Armazenamento',
    PHOTO:          'Fotografia',
    OTHER:          'Outro',
};
const TYPE_COLORS = {
    DIGITAL_DEVICE: 'blue',
    DOCUMENT:       'orange',
    STORAGE_MEDIA:  'green',
    PHOTO:          'red',
    OTHER:          'default',
};

const STATE_LABELS = {
    APREENDIDA:           'Apreendida',
    EM_TRANSPORTE:        'Em Transporte',
    RECEBIDA_LABORATORIO: 'No Laboratório',
    EM_PERICIA:           'Em Perícia',
    CONCLUIDA:            'Concluída',
    DEVOLVIDA:            'Devolvida',
    DESTRUIDA:            'Destruída',
};
const STATE_ICONS = {
    APREENDIDA: '\u{1F512}', EM_TRANSPORTE: '\u{1F690}', RECEBIDA_LABORATORIO: '\u{1F3DB}\uFE0F',
    EM_PERICIA: '\u{1F52C}', CONCLUIDA: '\u2705', DEVOLVIDA: '\u21A9\uFE0F', DESTRUIDA: '\u{1F5D1}\uFE0F',
};

const DEVICE_ICONS = {
    SMARTPHONE: '\u{1F4F1}', TABLET: '\u{1F4F1}', LAPTOP: '\u{1F4BB}', DESKTOP: '\u{1F5A5}\uFE0F',
    USB_DRIVE: '\u{1F4BE}', HARD_DRIVE: '\u{1F4BF}', SIM_CARD: '\u{1F4F6}', SD_CARD: '\u{1F4BE}',
    CAMERA: '\u{1F4F7}', DRONE: '\u{1F6E9}\uFE0F', OTHER: '\u{1F527}',
};
const CONDITION_LABELS = {
    FUNCTIONAL: 'Funcional', DAMAGED: 'Danificado', LOCKED: 'Bloqueado',
    OFF: 'Desligado', UNKNOWN: 'Desconhecido',
};

let map = null;

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    if (user) {
        document.getElementById('navbar-user').textContent = user.first_name || user.username;
        if (user.profile === 'AGENT') {
            document.getElementById('btn-new-evidence').style.display = '';
        }
    }
    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    await loadOccurrenceHub();
});

async function loadOccurrenceHub() {
    try {
        const occurrence = await API.get(`${CONFIG.ENDPOINTS.OCCURRENCES}${occurrenceId}/`);
        renderCaseHeader(occurrence);

        const evidenceData = await API.get(CONFIG.ENDPOINTS.EVIDENCES, {
            occurrence: occurrenceId,
            page_size: 200,
        });
        const evidences = evidenceData.results || [];
        const evidenceIds = evidences.map(e => e.id);

        const [custodyByEvidence, devicesByEvidence] = await Promise.all([
            loadCustodyForEvidences(evidenceIds),
            loadDevicesForEvidences(evidenceIds),
        ]);

        renderEvidences(evidences, custodyByEvidence, devicesByEvidence);
        renderCustodySummary(evidences, custodyByEvidence);
        renderDevices(evidences, devicesByEvidence);
        renderMap(occurrence, evidences);

    } catch (err) {
        console.error('Erro ao carregar ocorrência:', err);
        const container = document.getElementById('evidence-container');
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const p = document.createElement('p');
        p.className = 'text-danger';
        p.textContent = 'Erro ao carregar dados. Verifique se a ocorrência existe.';
        empty.appendChild(p);
        container.replaceChildren(empty);
    }
}

async function loadCustodyForEvidences(evidenceIds) {
    const result = {};
    if (evidenceIds.length === 0) return result;
    const promises = evidenceIds.map(async (id) => {
        try {
            const data = await API.get(`${CONFIG.ENDPOINTS.CUSTODY}evidence/${id}/timeline/`);
            result[id] = Array.isArray(data) ? data : (data.results || []);
        } catch {
            result[id] = [];
        }
    });
    await Promise.all(promises);
    return result;
}

async function loadDevicesForEvidences(evidenceIds) {
    const result = {};
    if (evidenceIds.length === 0) return result;
    const promises = evidenceIds.map(async (id) => {
        try {
            const data = await API.get(CONFIG.ENDPOINTS.DEVICES, { evidence: id, page_size: 100 });
            result[id] = data.results || [];
        } catch {
            result[id] = [];
        }
    });
    await Promise.all(promises);
    return result;
}

function renderCaseHeader(occ) {
    document.getElementById('page-subtitle').textContent = occ.number;
    document.getElementById('case-number').textContent = occ.number;
    document.getElementById('case-description').textContent = occ.description || '\u2014';

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

    if (occ.address) {
        document.getElementById('case-address').textContent = occ.address;
        document.getElementById('case-address-item').style.display = '';
    }
    if (occ.gps_lat && occ.gps_lon) {
        document.getElementById('case-gps').textContent =
            `${parseFloat(occ.gps_lat).toFixed(5)}, ${parseFloat(occ.gps_lon).toFixed(5)}`;
        document.getElementById('case-gps-item').style.display = '';
    }
    document.getElementById('case-header').style.display = '';
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
    const evidencesWithGps = evidences.filter(e => e.gps_lat && e.gps_lon);

    if (!hasOccGps && evidencesWithGps.length === 0) {
        document.getElementById('case-map-empty').style.display = '';
        return;
    }

    const mapEl = document.getElementById('case-map');
    mapEl.style.display = '';

    map = L.map('case-map', {
        center: [39.5, -8.0],
        zoom: 7,
        zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap',
        maxZoom: 19,
    }).addTo(map);

    const markers = [];

    if (hasOccGps) {
        const occMarker = L.marker(
            [parseFloat(occ.gps_lat), parseFloat(occ.gps_lon)],
            {
                icon: L.divIcon({
                    className: '',
                    html: '<div style="background:#1a237e;color:#fff;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;box-shadow:0 2px 6px rgba(0,0,0,0.3);border:2px solid #fff;">\u{1F4CD}</div>',
                    iconSize: [32, 32],
                    iconAnchor: [16, 16],
                }),
            }
        ).addTo(map);
        occMarker.bindPopup(buildMapPopup(occ.number, occ.address || 'Local da ocorrência'));
        markers.push(occMarker);
    }

    evidencesWithGps.forEach(ev => {
        const isDistinct = !hasOccGps ||
            Math.abs(parseFloat(ev.gps_lat) - parseFloat(occ.gps_lat)) > 0.0001 ||
            Math.abs(parseFloat(ev.gps_lon) - parseFloat(occ.gps_lon)) > 0.0001;

        if (isDistinct) {
            const evMarker = L.marker(
                [parseFloat(ev.gps_lat), parseFloat(ev.gps_lon)],
                {
                    icon: L.divIcon({
                        className: '',
                        html: '<div style="background:#ff6f00;color:#fff;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;box-shadow:0 2px 4px rgba(0,0,0,0.3);border:2px solid #fff;">\u{1F4CB}</div>',
                        iconSize: [24, 24],
                        iconAnchor: [12, 12],
                    }),
                }
            ).addTo(map);
            evMarker.bindPopup(buildMapPopup(`Evidência #${ev.id}`, (ev.description || '').substring(0, 60)));
            markers.push(evMarker);
        }
    });

    if (markers.length > 0) {
        const group = L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.3));
        if (markers.length === 1) {
            map.setZoom(15);
        }
    }
}

function makeBadge(cls, text) {
    const s = document.createElement('span');
    s.className = `badge badge-${cls}`;
    s.textContent = text;
    return s;
}

function buildEvidenceCard(ev, custodyRecords, devices) {
    const lastCustody = custodyRecords.length > 0 ? custodyRecords[custodyRecords.length - 1] : null;
    const currentState = lastCustody ? lastCustody.new_state : null;
    const stateLabel = currentState ? STATE_LABELS[currentState] : 'Sem custódia';
    const stateIcon = currentState ? STATE_ICONS[currentState] : '\u2014';
    const stateClass = currentState ? `state-${currentState}` : 'state-none';
    const typeBadgeColor = TYPE_COLORS[ev.type] || 'default';
    const typeLabel = TYPE_LABELS[ev.type] || ev.type;

    const dt = new Date(ev.timestamp_seizure).toLocaleString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
    const descFull = ev.description || '';
    const descTruncated = descFull.length > 100 ? descFull.substring(0, 100) + '\u2026' : (descFull || '\u2014');

    const card = document.createElement('div');
    card.className = 'evidence-card';
    card.style.cursor = 'pointer';
    card.addEventListener('click', () => {
        window.location.href = `/evidence/${ev.id}/custody/`;
    });

    const header = document.createElement('div');
    header.className = 'evidence-card-header';
    const title = document.createElement('span');
    title.className = 'evidence-card-title';
    title.textContent = `#${ev.id} \u2014 ${typeLabel}`;
    header.appendChild(title);
    const stateBadge = document.createElement('span');
    stateBadge.className = `custody-badge ${stateClass}`;
    stateBadge.textContent = `${stateIcon} ${stateLabel}`;
    header.appendChild(stateBadge);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'evidence-card-body';
    body.textContent = descTruncated;
    card.appendChild(body);

    const footer = document.createElement('div');
    footer.className = 'evidence-card-footer';

    const badges = document.createElement('div');
    badges.className = 'evidence-badges';
    badges.appendChild(makeBadge(typeBadgeColor, typeLabel));
    badges.appendChild(makeBadge('neutral', `\u{1F551} ${dt}`));
    if (ev.gps_lat) badges.appendChild(makeBadge('success', '\u{1F4CD} GPS'));
    if (ev.photo) badges.appendChild(makeBadge('success', '\u{1F4F7} Foto'));
    if (devices.length > 0) badges.appendChild(makeBadge('primary', `\u{1F4BB} ${devices.length}`));
    footer.appendChild(badges);

    const actions = document.createElement('div');
    actions.className = 'evidence-actions';
    const custLink = document.createElement('a');
    custLink.href = `/evidence/${ev.id}/custody/`;
    custLink.className = 'btn btn-sm btn-outline';
    custLink.textContent = '\u{1F4DC} Custódia';
    custLink.addEventListener('click', (e) => e.stopPropagation());
    actions.appendChild(custLink);

    const pdfBtn = document.createElement('button');
    pdfBtn.className = 'btn btn-sm btn-outline';
    pdfBtn.textContent = '\u{1F4C4} PDF';
    pdfBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        exportPDF(ev.id);
    });
    actions.appendChild(pdfBtn);
    footer.appendChild(actions);
    card.appendChild(footer);

    if (devices.length > 0) {
        const chipWrap = document.createElement('div');
        chipWrap.style.marginTop = '8px';
        devices.slice(0, 3).forEach(d => {
            const icon = DEVICE_ICONS[d.type] || '\u{1F527}';
            const label = [d.brand, d.model].filter(Boolean).join(' ') || d.type;
            const chip = document.createElement('span');
            chip.className = 'device-chip';
            const iconEl = document.createElement('span');
            iconEl.className = 'device-chip-icon';
            iconEl.textContent = icon;
            chip.appendChild(iconEl);
            chip.appendChild(document.createTextNode(` ${label}`));
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

    const hashWrap = document.createElement('div');
    hashWrap.style.marginTop = '6px';
    const hashSpan = document.createElement('span');
    hashSpan.className = 'hash-inline';
    hashSpan.title = `SHA-256: ${ev.integrity_hash || ''}`;
    hashSpan.textContent = `\u{1F510} ${(ev.integrity_hash || '').substring(0, 16)}\u2026`;
    hashWrap.appendChild(hashSpan);
    card.appendChild(hashWrap);

    return card;
}

function renderEvidences(evidences, custodyMap, devicesMap) {
    const container = document.getElementById('evidence-container');
    document.getElementById('evidence-count').textContent = evidences.length;

    if (evidences.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const icon = document.createElement('div');
        icon.className = 'empty-state-icon';
        icon.textContent = '\u{1F4CB}';
        empty.appendChild(icon);
        const p = document.createElement('p');
        p.textContent = 'Sem evidências registadas nesta ocorrência.';
        empty.appendChild(p);
        container.replaceChildren(empty);
        return;
    }

    container.replaceChildren();
    evidences.forEach(ev => {
        const custody = custodyMap[ev.id] || [];
        const devices = devicesMap[ev.id] || [];
        container.appendChild(buildEvidenceCard(ev, custody, devices));
    });
}

function buildStat(count, label, color) {
    const stat = document.createElement('div');
    stat.className = 'custody-stat';
    const cEl = document.createElement('div');
    cEl.className = 'custody-stat-count';
    if (color) cEl.style.color = color;
    cEl.textContent = count;
    stat.appendChild(cEl);
    const lEl = document.createElement('div');
    lEl.className = 'custody-stat-label';
    lEl.textContent = label;
    stat.appendChild(lEl);
    return stat;
}

function renderCustodySummary(evidences, custodyMap) {
    if (evidences.length === 0) return;

    const stateCounts = {};
    let withoutCustody = 0;

    evidences.forEach(ev => {
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
    section.style.display = '';
    container.replaceChildren();

    container.appendChild(buildStat(evidences.length, 'Total', 'var(--primary)'));

    Object.entries(stateCounts).forEach(([state, count]) => {
        const label = STATE_LABELS[state] || state;
        const icon = STATE_ICONS[state] || '\u25CF';
        container.appendChild(buildStat(`${icon} ${count}`, label));
    });

    if (withoutCustody > 0) {
        container.appendChild(buildStat(`\u26A0\uFE0F ${withoutCustody}`, 'Sem custódia', 'var(--text-light)'));
    }
}

function buildDeviceCard(d) {
    const icon = DEVICE_ICONS[d.type] || '\u{1F527}';
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
        window.location.href = `/evidence/${d.evidenceId}/custody/`;
    });

    const header = document.createElement('div');
    header.className = 'evidence-card-header';
    const title = document.createElement('span');
    title.className = 'evidence-card-title';
    title.textContent = `${icon} ${name}`;
    header.appendChild(title);
    header.appendChild(makeBadge(conditionColor, condition));
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'evidence-card-body';
    const parts = [`Evidência #${d.evidenceId}`];
    if (d.serial_number) parts.push(`S/N: ${d.serial_number}`);
    if (d.imei) parts.push(`IMEI: ${d.imei}`);
    body.textContent = parts.join(' \u00B7 ');
    card.appendChild(body);

    if (d.notes) {
        const notes = document.createElement('div');
        notes.style.fontSize = '0.8125rem';
        notes.style.color = 'var(--text-light)';
        notes.style.fontStyle = 'italic';
        notes.textContent = `"${d.notes}"`;
        card.appendChild(notes);
    }
    return card;
}

function renderDevices(evidences, devicesMap) {
    const allDevices = [];
    evidences.forEach(ev => {
        (devicesMap[ev.id] || []).forEach(d => {
            allDevices.push({ ...d, evidenceId: ev.id, evidenceDesc: ev.description });
        });
    });

    if (allDevices.length === 0) return;

    const section = document.getElementById('devices-section');
    const container = document.getElementById('devices-container');
    section.style.display = '';
    document.getElementById('device-count').textContent = allDevices.length;

    container.replaceChildren();
    allDevices.forEach(d => container.appendChild(buildDeviceCard(d)));
}

async function exportPDF(evidenceId) {
    try {
        Toast.info('A gerar PDF...');
        const response = await fetch(`${CONFIG.ENDPOINTS.EVIDENCES}${evidenceId}/pdf/`, {
            credentials: 'include',
        });
        if (!response.ok) throw new Error(`Erro ${response.status}`);

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ForensiQ_Evidencia_${String(evidenceId).padStart(4, '0')}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        Toast.success('PDF descarregado.');
    } catch (err) {
        Toast.error('Erro ao gerar PDF.');
        console.error(err);
    }
}
