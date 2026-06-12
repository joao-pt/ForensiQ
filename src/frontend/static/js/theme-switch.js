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

    // Chave + cores na fonte única window.FQTheme (theme-constants.js — D92).
    var KEY = window.FQTheme.KEY;
    var META_COLORS = window.FQTheme.META;
    var metaTheme   = document.getElementById('meta-theme-color');
    var announcer   = document.getElementById('theme-announce');
    var iconSun     = btn.querySelector('.icon-sun');
    var iconMoon    = btn.querySelector('.icon-moon');
    // Seletor Claro/Escuro/Auto das Definições (item 19) — só existe lá.
    var select      = document.querySelector('[data-theme-select]');

    function current() {
        return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    }

    function saved() {
        try { return localStorage.getItem(KEY); } catch (e) { return null; }
    }

    function autoTheme() {
        return (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches)
            ? 'light' : 'dark';
    }

    // `persist=false` aplica o VISUAL sem gravar — essencial para o modo
    // 'auto' (gravar o tema resolvido destruiria a preferência) e para a
    // chamada inicial (que antes re-gravava sempre e matava o 'auto').
    function apply(theme, announce, persist) {
        document.documentElement.setAttribute('data-theme', theme);
        if (persist) {
            try { localStorage.setItem(KEY, theme); } catch (e) { /* privado/quota */ }
            if (select) select.value = theme;
        }

        if (metaTheme) metaTheme.content = META_COLORS[theme] || META_COLORS.dark;

        // Ícone mostra o *destino* da próxima troca, à la Notion:
        //   - estás no dark → mostra o Sol (vais para o dia se clicares)
        //   - estás no light → mostra a Lua (vais para a noite se clicares)
        // Nota: em SVG o IDL `el.hidden` não reflecte o atributo HTML em todos
        // os browsers, por isso usamos setAttribute/removeAttribute para
        // garantir que o seletor [hidden] aplica.
        if (iconSun && iconMoon) {
            if (theme === 'dark') {
                iconSun.removeAttribute('hidden');
                iconMoon.setAttribute('hidden', '');
            } else {
                iconSun.setAttribute('hidden', '');
                iconMoon.removeAttribute('hidden');
            }
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
        // O toggle do cabeçalho continua binário: escolhe um tema EXPLÍCITO
        // (sai do modo 'auto', se ativo).
        apply(current() === 'dark' ? 'light' : 'dark', true, true);
    });

    if (select) {
        var pref = saved();
        select.value = (pref === 'dark' || pref === 'light') ? pref : 'auto';
        select.addEventListener('change', function () {
            if (select.value === 'auto') {
                try { localStorage.setItem(KEY, 'auto'); } catch (e) { /* privado/quota */ }
                apply(autoTheme(), true, false);
            } else {
                apply(select.value, true, true);
            }
        });
    }

    // Em modo 'auto', re-resolve ao vivo quando o SO muda de claro/escuro.
    if (window.matchMedia) {
        var mq = window.matchMedia('(prefers-color-scheme: light)');
        var onOsChange = function () { if (saved() === 'auto') apply(autoTheme(), false, false); };
        if (mq.addEventListener) mq.addEventListener('change', onOsChange);
        else if (mq.addListener) mq.addListener(onOsChange);
    }

    apply(current(), false, false);
})();
