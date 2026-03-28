/**
 * ForensiQ — Cliente HTTP para a API REST.
 *
 * Wrapper sobre fetch() com:
 * - Inclusão automática do token JWT no header Authorization.
 * - Renovação automática do token quando expira (401).
 * - Tratamento uniforme de erros.
 */

'use strict';

const API = (() => {

    /**
     * Faz um pedido HTTP autenticado à API.
     * Renova automaticamente o token se receber 401.
     *
     * @param {string} url - URL relativa ou absoluta do endpoint.
     * @param {Object} options - Opções do fetch (method, body, etc.).
     * @returns {Promise<Object>} Dados da resposta (JSON).
     * @throws {Error} Se o pedido falhar após tentativa de renovação.
     */
    async function request(url, options = {}) {
        const token = Auth.getAccessToken();

        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };

        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        let response = await fetch(url, { ...options, headers });

        // Token expirado — tentar renovar e repetir o pedido
        if (response.status === 401 && token) {
            const newToken = await Auth.refreshAccessToken();
            if (newToken) {
                headers['Authorization'] = `Bearer ${newToken}`;
                response = await fetch(url, { ...options, headers });
            } else {
                Auth.logout();
                throw new Error('Sessão expirada. Por favor, inicie sessão novamente.');
            }
        }

        // Tratar erros HTTP
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail
                || Object.values(errorData).flat().join(' ')
                || `Erro ${response.status}`;
            throw new Error(message);
        }

        // 204 No Content
        if (response.status === 204) return null;

        return response.json();
    }

    /**
     * GET request.
     * @param {string} url
     * @param {Object} params - Query parameters (opcional).
     * @returns {Promise<Object>}
     */
    async function get(url, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const fullUrl = queryString ? `${url}?${queryString}` : url;
        return request(fullUrl, { method: 'GET' });
    }

    /**
     * POST request.
     * @param {string} url
     * @param {Object} data - Corpo do pedido (será serializado para JSON).
     * @returns {Promise<Object>}
     */
    async function post(url, data = {}) {
        return request(url, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    /**
     * PATCH request (actualização parcial).
     * @param {string} url
     * @param {Object} data
     * @returns {Promise<Object>}
     */
    async function patch(url, data = {}) {
        return request(url, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    /**
     * DELETE request.
     * @param {string} url
     * @returns {Promise<Object|null>}
     */
    async function del(url) {
        return request(url, { method: 'DELETE' });
    }

    // API pública
    return { get, post, patch, del, request };
})();
