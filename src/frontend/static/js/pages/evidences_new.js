'use strict';

var selectedPhoto = null;
var wizard = null;

document.addEventListener('DOMContentLoaded', async function () {
    var authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    var user = Auth.getUser();
    if (user) {
        var navUser = document.getElementById('navbar-user');
        if (navUser) navUser.textContent = user.first_name || user.username;

        if (user.profile !== 'AGENT') {
            Toast.show('Sem permissão para registar evidências.', 'error');
            setTimeout(function () { window.location.href = '/evidences/'; }, 1500);
            return;
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    setDefaultTimestamp();
    loadOccurrences();
    setupTypeSelector();
    setupPhotoCapture();
    captureGPS();
    document.getElementById('btn-gps').addEventListener('click', captureGPS);

    initWizard();
});

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
            showError('type-error', 'Selecione o tipo de evidência.');
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

    // Skip buttons for optional steps (4=serial, 5=photo, 6=GPS)
    var skipBtns = document.querySelectorAll('[data-skip]');
    skipBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (wizard) wizard.next();
        });
    });

    // Pre-select occurrence from URL param
    var urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('occurrence')) {
        window._preselectedOccurrence = urlParams.get('occurrence');
    }
}

function onStepChange(step) {
    clearErrors();
    if (step === 7) buildSummary();
}

/* ---- Type selector with auto-advance ---- */

function setupTypeSelector() {
    var btns = document.querySelectorAll('.type-btn');
    btns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            btns.forEach(function (b) { b.classList.remove('selected'); });
            btn.classList.add('selected');
            document.getElementById('type').value = btn.dataset.value;
            clearError('type-error');
            if (wizard) {
                wizard.markDotDone(1);
                setTimeout(function () { wizard.next(); }, 300);
            }
        });
    });
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

        if (window._preselectedOccurrence) {
            select.value = window._preselectedOccurrence;
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
        showGpsStatus('GPS n\u00e3o dispon\u00edvel neste dispositivo.', 'warning');
        return;
    }

    btn.disabled = true;
    btn.textContent = '\u23F3 A obter localiza\u00e7\u00e3o...';
    showGpsStatus('A aguardar sinal GPS...', 'info');

    navigator.geolocation.getCurrentPosition(
        function (pos) {
            document.getElementById('gps_lat').value = pos.coords.latitude.toFixed(7);
            document.getElementById('gps_lon').value = pos.coords.longitude.toFixed(7);
            btn.disabled = false;
            btn.textContent = '\uD83D\uDCCD Atualizar localiza\u00e7\u00e3o';
            showGpsStatus('\u2705 GPS capturado (\u00B1' + Math.round(pos.coords.accuracy) + 'm)', 'success');
        },
        function (err) {
            btn.disabled = false;
            btn.textContent = '\uD83D\uDCCD Tentar novamente';
            var msgs = { 1: 'Permiss\u00e3o negada.', 2: 'Posi\u00e7\u00e3o indispon\u00edvel.', 3: 'Tempo excedido.' };
            showGpsStatus('\u26A0\uFE0F ' + (msgs[err.code] || 'Erro GPS.'), 'warning');
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
}

function showGpsStatus(message, type) {
    var el = document.getElementById('gps-status');
    el.style.display = 'block';
    el.className = 'gps-status gps-status-' + type;
    el.textContent = message;
}

/* ---- Summary (step 7) ---- */

function buildSummary() {
    var occSelect = document.getElementById('occurrence');
    var occText = occSelect.options[occSelect.selectedIndex]
        ? occSelect.options[occSelect.selectedIndex].textContent
        : '\u2014';

    var TYPE_LABELS = {
        DIGITAL_DEVICE: 'Dispositivo Digital',
        STORAGE_MEDIA: 'Suporte Armazenamento',
        DOCUMENT: 'Documento',
        PHOTO: 'Fotografia',
        OTHER: 'Outro'
    };

    setText('sum-occurrence', occText);
    setText('sum-type', TYPE_LABELS[document.getElementById('type').value] || '\u2014');
    setText('sum-description', document.getElementById('description').value.trim() || '\u2014');
    setText('sum-serial', document.getElementById('serial_number').value.trim() || 'N/A');
    setText('sum-timestamp', document.getElementById('timestamp_seizure').value || '\u2014');

    var lat = document.getElementById('gps_lat').value;
    var lon = document.getElementById('gps_lon').value;
    setText('sum-gps', lat && lon ? lat + ', ' + lon : 'N\u00e3o capturado');

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
                Object.entries(errorData).forEach(function (entry) {
                    var field = entry[0];
                    var messages = entry[1];
                    var msg = Array.isArray(messages) ? messages.join(' ') : String(messages);
                    showError(field + '-error', msg);
                });
                Toast.show('Corrija os erros assinalados.', 'error');
                setSubmitting(false);
                return;
            }
            throw new Error('HTTP ' + res.status);
        }

        Toast.show('Evid\u00eancia registada com sucesso!', 'success');
        setTimeout(function () { window.location.href = '/evidences/'; }, 1200);

    } catch (err) {
        setSubmitting(false);
        Toast.show('Erro ao registar a evid\u00eancia. Tente novamente.', 'error');
        console.error('Erro:', err);
    }
}

function setSubmitting(loading) {
    var nextBtn = wizard.nextBtn;
    var spinner = document.getElementById('submit-spinner');

    nextBtn.disabled = loading;
    nextBtn.textContent = loading ? 'A registar...' : 'Registar';
    spinner.style.display = loading ? 'block' : 'none';

    if (wizard.backBtn) wizard.backBtn.disabled = loading;
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
