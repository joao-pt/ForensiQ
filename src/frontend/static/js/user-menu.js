/**
 * ForensiQ — Fim de sessão (navbar).
 *
 * O canto direito do cabeçalho tem um único controlo: terminar sessão. As
 * iniciais (avatar) identificam a sessão; o nome completo vive no chip de
 * contexto. Clicar abre uma confirmação num <dialog> nativo central
 * (showModal): escurece e inativa o resto da página (::backdrop) e prende o
 * foco até o utilizador decidir. Sair só acontece após confirmação explícita —
 * Cancelar, Esc ou clique no fundo cancelam.
 *
 * CSP-safe: sem inline handlers, sem dependências externas.
 */
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var trigger = document.getElementById('user-menu-trigger');
        if (!trigger) return;

        // ---- Avatar (iniciais) ----
        populateAvatar();

        async function populateAvatar() {
            if (typeof Auth === 'undefined') return;

            var user = Auth.getUser ? Auth.getUser() : null;
            if (!user && Auth.isAuthenticated) {
                try {
                    var ok = await Auth.isAuthenticated();
                    if (!ok) return;
                    user = Auth.getUser ? Auth.getUser() : null;
                } catch (e) { /* ignore */ }
            }
            if (!user) return;

            setText('user-avatar', computeInitials(user.first_name, user.last_name, user.username));
        }

        function computeInitials(first, last, username) {
            var source = ((first || '') + ' ' + (last || '')).trim();
            if (!source) source = username || '?';

            var parts = source.split(/\s+/);
            var a = (parts[0] || '').charAt(0);
            var b = (parts[parts.length - 1] || '').charAt(0);
            return ((a + (parts.length > 1 ? b : '')).toUpperCase()) || '?';
        }

        function setText(id, value) {
            var el = document.getElementById(id);
            if (el) el.textContent = value;
        }

        // ---- Confirmação de fim de sessão (<dialog> nativo) ----
        var dialog     = document.getElementById('logout-dialog');
        var confirmBtn = document.getElementById('logout-confirm');
        var cancelBtn  = document.getElementById('logout-cancel');

        function openDialog() {
            // Sem diálogo (markup ausente): degrada para a ação directa.
            if (!dialog) { doLogout(); return; }
            if (typeof dialog.showModal === 'function') {
                if (!dialog.open) dialog.showModal();
            } else {
                dialog.setAttribute('open', '');
            }
            // Foca o Cancelar (ação não-destrutiva) depois do paint: premir Enter
            // por reflexo não termina a sessão sem querer.
            requestAnimationFrame(function () {
                try { (cancelBtn || dialog).focus(); } catch (e) { /* noop */ }
            });
        }

        function closeDialog() {
            if (!dialog) return;
            if (dialog.open && typeof dialog.close === 'function') dialog.close();
            else dialog.removeAttribute('open');
        }

        function doLogout() {
            if (typeof Auth !== 'undefined' && typeof Auth.logout === 'function') {
                Auth.logout();
            } else {
                window.location.href = '/login/';
            }
        }

        trigger.addEventListener('click', function (e) {
            e.preventDefault();
            openDialog();
        });

        if (cancelBtn) cancelBtn.addEventListener('click', closeDialog);
        if (confirmBtn) confirmBtn.addEventListener('click', function () {
            confirmBtn.disabled = true;   // evita duplo-clique enquanto o pedido corre
            doLogout();
        });

        if (dialog) {
            // Clique no fundo do <dialog> (target é o próprio dialog) cancela.
            dialog.addEventListener('click', function (ev) {
                if (ev.target === dialog) closeDialog();
            });
            // Esc é nativo do <dialog>; ao fechar (Esc/fundo/Cancelar) devolve o foco.
            dialog.addEventListener('close', function () {
                if (confirmBtn) confirmBtn.disabled = false;
                try { trigger.focus(); } catch (e) { /* noop */ }
            });
        }
    });
})();
