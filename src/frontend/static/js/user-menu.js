/**
 * ForensiQ — User menu (navbar).
 *
 * Dropdown simples: clique no trigger abre/fecha o panel. Fecha com
 * clique fora, tecla Escape ou perda de foco. Popula nome, avatar
 * (iniciais) e papel a partir do Auth.getUser() / /api/users/me/.
 *
 * CSP-safe: sem inline handlers. Sem dependências externas.
 */
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var trigger = document.getElementById('user-menu-trigger');
        var panel   = document.getElementById('user-menu-panel');
        if (!trigger || !panel) return;

        // ---- Populate ----
        populate();

        async function populate() {
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

            var name = user.first_name || user.username || 'Utilizador';
            var full = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username || 'Utilizador';
            var initials = computeInitials(user.first_name, user.last_name, user.username);

            setText('user-menu-name', name);
            setText('user-menu-full-name', full);
            setText('user-menu-role', roleLabel(user.profile));
            setText('user-avatar', initials);
        }

        function computeInitials(first, last, username) {
            var source = (first || '') + ' ' + (last || '');
            source = source.trim();
            if (!source) source = username || '?';

            var parts = source.split(/\s+/);
            var a = (parts[0] || '').charAt(0);
            var b = (parts[parts.length - 1] || '').charAt(0);
            var initials = (a + (parts.length > 1 ? b : '')).toUpperCase();
            return initials || '?';
        }

        function roleLabel(profile) {
            if (profile === 'AGENT')  return 'Agente / First Responder';
            if (profile === 'EXPERT') return 'Perito Forense Digital';
            return '';
        }

        function setText(id, value) {
            var el = document.getElementById(id);
            if (el) el.textContent = value;
        }

        // ---- Open / close ----
        function isOpen() {
            return !panel.hasAttribute('hidden');
        }

        function open() {
            panel.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            // clique fora
            setTimeout(function () {
                document.addEventListener('click', onDocClick);
                document.addEventListener('keydown', onKey);
            }, 0);
        }

        function close() {
            panel.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            document.removeEventListener('click', onDocClick);
            document.removeEventListener('keydown', onKey);
        }

        function onDocClick(e) {
            if (!panel.contains(e.target) && !trigger.contains(e.target)) close();
        }

        function onKey(e) {
            if (e.key === 'Escape') {
                close();
                trigger.focus();
            }
        }

        trigger.addEventListener('click', function (e) {
            e.stopPropagation();
            if (isOpen()) close(); else open();
        });

        // ---- Logout ----
        var btnLogout = document.getElementById('btn-logout');
        if (btnLogout) {
            btnLogout.addEventListener('click', function () {
                if (typeof Auth !== 'undefined' && typeof Auth.logout === 'function') {
                    Auth.logout();
                } else {
                    window.location.href = '/login/';
                }
            });
        }
    });
})();
