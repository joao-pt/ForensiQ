/**
 * ForensiQ — Configuração global do frontend.
 *
 * Reduzido ao mínimo que o cliente de autenticação (auth.js) consome:
 * os endpoints de sessão e o /me/. O domínio (tipos de prova, perfis,
 * eventos de custódia) é renderizado server-side pelo Django, pelo que
 * não se duplica aqui — manter dicionários paralelos só gera deriva
 * entre frontend e backend.
 */

'use strict';

const CONFIG = Object.freeze({
    // Endpoints de autenticação (cookies HttpOnly — sem exposição ao JS)
    AUTH: {
        LOGIN: '/api/auth/login/',
        REFRESH: '/api/auth/refresh/',
        LOGOUT: '/api/auth/logout/',
    },

    // Identidade do utilizador autenticado.
    ENDPOINTS: {
        USERS_ME: '/api/users/me/',
    },
});
