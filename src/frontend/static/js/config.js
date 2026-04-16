/**
 * ForensiQ — Configuração global do frontend.
 *
 * Centraliza constantes, URLs da API e definições de estado.
 */

'use strict';

const CONFIG = Object.freeze({
    // URL base da API (ajustar em produção)
    API_BASE: '/api',

    // Endpoints de autenticação (cookies HttpOnly — sem exposição ao JS)
    AUTH: {
        LOGIN: '/api/auth/login/',
        REFRESH: '/api/auth/refresh/',
        LOGOUT: '/api/auth/logout/',
    },

    // Endpoints REST
    ENDPOINTS: {
        USERS: '/api/users/',
        USERS_ME: '/api/users/me/',
        OCCURRENCES: '/api/occurrences/',
        EVIDENCES: '/api/evidences/',
        DEVICES: '/api/devices/',
        CUSTODY: '/api/custody/',
    },

    // Estados da cadeia de custódia (correspondem ao backend)
    CUSTODY_STATES: {
        'APREENDIDA': 'Apreendida',
        'EM_TRANSPORTE': 'Em Transporte',
        'RECEBIDA_LABORATORIO': 'Recebida no Laboratório',
        'EM_PERICIA': 'Em Perícia',
        'CONCLUIDA': 'Concluída',
        'DEVOLVIDA': 'Devolvida',
        'DESTRUIDA': 'Destruída',
    },

    // Tipos de evidência
    EVIDENCE_TYPES: {
        'DIGITAL_DEVICE': 'Dispositivo Digital',
        'DOCUMENT': 'Documento',
        'STORAGE_MEDIA': 'Suporte de Armazenamento',
        'PHOTO': 'Fotografia',
        'OTHER': 'Outro',
    },

    // Perfis de utilizador
    PROFILES: {
        'AGENT': 'Agente / First Responder',
        'EXPERT': 'Perito Forense Digital',
    },
});
