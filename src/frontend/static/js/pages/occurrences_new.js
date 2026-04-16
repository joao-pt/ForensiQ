'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    if (user) {
        document.getElementById('navbar-user').textContent = user.first_name || user.username;

        // Só agentes podem registar ocorrências
        if (user.profile !== 'AGENT') {
            Toast.show('Sem permissão para registar ocorrências.', 'error');
            setTimeout(() => { window.location.href = '/occurrences/'; }, 1500);
            return;
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    // Pré-preencher data/hora com o momento atual
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    document.getElementById('date_time').value = local.toISOString().slice(0, 16);

    // Tentar obter GPS automaticamente ao carregar
    captureGPS();

    // Botão GPS manual
    document.getElementById('btn-gps').addEventListener('click', captureGPS);

    // Submissão do formulário
    document.getElementById('occurrence-form').addEventListener('submit', handleSubmit);
});

/**
 * Obtém o token CSRF dos cookies.
 */
function getCsrfToken() {
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

/**
 * Captura a localização GPS atual do dispositivo.
 */
function captureGPS() {
    const btn = document.getElementById('btn-gps');
    const status = document.getElementById('gps-status');

    if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
        showGpsStatus('GPS requer HTTPS. Em desenvolvimento, use localhost ou ngrok.', 'warning');
        return;
    }

    if (!navigator.geolocation) {
        showGpsStatus('GPS não disponível neste dispositivo.', 'warning');
        return;
    }

    btn.disabled = true;
    btn.textContent = '⏳ A obter localização...';
    showGpsStatus('A aguardar sinal GPS...', 'info');
    status.style.display = 'block';

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude.toFixed(7);
            const lon = pos.coords.longitude.toFixed(7);
            document.getElementById('gps_lat').value = lat;
            document.getElementById('gps_lon').value = lon;

            btn.disabled = false;
            btn.textContent = '📍 Atualizar localização';
            showGpsStatus(`✅ GPS capturado (±${Math.round(pos.coords.accuracy)}m) — ${lat}, ${lon}`, 'success');

            // Reverse geocoding via Nominatim (gratuito, sem API key)
            reverseGeocode(lat, lon);
        },
        (err) => {
            btn.disabled = false;
            btn.textContent = '📍 Tentar novamente';
            const msgs = {
                1: 'Permissão de localização negada.',
                2: 'Posição indisponível. Verifique o GPS.',
                3: 'Tempo de espera excedido. Tente novamente.',
            };
            showGpsStatus('⚠️ ' + (msgs[err.code] || 'Erro desconhecido.'), 'warning');
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
}

/**
 * Reverse geocoding via Nominatim (OpenStreetMap).
 */
async function reverseGeocode(lat, lon) {
    try {
        const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
            { headers: { 'Accept-Language': 'pt' } }
        );
        if (!res.ok) return;
        const data = await res.json();
        if (data.display_name) {
            const addressEl = document.getElementById('address');
            if (!addressEl.value) {
                // Simplificar: rua + localidade
                const parts = [
                    data.address?.road,
                    data.address?.house_number,
                    data.address?.city || data.address?.town || data.address?.village,
                    data.address?.country,
                ].filter(Boolean);
                addressEl.value = parts.join(', ');
            }
        }
    } catch (e) {
        // Silencioso — reverse geocoding é opcional
    }
}

function showGpsStatus(message, type) {
    const el = document.getElementById('gps-status');
    el.style.display = 'block';
    el.className = `gps-status gps-status-${type}`;
    el.textContent = message;
}

/**
 * Submissão do formulário.
 */
async function handleSubmit(e) {
    e.preventDefault();

    clearErrors();

    const form = e.target;
    const data = {
        number: form.number.value.trim(),
        description: form.description.value.trim(),
        date_time: new Date(form.date_time.value).toISOString(),
        address: form.address.value.trim() || '',
    };

    const lat = form.gps_lat.value;
    const lon = form.gps_lon.value;
    if (lat) data.gps_lat = parseFloat(lat);
    if (lon) data.gps_lon = parseFloat(lon);

    // Validação client-side básica
    let hasErrors = false;
    if (!data.number) {
        showError('number-error', 'O número da ocorrência é obrigatório.');
        hasErrors = true;
    }
    if (!data.description) {
        showError('description-error', 'A descrição é obrigatória.');
        hasErrors = true;
    }
    if (!form.date_time.value) {
        showError('date_time-error', 'A data e hora são obrigatórias.');
        hasErrors = true;
    }
    if (hasErrors) return;

    setSubmitting(true);

    try {
        // API.post handles CSRF token via wrapper, but ensuring CSRF is protected
        const result = await API.post(CONFIG.ENDPOINTS.OCCURRENCES, data);
        Toast.show('Ocorrência registada com sucesso!', 'success');
        setTimeout(() => {
            window.location.href = '/occurrences/';
        }, 1200);
    } catch (err) {
        setSubmitting(false);
        if (err.data && typeof err.data === 'object') {
            // Erros de validação da API
            Object.entries(err.data).forEach(([field, messages]) => {
                const errorId = `${field}-error`;
                const msg = Array.isArray(messages) ? messages.join(' ') : String(messages);
                showError(errorId, msg);
            });
            Toast.show('Corrija os erros assinalados.', 'error');
        } else {
            Toast.show('Erro ao registar a ocorrência. Tente novamente.', 'error');
        }
    }
}

function setSubmitting(loading) {
    const btn = document.getElementById('btn-submit');
    const text = document.getElementById('btn-text');
    const spinner = document.getElementById('btn-spinner');

    btn.disabled = loading;
    text.textContent = loading ? 'A registar...' : 'Registar Ocorrência';
    spinner.classList.toggle('hidden', !loading);
}

function showError(id, message) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = message;
        el.style.display = 'block';
    }
}

function clearErrors() {
    document.querySelectorAll('.form-error').forEach(el => {
        el.textContent = '';
        el.style.display = 'none';
    });
}
