'use strict';

document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('login-form');
    var errorBox = document.getElementById('login-error');
    var btnLogin = document.getElementById('btn-login');
    var usernameInput = document.getElementById('username');
    var passwordInput = document.getElementById('password');

    Auth.isAuthenticated().then(function (authenticated) {
        if (authenticated) {
            window.location.href = '/dashboard/';
        }
    });

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        var username = usernameInput.value.trim();
        var password = passwordInput.value;

        if (!username || !password) {
            showError('Preencha o nome de utilizador e a palavra-passe.');
            return;
        }

        btnLogin.disabled = true;
        btnLogin.textContent = '';
        var spinner = document.createElement('span');
        spinner.className = 'spinner';
        btnLogin.appendChild(spinner);

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

    usernameInput.focus();
});
