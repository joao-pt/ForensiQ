/**
 * ForensiQ — Ícones SVG (linhagem Lucide).
 *
 * Biblioteca mínima de ícones usados pela aplicação. SVG line-icons
 * 24×24, stroke 1.8, rounded caps. Substituem os emojis que antes
 * tornavam a UI inconsistente entre plataformas (Windows vs macOS)
 * e pouco profissional num contexto forense.
 *
 * API:
 *   Icons.svg(name, opts?)               → string com <svg>...</svg>
 *   Icons.element(name, opts?)           → SVGElement (createElementNS)
 *   Icons.forEvidence(type, opts?)       → string SVG para tipo de evidência
 *   Icons.forEvidenceElement(type, opts?)→ SVGElement idem
 *
 * Opções: { size: 18, strokeWidth: 1.8, className: 'foo' }
 *
 * Notação: todos os ícones usam currentColor — a cor vem do CSS do pai.
 * Construímos o DOM via createElementNS (sem innerHTML) — CSP-safe.
 */
'use strict';

(function (global) {

    var NS = 'http://www.w3.org/2000/svg';

    // Cada entrada é um array de nós filhos; cada nó tem { type, ...attrs }.
    var PATHS = {

        // ---------- Navegação / UI genérica ----------
        'plus':         [{ type: 'path', d: 'M12 5v14M5 12h14' }],
        'minus':        [{ type: 'path', d: 'M5 12h14' }],
        'search':       [
            { type: 'circle', cx: 11, cy: 11, r: 7 },
            { type: 'path', d: 'm21 21-4.3-4.3' }
        ],
        'arrow-right':  [{ type: 'path', d: 'M5 12h14m-6-6 6 6-6 6' }],
        'arrow-left':   [{ type: 'path', d: 'M19 12H5m6 6-6-6 6-6' }],
        'chevron-left': [{ type: 'path', d: 'm15 18-6-6 6-6' }],
        'chevron-right':[{ type: 'path', d: 'm9 18 6-6-6-6' }],
        'close':        [{ type: 'path', d: 'M18 6 6 18M6 6l12 12' }],
        'check':        [{ type: 'path', d: 'm5 12 5 5L20 7' }],
        'sun':          [
            { type: 'circle', cx: 12, cy: 12, r: 4 },
            { type: 'path', d: 'M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41' }
        ],
        'moon':         [{ type: 'path', d: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z' }],
        'alert':        [
            { type: 'circle', cx: 12, cy: 12, r: 9 },
            { type: 'path', d: 'M12 8v5M12 16h.01' }
        ],
        'info':         [
            { type: 'circle', cx: 12, cy: 12, r: 9 },
            { type: 'path', d: 'M12 16v-4M12 8h.01' }
        ],

        // ---------- Domínio forense (navegação + dashboard) ----------
        'folder':       [{ type: 'path', d: 'M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z' }],
        'shield':       [{ type: 'path', d: 'M12 3 4 6v6c0 5 3.5 9 8 10 4.5-1 8-5 8-10V6l-8-3z' }],
        'shield-check': [
            { type: 'path', d: 'M12 3 4 6v6c0 5 3.5 9 8 10 4.5-1 8-5 8-10V6l-8-3z' },
            { type: 'path', d: 'm9 12 2 2 4-4' }
        ],
        'lock':         [
            { type: 'rect', x: 5, y: 11, width: 14, height: 9, rx: 2 },
            { type: 'path', d: 'M8 11V7a4 4 0 0 1 8 0v4' }
        ],
        'link':         [
            { type: 'path', d: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5' },
            { type: 'path', d: 'M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5' }
        ],
        'file-text':    [
            { type: 'path', d: 'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z' },
            { type: 'path', d: 'M14 3v6h6M9 13h6M9 17h4' }
        ],
        'bar-chart':    [{ type: 'path', d: 'M3 20h18M6 16V9M11 16V5M16 16v-8M21 16V11' }],
        'settings':     [
            { type: 'circle', cx: 12, cy: 12, r: 3 },
            { type: 'path', d: 'M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z' }
        ],
        'log-out':      [
            { type: 'path', d: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4' },
            { type: 'path', d: 'm16 17 5-5-5-5M21 12H9' }
        ],
        'user':         [
            { type: 'circle', cx: 12, cy: 8, r: 4 },
            { type: 'path', d: 'M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8' }
        ],
        'map-pin':      [
            { type: 'path', d: 'M12 2a8 8 0 0 0-8 8c0 6 8 12 8 12s8-6 8-12a8 8 0 0 0-8-8z' },
            { type: 'circle', cx: 12, cy: 10, r: 3 }
        ],
        'upload':       [{ type: 'path', d: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12' }],

        // ---------- Tipos de evidência (18 tipos — Wave 2a) ----------
        'smartphone':   [
            { type: 'rect', x: 7, y: 2, width: 10, height: 20, rx: 2 },
            { type: 'path', d: 'M11 18h2' }
        ],
        'laptop':       [
            { type: 'rect', x: 4, y: 5, width: 16, height: 11, rx: 2 },
            { type: 'path', d: 'M2 20h20' }
        ],
        'gamepad':      [
            { type: 'path', d: 'M6 12h4M8 10v4' },
            { type: 'circle', cx: 15, cy: 13, r: 1 },
            { type: 'circle', cx: 17, cy: 11, r: 1 },
            { type: 'rect', x: 2, y: 7, width: 20, height: 10, rx: 5 }
        ],
        'satellite':    [
            { type: 'path', d: 'M4 10a6 6 0 0 1 6-6M4 14a10 10 0 0 1 6 3' },
            { type: 'path', d: 'm13.5 6.5 4 4-3 3-4-4 3-3zM14 14l6 6' }
        ],
        'tag':          [
            { type: 'path', d: 'M21 12 12 21 3 12V3h9z' },
            { type: 'circle', cx: 8, cy: 8, r: 1.2 }
        ],
        'cctv':         [
            { type: 'path', d: 'M2 10V6a2 2 0 0 1 2-2h10v8H4a2 2 0 0 1-2-2z' },
            { type: 'path', d: 'M14 6h5l3 3-3 3h-5M8 12v4a2 2 0 0 0 2 2h2' }
        ],
        'drone':        [
            { type: 'circle', cx: 5, cy: 6, r: 2 },
            { type: 'circle', cx: 19, cy: 6, r: 2 },
            { type: 'circle', cx: 5, cy: 18, r: 2 },
            { type: 'circle', cx: 19, cy: 18, r: 2 },
            { type: 'path', d: 'M7 6h10M7 18h10M5 8v8M19 8v8' },
            { type: 'rect', x: 9, y: 10, width: 6, height: 4, rx: 1 }
        ],
        'car':          [
            { type: 'path', d: 'M5 17h14M3 13l2-5a2 2 0 0 1 2-1h10a2 2 0 0 1 2 1l2 5v4a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-1H7v1a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-4z' },
            { type: 'circle', cx: 7.5, cy: 15.5, r: 1 },
            { type: 'circle', cx: 16.5, cy: 15.5, r: 1 }
        ],
        'wrench':       [{ type: 'path', d: 'M15 3a5 5 0 0 1 3.8 8.2L21 13.4 13.4 21l-2.2-2.2A5 5 0 0 1 3 15l3 3 3-3-3-3 3-3 3 3a5 5 0 0 1 3-6z' }],
        'network':      [
            { type: 'rect', x: 4, y: 15, width: 16, height: 6, rx: 1 },
            { type: 'path', d: 'M8 15v-4h8v4M12 11V6M10 6h4' }
        ],
        'lightbulb':    [
            { type: 'path', d: 'M9 18h6M10 21h4' },
            { type: 'path', d: 'M12 3a6 6 0 0 0-4 10.5c.7.8 1 1.7 1 2.5h6c0-.8.3-1.7 1-2.5A6 6 0 0 0 12 3z' }
        ],
        'hard-drive':   [
            { type: 'rect', x: 3, y: 13, width: 18, height: 6, rx: 1 },
            { type: 'path', d: 'M21 13 17.5 5a1 1 0 0 0-1-.6h-9a1 1 0 0 0-1 .6L3 13' },
            { type: 'circle', cx: 7, cy: 16, r: 0.8 }
        ],
        'sd-card':      [
            { type: 'path', d: 'M6 2h9l4 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z' },
            { type: 'path', d: 'M9 6v3M12 6v3M15 6v3' }
        ],
        'disc':         [
            { type: 'circle', cx: 12, cy: 12, r: 9 },
            { type: 'circle', cx: 12, cy: 12, r: 3 }
        ],
        'sim-card':     [
            { type: 'path', d: 'M5 2h10l4 4v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z' },
            { type: 'path', d: 'M8 10h8v8H8zM8 14h8M12 10v8' }
        ],
        'credit-card':  [
            { type: 'rect', x: 3, y: 6, width: 18, height: 13, rx: 2 },
            { type: 'path', d: 'M3 10h18' }
        ],
        'file':         [
            { type: 'path', d: 'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z' },
            { type: 'path', d: 'M14 3v6h6' }
        ],
        'box':          [
            { type: 'path', d: 'M21 8 12 3 3 8v8l9 5 9-5V8z' },
            { type: 'path', d: 'M3 8 12 13 21 8M12 13v8' }
        ]
    };

    // Mapa tipo-de-evidência → nome de ícone.
    var EVIDENCE_TO_ICON = {
        'MOBILE_DEVICE':      'smartphone',
        'COMPUTER':           'laptop',
        'GAMING_CONSOLE':     'gamepad',
        'GPS_TRACKER':        'satellite',
        'SMART_TAG':          'tag',
        'CCTV_DEVICE':        'cctv',
        'DRONE':              'drone',
        'VEHICLE':            'car',
        'VEHICLE_COMPONENT':  'wrench',
        'NETWORK_DEVICE':     'network',
        'IOT_DEVICE':         'lightbulb',
        'STORAGE_MEDIA':      'hard-drive',
        'MEMORY_CARD':        'sd-card',
        'INTERNAL_DRIVE':     'disc',
        'SIM_CARD':           'sim-card',
        'RFID_NFC_CARD':      'credit-card',
        'DIGITAL_FILE':       'file',
        'OTHER_DIGITAL':      'box'
    };

    // ---------- Helpers --------------------------------------------------

    function escapeAttr(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;');
    }

    function serializeChildren(children) {
        return children.map(function (node) {
            var parts = [node.type];
            Object.keys(node).forEach(function (key) {
                if (key === 'type') return;
                parts.push(key + '="' + escapeAttr(node[key]) + '"');
            });
            return '<' + parts.join(' ') + '/>';
        }).join('');
    }

    /** Devolve markup SVG como string. Todos os valores são confiáveis (hardcoded). */
    function svg(name, opts) {
        var children = PATHS[name];
        if (!children) return '';

        opts = opts || {};
        var size   = opts.size || 18;
        var stroke = opts.strokeWidth || 1.8;
        var cls    = opts.className ? ' class="' + escapeAttr(opts.className) + '"' : '';

        return '<svg xmlns="' + NS + '"' + cls +
               ' width="' + size + '" height="' + size + '"' +
               ' viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
               ' stroke-width="' + stroke + '" stroke-linecap="round"' +
               ' stroke-linejoin="round" aria-hidden="true">' +
               serializeChildren(children) +
               '</svg>';
    }

    /**
     * Constrói um SVGElement via createElementNS — caminho CSP-safe.
     * Preferir em código novo que manipula DOM diretamente.
     */
    function element(name, opts) {
        var children = PATHS[name];
        if (!children) return null;

        opts = opts || {};
        var size   = opts.size || 18;
        var stroke = opts.strokeWidth || 1.8;

        var root = document.createElementNS(NS, 'svg');
        root.setAttribute('width', size);
        root.setAttribute('height', size);
        root.setAttribute('viewBox', '0 0 24 24');
        root.setAttribute('fill', 'none');
        root.setAttribute('stroke', 'currentColor');
        root.setAttribute('stroke-width', stroke);
        root.setAttribute('stroke-linecap', 'round');
        root.setAttribute('stroke-linejoin', 'round');
        root.setAttribute('aria-hidden', 'true');
        if (opts.className) root.setAttribute('class', opts.className);

        children.forEach(function (node) {
            var child = document.createElementNS(NS, node.type);
            Object.keys(node).forEach(function (key) {
                if (key === 'type') return;
                child.setAttribute(key, node[key]);
            });
            root.appendChild(child);
        });

        return root;
    }

    function forEvidence(type, opts) {
        return svg(EVIDENCE_TO_ICON[type] || 'box', opts);
    }

    function forEvidenceElement(type, opts) {
        return element(EVIDENCE_TO_ICON[type] || 'box', opts);
    }

    global.Icons = {
        svg: svg,
        element: element,
        forEvidence: forEvidence,
        forEvidenceElement: forEvidenceElement,
        has: function (name) { return Object.prototype.hasOwnProperty.call(PATHS, name); }
    };
})(window);
