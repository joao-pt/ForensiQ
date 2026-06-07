/**
 * ForensiQ — User menu (navbar).
 *
 * Dropdown com role="menu": clique no trigger abre/fecha o panel. Como o
 * markup declara role="menu"/role="menuitem", honra-se o padrão de teclado
 * WAI-ARIA — ao abrir o foco move-se para o 1.º item; ↑/↓/Home/End percorrem
 * os itens; Escape e Tab fecham. Fecha também com clique fora. Popula nome,
 * avatar (iniciais) e papel a partir do Auth.getUser() / /api/users/me/.
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
            var labels = {
                'FIRST_RESPONDER': 'Agente / Primeiro interveniente',
                'FORENSIC_EXPERT': 'Perito forense digital',
                'EVIDENCE_CUSTODIAN': 'Custódio / Fiel depositário',
                'CASE_AUTHORITY': 'Autoridade judiciária (MP)',
                'CHEFE_SERVICO': 'Chefe de serviço',
                'AUDITOR': 'Auditor',
            };
            return labels[profile] || '';
        }

        function setText(id, value) {
            var el = document.getElementById(id);
            if (el) el.textContent = value;
        }

        // ---- Open / close (padrão WAI-ARIA menu) ----
        function items() {
            return Array.prototype.slice.call(panel.querySelectorAll('[role="menuitem"]'));
        }

        function isOpen() {
            return !panel.hasAttribute('hidden');
        }

        function open() {
            panel.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            focusItem(0);
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

        function focusItem(index) {
            var list = items();
            if (!list.length) return;
            if (index < 0) index = list.length - 1;
            if (index >= list.length) index = 0;
            list[index].focus();
        }

        function moveFocus(delta) {
            var list = items();
            if (!list.length) return;
            var i = list.indexOf(document.activeElement);
            focusItem((i < 0 ? 0 : i) + delta);
        }

        function onDocClick(e) {
            if (!panel.contains(e.target) && !trigger.contains(e.target)) close();
        }

        function onKey(e) {
            switch (e.key) {
                case 'Escape':
                    close();
                    trigger.focus();
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    moveFocus(1);
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    moveFocus(-1);
                    break;
                case 'Home':
                    e.preventDefault();
                    focusItem(0);
                    break;
                case 'End':
                    e.preventDefault();
                    focusItem(items().length - 1);
                    break;
                case 'Tab':
                    // O menu não retém o Tab: fecha e deixa o foco sair.
                    close();
                    break;
                default:
                    break;
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
