/**
 * ForensiQ — Autenticação via cookies HttpOnly.
 *
 * O token JWT nunca é exposto ao JavaScript (HttpOnly). Pedidos de
 * escrita enviam o CSRF token no header X-CSRFToken. Os dados do
 * utilizador são obtidos em /api/users/me/ e mantidos apenas em
 * memória para esta página (nada em localStorage).
 */

'use strict';

const Auth = (() => {
    let userCache = null;

    function getCsrfToken() {
        const row = document.cookie.split('; ').find(r => r.startsWith('csrftoken='));
        return row ? row.split('=')[1] : '';
    }

    async function login(username, password) {
        const response = await fetch(CONFIG.AUTH.LOGIN, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ username, password }),
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || 'Credenciais inválidas.');
        }

        const data = await response.json();
        userCache = data.user;
        return userCache;
    }

    async function refreshAccessToken() {
        try {
            const response = await fetch(CONFIG.AUTH.REFRESH, {
                method: 'POST',
                credentials: 'include',
                headers: { 'X-CSRFToken': getCsrfToken() },
            });
            return response.ok;
        } catch {
            return false;
        }
    }

    async function fetchCurrentUser() {
        const response = await fetch(CONFIG.ENDPOINTS.USERS_ME, {
            credentials: 'include',
        });
        if (!response.ok) return null;
        userCache = await response.json();
        return userCache;
    }

    async function logout() {
        try {
            await fetch(CONFIG.AUTH.LOGOUT, {
                method: 'POST',
                credentials: 'include',
                headers: { 'X-CSRFToken': getCsrfToken() },
            });
        } catch { /* ignore */ }
        userCache = null;
        window.location.href = '/login/';
    }

    function getUser() {
        return userCache;
    }

    async function isAuthenticated() {
        const user = await fetchCurrentUser();
        if (user) return true;

        const refreshed = await refreshAccessToken();
        if (!refreshed) return false;

        const retry = await fetchCurrentUser();
        return retry !== null;
    }

    async function requireAuth() {
        const authenticated = await isAuthenticated();
        if (!authenticated) {
            window.location.href = '/login/';
            return false;
        }
        return true;
    }

    return {
        login,
        logout,
        refreshAccessToken,
        fetchCurrentUser,
        getUser,
        getCsrfToken,
        isAuthenticated,
        requireAuth,
    };
})();
