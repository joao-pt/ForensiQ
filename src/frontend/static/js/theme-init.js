/**
 * ForensiQ — Theme init (dia / noite).
 *
 * Aplica o tema antes do primeiro paint para evitar flash (FOUC).
 *
 * Página de login (/login, /): tema é determinado pela hora local do
 * browser (07h–19h light, fora dark). Não lê nem escreve localStorage —
 * antes do utilizador autenticar não há preferência pessoal a recordar.
 *
 * Restantes páginas — ordem de decisão:
 *   1. Preferência guardada pelo utilizador (localStorage 'fq-theme').
 *   2. Preferência do sistema operativo (prefers-color-scheme).
 *   3. Default: dark (noite) — é a marca forense ForensiQ.
 *
 * Valores aceites: 'dark' | 'light'.
 */
(function () {
    try {
        var path = window.location.pathname;
        var isLogin = path === '/' || path.indexOf('/login') === 0;

        var theme;
        if (isLogin) {
            var h = new Date().getHours();
            theme = (h >= 7 && h < 19) ? 'light' : 'dark';
        } else {
            var saved = localStorage.getItem('fq-theme');
            if (saved === 'light' || saved === 'dark') {
                theme = saved;
            } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
                theme = 'light';
            } else {
                theme = 'dark';
            }
        }

        document.documentElement.setAttribute('data-theme', theme);

        // Alinhar a chrome do browser (barra de endereço mobile, splash iOS)
        // com o tema resolvido, ainda antes do primeiro paint, para não ficar
        // a cor dark fixa do <meta> enquanto o resto do <head> não termina.
        // As cores espelham theme-switch.js (META_COLORS).
        var meta = document.getElementById('meta-theme-color');
        if (meta) meta.content = theme === 'light' ? '#FAFAF9' : '#0F1115';
    } catch (err) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
})();
