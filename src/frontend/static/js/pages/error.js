/**
 * ForensiQ — Páginas de erro (404).
 * Liga o botão "Voltar" ao history.back() sem inline handlers (CSP).
 */
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.getElementById('btn-back');
        if (btn) {
            btn.addEventListener('click', function () {
                if (window.history.length > 1) {
                    window.history.back();
                } else {
                    window.location.href = '/dashboard/';
                }
            });
        }
    });
})();
