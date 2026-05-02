/**
 * ForensiQ — Cliente HTTP para a API REST.
 *
 * Usa cookies HttpOnly para autenticação (credentials:'include') e
 * envia o CSRF token em mutações. Em 401 tenta renovar via /refresh/
 * e repete o pedido uma vez.
 */

'use strict';

const API = (() => {
    const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

    function buildHeaders(method, extra) {
        const headers = { 'Content-Type': 'application/json', ...extra };
        if (!SAFE_METHODS.has(method)) {
            headers['X-CSRFToken'] = Auth.getCsrfToken();
        }
        return headers;
    }

    async function request(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const init = {
            ...options,
            method,
            credentials: 'include',
            headers: buildHeaders(method, options.headers),
        };

        let response = await fetch(url, init);

        if (response.status === 401 && await Auth.refreshAccessToken()) {
            init.headers = buildHeaders(method, options.headers);
            response = await fetch(url, init);
        }

        if (response.status === 401) {
            Auth.logout();
            throw new Error('Sessão expirada. Por favor, inicie sessão novamente.');
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail
                || Object.values(errorData).flat().join(' ')
                || `Erro ${response.status}`;
            throw new Error(message);
        }

        if (response.status === 204) return null;
        return response.json();
    }

    async function get(url, params = {}) {
        // Expandir arrays como múltiplos params (?type=A&type=B em vez de
        // ?type=A,B). django-filter MultipleChoiceFilter espera o primeiro.
        const usp = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
            if (v == null) return;
            if (Array.isArray(v)) {
                v.forEach((item) => {
                    if (item != null && item !== '') usp.append(k, String(item));
                });
            } else if (v !== '') {
                usp.set(k, String(v));
            }
        });
        const queryString = usp.toString();
        const fullUrl = queryString ? `${url}?${queryString}` : url;
        return request(fullUrl, { method: 'GET' });
    }

    async function post(url, data = {}) {
        return request(url, { method: 'POST', body: JSON.stringify(data) });
    }

    async function patch(url, data = {}) {
        return request(url, { method: 'PATCH', body: JSON.stringify(data) });
    }

    async function del(url) {
        return request(url, { method: 'DELETE' });
    }

    return { get, post, patch, del, request };
})();
