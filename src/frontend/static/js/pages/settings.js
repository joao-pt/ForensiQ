'use strict';

/**
 * ForensiQ — Definições e perfil (/settings/).
 *
 * Pinta o perfil em read-only (dados vêm de /api/users/me/) e sincroniza
 * o segmented control dia/noite com a preferência guardada (mesma chave
 * que o toggle da navbar).
 */

const THEME_KEY = 'fq-theme';

document.addEventListener('DOMContentLoaded', async () => {
    if (!await Auth.requireAuth()) return;

    const user = Auth.getUser();
    renderProfile(user);
    bindThemeChoice();
    bindAutoNightToggle();
    bindLogout();
});

function renderProfile(user) {
    if (!user) return;

    const name = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username;
    const roleLabel = CONFIG.PROFILES[user.profile] || user.profile || '—';

    setText('profile-initials', initials(user));
    setText('profile-name', name);
    setText('profile-role', roleLabel);
    setText('profile-username', user.username || '—');
    setText('profile-email', user.email || '—');

    if (user.badge_number) {
        document.getElementById('profile-badge-row').hidden = false;
        setText('profile-badge', user.badge_number);
    }
    if (user.phone) {
        document.getElementById('profile-phone-row').hidden = false;
        setText('profile-phone', user.phone);
    }
}

function initials(user) {
    const source = [(user.first_name || ''), (user.last_name || '')].join(' ').trim()
                  || user.username || '?';
    const parts = source.split(/\s+/);
    const a = (parts[0] || '').charAt(0);
    const b = (parts.length > 1 ? parts[parts.length - 1].charAt(0) : '');
    return (a + b).toUpperCase() || '?';
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ----------------------------------------------------------
// Theme choice (segmented, mirrored with navbar toggle)
// ----------------------------------------------------------
function bindThemeChoice() {
    const options = document.querySelectorAll('.theme-option');
    if (!options.length) return;

    options.forEach(opt => {
        opt.addEventListener('click', () => {
            const choice = opt.dataset.themeChoice;
            applyTheme(choice);
        });
    });

    paintActive();

    // Escuta mudanças feitas pela navbar e mantém o segmented em sincronia
    const mo = new MutationObserver(paintActive);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* quota */ }
    const meta = document.getElementById('meta-theme-color');
    if (meta) meta.content = theme === 'light' ? '#FAFAF9' : '#0F1115';
    paintActive();
}

function paintActive() {
    const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    document.querySelectorAll('.theme-option').forEach(el => {
        const isActive = el.dataset.themeChoice === current;
        el.classList.toggle('active', isActive);
        el.setAttribute('aria-checked', String(isActive));
    });
}

// ----------------------------------------------------------
// Tema automático ao entardecer
// Activa o modo noite uma hora após o pôr-do-sol detectado pela
// localização do device. A pref é apenas client-side (localStorage),
// nunca enviada para o servidor.
// ----------------------------------------------------------
const AUTO_NIGHT_KEY = 'fq-auto-night';

function bindAutoNightToggle() {
    const toggle = document.getElementById('auto-night');
    if (!toggle) return;

    let enabled = false;
    try { enabled = localStorage.getItem(AUTO_NIGHT_KEY) === '1'; } catch (e) { /* */ }
    toggle.checked = enabled;

    toggle.addEventListener('change', () => {
        try {
            localStorage.setItem(AUTO_NIGHT_KEY, toggle.checked ? '1' : '0');
        } catch (e) { /* quota */ }
        if (toggle.checked) {
            requestLocationAndApply();
        }
    });
}

function requestLocationAndApply() {
    if (!navigator.geolocation) {
        Toast && Toast.show('Geolocalização indisponível neste browser.', 'warning');
        return;
    }
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            applyAutoNightFromPosition(pos.coords.latitude, pos.coords.longitude);
            Toast && Toast.show('Tema automático activado.', 'success');
        },
        () => {
            Toast && Toast.show('Não foi possível obter localização — tema automático desactivado.', 'warning');
            const t = document.getElementById('auto-night');
            if (t) t.checked = false;
            try { localStorage.setItem(AUTO_NIGHT_KEY, '0'); } catch (e) { /* */ }
        },
        { maximumAge: 3600 * 1000, timeout: 8000 },
    );
}

function applyAutoNightFromPosition(lat, lon) {
    const now = new Date();
    const sunset = computeSunsetUTC(now, lat, lon);
    if (!sunset) return;
    // Activa modo noite 1h depois do pôr-do-sol; volta ao dia ao nascer do sol.
    const sunriseTomorrow = computeSunriseUTC(addDays(now, 1), lat, lon);
    const nightStart = new Date(sunset.getTime() + 60 * 60 * 1000);
    const isNight = now >= nightStart && (sunriseTomorrow ? now < sunriseTomorrow : true);
    applyTheme(isNight ? 'dark' : 'light');
}

function addDays(d, n) { const r = new Date(d); r.setDate(r.getDate() + n); return r; }

// Algoritmo NOAA simplificado (precisão ~1 minuto, suficiente para UX).
function computeSunsetUTC(date, lat, lon)  { return solarTime(date, lat, lon, false); }
function computeSunriseUTC(date, lat, lon) { return solarTime(date, lat, lon, true); }

function solarTime(date, lat, lon, isSunrise) {
    const rad = Math.PI / 180;
    const dayOfYear = Math.floor((date - new Date(date.getFullYear(), 0, 0)) / 86400000);
    const lngHour = lon / 15;
    const t = dayOfYear + ((isSunrise ? 6 : 18) - lngHour) / 24;
    const M = (0.9856 * t) - 3.289;
    let L = M + (1.916 * Math.sin(M * rad)) + (0.020 * Math.sin(2 * M * rad)) + 282.634;
    L = ((L % 360) + 360) % 360;
    let RA = Math.atan(0.91764 * Math.tan(L * rad)) / rad;
    RA = ((RA % 360) + 360) % 360;
    const Lquadrant  = Math.floor(L / 90) * 90;
    const RAquadrant = Math.floor(RA / 90) * 90;
    RA = RA + (Lquadrant - RAquadrant);
    RA = RA / 15;
    const sinDec = 0.39782 * Math.sin(L * rad);
    const cosDec = Math.cos(Math.asin(sinDec));
    const zenith = 90.833 * rad;
    const cosH = (Math.cos(zenith) - (sinDec * Math.sin(lat * rad))) / (cosDec * Math.cos(lat * rad));
    if (cosH > 1 || cosH < -1) return null; // Sol nunca nasce/põe
    let H = isSunrise ? 360 - Math.acos(cosH) / rad : Math.acos(cosH) / rad;
    H = H / 15;
    const T = H + RA - (0.06571 * t) - 6.622;
    let UT = (T - lngHour) % 24;
    if (UT < 0) UT += 24;
    const result = new Date(date);
    result.setUTCHours(0, 0, 0, 0);
    return new Date(result.getTime() + UT * 3600 * 1000);
}

// ----------------------------------------------------------
// Logout button
// ----------------------------------------------------------
function bindLogout() {
    const btn = document.getElementById('btn-settings-logout');
    if (btn) btn.addEventListener('click', Auth.logout);
}
