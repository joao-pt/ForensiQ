'use strict';

var wizard = null;

document.addEventListener('DOMContentLoaded', async function () {
    var authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    var user = Auth.getUser();
    if (user) {
        var navUser = document.getElementById('navbar-user');
        if (navUser) navUser.textContent = user.first_name || user.username;

        if (user.profile !== 'AGENT') {
            Toast.show('Sem permissão para registar ocorrências.', 'error');
            setTimeout(function () { window.location.href = '/occurrences/'; }, 1500);
            return;
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    setDefaultTimestamp();
    captureGPS();
    document.getElementById('btn-gps').addEventListener('click', captureGPS);

    initWizard();
});

/* ---- Wizard ---- */

function initWizard() {
    var el = document.getElementById('occurrence-wizard');
    wizard = new Wizard(el, {
        onStep: onStepChange,
        onComplete: handleSubmit
    });

    wizard.setValidator(0, function () {
        if (!document.getElementById('number').value.trim()) {
            showError('number-error', 'O número da ocorrência é obrigatório.');
            return false;
        }
        return true;
    });
    wizard.setValidator(1, function () {
        if (!document.getElementById('description').value.trim()) {
            showError('description-error', 'A descrição é obrigatória.');
            return false;
        }
        return true;
    });
    wizard.setValidator(2, function () {
        if (!document.getElementById('date_time').value) {
            showError('date_time-error', 'A data e hora são obrigatórias.');
            return false;
        }
        return true;
    });

    var skipBtns = document.querySelectorAll('[data-skip]');
    skipBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (wizard) wizard.next();
        });
    });
}

function onStepChange(step) {
    clearErrors();
    if (step === 5) buildSummary();
}

/* ---- Timestamp ---- */

function setDefaultTimestamp() {
    var now = new Date();
    var local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    document.getElementById('date_time').value = local.toISOString().slice(0, 16);
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
    btn.textContent = '\u23F3 A obter localização...';
    showGpsStatus('A aguardar sinal GPS...', 'info');

    navigator.geolocation.getCurrentPosition(
        function (pos) {
            var lat = pos.coords.latitude.toFixed(7);
            var lon = pos.coords.longitude.toFixed(7);
            document.getElementById('gps_lat').value = lat;
            document.getElementById('gps_lon').value = lon;
            btn.disabled = false;
            btn.textContent = '\uD83D\uDCCD Atualizar localização';
            showGpsStatus('\u2705 GPS capturado (\u00B1' + Math.round(pos.coords.accuracy) + 'm)', 'success');
            reverseGeocode(lat, lon);
        },
        function (err) {
            btn.disabled = false;
            btn.textContent = '\uD83D\uDCCD Tentar novamente';
            var msgs = { 1: 'Permissão negada.', 2: 'Posição indisponível.', 3: 'Tempo excedido.' };
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

/* ---- Reverse geocoding (Nominatim) ---- */

function reverseGeocode(lat, lon) {
    fetch('https://nominatim.openstreetmap.org/reverse?lat=' + lat + '&lon=' + lon + '&format=json', {
        headers: { 'Accept-Language': 'pt' }
    })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (data) {
        if (!data || !data.address) return;
        var addressEl = document.getElementById('address');
        if (!addressEl.value) {
            var parts = [
                data.address.road,
                data.address.house_number,
                data.address.city || data.address.town || data.address.village,
                data.address.country
            ].filter(Boolean);
            addressEl.value = parts.join(', ');
        }
    })
    .catch(function () {});
}

/* ---- Summary (step 5) ---- */

function buildSummary() {
    setText('sum-number', document.getElementById('number').value.trim() || '\u2014');
    setText('sum-description', document.getElementById('description').value.trim() || '\u2014');
    setText('sum-datetime', document.getElementById('date_time').value || '\u2014');

    var lat = document.getElementById('gps_lat').value;
    var lon = document.getElementById('gps_lon').value;
    setText('sum-gps', lat && lon ? lat + ', ' + lon : 'Não capturado');

    var address = document.getElementById('address').value.trim();
    setText('sum-address', address || 'N/A');
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
        var form = document.getElementById('occurrence-form');
        var data = {
            number: form.number.value.trim(),
            description: form.description.value.trim(),
            date_time: new Date(form.date_time.value).toISOString(),
            address: form.address.value.trim() || ''
        };

        var lat = form.gps_lat.value;
        var lon = form.gps_lon.value;
        if (lat) data.gps_lat = parseFloat(lat);
        if (lon) data.gps_lon = parseFloat(lon);

        var result = await API.post(CONFIG.ENDPOINTS.OCCURRENCES, data);
        Toast.show('Ocorrência registada com sucesso!', 'success');
        setTimeout(function () { window.location.href = '/occurrences/'; }, 1200);

    } catch (err) {
        setSubmitting(false);
        if (err.data && typeof err.data === 'object') {
            Object.entries(err.data).forEach(function (entry) {
                var field = entry[0];
                var messages = entry[1];
                var msg = Array.isArray(messages) ? messages.join(' ') : String(messages);
                showError(field + '-error', msg);
            });
            Toast.show('Corrija os erros assinalados.', 'error');
        } else {
            Toast.show('Erro ao registar a ocorrência. Tente novamente.', 'error');
        }
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

function clearErrors() {
    document.querySelectorAll('.form-error').forEach(function (el) {
        el.textContent = '';
        el.style.display = 'none';
    });
}
