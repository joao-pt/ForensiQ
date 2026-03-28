/**
 * ForensiQ — Sistema de notificações toast.
 *
 * Mostra mensagens temporárias ao utilizador (sucesso, erro, aviso).
 */

'use strict';

const Toast = (() => {

    const DURATION = 4000; // 4 segundos

    /**
     * Mostra uma notificação toast.
     * @param {string} message - Texto da mensagem.
     * @param {'success'|'error'|'warning'|'info'} type - Tipo de toast.
     */
    function show(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);

        // Remover após a duração
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, DURATION);
    }

    function success(message) { show(message, 'success'); }
    function error(message) { show(message, 'error'); }
    function warning(message) { show(message, 'warning'); }
    function info(message) { show(message, 'info'); }

    return { show, success, error, warning, info };
})();
