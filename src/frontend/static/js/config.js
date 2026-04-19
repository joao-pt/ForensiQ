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
        STATS_DASHBOARD: '/api/stats/dashboard/',
        STATS_LEGACY: '/api/stats/',
        LOOKUP_IMEI: '/api/evidences/lookup/imei/',
        LOOKUP_VIN: '/api/evidences/lookup/vin/',
        HEALTH: '/api/health/',
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

    // Tipos de evidência — 18 tipos (Wave 2a)
    EVIDENCE_TYPES: {
        'MOBILE_DEVICE': 'Telemóvel / Smartphone / Tablet',
        'COMPUTER': 'Computador (PC / portátil / servidor)',
        'GAMING_CONSOLE': 'Consola de Jogos',
        'GPS_TRACKER': 'Rastreador GPS',
        'SMART_TAG': 'AirTag / SmartTag / Tile',
        'CCTV_DEVICE': 'CCTV / DVR / NVR',
        'DRONE': 'Drone / UAV',
        'VEHICLE': 'Veículo',
        'VEHICLE_COMPONENT': 'Componente Electrónico de Veículo',
        'NETWORK_DEVICE': 'Equipamento de Rede',
        'IOT_DEVICE': 'Dispositivo IoT',
        'STORAGE_MEDIA': 'Suporte de Armazenamento Externo',
        'MEMORY_CARD': 'Cartão de Memória (SD / microSD / CF)',
        'INTERNAL_DRIVE': 'Disco Interno (HDD / SSD / NVMe)',
        'SIM_CARD': 'Cartão SIM',
        'RFID_NFC_CARD': 'Cartão RFID / NFC',
        'DIGITAL_FILE': 'Ficheiro Digital (captura)',
        'OTHER_DIGITAL': 'Outro Dispositivo Digital',
    },

    // Agrupamento por família (para <optgroup> no wizard)
    EVIDENCE_TYPE_GROUPS: [
        {
            label: 'Dispositivos pessoais',
            types: ['MOBILE_DEVICE', 'COMPUTER', 'GAMING_CONSOLE'],
        },
        {
            label: 'Localização / Tracking',
            types: ['GPS_TRACKER', 'SMART_TAG'],
        },
        {
            label: 'Vigilância',
            types: ['CCTV_DEVICE', 'DRONE'],
        },
        {
            label: 'Veículos',
            types: ['VEHICLE', 'VEHICLE_COMPONENT'],
        },
        {
            label: 'Rede / IoT',
            types: ['NETWORK_DEVICE', 'IOT_DEVICE'],
        },
        {
            label: 'Suportes de armazenamento',
            types: ['STORAGE_MEDIA', 'MEMORY_CARD', 'INTERNAL_DRIVE'],
        },
        {
            label: 'Cartões',
            types: ['SIM_CARD', 'RFID_NFC_CARD'],
        },
        {
            label: 'Outros',
            types: ['DIGITAL_FILE', 'OTHER_DIGITAL'],
        },
    ],

    // Ícones foram migrados para `icons.js` (SVG profissionais, linhagem
    // Lucide). Usar `Icons.forEvidence(type)` ou `Icons.forEvidenceElement(type)`
    // em consumidores. A chave anterior (EVIDENCE_ICONS com emojis) foi removida.

    // Cores de badge por tipo (classes CSS existentes)
    EVIDENCE_BADGE_COLORS: {
        'MOBILE_DEVICE': 'blue',
        'COMPUTER': 'blue',
        'GAMING_CONSOLE': 'default',
        'GPS_TRACKER': 'orange',
        'SMART_TAG': 'orange',
        'CCTV_DEVICE': 'red',
        'DRONE': 'orange',
        'VEHICLE': 'red',
        'VEHICLE_COMPONENT': 'default',
        'NETWORK_DEVICE': 'green',
        'IOT_DEVICE': 'green',
        'STORAGE_MEDIA': 'green',
        'MEMORY_CARD': 'green',
        'INTERNAL_DRIVE': 'green',
        'SIM_CARD': 'blue',
        'RFID_NFC_CARD': 'default',
        'DIGITAL_FILE': 'orange',
        'OTHER_DIGITAL': 'default',
    },

    // Sugestões de sub-componentes por tipo-pai — não bloqueante
    EVIDENCE_CHILD_SUGGESTIONS: {
        'MOBILE_DEVICE': ['SIM_CARD', 'MEMORY_CARD', 'INTERNAL_DRIVE', 'OTHER_DIGITAL'],
        'COMPUTER': ['INTERNAL_DRIVE', 'MEMORY_CARD', 'STORAGE_MEDIA', 'OTHER_DIGITAL'],
        'GAMING_CONSOLE': ['INTERNAL_DRIVE', 'MEMORY_CARD', 'STORAGE_MEDIA', 'OTHER_DIGITAL'],
        'VEHICLE': ['VEHICLE_COMPONENT', 'SIM_CARD', 'MEMORY_CARD', 'OTHER_DIGITAL'],
        'VEHICLE_COMPONENT': ['SIM_CARD', 'MEMORY_CARD', 'OTHER_DIGITAL'],
        'CCTV_DEVICE': ['INTERNAL_DRIVE', 'MEMORY_CARD', 'OTHER_DIGITAL'],
        'DRONE': ['MEMORY_CARD', 'INTERNAL_DRIVE', 'OTHER_DIGITAL'],
        'NETWORK_DEVICE': ['INTERNAL_DRIVE', 'MEMORY_CARD', 'OTHER_DIGITAL'],
        'IOT_DEVICE': ['SIM_CARD', 'MEMORY_CARD', 'OTHER_DIGITAL'],
        'GPS_TRACKER': ['SIM_CARD', 'MEMORY_CARD'],
    },

    // Profundidade máxima da árvore pai-filho (ISO/IEC 27037 — evitar
    // detalhe excessivo)
    MAX_TREE_DEPTH: 3,

    // Perfis de utilizador
    PROFILES: {
        'AGENT': 'Agente / First Responder',
        'EXPERT': 'Perito Forense Digital',
    },
});
