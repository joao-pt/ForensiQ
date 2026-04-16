(function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    var KEY = 'fq-theme';
    var THEME_COLORS = { midnight: '#0B1220', indigo: '#1a237e' };
    var metaTheme = document.getElementById('meta-theme-color');

    function current() {
        return document.documentElement.getAttribute('data-theme') || 'midnight';
    }

    function apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(KEY, theme);
        if (metaTheme) metaTheme.content = THEME_COLORS[theme] || THEME_COLORS.midnight;
        btn.title = theme === 'midnight'
            ? 'Tema actual: Midnight \u2014 clique para Indigo'
            : 'Tema actual: Indigo \u2014 clique para Midnight';
    }

    btn.addEventListener('click', function () {
        var next = current() === 'midnight' ? 'indigo' : 'midnight';
        apply(next);
    });

    apply(current());
})();
