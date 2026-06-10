/**
 * ForensiQ — Constantes de tema (fonte ÚNICA — auditoria D92).
 *
 * Carregado ANTES de theme-init.js / theme-switch.js (ordem garantida em
 * base.html). Expõe a chave do localStorage e as cores de chrome do browser —
 * o par do <meta name="theme-color"> (partials/_head_meta.html) e dos tokens
 * --bg de main.css. Mudar a paleta de fundo edita-se AQUI + main.css.
 */
window.FQTheme = {
    KEY: 'fq-theme',
    META: { dark: '#0F1115', light: '#FAFAF9' }
};
