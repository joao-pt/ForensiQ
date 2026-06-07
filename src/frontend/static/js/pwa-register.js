/* ForensiQ — Registo do service worker (PWA). CSP-safe (ficheiro 'self'). */
(function () {
    'use strict';
    if (!('serviceWorker' in navigator)) return;
    window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js').catch(function () {
            /* silencioso — a app funciona na mesma sem SW */
        });
    });
})();
