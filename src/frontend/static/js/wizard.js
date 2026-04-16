'use strict';

/**
 * Wizard — componente genérico de passos full-screen (Revolut-style).
 *
 * HTML esperado:
 *   <div class="wizard" id="my-wizard">
 *     <div class="wizard-track">
 *       <section class="wizard-step" data-step="0">...</section>
 *       <section class="wizard-step" data-step="1">...</section>
 *     </div>
 *     <nav class="wizard-nav">
 *       <button class="wizard-back" aria-label="Voltar">‹</button>
 *       <div class="wizard-dots"></div>
 *       <button class="wizard-next">Seguinte</button>
 *     </nav>
 *   </div>
 */
function Wizard(el, opts) {
    opts = opts || {};
    this.el = el;
    this.track = el.querySelector('.wizard-track');
    this.steps = [].slice.call(el.querySelectorAll('.wizard-step'));
    this.dotsContainer = el.querySelector('.wizard-dots');
    this.backBtn = el.querySelector('.wizard-back');
    this.nextBtn = el.querySelector('.wizard-next');
    this.current = 0;
    this.count = this.steps.length;
    this.onStep = opts.onStep || null;
    this.onComplete = opts.onComplete || null;
    this.validators = {};

    this._buildDots();
    this._bind();
    this.goTo(0, true);

    history.replaceState({ wizardStep: 0 }, '');
}

Wizard.prototype._buildDots = function () {
    this.dotsContainer.textContent = '';
    this.dots = [];
    for (var i = 0; i < this.count; i++) {
        var dot = document.createElement('span');
        dot.className = 'wizard-dot';
        dot.setAttribute('data-dot', i);
        this.dotsContainer.appendChild(dot);
        this.dots.push(dot);
    }
};

Wizard.prototype._bind = function () {
    var self = this;

    if (this.backBtn) {
        this.backBtn.addEventListener('click', function () { self.prev(); });
    }
    if (this.nextBtn) {
        this.nextBtn.addEventListener('click', function () {
            if (self.current === self.count - 1) {
                if (self.onComplete) self.onComplete();
            } else {
                self.next();
            }
        });
    }

    window.addEventListener('popstate', function (e) {
        if (e.state && typeof e.state.wizardStep === 'number') {
            self.goTo(e.state.wizardStep, true);
        }
    });
};

Wizard.prototype.setValidator = function (stepIndex, fn) {
    this.validators[stepIndex] = fn;
};

Wizard.prototype.goTo = function (index, skipHistory) {
    if (index < 0 || index >= this.count) return;

    if (index > this.current && this.validators[this.current]) {
        if (!this.validators[this.current]()) return;
    }

    this.current = index;
    this.track.style.transform = 'translateX(-' + (index * 100) + '%)';

    for (var i = 0; i < this.count; i++) {
        var step = this.steps[i];
        var dot = this.dots[i];
        step.classList.toggle('active', i === index);
        dot.classList.toggle('active', i === index);
        dot.classList.toggle('done', i < index);
    }

    if (this.backBtn) {
        this.backBtn.disabled = index === 0;
    }
    if (this.nextBtn) {
        if (index === this.count - 1) {
            this.nextBtn.textContent = 'Registar';
        } else {
            this.nextBtn.textContent = 'Seguinte';
        }
    }

    if (!skipHistory) {
        history.pushState({ wizardStep: index }, '');
    }

    if (this.onStep) this.onStep(index);

    var activeStep = this.steps[index];
    var firstInput = activeStep.querySelector('input:not([type=hidden]):not([readonly]), select, textarea');
    if (firstInput && firstInput.offsetParent !== null) {
        setTimeout(function () { firstInput.focus(); }, 400);
    }
};

Wizard.prototype.next = function () {
    this.goTo(this.current + 1);
};

Wizard.prototype.prev = function () {
    this.goTo(this.current - 1);
};

Wizard.prototype.markDotDone = function (index) {
    if (this.dots[index]) this.dots[index].classList.add('done');
};

window.Wizard = Wizard;
