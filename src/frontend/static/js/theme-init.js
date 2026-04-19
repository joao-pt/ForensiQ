/**
 * ForensiQ — Theme init (dia / noite).
 *
 * Aplica o tema antes do primeiro paint para evitar flash (FOUC).
 * Ordem de decisão:
 *   1. Preferência guardada pelo utilizador (localStorage).
 *   2. Preferência do sistema operativo (prefers-color-scheme).
 *   3. Default: dark (noite) — é a marca forense ForensiQ.
 *
 * Valores aceites: 'dark' | 'light'.
 */
(function () {
    try {
        var saved = localStorage.getItem('fq-theme');
        var theme;

        if (saved === 'light' || saved === 'dark') {
            theme = saved;
        } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            theme = 'light';
        } else {
            theme = 'dark';
        }

        document.documentElement.setAttribute('data-theme', theme);
    } catch (err) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
})();
