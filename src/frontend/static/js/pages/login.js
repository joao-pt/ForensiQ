'use strict';

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('login-form');
    const errorBox = document.getElementById('login-error');
    const btnLogin = document.getElementById('btn-login');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');

    Auth.isAuthenticated().then(authenticated => {
        if (authenticated) {
            window.location.href = '/dashboard/';
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const username = usernameInput.value.trim();
        const password = passwordInput.value;

        if (!username || !password) {
            showError('Preencha o nome de utilizador e a palavra-passe.');
            return;
        }

        btnLogin.disabled = true;
        setSpinner(btnLogin);

        try {
            await Auth.login(username, password);
            window.location.href = '/dashboard/';
        } catch (err) {
            showError(err.message || 'Credenciais inválidas. Tente novamente.');
            btnLogin.disabled = false;
            btnLogin.textContent = 'Entrar';
            passwordInput.value = '';
            passwordInput.focus();
        }
    });

    function showError(message) {
        errorBox.textContent = message;
        errorBox.classList.add('visible');
    }

    function setSpinner(el) {
        el.textContent = '';
        const spinner = document.createElement('span');
        spinner.className = 'spinner';
        el.appendChild(spinner);
    }

    usernameInput.focus();
});
