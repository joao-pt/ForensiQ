/**
 * ForensiQ — Theme switch (dia / noite).
 *
 * Alterna entre dark (noite) e light (dia). Guarda preferência em
 * localStorage e atualiza <meta name="theme-color"> para integrar com a
 * chrome do browser (barra de endereço em mobile, splash no iOS).
 *
 * Audit #12 — anuncia mudança a leitores de ecrã via aria-pressed e
 * live region, para que utilizadores não-sighted percebam o feedback
 * da acção sem depender de cor.
 */
(function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    var KEY = 'fq-theme';
    var META_COLORS = { dark: '#0F1115', light: '#FAFAF9' };
    var metaTheme   = document.getElementById('meta-theme-color');
    var announcer   = document.getElementById('theme-announce');
    var iconSun     = btn.querySelector('.icon-sun');
    var iconMoon    = btn.querySelector('.icon-moon');

    function current() {
        return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    }

    function apply(theme, announce) {
        document.documentElement.setAttribute('data-theme', theme);
        try { localStorage.setItem(KEY, theme); } catch (e) { /* privado/quota */ }

        if (metaTheme) metaTheme.content = META_COLORS[theme] || META_COLORS.dark;

        // Ícone mostra o *destino* da próxima troca, à la Notion:
        //   - estás no dark → mostra o Sol (vais para o dia se clicares)
        //   - estás no light → mostra a Lua (vais para a noite se clicares)
        if (iconSun && iconMoon) {
            iconSun.hidden  = theme !== 'dark';
            iconMoon.hidden = theme === 'dark';
        }

        // aria-pressed: true = tema claro activo (botão "pressionado" para mudar).
        // Combinado com aria-label dinâmico, o leitor anuncia estado actual e acção.
        btn.setAttribute('aria-pressed', theme === 'light' ? 'true' : 'false');
        var nextLabel = theme === 'dark' ? 'Passar para modo dia' : 'Passar para modo noite';
        btn.setAttribute('aria-label', nextLabel);
        btn.title = nextLabel;

        if (announce && announcer) {
            announcer.textContent = theme === 'dark' ? 'Modo noite ativado' : 'Modo dia ativado';
        }
    }

    btn.addEventListener('click', function () {
        apply(current() === 'dark' ? 'light' : 'dark', true);
    });

    apply(current(), false);
})();
