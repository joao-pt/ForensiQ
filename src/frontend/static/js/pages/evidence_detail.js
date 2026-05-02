'use strict';

/**
 * ForensiQ — Detalhe do item de prova (/evidences/<id>/).
 *
 * Carrega o item, sub-componentes integrantes (Evidence.sub_components),
 * dispositivos digitais legados (DigitalDevice) e o estado actual da
 * cadeia de custódia. Permite descarregar PDF individual e criar sub-
 * componentes directamente (com parent_evidence pré-preenchido).
 */

const evidenceId = parseInt(
    document.querySelector('[data-evidence-id]')?.dataset.evidenceId,
    10,
);

const STATE_LABELS = {
    APREENDIDA: 'Apreendida',
    EM_TRANSPORTE: 'Em transporte',
    RECEBIDA_LABORATORIO: 'Recebida no laboratório',
    EM_PERICIA: 'Em perícia',
    CONCLUIDA: 'Concluída',
    DEVOLVIDA: 'Devolvida',
    DESTRUIDA: 'Destruída',
};

const DEVICE_LABELS = {
    SMARTPHONE: 'Smartphone',     TABLET: 'Tablet',        LAPTOP: 'Portátil',
    DESKTOP:    'Desktop',        USB_DRIVE: 'Pen USB',    HARD_DRIVE: 'Disco rígido',
    SIM_CARD:   'Cartão SIM',     SD_CARD: 'Cartão SD',    CAMERA: 'Câmara',
    DRONE:      'Drone',          OTHER: 'Outro',
};

const CONDITION_LABELS = {
    FUNCTIONAL: 'Funcional', DAMAGED: 'Danificado', LOCKED: 'Bloqueado',
    OFF: 'Desligado',        UNKNOWN: 'Desconhecido',
};

const LEGACY_DEVICE_ICON = {
    SMARTPHONE: 'smartphone', TABLET: 'smartphone', LAPTOP: 'laptop',
    DESKTOP: 'laptop',        USB_DRIVE: 'hard-drive', HARD_DRIVE: 'disc',
    SIM_CARD: 'sim-card',     SD_CARD: 'sd-card', CAMERA: 'cctv',
    DRONE: 'drone',           OTHER: 'box',
};

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;
    if (!evidenceId) {
        showError('ID do item inválido.');
        return;
    }
    const pdfBtn = document.getElementById('btn-evidence-pdf');
    if (pdfBtn) pdfBtn.addEventListener('click', exportPdf);

    await loadEvidence();
});

async function loadEvidence() {
    try {
        const ev = await API.get(`${CONFIG.ENDPOINTS.EVIDENCES}${evidenceId}/`);
        renderEvidence(ev);
        renderSubComponents(ev.sub_components || []);

        const devicesData = await API.get(CONFIG.ENDPOINTS.DEVICES, {
            evidence: evidenceId,
            page_size: 50,
        });
        renderDevices(devicesData.results || []);

        const custodyData = await API.get(CONFIG.ENDPOINTS.CUSTODY, {
            evidence: evidenceId,
            page_size: 1,
        });
        const latest = (custodyData.results || [])[0];
        renderCurrentCustody(latest);
    } catch (err) {
        showError(err?.message || 'Erro ao carregar o item.');
    }
}

function renderEvidence(ev) {
    const typeLabel = CONFIG.EVIDENCE_TYPES[ev.type] || ev.type;

    // Title = código humano (ex.: ITM-2026-00001). Subtitle = tipo. Sem duplicar o código.
    const title = ev.code || `Item #${ev.id}`;
    document.getElementById('breadcrumb-title').textContent = title;
    document.getElementById('evidence-title').textContent = title;
    document.getElementById('evidence-subtitle').textContent = typeLabel;

    document.getElementById('meta-type').textContent = typeLabel;
    document.getElementById('meta-description').textContent = ev.description || '—';
    document.getElementById('meta-timestamp').textContent = formatDateTime(ev.timestamp_seizure);
    document.getElementById('meta-agent').textContent = ev.agent_name || ev.agent || '—';

    if (ev.serial_number) {
        document.getElementById('meta-serial-row').hidden = false;
        document.getElementById('meta-serial').textContent = ev.serial_number;
    }

    if (ev.gps_lat && ev.gps_lon) {
        document.getElementById('meta-gps-row').hidden = false;
        document.getElementById('meta-gps').textContent =
            `${parseFloat(ev.gps_lat).toFixed(5)}, ${parseFloat(ev.gps_lon).toFixed(5)}`;
    }

    const occLink = document.getElementById('meta-occurrence');
    if (ev.occurrence) {
        // NUIPC é o identificador reconhecido pelo utilizador.
        const nuipc = ev.occurrence_number || ev.occurrence_code || '';
        occLink.textContent = nuipc || `Caso ${ev.occurrence}`;
        occLink.href = `/occurrences/${ev.occurrence}/`;
    }

    if (ev.integrity_hash) {
        document.getElementById('integrity-card').hidden = false;
        document.getElementById('integrity-hash').textContent = ev.integrity_hash;
        document.getElementById('integrity-meta').textContent =
            'Calculado no momento do registo — verificável por qualquer perito independente.';
    }

    if (ev.photo) {
        document.getElementById('evidence-photo-card').hidden = false;
        document.getElementById('evidence-photo').src = ev.photo;
    }

    // Banner de pai (se for sub-componente) — sempre com rótulo legível,
    // nunca o ID cru (ISO/IEC 27037: rastreabilidade clara).
    if (ev.parent_evidence) {
        const banner = document.getElementById('parent-banner');
        const link = document.getElementById('parent-link');
        const parentLabel = ev.parent_evidence_label
            || `Item ${ev.parent_evidence}`;
        link.textContent = parentLabel;
        link.href = `/evidences/${ev.parent_evidence}/`;
        banner.hidden = false;
    }

    // Botão "Adicionar sub-componente" — apenas para AGENT e se houver
    // margem na profundidade da árvore. Servidor valida profundidade ≤ 3.
    const user = Auth.getUser();
    if (user && user.profile === 'AGENT') {
        const btn = document.getElementById('btn-add-sub');
        if (btn) {
            const params = new URLSearchParams({
                occurrence: ev.occurrence,
                parent: ev.id,
            });
            btn.href = `/evidences/new/?${params.toString()}`;
            btn.hidden = false;
        }
    }
}

function renderSubComponents(subs) {
    if (!subs || subs.length === 0) {
        // Secção só aparece se houver algo para mostrar OU se o botão estiver visível.
        const btn = document.getElementById('btn-add-sub');
        if (btn && !btn.hidden) {
            document.getElementById('sub-section').hidden = false;
            document.getElementById('sub-count').textContent = '0';
        }
        return;
    }

    document.getElementById('sub-section').hidden = false;
    document.getElementById('sub-count').textContent = subs.length;

    const container = document.getElementById('sub-container');
    container.replaceChildren();

    subs.forEach((sub) => {
        const row = document.createElement('a');
        row.className = 'device-row';
        row.href = `/evidences/${sub.id}/`;
        row.style.textDecoration = 'none';
        row.style.color = 'inherit';

        const iconWrap = document.createElement('div');
        iconWrap.className = 'device-row-icon';
        const icon = Icons.forEvidenceElement(sub.type, { size: 20 });
        if (icon) iconWrap.appendChild(icon);

        const body = document.createElement('div');
        body.className = 'device-row-body';

        const title = document.createElement('div');
        title.className = 'device-row-title';
        const typeLabel = CONFIG.EVIDENCE_TYPES[sub.type] || sub.type;
        const codePrefix = sub.code ? `${sub.code} · ` : '';
        title.textContent = `${codePrefix}${typeLabel}`;
        body.appendChild(title);

        if (sub.description) {
            const desc = document.createElement('div');
            desc.className = 'device-row-desc';
            desc.textContent = sub.description.length > 80
                ? sub.description.substring(0, 80) + '…'
                : sub.description;
            body.appendChild(desc);
        }

        const metaParts = [];
        if (sub.serial_number) metaParts.push(`S/N ${sub.serial_number}`);
        if (sub.integrity_hash) {
            metaParts.push('SHA-256 ' + sub.integrity_hash.substring(0, 12) + '…');
        }
        if (metaParts.length > 0) {
            const meta = document.createElement('div');
            meta.className = 'device-row-meta';
            meta.textContent = metaParts.join(' · ');
            body.appendChild(meta);
        }

        row.appendChild(iconWrap);
        row.appendChild(body);
        container.appendChild(row);
    });
}

function renderDevices(devices) {
    if (!devices.length) return;
    document.getElementById('devices-section').hidden = false;
    document.getElementById('device-count').textContent = devices.length;

    const container = document.getElementById('devices-container');
    container.replaceChildren();

    devices.forEach((d) => {
        const row = document.createElement('div');
        row.className = 'device-row';

        const iconWrap = document.createElement('div');
        iconWrap.className = 'device-row-icon';
        const icon = Icons.element(LEGACY_DEVICE_ICON[d.type] || 'box', { size: 20 });
        if (icon) iconWrap.appendChild(icon);

        const body = document.createElement('div');
        body.className = 'device-row-body';

        const title = document.createElement('div');
        title.className = 'device-row-title';
        const typeLabel = DEVICE_LABELS[d.type] || d.type;
        // Prefere "Marca Nome comercial (SKU)"; fallback para texto livre.
        const brand = d.brand || '';
        const commercial = d.commercial_name || '';
        const sku = d.model || '';
        let identity;
        if (commercial && sku) identity = `${brand} ${commercial} (${sku})`.trim();
        else if (commercial)   identity = `${brand} ${commercial}`.trim();
        else if (sku)          identity = `${brand} ${sku}`.trim();
        else                   identity = brand;
        title.textContent = identity ? `${identity} (${typeLabel})` : typeLabel;
        body.appendChild(title);

        const metaParts = [];
        if (d.serial_number) metaParts.push('S/N ' + d.serial_number);
        if (d.imei)          metaParts.push('IMEI ' + d.imei);
        metaParts.push(CONDITION_LABELS[d.condition] || d.condition);

        const meta = document.createElement('div');
        meta.className = 'device-row-meta';
        meta.textContent = metaParts.join(' · ');
        body.appendChild(meta);

        row.appendChild(iconWrap);
        row.appendChild(body);
        container.appendChild(row);
    });
}

function renderCurrentCustody(record) {
    const section = document.getElementById('custody-summary-section');
    const container = document.getElementById('custody-current');
    section.hidden = false;

    const iconWrap = document.createElement('div');
    iconWrap.className = 'custody-current-icon';
    const icon = Icons.element(record ? 'check' : 'alert', { size: 22 });
    if (icon) iconWrap.appendChild(icon);

    const body = document.createElement('div');
    body.className = 'custody-current-body';

    const state = document.createElement('div');
    state.className = 'custody-current-state';
    state.textContent = record
        ? STATE_LABELS[record.new_state] || record.new_state
        : 'Sem registo de custódia';
    body.appendChild(state);

    const meta = document.createElement('div');
    meta.className = 'custody-current-meta';
    meta.textContent = record
        ? `Atualizado em ${formatDateTime(record.timestamp)} · Sequência #${record.sequence}`
        : 'Cria a primeira transição na timeline.';
    body.appendChild(meta);

    container.replaceChildren(iconWrap, body);
}

async function exportPdf() {
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

function formatDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    return d.toLocaleString('pt-PT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function showError(message) {
    const subtitle = document.getElementById('evidence-subtitle');
    subtitle.textContent = message;
    subtitle.classList.add('text-danger');
}
