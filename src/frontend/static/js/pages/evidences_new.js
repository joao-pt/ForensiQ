'use strict';

/**
 * ForensiQ — Wizard de nova evidência (Wave 2d).
 *
 * Suporta:
 *  - 18 tipos de evidência agrupados por família (CONFIG.EVIDENCE_TYPE_GROUPS).
 *  - Campos type-specific dinâmicos serializados para type_specific_data (JSON).
 *  - Botão "Consultar IMEI" (chama /api/evidences/lookup/imei/<imei>/).
 *  - Botão "Abrir vindecoder.eu" (chama /api/evidences/lookup/vin/<vin>/).
 *  - Fluxo de sub-componentes com parent_evidence e profundidade máxima 3.
 */

var selectedPhoto = null;
var wizard = null;
var createdEvidenceId = null;
var createdEvidenceType = null;

document.addEventListener('DOMContentLoaded', async function () {
    var authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    var user = Auth.getUser();
    if (user) {
        var navUser = document.getElementById('navbar-user');
        if (navUser) navUser.textContent = user.first_name || user.username;

        if (user.profile !== 'AGENT') {
            Toast.show('Sem permissão para registar itens.', 'error');
            setTimeout(function () { window.location.href = '/evidences/'; }, 1500);
            return;
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    setDefaultTimestamp();
    populateTypeSelect();
    loadOccurrences();
    readParentFromUrl();
    setupTypeChange();
    setupPhotoCapture();
    captureGPS();
    document.getElementById('btn-gps').addEventListener('click', captureGPS);

    initWizard();
    initSubPromptHandlers();
});

/* ---- Type select (optgroups) ---- */

function populateTypeSelect() {
    var select = document.getElementById('type');
    // Mantém a primeira opção vazia e remove o resto (caso existam leftovers).
    while (select.options.length > 1) {
        select.remove(1);
    }

    CONFIG.EVIDENCE_TYPE_GROUPS.forEach(function (group) {
        var og = document.createElement('optgroup');
        og.label = group.label;
        group.types.forEach(function (t) {
            var opt = document.createElement('option');
            opt.value = t;
            // <option> não permite SVG — texto puro; ícones aparecem na UI que consome a selecção.
            opt.textContent = CONFIG.EVIDENCE_TYPES[t] || t;
            og.appendChild(opt);
        });
        select.appendChild(og);
    });
}

/* ---- Sub-componente: ler parent da URL ---- */

async function readParentFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var parentId = params.get('parent');
    if (!parentId) return;

    var parentHidden = document.getElementById('parent_evidence');
    parentHidden.value = parentId;

    var crumb = document.getElementById('wizard-breadcrumb-current');
    if (crumb) crumb.textContent = 'Sub-componente de #' + parentId;

    // Mostra info-box e tenta carregar dados do parent para breadcrumb
    var info = document.getElementById('parent-info');
    var bc = document.getElementById('parent-breadcrumb');
    info.classList.remove('hidden');
    bc.textContent = '#' + parentId + ' → [novo componente]';

    try {
        var parent = await API.get(CONFIG.ENDPOINTS.EVIDENCES + parentId + '/');
        if (parent) {
            document.getElementById('parent_type').value = parent.type || '';
            var depth = computeDepth(parent);
            document.getElementById('parent_depth').value = String(depth);

            var typeLabel = CONFIG.EVIDENCE_TYPES[parent.type] || parent.type;
            var snippet = (parent.description || '').substring(0, 50);
            bc.textContent = 'Ocorrência #' + (parent.occurrence || '?')
                + ' → ' + typeLabel + ' #' + parent.id
                + (snippet ? ' (' + snippet + ')' : '')
                + ' → [novo]';

            // Pré-selecciona a ocorrência
            var occSelect = document.getElementById('occurrence');
            if (parent.occurrence) {
                occSelect.value = String(parent.occurrence);
                occSelect.disabled = true;
            }

            // Filtra o select de tipos para sugerir sub-componentes típicos
            filterTypeSuggestions(parent.type);
        }
    } catch (err) {
        console.warn('Não foi possível carregar o evidence-pai:', err);
    }
}

function computeDepth(ev) {
    // Heurística client-side: contamos saltos parent_evidence. Se o backend
    // incluir um campo `depth`/`tree_depth`, preferimos esse.
    if (typeof ev.tree_depth === 'number') return ev.tree_depth;
    if (typeof ev.depth === 'number') return ev.depth;
    return ev.parent_evidence ? 1 : 0;
}

function filterTypeSuggestions(parentType) {
    var suggestions = (CONFIG.EVIDENCE_CHILD_SUGGESTIONS || {})[parentType];
    if (!suggestions || !suggestions.length) return;

    var select = document.getElementById('type');
    // Marca sugestões com um prefixo visual nas labels (sem bloquear outros).
    Array.from(select.querySelectorAll('option')).forEach(function (opt) {
        if (!opt.value) return;
        if (suggestions.indexOf(opt.value) !== -1) {
            var marker = '[sugerido] ';
            if (opt.textContent.indexOf(marker) !== 0) {
                opt.textContent = marker + opt.textContent;
            }
        }
    });
    var hint = document.getElementById('type-hint');
    if (hint) {
        hint.textContent = 'Tipos marcados com "[sugerido]" são típicos para este pai — podes escolher qualquer outro.';
    }
}

/* ---- Campos específicos do tipo ---- */

function setupTypeChange() {
    var select = document.getElementById('type');
    select.addEventListener('change', function () {
        clearError('type-error');
        renderTypeSpecificFields(select.value);
    });
}

function renderTypeSpecificFields(type) {
    var container = document.getElementById('type-specific-fields');
    container.replaceChildren();
    if (!type) return;

    switch (type) {
        case 'MOBILE_DEVICE':
            container.appendChild(buildImeiGroup());
            container.appendChild(buildTextField('brand', 'Marca', 'Ex.: Apple, Samsung'));
            container.appendChild(buildTextField('model', 'Modelo', 'Ex.: iPhone 14 Pro'));
            container.appendChild(buildTextField('os', 'Sistema operativo', 'Ex.: iOS 17.4'));
            container.appendChild(buildTextField('storage', 'Armazenamento', 'Ex.: 256GB'));
            container.appendChild(buildTextField('color', 'Cor', 'Ex.: Preto'));
            break;

        case 'COMPUTER':
            container.appendChild(buildTextField('mac_address', 'MAC address',
                'AA:BB:CC:DD:EE:FF', { pattern: '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' }));
            container.appendChild(buildTextField('hostname', 'Hostname', 'Ex.: laptop-joao'));
            container.appendChild(buildTextField('os', 'Sistema operativo', 'Ex.: Windows 11 Pro'));
            container.appendChild(buildTextField('storage', 'Armazenamento principal', 'Ex.: 1TB NVMe'));
            break;

        case 'VEHICLE':
            container.appendChild(buildVinGroup());
            container.appendChild(buildTextField('plate', 'Matrícula (opcional)', 'Ex.: 12-AB-34'));
            container.appendChild(buildTextField('brand', 'Marca', 'Ex.: Volkswagen'));
            container.appendChild(buildTextField('model', 'Modelo', 'Ex.: Golf GTI'));
            container.appendChild(buildTextField('color', 'Cor', 'Ex.: Azul'));
            container.appendChild(buildTextField('year', 'Ano (opcional)', 'Ex.: 2022',
                { type: 'number', min: '1900', max: '2100' }));
            break;

        case 'VEHICLE_COMPONENT':
            var parentType = document.getElementById('parent_type').value;
            if (parentType && parentType !== 'VEHICLE') {
                container.appendChild(buildInlineWarn(
                    'Atenção: normalmente este tipo é um sub-componente de um VEÍCULO. '
                    + 'O backend irá validar a hierarquia.'
                ));
            }
            container.appendChild(buildSelectField('component_type', 'Tipo de componente', [
                ['ECU', 'ECU / Centralina'],
                ['AUTORADIO', 'Autorrádio / Head unit'],
                ['DASHCAM', 'Dashcam'],
                ['TELEMATICS', 'Telemática / eCall'],
                ['OTHER', 'Outro']
            ]));
            container.appendChild(buildTextField('manufacturer', 'Fabricante', 'Ex.: Bosch'));
            container.appendChild(buildTextField('component_serial', 'Serial do componente',
                'Ex.: 0261S12345'));
            break;

        case 'SIM_CARD':
            container.appendChild(buildTextField('imsi', 'IMSI',
                '14-15 dígitos (ex.: 268060000000001)',
                { pattern: '[0-9]{14,15}', inputmode: 'numeric' }));
            container.appendChild(buildTextField('iccid', 'ICCID',
                '19-20 dígitos impressos no cartão',
                { pattern: '[0-9]{19,20}', inputmode: 'numeric' }));
            container.appendChild(buildTextField('operator', 'Operador', 'Ex.: MEO, NOS, Vodafone'));
            break;

        case 'MEMORY_CARD':
            container.appendChild(buildTextField('capacity_gb', 'Capacidade (GB)', 'Ex.: 128',
                { type: 'number', min: '1' }));
            container.appendChild(buildTextField('brand', 'Marca', 'Ex.: SanDisk'));
            container.appendChild(buildTextField('card_serial', 'Serial (se visível)', ''));
            break;

        case 'INTERNAL_DRIVE':
            container.appendChild(buildSelectField('drive_type', 'Tipo', [
                ['HDD', 'HDD — Disco rígido'],
                ['SSD', 'SSD — Solid State'],
                ['NVMe', 'NVMe — PCIe'],
                ['eMMC', 'eMMC']
            ]));
            container.appendChild(buildTextField('capacity_gb', 'Capacidade (GB)', 'Ex.: 1000',
                { type: 'number', min: '1' }));
            container.appendChild(buildTextField('drive_serial', 'Serial', 'Ex.: S1A2B3C4'));
            container.appendChild(buildTextField('manufacturer', 'Fabricante', 'Ex.: Samsung'));
            break;

        case 'CCTV_DEVICE':
            container.appendChild(buildTextField('channels', 'Nº canais', 'Ex.: 8',
                { type: 'number', min: '1', max: '128' }));
            container.appendChild(buildTextField('manufacturer', 'Fabricante', 'Ex.: Hikvision'));
            container.appendChild(buildTextField('model', 'Modelo', 'Ex.: DS-7608NI'));
            container.appendChild(buildTextField('ip_address', 'IP', 'Ex.: 192.168.1.50'));
            break;

        case 'GPS_TRACKER':
            container.appendChild(buildImeiGroup({ optional: true, label: 'IMEI (opcional)' }));
            container.appendChild(buildTextField('tracker_serial', 'Serial', ''));
            container.appendChild(buildTextField('account_email', 'Conta associada',
                'email iCloud/Samsung/Google', { type: 'email' }));
            break;

        case 'SMART_TAG':
            container.appendChild(buildTextField('tag_serial', 'Serial', ''));
            container.appendChild(buildTextField('account_email', 'Conta Apple / Samsung / Google',
                'email associado', { type: 'email' }));
            container.appendChild(buildTextField('brand', 'Marca', 'Ex.: AirTag, SmartTag, Tile'));
            break;

        case 'DRONE':
            container.appendChild(buildTextField('drone_serial', 'Serial', ''));
            container.appendChild(buildTextField('manufacturer', 'Fabricante', 'Ex.: DJI'));
            container.appendChild(buildTextField('model', 'Modelo', 'Ex.: Mavic 3'));
            container.appendChild(buildTextField('remote_id', 'Remote ID (se conhecido)', ''));
            break;

        case 'DIGITAL_FILE':
            container.appendChild(buildTextField('sha256', 'Hash SHA-256',
                '64 caracteres hex',
                { pattern: '[A-Fa-f0-9]{64}' }));
            container.appendChild(buildTextField('file_name', 'Nome do ficheiro', 'Ex.: imagem.dd'));
            container.appendChild(buildTextField('file_size', 'Tamanho (bytes)', 'Ex.: 1048576',
                { type: 'number', min: '0' }));
            container.appendChild(buildTextField('source', 'Origem', 'Ex.: dispositivo #123'));
            break;

        case 'GAMING_CONSOLE':
            container.appendChild(buildTextField('brand', 'Marca', 'Ex.: Sony, Microsoft, Nintendo'));
            container.appendChild(buildTextField('model', 'Modelo', 'Ex.: PS5, Xbox Series X, Switch'));
            container.appendChild(buildTextField('account_id', 'ID de conta (se visível)', ''));
            break;

        case 'NETWORK_DEVICE':
            container.appendChild(buildTextField('manufacturer', 'Fabricante', 'Ex.: Cisco'));
            container.appendChild(buildTextField('model', 'Modelo', 'Ex.: ISR 4331'));
            container.appendChild(buildTextField('mac_address', 'MAC address',
                'AA:BB:CC:DD:EE:FF', { pattern: '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' }));
            container.appendChild(buildTextField('ip_address', 'IP', 'Ex.: 192.168.1.1'));
            break;

        case 'IOT_DEVICE':
            container.appendChild(buildTextField('device_name', 'Nome / categoria',
                'Ex.: Câmara Nest, Termostato'));
            container.appendChild(buildTextField('manufacturer', 'Fabricante', ''));
            container.appendChild(buildTextField('account_email', 'Conta associada',
                '', { type: 'email' }));
            break;

        case 'STORAGE_MEDIA':
            container.appendChild(buildSelectField('media_type', 'Tipo', [
                ['USB', 'Pen USB'],
                ['EXT_HDD', 'Disco externo HDD'],
                ['EXT_SSD', 'Disco externo SSD'],
                ['OPTICAL', 'Disco óptico (CD/DVD/Blu-ray)'],
                ['OTHER', 'Outro']
            ]));
            container.appendChild(buildTextField('capacity_gb', 'Capacidade (GB)', 'Ex.: 256',
                { type: 'number', min: '0' }));
            container.appendChild(buildTextField('brand', 'Marca', ''));
            break;

        case 'RFID_NFC_CARD':
            container.appendChild(buildTextField('uid', 'UID do cartão', 'Hex uppercase'));
            container.appendChild(buildTextField('card_issuer', 'Emissor', 'Ex.: Lisboa Viva, Via Verde'));
            container.appendChild(buildTextField('notes', 'Observações', ''));
            break;

        case 'OTHER_DIGITAL':
        default:
            container.appendChild(buildTextField('device_name', 'Descrição curta do dispositivo',
                'Ex.: Smartwatch, câmara fotográfica'));
            container.appendChild(buildTextField('manufacturer', 'Fabricante (opcional)', ''));
            container.appendChild(buildTextField('notes', 'Observações', ''));
            break;
    }
}

/* ---- Field builders ---- */

function buildTextField(name, label, placeholder, opts) {
    opts = opts || {};
    var group = document.createElement('div');
    group.className = 'form-group';

    var lbl = document.createElement('label');
    lbl.className = 'form-label';
    lbl.setAttribute('for', 'tsd-' + name);
    lbl.textContent = label;
    group.appendChild(lbl);

    var input = document.createElement('input');
    input.type = opts.type || 'text';
    input.id = 'tsd-' + name;
    input.name = 'tsd-' + name;
    input.className = 'form-control' + (opts.mono ? ' mono' : '');
    if (placeholder) input.placeholder = placeholder;
    if (opts.pattern) input.pattern = opts.pattern;
    if (opts.min !== undefined) input.min = opts.min;
    if (opts.max !== undefined) input.max = opts.max;
    if (opts.inputmode) input.inputMode = opts.inputmode;
    input.autocomplete = 'off';
    input.setAttribute('data-tsd-key', name);
    group.appendChild(input);

    return group;
}

function buildSelectField(name, label, options) {
    var group = document.createElement('div');
    group.className = 'form-group';

    var lbl = document.createElement('label');
    lbl.className = 'form-label';
    lbl.setAttribute('for', 'tsd-' + name);
    lbl.textContent = label;
    group.appendChild(lbl);

    var select = document.createElement('select');
    select.id = 'tsd-' + name;
    select.name = 'tsd-' + name;
    select.className = 'form-control';
    select.setAttribute('data-tsd-key', name);

    var blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '— Selecionar —';
    select.appendChild(blank);

    options.forEach(function (pair) {
        var opt = document.createElement('option');
        opt.value = pair[0];
        opt.textContent = pair[1];
        select.appendChild(opt);
    });
    group.appendChild(select);
    return group;
}

function buildInlineWarn(text) {
    var wrap = document.createElement('div');
    wrap.className = 'callout warning mb-4';
    wrap.setAttribute('role', 'note');
    var icon = Icons.element('alert', { size: 18, className: 'callout-icon' });
    if (icon) wrap.appendChild(icon);
    var body = document.createElement('div');
    body.className = 'callout-body';
    body.textContent = text;
    wrap.appendChild(body);
    return wrap;
}

/* ---- IMEI lookup group ---- */

function buildImeiGroup(opts) {
    opts = opts || {};
    var group = document.createElement('div');
    group.className = 'form-group lookup-group';

    var lbl = document.createElement('label');
    lbl.className = 'form-label';
    lbl.setAttribute('for', 'tsd-imei');
    lbl.textContent = opts.label || 'IMEI';
    group.appendChild(lbl);

    var row = document.createElement('div');
    row.className = 'lookup-row';

    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'tsd-imei';
    input.name = 'tsd-imei';
    input.className = 'form-control mono';
    input.placeholder = '490154203237518';
    input.pattern = '[0-9]{15}';
    input.maxLength = 15;
    input.inputMode = 'numeric';
    input.setAttribute('data-tsd-key', 'imei');
    input.setAttribute('aria-describedby', 'imei-hint imei-status');
    row.appendChild(input);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'btn-lookup-imei';
    btn.className = 'btn btn-outline';
    btn.textContent = 'Consultar IMEI';
    btn.addEventListener('click', onLookupImei);
    row.appendChild(btn);

    group.appendChild(row);

    var status = document.createElement('div');
    status.id = 'imei-status';
    status.className = 'lookup-status';
    status.setAttribute('role', 'status');
    group.appendChild(status);

    var hint = document.createElement('small');
    hint.id = 'imei-hint';
    hint.className = 'text-muted';
    hint.textContent = 'Consultas contam para saldo externo — usa cache quando possível.';
    group.appendChild(hint);

    return group;
}

async function onLookupImei() {
    var input = document.getElementById('tsd-imei');
    var status = document.getElementById('imei-status');
    var btn = document.getElementById('btn-lookup-imei');
    if (!input) return;

    var imei = (input.value || '').trim();
    if (!/^\d{15}$/.test(imei)) {
        setLookupStatus(status, 'error', 'IMEI deve ter 15 dígitos.');
        input.focus();
        return;
    }

    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    setLookupStatus(status, 'info', 'A consultar IMEI…');

    try {
        var r = await fetch(CONFIG.ENDPOINTS.LOOKUP_IMEI + encodeURIComponent(imei) + '/', {
            credentials: 'include'
        });
        if (r.status === 503) {
            setLookupStatus(status, 'warn',
                'Serviço externo indisponível. Preenche manualmente.');
            return;
        }
        if (r.status === 429) {
            setLookupStatus(status, 'warn',
                'Muitos pedidos. Aguarda e tenta novamente.');
            return;
        }
        if (!r.ok) {
            var txt = await r.text().catch(function () { return ''; });
            throw new Error('HTTP ' + r.status + ' ' + txt);
        }
        var data = await r.json();
        fillIfPresent('tsd-brand', data.brand);
        fillIfPresent('tsd-model', data.model);
        fillIfPresent('tsd-os', data.os);
        fillIfPresent('tsd-storage', data.storage);
        fillIfPresent('tsd-color', data.color);

        if (data.cached) {
            setLookupStatus(status, 'cached', 'Dados de cache (verifica).');
        } else {
            setLookupStatus(status, 'live',
                'Dados obtidos de ' + (data.source || 'API externa') + '. Verifica.');
        }
    } catch (err) {
        console.error('Falha lookup IMEI:', err);
        setLookupStatus(status, 'error',
            'Falha na consulta. Preenche manualmente.');
    } finally {
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
    }
}

function fillIfPresent(id, value) {
    if (value === undefined || value === null || value === '') return;
    var el = document.getElementById(id);
    if (el && !el.value) el.value = String(value);
}

/* ---- VIN lookup group ---- */

function buildVinGroup() {
    var group = document.createElement('div');
    group.className = 'form-group lookup-group';

    var lbl = document.createElement('label');
    lbl.className = 'form-label';
    lbl.setAttribute('for', 'tsd-vin');
    lbl.textContent = 'VIN';
    group.appendChild(lbl);

    var row = document.createElement('div');
    row.className = 'lookup-row';

    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'tsd-vin';
    input.name = 'tsd-vin';
    input.className = 'form-control mono';
    input.placeholder = '1HGBH41JXMN109186';
    input.pattern = '[A-HJ-NPR-Z0-9]{17}';
    input.maxLength = 17;
    input.style.textTransform = 'uppercase';
    input.setAttribute('data-tsd-key', 'vin');
    input.setAttribute('aria-describedby', 'vin-status');
    row.appendChild(input);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'btn-open-vindecoder';
    btn.className = 'btn btn-outline';
    btn.textContent = 'Abrir vindecoder.eu';
    btn.addEventListener('click', onOpenVindecoder);
    row.appendChild(btn);

    group.appendChild(row);

    var status = document.createElement('div');
    status.id = 'vin-status';
    status.className = 'lookup-status';
    status.setAttribute('role', 'status');
    group.appendChild(status);

    var hint = document.createElement('small');
    hint.className = 'text-muted';
    hint.textContent = 'Copia os dados do vindecoder.eu para os campos abaixo.';
    group.appendChild(hint);

    return group;
}

async function onOpenVindecoder() {
    var input = document.getElementById('tsd-vin');
    var status = document.getElementById('vin-status');
    var btn = document.getElementById('btn-open-vindecoder');
    if (!input) return;

    var vin = (input.value || '').trim().toUpperCase();
    input.value = vin;
    if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) {
        setLookupStatus(status, 'error',
            'VIN deve ter 17 caracteres ISO 3779 (sem I, O ou Q).');
        input.focus();
        return;
    }

    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    setLookupStatus(status, 'info', 'A obter URL…');

    try {
        var r = await fetch(CONFIG.ENDPOINTS.LOOKUP_VIN + encodeURIComponent(vin) + '/', {
            credentials: 'include'
        });
        if (!r.ok) {
            // Fallback: construímos a URL do vindecoder.eu nós mesmos.
            var fallbackUrl = 'https://www.vindecoder.eu/check-vin/' + encodeURIComponent(vin);
            window.open(fallbackUrl, '_blank', 'noopener');
            setLookupStatus(status, 'warn',
                'Serviço indisponível; abri vindecoder.eu com o VIN.');
            return;
        }
        var data = await r.json();
        window.open(data.url, '_blank', 'noopener');
        setLookupStatus(status, 'live',
            'Abrimos vindecoder.eu. Copia os dados para os campos.');
    } catch (err) {
        console.error('Falha lookup VIN:', err);
        setLookupStatus(status, 'error', 'Erro ao obter URL.');
    } finally {
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
    }
}

function setLookupStatus(el, kind, msg) {
    if (!el) return;
    el.className = 'lookup-status lookup-status-' + kind;
    el.textContent = msg;
}

/* ---- Wizard ---- */

function initWizard() {
    var el = document.getElementById('evidence-wizard');
    wizard = new Wizard(el, {
        onStep: onStepChange,
        onComplete: handleSubmit
    });

    wizard.setValidator(0, function () {
        if (!document.getElementById('occurrence').value) {
            showError('occurrence-error', 'Selecione uma ocorrência.');
            return false;
        }
        return true;
    });
    wizard.setValidator(1, function () {
        if (!document.getElementById('type').value) {
            showError('type-error', 'Selecione o tipo de item.');
            return false;
        }
        return true;
    });
    wizard.setValidator(2, function () {
        if (!document.getElementById('description').value.trim()) {
            showError('description-error', 'A descrição é obrigatória.');
            return false;
        }
        return true;
    });
    wizard.setValidator(3, function () {
        if (!document.getElementById('timestamp_seizure').value) {
            showError('timestamp_seizure-error', 'A data/hora é obrigatória.');
            return false;
        }
        return true;
    });

    // Auto-advance: occurrence select
    document.getElementById('occurrence').addEventListener('change', function () {
        if (this.value) {
            clearError('occurrence-error');
            wizard.markDotDone(0);
            setTimeout(function () { wizard.next(); }, 250);
        }
    });

    // Auto-advance: type select (depois de um pequeno delay para permitir
    // que o utilizador veja os campos que vão aparecer)
    document.getElementById('type').addEventListener('change', function () {
        if (this.value) {
            wizard.markDotDone(1);
        }
    });

    // Skip buttons
    var skipBtns = document.querySelectorAll('[data-skip]');
    skipBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (wizard) wizard.next();
        });
    });
}

function onStepChange(step) {
    clearErrors();
    if (step === 7) buildSummary();
}

/* ---- Occurrences ---- */

async function loadOccurrences() {
    var select = document.getElementById('occurrence');
    try {
        var data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 100 });
        var occurrences = data.results || [];

        occurrences.forEach(function (occ) {
            var option = document.createElement('option');
            option.value = occ.id;
            option.textContent = occ.number + ' \u2014 ' + (occ.description || '').substring(0, 50);
            select.appendChild(option);
        });

        // Pré-selecção por URL (?occurrence=...)
        var urlParams = new URLSearchParams(window.location.search);
        var preOcc = urlParams.get('occurrence');
        if (preOcc) {
            select.value = preOcc;
            if (select.value && wizard) {
                wizard.markDotDone(0);
                setTimeout(function () { wizard.next(); }, 400);
            }
        }
    } catch (err) {
        console.error('Erro ao carregar ocorrências:', err);
        Toast.show('Erro ao carregar lista de ocorrências.', 'error');
    }
}

/* ---- Timestamp ---- */

function setDefaultTimestamp() {
    var now = new Date();
    var local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    document.getElementById('timestamp_seizure').value = local.toISOString().slice(0, 16);
}

/* ---- Photo capture ---- */

function setupPhotoCapture() {
    ['photo-camera', 'photo-file'].forEach(function (id) {
        document.getElementById(id).addEventListener('change', function (e) {
            var file = e.target.files[0];
            if (!file) return;
            if (file.size > 10 * 1024 * 1024) {
                Toast.show('Ficheiro demasiado grande. Máximo: 10 MB.', 'error');
                e.target.value = '';
                return;
            }
            selectedPhoto = file;
            var reader = new FileReader();
            reader.onload = function (ev) {
                document.getElementById('preview-img').src = ev.target.result;
                document.getElementById('photo-preview').classList.remove('hidden');
                document.getElementById('photo-buttons').style.display = 'none';
            };
            reader.readAsDataURL(file);
        });
    });

    document.getElementById('btn-remove-photo').addEventListener('click', function () {
        selectedPhoto = null;
        document.getElementById('preview-img').src = '';
        document.getElementById('photo-preview').classList.add('hidden');
        document.getElementById('photo-buttons').style.display = '';
        document.getElementById('photo-camera').value = '';
        document.getElementById('photo-file').value = '';
    });
}

/* ---- GPS ---- */

function captureGPS() {
    var btn = document.getElementById('btn-gps');

    if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
        showGpsStatus('GPS requer HTTPS.', 'warning');
        return;
    }
    if (!navigator.geolocation) {
        showGpsStatus('GPS não disponível neste dispositivo.', 'warning');
        return;
    }

    btn.disabled = true;
    setGpsButtonLabel(btn, 'A obter localização…');
    showGpsStatus('A aguardar sinal GPS…', 'info');

    navigator.geolocation.getCurrentPosition(
        function (pos) {
            document.getElementById('gps_lat').value = pos.coords.latitude.toFixed(7);
            document.getElementById('gps_lon').value = pos.coords.longitude.toFixed(7);
            btn.disabled = false;
            setGpsButtonLabel(btn, 'Atualizar localização');
            showGpsStatus('GPS capturado (±' + Math.round(pos.coords.accuracy) + 'm)', 'success');
        },
        function (err) {
            btn.disabled = false;
            setGpsButtonLabel(btn, 'Tentar novamente');
            var msgs = { 1: 'Permissão negada.', 2: 'Posição indisponível.', 3: 'Tempo excedido.' };
            showGpsStatus(msgs[err.code] || 'Erro GPS.', 'warning');
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
}

function setGpsButtonLabel(btn, text) {
    var lbl = btn.querySelector('#btn-gps-label');
    if (lbl) lbl.textContent = text;
    else btn.textContent = text;
}

function showGpsStatus(message, type) {
    var el = document.getElementById('gps-status');
    el.style.display = 'block';
    el.className = 'gps-status gps-status-' + type;
    el.textContent = message;
}

/* ---- type_specific_data harvesting ---- */

function collectTypeSpecificData() {
    var tsd = {};
    var nodes = document.querySelectorAll('#type-specific-fields [data-tsd-key]');
    nodes.forEach(function (n) {
        var key = n.getAttribute('data-tsd-key');
        var val = (n.value || '').trim();
        if (val === '') return;
        if (n.type === 'number') {
            var num = Number(val);
            if (!Number.isNaN(num)) tsd[key] = num;
        } else if (key === 'vin' || key === 'sha256') {
            tsd[key] = val.toUpperCase();
        } else {
            tsd[key] = val;
        }
    });
    return tsd;
}

/* ---- Summary (step 7) ---- */

function buildSummary() {
    var occSelect = document.getElementById('occurrence');
    var occText = occSelect.options[occSelect.selectedIndex]
        ? occSelect.options[occSelect.selectedIndex].textContent
        : '—';

    var typeValue = document.getElementById('type').value;
    setText('sum-occurrence', occText);
    setText('sum-type', CONFIG.EVIDENCE_TYPES[typeValue] || '—');
    setText('sum-description', document.getElementById('description').value.trim() || '—');
    setText('sum-serial', document.getElementById('serial_number').value.trim() || 'N/A');
    setText('sum-timestamp', document.getElementById('timestamp_seizure').value || '—');

    var parentId = document.getElementById('parent_evidence').value;
    var parentRow = document.getElementById('sum-parent-row');
    if (parentId) {
        parentRow.style.display = '';
        setText('sum-parent', '#' + parentId);
    } else {
        parentRow.style.display = 'none';
    }

    var lat = document.getElementById('gps_lat').value;
    var lon = document.getElementById('gps_lon').value;
    setText('sum-gps', lat && lon ? lat + ', ' + lon : 'Não capturado');

    // Detalhes type-specific
    var tsd = collectTypeSpecificData();
    var tsdRow = document.getElementById('sum-tsd-row');
    var keys = Object.keys(tsd);
    if (keys.length) {
        tsdRow.style.display = '';
        var txt = keys.map(function (k) { return k + ': ' + tsd[k]; }).join(', ');
        setText('sum-tsd', txt);
    } else {
        tsdRow.style.display = 'none';
    }

    var photoRow = document.getElementById('sum-photo-row');
    if (selectedPhoto) {
        photoRow.style.display = '';
        document.getElementById('sum-photo').src = document.getElementById('preview-img').src;
    } else {
        photoRow.style.display = 'none';
    }
}

function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
}

/* ---- Submit ---- */

function getCsrfToken() {
    var cookie = document.cookie.split('; ').find(function (row) {
        return row.startsWith('csrftoken=');
    });
    return cookie ? cookie.split('=')[1] : '';
}

async function handleSubmit() {
    clearErrors();
    setSubmitting(true);

    try {
        var form = document.getElementById('evidence-form');
        var formData = new FormData();
        formData.append('occurrence', form.occurrence.value);
        formData.append('type', document.getElementById('type').value);
        formData.append('description', form.description.value.trim());
        formData.append('timestamp_seizure', new Date(form.timestamp_seizure.value).toISOString());
        formData.append('serial_number', form.serial_number.value.trim() || '');

        var parentId = form.parent_evidence.value;
        if (parentId) formData.append('parent_evidence', parentId);

        var tsd = collectTypeSpecificData();
        if (Object.keys(tsd).length) {
            formData.append('type_specific_data', JSON.stringify(tsd));
        }

        var lat = form.gps_lat.value;
        var lon = form.gps_lon.value;
        if (lat) formData.append('gps_lat', lat);
        if (lon) formData.append('gps_lon', lon);
        if (selectedPhoto) formData.append('photo', selectedPhoto);

        var res = await fetch(CONFIG.ENDPOINTS.EVIDENCES, {
            method: 'POST',
            credentials: 'include',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: formData
        });

        if (!res.ok) {
            var errorData = await res.json().catch(function () { return {}; });
            if (res.status === 400 && typeof errorData === 'object') {
                handleValidationErrors(errorData);
                Toast.show('Corrija os erros assinalados.', 'error');
                setSubmitting(false);
                return;
            }
            throw new Error('HTTP ' + res.status);
        }

        var data = await res.json();
        createdEvidenceId = data.id;
        createdEvidenceType = data.type;
        var label = data.code ? 'Item ' + data.code : 'Item #' + data.id;
        Toast.show(label + ' registado com sucesso!', 'success');
        setSubmitting(false);

        // Pergunta sub-componentes — só se ainda houver profundidade
        showSubPrompt(data);
    } catch (err) {
        setSubmitting(false);
        Toast.show('Erro ao registar o item. Tente novamente.', 'error');
        console.error('Erro:', err);
    }
}

function handleValidationErrors(errorData) {
    Object.entries(errorData).forEach(function (entry) {
        var field = entry[0];
        var messages = entry[1];
        var msg = Array.isArray(messages) ? messages.join(' ') : String(messages);
        // Mapeamento especial para type_specific_data (um erro genérico)
        if (field === 'type_specific_data') {
            showError('submit-error', 'Detalhes específicos: ' + msg);
            return;
        }
        showError(field + '-error', msg);
    });
}

function setSubmitting(loading) {
    var nextBtn = wizard.nextBtn;
    var spinner = document.getElementById('submit-spinner');

    nextBtn.disabled = loading;
    nextBtn.textContent = loading ? 'A registar...' : 'Registar';
    spinner.style.display = loading ? 'block' : 'none';

    if (wizard.backBtn) wizard.backBtn.disabled = loading;
}

/* ---- Sub-component prompt modal ---- */

function initSubPromptHandlers() {
    var modal = document.getElementById('sub-prompt-modal');
    var btnAdd = document.getElementById('btn-sub-add');
    var btnFinish = document.getElementById('btn-sub-finish');

    btnAdd.addEventListener('click', function () {
        if (!createdEvidenceId) return;
        // Abrimos o wizard de novo, mas como sub-componente do que acabámos de criar.
        var url = '/evidences/new/?parent=' + encodeURIComponent(createdEvidenceId);
        window.location.href = url;
    });

    btnFinish.addEventListener('click', function () {
        closeSubPrompt();
        if (createdEvidenceId) {
            window.location.href = '/evidences/' + createdEvidenceId + '/';
        } else {
            window.location.href = '/evidences/';
        }
    });
}

function showSubPrompt(evidence) {
    var modal = document.getElementById('sub-prompt-modal');
    var btnAdd = document.getElementById('btn-sub-add');
    var maxBox = document.getElementById('sub-prompt-max');
    var suggestionsBox = document.getElementById('sub-prompt-suggestions');

    // Profundidade: calculamos a partir do depth do pai + 1
    var parentDepth = Number(document.getElementById('parent_depth').value || 0);
    var newDepth = document.getElementById('parent_evidence').value ? parentDepth + 1 : 0;

    // MAX_TREE_DEPTH = 3. Um componente de profundidade 2 não pode ter filhos
    // (depth 3 seria a folha e já não cabe mais nada).
    if (newDepth >= CONFIG.MAX_TREE_DEPTH - 1) {
        btnAdd.hidden = true;
        btnAdd.setAttribute('aria-hidden', 'true');
        maxBox.classList.remove('hidden');
    } else {
        btnAdd.hidden = false;
        btnAdd.removeAttribute('aria-hidden');
        maxBox.classList.add('hidden');
    }

    // Mostra sugestões baseadas no tipo recém-criado
    suggestionsBox.replaceChildren();
    var suggestions = (CONFIG.EVIDENCE_CHILD_SUGGESTIONS || {})[evidence.type];
    if (suggestions && suggestions.length && !btnAdd.hidden) {
        var title = document.createElement('small');
        title.className = 'text-muted';
        title.textContent = 'Sugestões para ' + (CONFIG.EVIDENCE_TYPES[evidence.type] || evidence.type) + ':';
        suggestionsBox.appendChild(title);

        var row = document.createElement('div');
        row.className = 'sub-suggestion-pills';
        suggestions.forEach(function (t) {
            var pill = document.createElement('span');
            pill.className = 'pill';
            var svgIcon = Icons.forEvidenceElement(t, { size: 14 });
            if (svgIcon) pill.appendChild(svgIcon);
            var label = document.createElement('span');
            label.textContent = CONFIG.EVIDENCE_TYPES[t] || t;
            pill.appendChild(label);
            row.appendChild(pill);
        });
        suggestionsBox.appendChild(row);
        suggestionsBox.setAttribute('aria-hidden', 'false');
    } else {
        suggestionsBox.setAttribute('aria-hidden', 'true');
    }

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');
    modal.classList.add('open');
    modal.classList.add('active');
    // Coloca o foco no botão primário (ou terminar se max atingido)
    setTimeout(function () {
        (btnAdd.hidden ? document.getElementById('btn-sub-finish') : btnAdd).focus();
    }, 50);
}

function closeSubPrompt() {
    var modal = document.getElementById('sub-prompt-modal');
    modal.hidden = true;
    modal.setAttribute('hidden', 'hidden');
    modal.setAttribute('aria-hidden', 'true');
    modal.classList.remove('open');
    modal.classList.remove('active');
}

/* ---- Error helpers ---- */

function showError(id, message) {
    var el = document.getElementById(id);
    if (el) { el.textContent = message; el.style.display = 'block'; }
}

function clearError(id) {
    var el = document.getElementById(id);
    if (el) { el.textContent = ''; el.style.display = 'none'; }
}

function clearErrors() {
    document.querySelectorAll('.form-error').forEach(function (el) {
        el.textContent = '';
        el.style.display = 'none';
    });
}
