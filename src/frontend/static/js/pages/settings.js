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
// Logout button
// ----------------------------------------------------------
function bindLogout() {
    const btn = document.getElementById('btn-settings-logout');
    if (btn) btn.addEventListener('click', Auth.logout);
}
