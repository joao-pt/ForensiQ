'use strict';

let selectedPhoto = null;

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await Auth.requireAuth();
    if (!authenticated) return;

    const user = Auth.getUser();
    if (user) {
        document.getElementById('navbar-user').textContent = user.first_name || user.username;

        if (user.profile !== 'AGENT') {
            Toast.show('Sem permissão para registar evidências.', 'error');
            setTimeout(() => { window.location.href = '/evidences/'; }, 1500);
            return;
        }
    }

    document.getElementById('btn-logout').addEventListener('click', Auth.logout);

    // Data/hora actual
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    document.getElementById('timestamp_seizure').value = local.toISOString().slice(0, 16);

    // Carregar ocorrências para o select
    loadOccurrences();

    // Verificar se vem com ?occurrence=id na URL
    const urlParams = new URLSearchParams(window.location.search);
    const occId = urlParams.get('occurrence');

    // Tipo selector
    document.querySelectorAll('.type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            document.getElementById('type').value = btn.dataset.value;
            document.getElementById('type-error').textContent = '';
        });
    });

    // Fotos
    setupPhotoCapture();

    // GPS automático
    captureGPS();
    document.getElementById('btn-gps').addEventListener('click', captureGPS);

    // Formulário
    document.getElementById('evidence-form').addEventListener('submit', handleSubmit);

    // Se veio com occurrence na URL, pré-selecionar após carregar o select
    if (occId) {
        window._preselectedOccurrence = occId;
    }
});

async function loadOccurrences() {
    const select = document.getElementById('occurrence');
    try {
        // Carregar todas as ocorrências (paginação simples — max 100)
        const data = await API.get(CONFIG.ENDPOINTS.OCCURRENCES, { page_size: 100 });
        const occurrences = data.results || [];

        occurrences.forEach(occ => {
            const option = document.createElement('option');
            option.value = occ.id;
            option.textContent = `${occ.number} — ${(occ.description || '').substring(0, 50)}`;
            select.appendChild(option);
        });

        // Pré-selecionar se URL tem ?occurrence=id
        if (window._preselectedOccurrence) {
            select.value = window._preselectedOccurrence;
        }
    } catch (err) {
        console.error('Erro ao carregar ocorrências:', err);
        Toast.show('Erro ao carregar lista de ocorrências.', 'error');
    }
}

function setupPhotoCapture() {
    const inputs = ['photo-camera', 'photo-file'];
    inputs.forEach(id => {
        document.getElementById(id).addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            if (file.size > 10 * 1024 * 1024) {
                Toast.show('Ficheiro demasiado grande. Máximo: 10 MB.', 'error');
                e.target.value = '';
                return;
            }
            selectedPhoto = file;
            const reader = new FileReader();
            reader.onload = (ev) => {
                document.getElementById('preview-img').src = ev.target.result;
                document.getElementById('photo-preview').classList.remove('hidden');
                document.getElementById('photo-buttons').style.display = 'none';
            };
            reader.readAsDataURL(file);
        });
    });

    document.getElementById('btn-remove-photo').addEventListener('click', () => {
        selectedPhoto = null;
        document.getElementById('preview-img').src = '';
        document.getElementById('photo-preview').classList.add('hidden');
        document.getElementById('photo-buttons').style.display = '';
        document.getElementById('photo-camera').value = '';
        document.getElementById('photo-file').value = '';
    });
}

function getCsrfToken() {
    const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

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
    status.style.display = 'block';
    showGpsStatus('A aguardar sinal GPS...', 'info');

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            document.getElementById('gps_lat').value = pos.coords.latitude.toFixed(7);
            document.getElementById('gps_lon').value = pos.coords.longitude.toFixed(7);
            btn.disabled = false;
            btn.textContent = '📍 Atualizar localização';
            showGpsStatus(`✅ GPS capturado (±${Math.round(pos.coords.accuracy)}m)`, 'success');
        },
        (err) => {
            btn.disabled = false;
            btn.textContent = '📍 Tentar novamente';
            const msgs = { 1: 'Permissão negada.', 2: 'Posição indisponível.', 3: 'Tempo excedido.' };
            showGpsStatus('⚠️ ' + (msgs[err.code] || 'Erro GPS.'), 'warning');
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
}

function showGpsStatus(message, type) {
    const el = document.getElementById('gps-status');
    el.style.display = 'block';
    el.className = `gps-status gps-status-${type}`;
    el.textContent = message;
}

async function handleSubmit(e) {
    e.preventDefault();
    clearErrors();

    const form = e.target;

    // Validação
    let hasErrors = false;
    if (!form.occurrence.value) {
        showError('occurrence-error', 'Selecione uma ocorrência.');
        hasErrors = true;
    }
    if (!document.getElementById('type').value) {
        showError('type-error', 'Selecione o tipo de evidência.');
        hasErrors = true;
    }
    if (!form.description.value.trim()) {
        showError('description-error', 'A descrição é obrigatória.');
        hasErrors = true;
    }
    if (!form.timestamp_seizure.value) {
        showError('timestamp_seizure-error', 'A data/hora de apreensão é obrigatória.');
        hasErrors = true;
    }
    if (hasErrors) return;

    setSubmitting(true);

    try {
        // Usar FormData para suportar upload de foto
        const formData = new FormData();
        formData.append('occurrence', form.occurrence.value);
        formData.append('type', document.getElementById('type').value);
        formData.append('description', form.description.value.trim());
        formData.append('timestamp_seizure', new Date(form.timestamp_seizure.value).toISOString());
        formData.append('serial_number', form.serial_number.value.trim() || '');

        const lat = form.gps_lat.value;
        const lon = form.gps_lon.value;
        if (lat) formData.append('gps_lat', lat);
        if (lon) formData.append('gps_lon', lon);
        if (selectedPhoto) formData.append('photo', selectedPhoto);

        // Multipart: Content-Type é definido pelo browser; cookie HttpOnly + CSRF
        const res = await fetch(CONFIG.ENDPOINTS.EVIDENCES, {
            method: 'POST',
            credentials: 'include',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: formData,
        });

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({}));
            if (res.status === 400 && typeof errorData === 'object') {
                Object.entries(errorData).forEach(([field, messages]) => {
                    const msg = Array.isArray(messages) ? messages.join(' ') : String(messages);
                    showError(`${field}-error`, msg);
                });
                Toast.show('Corrija os erros assinalados.', 'error');
                setSubmitting(false);
                return;
            }
            throw new Error(`HTTP ${res.status}`);
        }

        Toast.show('Evidência registada com sucesso!', 'success');
        setTimeout(() => { window.location.href = '/evidences/'; }, 1200);

    } catch (err) {
        setSubmitting(false);
        Toast.show('Erro ao registar a evidência. Tente novamente.', 'error');
        console.error('Erro:', err);
    }
}

function setSubmitting(loading) {
    const btn = document.getElementById('btn-submit');
    const text = document.getElementById('btn-text');
    const spinner = document.getElementById('btn-spinner');
    btn.disabled = loading;
    text.textContent = loading ? 'A registar...' : 'Registar Evidência';
    spinner.classList.toggle('hidden', !loading);
}

function showError(id, message) {
    const el = document.getElementById(id);
    if (el) { el.textContent = message; el.style.display = 'block'; }
}

function clearErrors() {
    document.querySelectorAll('.form-error').forEach(el => {
        el.textContent = ''; el.style.display = 'none';
    });
}
