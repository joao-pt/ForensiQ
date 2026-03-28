/**
 * ForensiQ — Módulo de autenticação JWT.
 *
 * Gere tokens de acesso e refresh, login, logout e verificação de sessão.
 * Os tokens são armazenados em localStorage.
 */

'use strict';

const Auth = (() => {

    /**
     * Efectua login com username e password.
     * @param {string} username
     * @param {string} password
     * @returns {Promise<Object>} Dados do utilizador autenticado.
     * @throws {Error} Se as credenciais forem inválidas.
     */
    async function login(username, password) {
        const response = await fetch(CONFIG.AUTH.TOKEN, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || 'Credenciais inválidas.');
        }

        const tokens = await response.json();
        localStorage.setItem(CONFIG.STORAGE.ACCESS_TOKEN, tokens.access);
        localStorage.setItem(CONFIG.STORAGE.REFRESH_TOKEN, tokens.refresh);

        // Cookie para verificação server-side (protege templates HTML)
        _setAccessCookie(tokens.access);

        // Obter dados do utilizador
        const user = await fetchCurrentUser(tokens.access);
        localStorage.setItem(CONFIG.STORAGE.USER_DATA, JSON.stringify(user));

        return user;
    }

    /**
     * Obtém os dados do utilizador autenticado (/api/users/me/).
     * @param {string} accessToken
     * @returns {Promise<Object>}
     */
    async function fetchCurrentUser(accessToken) {
        const response = await fetch(CONFIG.ENDPOINTS.USERS_ME, {
            headers: { 'Authorization': `Bearer ${accessToken}` },
        });

        if (!response.ok) {
            throw new Error('Não foi possível obter os dados do utilizador.');
        }

        return response.json();
    }

    /**
     * Tenta renovar o token de acesso usando o refresh token.
     * @returns {Promise<string|null>} Novo access token ou null se falhar.
     */
    async function refreshAccessToken() {
        const refreshToken = localStorage.getItem(CONFIG.STORAGE.REFRESH_TOKEN);
        if (!refreshToken) return null;

        try {
            const response = await fetch(CONFIG.AUTH.REFRESH, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh: refreshToken }),
            });

            if (!response.ok) return null;

            const data = await response.json();
            localStorage.setItem(CONFIG.STORAGE.ACCESS_TOKEN, data.access);
            _setAccessCookie(data.access);

            // Se o backend devolver novo refresh token (rotate)
            if (data.refresh) {
                localStorage.setItem(CONFIG.STORAGE.REFRESH_TOKEN, data.refresh);
            }

            return data.access;
        } catch {
            return null;
        }
    }

    /**
     * Termina sessão — limpa tokens e dados do utilizador.
     */
    function logout() {
        localStorage.removeItem(CONFIG.STORAGE.ACCESS_TOKEN);
        localStorage.removeItem(CONFIG.STORAGE.REFRESH_TOKEN);
        localStorage.removeItem(CONFIG.STORAGE.USER_DATA);
        // Limpar cookie de verificação server-side
        document.cookie = 'forensiq_access=; path=/; max-age=0; SameSite=Strict';
        window.location.href = '/login/';
    }

    /**
     * Retorna o access token actual (ou null).
     * @returns {string|null}
     */
    function getAccessToken() {
        return localStorage.getItem(CONFIG.STORAGE.ACCESS_TOKEN);
    }

    /**
     * Retorna os dados do utilizador guardados em cache.
     * @returns {Object|null}
     */
    function getUser() {
        const data = localStorage.getItem(CONFIG.STORAGE.USER_DATA);
        return data ? JSON.parse(data) : null;
    }

    /**
     * Verifica se o utilizador está autenticado.
     * Tenta renovar o token se necessário.
     * @returns {Promise<boolean>}
     */
    async function isAuthenticated() {
        const token = getAccessToken();
        if (!token) return false;

        // Verificar se o token ainda é válido
        try {
            const response = await fetch(CONFIG.AUTH.VERIFY, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token }),
            });

            if (response.ok) return true;

            // Token expirado — tentar renovar
            const newToken = await refreshAccessToken();
            return newToken !== null;
        } catch {
            return false;
        }
    }

    /**
     * Garante que o utilizador está autenticado.
     * Redireciona para login se não estiver.
     */
    async function requireAuth() {
        const authenticated = await isAuthenticated();
        if (!authenticated) {
            window.location.href = '/login/';
            return false;
        }
        return true;
    }

    /**
     * Define o cookie 'forensiq_access' para verificação server-side.
     * SameSite=Strict previne CSRF. max-age alinhado com lifetime do token.
     * @param {string} token - Access token JWT.
     */
    function _setAccessCookie(token) {
        const maxAge = 3600; // 1 hora (alinhado com JWT_ACCESS_TOKEN_LIFETIME)
        document.cookie = `forensiq_access=${token}; path=/; max-age=${maxAge}; SameSite=Strict`;
    }

    // API pública
    return {
        login,
        logout,
        refreshAccessToken,
        getAccessToken,
        getUser,
        isAuthenticated,
        requireAuth,
    };
})();
