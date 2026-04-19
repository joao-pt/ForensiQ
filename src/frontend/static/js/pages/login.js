'use strict';

/**
 * ForensiQ — Login: "Corrente Viva"
 *
 * Reutiliza o fluxo de autenticação (Auth.login / Auth.isAuthenticated) e
 * acrescenta três polimentos UX:
 *   1. Toggle de visibilidade da palavra-passe (ícone olho)
 *   2. Aviso de Caps Lock ligado enquanto se escreve a password
 *   3. Link "Esqueceu a palavra-passe?" com feedback via toast
 *
 * Inline handlers não são usados — respeita a CSP estrita do ForensiQ.
 *
 * Linhagem / créditos: ver docs/design/login-design-credits.md
 */

document.addEventListener('DOMContentLoaded', function () {
    var form          = document.getElementById('login-form');
    var errorBox      = document.getElementById('login-error');
    var btnLogin      = document.getElementById('btn-login');
    var btnLabel      = btnLogin.querySelector('.lp-submit-label');
    var btnArrow      = btnLogin.querySelector('.btn-arrow');
    var usernameInput = document.getElementById('username');
    var passwordInput = document.getElementById('password');
    var pwToggle      = document.getElementById('pw-toggle');
    var eyeShow       = pwToggle.querySelector('.lp-eye-show');
    var eyeHide       = pwToggle.querySelector('.lp-eye-hide');
    var capsWarn      = document.getElementById('caps-warn');
    var forgotLink    = document.getElementById('lp-forgot');

    // ----------------------------------------------------------
    // Auto-redirect se já autenticado
    // ----------------------------------------------------------
    if (typeof Auth !== 'undefined' && typeof Auth.isAuthenticated === 'function') {
        Auth.isAuthenticated().then(function (authenticated) {
            if (authenticated) {
                window.location.href = '/dashboard/';
            }
        }).catch(function () { /* silencioso — continua no form */ });
    }

    // ----------------------------------------------------------
    // Toggle palavra-passe (olho)
    // ----------------------------------------------------------
    pwToggle.addEventListener('click', function () {
        var isHidden = passwordInput.type === 'password';
        passwordInput.type = isHidden ? 'text' : 'password';
        pwToggle.setAttribute('aria-pressed', String(isHidden));
        pwToggle.setAttribute(
            'aria-label',
            isHidden ? 'Ocultar palavra-passe' : 'Mostrar palavra-passe'
        );
        if (isHidden) {
            eyeShow.hidden = true;
            eyeHide.hidden = false;
        } else {
            eyeShow.hidden = false;
            eyeHide.hidden = true;
        }
        passwordInput.focus();
    });

    // ----------------------------------------------------------
    // Aviso de Caps Lock — só quando o foco está na password
    // ----------------------------------------------------------
    function updateCapsLock(event) {
        if (document.activeElement !== passwordInput) {
            capsWarn.hidden = true;
            return;
        }
        var capsOn = event.getModifierState && event.getModifierState('CapsLock');
        capsWarn.hidden = !capsOn;
    }

    passwordInput.addEventListener('keydown', updateCapsLock);
    passwordInput.addEventListener('keyup', updateCapsLock);
    passwordInput.addEventListener('blur', function () {
        capsWarn.hidden = true;
    });

    // ----------------------------------------------------------
    // Link "Esqueceu a palavra-passe?" — ainda não implementado
    // ----------------------------------------------------------
    forgotLink.addEventListener('click', function (e) {
        e.preventDefault();
        if (window.Toast && typeof Toast.info === 'function') {
            Toast.info('Contacte o administrador do sistema para repor credenciais.');
        } else {
            showError('Contacte o administrador do sistema para repor credenciais.');
        }
    });

    // ----------------------------------------------------------
    // Submissão do formulário
    // ----------------------------------------------------------
    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        clearError();

        var username = usernameInput.value.trim();
        var password = passwordInput.value;

        if (!username || !password) {
            showError('Preencha o nome de utilizador e a palavra-passe.');
            return;
        }

        setLoading(true);

        try {
            await Auth.login(username, password);
            window.location.href = '/dashboard/';
        } catch (err) {
            showError(err && err.message
                ? err.message
                : 'Autenticação falhou. Verifique o utilizador e a palavra-passe.');
            setLoading(false);
            passwordInput.value = '';
            passwordInput.focus();
        }
    });

    // ----------------------------------------------------------
    // Estado visual do botão (loading / pronto)
    // ----------------------------------------------------------
    function setLoading(loading) {
        btnLogin.disabled = loading;
        if (loading) {
            btnLabel.textContent = 'A autenticar...';
            btnArrow.hidden = true;
            if (!btnLogin.querySelector('.spinner')) {
                var spinner = document.createElement('span');
                spinner.className = 'spinner';
                btnLogin.appendChild(spinner);
            }
        } else {
            btnLabel.textContent = 'Autenticar';
            btnArrow.hidden = false;
            var existingSpinner = btnLogin.querySelector('.spinner');
            if (existingSpinner) existingSpinner.remove();
        }
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.classList.add('visible');
    }

    function clearError() {
        errorBox.textContent = '';
        errorBox.classList.remove('visible');
    }

    // Foco inicial — ajuda mobile e teclado
    usernameInput.focus();
});


/* =================================================================
 * Constellation — rede animada de nós no painel esquerdo.
 *
 * Canvas 2D puro. Sem dependências. CSP-safe (script externo).
 * - Pontos movem-se devagar, colidem com as margens
 * - Ligações entre vizinhos (<= LINK_DIST) com alpha proporcional à distância
 * - Cursor acende ligações teal (interacção física com a rede)
 * - Respeita prefers-reduced-motion (renderiza uma frame estática)
 * - Pausa quando a tab não está visível (poupa CPU e bateria)
 *
 * Técnica: "particle network" — linhagem pública (particles.js, tsParticles).
 * Código escrito de raiz para ForensiQ. Ver docs/design/login-design-credits.md
 * ================================================================= */
document.addEventListener('DOMContentLoaded', function initConstellation() {
    var canvas = document.getElementById('lp-constellation');
    if (!canvas || typeof canvas.getContext !== 'function') return;

    var ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Finding #28 — não desenhar se o painel está escondido (mobile).
    // Poupa bateria e evita animação invisível. Usamos offsetWidth em vez
    // de matchMedia para respeitar CSS real (incluindo hover/dev tools).
    function isVisible() {
        return canvas.offsetWidth > 0 && canvas.offsetHeight > 0;
    }

    var dpr = Math.min(2, window.devicePixelRatio || 1);
    var reducedMotion = window.matchMedia &&
                        window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var W = 0;
    var H = 0;
    var points = [];
    var mouse = { x: -9999, y: -9999, active: false };
    var rafId = null;

    // Parâmetros de visual
    var DENSITY       = 9000;   // 1 ponto por cada ~9000 px² de área
    var MIN_POINTS    = 30;
    var MAX_POINTS    = 110;
    var LINK_DIST     = 140;    // distância máxima entre nós ligados
    var CURSOR_RADIUS = 170;    // raio de influência do cursor
    var POINT_MIN_R   = 0.8;
    var POINT_MAX_R   = 1.8;
    var SPEED         = 0.22;   // px / frame

    // Cores alinhadas com os tokens --lp-*
    var COLOR_POINT        = 'rgba(143, 163, 192, 0.55)';
    var COLOR_LINK_PREFIX  = 'rgba(107, 125, 154, ';
    var COLOR_LINK_CURSOR  = 'rgba(45, 212, 191, ';

    function resize() {
        var rect = canvas.getBoundingClientRect();
        W = Math.max(1, Math.floor(rect.width));
        H = Math.max(1, Math.floor(rect.height));
        canvas.width  = W * dpr;
        canvas.height = H * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        seed();
    }

    function seed() {
        var target = Math.round((W * H) / DENSITY);
        if (target < MIN_POINTS) target = MIN_POINTS;
        if (target > MAX_POINTS) target = MAX_POINTS;

        points = [];
        for (var i = 0; i < target; i++) {
            points.push({
                x:  Math.random() * W,
                y:  Math.random() * H,
                vx: (Math.random() - 0.5) * SPEED,
                vy: (Math.random() - 0.5) * SPEED,
                r:  POINT_MIN_R + Math.random() * (POINT_MAX_R - POINT_MIN_R)
            });
        }
    }

    function drawFrame() {
        ctx.clearRect(0, 0, W, H);

        var i, j, p, dx, dy, distSq, dist, alpha;
        var linkSq   = LINK_DIST * LINK_DIST;
        var cursorSq = CURSOR_RADIUS * CURSOR_RADIUS;

        // Mover pontos e rebater nas margens
        for (i = 0; i < points.length; i++) {
            p = points[i];
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0)      { p.x = 0; p.vx = -p.vx; }
            else if (p.x > W) { p.x = W; p.vx = -p.vx; }
            if (p.y < 0)      { p.y = 0; p.vy = -p.vy; }
            else if (p.y > H) { p.y = H; p.vy = -p.vy; }
        }

        // Ligações entre vizinhos — O(n²) aceitável para n<=110
        ctx.lineWidth = 1;
        for (i = 0; i < points.length; i++) {
            for (j = i + 1; j < points.length; j++) {
                dx = points[i].x - points[j].x;
                dy = points[i].y - points[j].y;
                distSq = dx * dx + dy * dy;
                if (distSq < linkSq) {
                    dist = Math.sqrt(distSq);
                    alpha = (1 - dist / LINK_DIST) * 0.22;
                    ctx.strokeStyle = COLOR_LINK_PREFIX + alpha.toFixed(3) + ')';
                    ctx.beginPath();
                    ctx.moveTo(points[i].x, points[i].y);
                    ctx.lineTo(points[j].x, points[j].y);
                    ctx.stroke();
                }
            }
        }

        // Ligações ao cursor — destaque teal
        if (mouse.active) {
            ctx.lineWidth = 1.1;
            for (i = 0; i < points.length; i++) {
                dx = points[i].x - mouse.x;
                dy = points[i].y - mouse.y;
                distSq = dx * dx + dy * dy;
                if (distSq < cursorSq) {
                    dist = Math.sqrt(distSq);
                    alpha = (1 - dist / CURSOR_RADIUS) * 0.6;
                    ctx.strokeStyle = COLOR_LINK_CURSOR + alpha.toFixed(3) + ')';
                    ctx.beginPath();
                    ctx.moveTo(points[i].x, points[i].y);
                    ctx.lineTo(mouse.x, mouse.y);
                    ctx.stroke();
                }
            }
        }

        // Nós por cima das ligações
        ctx.fillStyle = COLOR_POINT;
        for (i = 0; i < points.length; i++) {
            p = points[i];
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    function animate() {
        drawFrame();
        rafId = requestAnimationFrame(animate);
    }

    function start() {
        if (!isVisible()) return;
        if (rafId === null) rafId = requestAnimationFrame(animate);
    }

    function stop() {
        if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
    }

    // Cursor — coordenadas em espaço do canvas
    canvas.addEventListener('mousemove', function (e) {
        var rect = canvas.getBoundingClientRect();
        mouse.x = e.clientX - rect.left;
        mouse.y = e.clientY - rect.top;
        mouse.active = true;
    });
    canvas.addEventListener('mouseleave', function () {
        mouse.active = false;
    });

    // Redimensionar com debounce — inclui start/stop conforme visibilidade
    var resizeTimer = null;
    window.addEventListener('resize', function () {
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            resize();
            if (isVisible() && !reducedMotion) start();
            else stop();
        }, 120);
    });

    // Pausar quando a tab fica escondida
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) stop();
        else if (!reducedMotion) start();
    });

    resize();
    if (reducedMotion) {
        drawFrame(); // uma frame estática, sem loop
    } else {
        start();
    }
});
