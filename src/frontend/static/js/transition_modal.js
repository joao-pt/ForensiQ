/**
 * ForensiQ — Modal partilhado para registar transições de estado de items.
 *
 * Substitui dois pontos de uso anteriores:
 * - cascade transition na tabela de items da página da ocorrência
 * - registo de transição (com cascade opcional para sub-componentes) na
 *   página da timeline de custódia de um item
 *
 * Pre-validação client-side: usa CustodyStates.commonNextStates() para
 * mostrar apenas os destinos que TODOS os items seleccionados podem atingir.
 * O backend valida sempre de novo (atomicidade em /api/custody/cascade/).
 */

'use strict';

window.TransitionModal = (() => {

    const {
        CUSTODY_STATE_LABELS,
        commonNextStates,
    } = window.CustodyStates;

    const SVG_NS = 'http://www.w3.org/2000/svg';

    let activeOverlay = null;
    let activeKeyHandler = null;

    /**
     * Abre o modal de transição.
     *
     * @param {Object} opts
     * @param {Array<{id:number, code:string, currentState:string}>} opts.items
     *        Items a transitar — cada um com o seu estado actual.
     * @param {Array<{id:number, label:string, checked?:boolean, disabled?:boolean}>}
     *        [opts.cascadeItems] Sub-componentes opcionais a apresentar como
     *        checklist (caso do timeline de um item-pai). Quando presente, o
     *        utilizador pode (des)marcar sub-items individualmente. Sub-itens
     *        com `disabled:true` ficam fixos (típico do item principal).
     * @param {string} [opts.title] Título do modal. Default: "Registar transição".
     * @param {string} [opts.submitLabel] Texto do botão Confirmar.
     * @param {Function} opts.onSubmit  Recebe `{ids:number[], newState:string,
     *        observations:string}`. Deve devolver Promise — se rejeitar, o erro
     *        é mostrado no modal via `formatCascadeError`.
     */
    function open(opts) {
        close();
        const items = opts.items || [];
        const overlay = buildDom(opts, items);
        document.body.appendChild(overlay);
        activeOverlay = overlay;

        activeKeyHandler = (ev) => {
            if (ev.key === 'Escape') {
                ev.preventDefault();
                close();
            }
        };
        document.addEventListener('keydown', activeKeyHandler);

        requestAnimationFrame(() => {
            const select = overlay.querySelector('#tm-new-state');
            const cancelBtn = overlay.querySelector('[data-action="cancel"]');
            if (select && !select.disabled) select.focus();
            else if (cancelBtn) cancelBtn.focus();
        });
    }

    function close() {
        if (activeKeyHandler) {
            document.removeEventListener('keydown', activeKeyHandler);
            activeKeyHandler = null;
        }
        if (activeOverlay && activeOverlay.parentNode) {
            activeOverlay.parentNode.removeChild(activeOverlay);
        }
        activeOverlay = null;
    }

    function buildDom(opts, items) {
        const currentStates = items.map((i) => i.currentState || '');
        const uniqueStates = [...new Set(currentStates)];
        const allowed = commonNextStates(currentStates);

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-labelledby', 'tm-title');

        const modal = document.createElement('div');
        modal.className = 'modal';

        const h3 = document.createElement('h3');
        h3.id = 'tm-title';
        h3.textContent = opts.title || 'Registar transição';
        modal.appendChild(h3);

        const summary = buildSummary(items, uniqueStates);
        if (summary) modal.appendChild(summary);

        const stateGroup = document.createElement('div');
        stateGroup.className = 'form-group';
        const stateLabel = document.createElement('label');
        stateLabel.className = 'form-label';
        stateLabel.htmlFor = 'tm-new-state';
        stateLabel.textContent = 'Novo estado';
        stateGroup.appendChild(stateLabel);

        const select = document.createElement('select');
        select.id = 'tm-new-state';
        select.className = 'form-control';
        allowed.forEach((key) => {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = CUSTODY_STATE_LABELS[key] || key;
            select.appendChild(opt);
        });
        if (allowed.length === 0) {
            select.disabled = true;
            const opt = document.createElement('option');
            opt.textContent = '— sem destino comum —';
            select.appendChild(opt);
        }
        stateGroup.appendChild(select);
        modal.appendChild(stateGroup);

        let cascadeList = null;
        if (Array.isArray(opts.cascadeItems) && opts.cascadeItems.length > 0) {
            const section = buildCascadeSection(opts.cascadeItems);
            cascadeList = section.querySelector('.cascade-list');
            modal.appendChild(section);
        }

        const obsGroup = document.createElement('div');
        obsGroup.className = 'form-group';
        const obsLabel = document.createElement('label');
        obsLabel.className = 'form-label';
        obsLabel.htmlFor = 'tm-observations';
        obsLabel.textContent = 'Observações';
        obsGroup.appendChild(obsLabel);
        const obs = document.createElement('textarea');
        obs.id = 'tm-observations';
        obs.className = 'form-control';
        obs.rows = 3;
        obs.placeholder = 'Ex.: Entregue ao laboratório com lacre intacto…';
        obsGroup.appendChild(obs);
        modal.appendChild(obsGroup);

        const errorEl = document.createElement('div');
        errorEl.className = 'form-error';
        errorEl.id = 'tm-error';
        modal.appendChild(errorEl);

        if (allowed.length === 0) {
            const detail = uniqueStates
                .map((s) => `«${CUSTODY_STATE_LABELS[s] || s || 'sem estado'}»`)
                .join(', ');
            errorEl.textContent = uniqueStates.length === 1
                ? `Os items seleccionados estão em ${detail} — estado terminal, sem próxima transição.`
                : `Sem próximo estado comum. Estados presentes: ${detail}.`;
            errorEl.classList.add('visible');
        }

        const actions = document.createElement('div');
        actions.className = 'form-actions modal-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-ghost';
        cancelBtn.dataset.action = 'cancel';
        cancelBtn.textContent = 'Cancelar';
        cancelBtn.addEventListener('click', close);

        const submitBtn = document.createElement('button');
        submitBtn.type = 'button';
        submitBtn.className = 'btn btn-primary';
        submitBtn.dataset.action = 'submit';
        submitBtn.textContent = opts.submitLabel || 'Confirmar';
        submitBtn.disabled = allowed.length === 0;
        submitBtn.addEventListener('click', () => handleSubmit({
            opts, select, obs, cascadeList, submitBtn, errorEl,
        }));

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);
        modal.appendChild(actions);

        overlay.appendChild(modal);

        overlay.addEventListener('click', (ev) => {
            if (ev.target === overlay) close();
        });

        return overlay;
    }

    function buildSummary(items, uniqueStates) {
        if (items.length === 0) return null;
        const wrap = document.createElement('div');
        wrap.className = 'transition-summary';

        const n = items.length;
        const labelFor = (s) => CUSTODY_STATE_LABELS[s] || s || 'sem estado';

        const strongN = document.createElement('strong');
        strongN.textContent = String(n);
        wrap.appendChild(strongN);

        if (uniqueStates.length === 1) {
            wrap.appendChild(document.createTextNode(
                ` item${n === 1 ? '' : 's'} no estado `,
            ));
            const strongState = document.createElement('strong');
            strongState.textContent = `«${labelFor(uniqueStates[0])}»`;
            wrap.appendChild(strongState);
            wrap.appendChild(document.createTextNode('.'));
        } else {
            const counts = uniqueStates.map((s) => {
                const c = items.filter((i) => (i.currentState || '') === s).length;
                return `${c} em «${labelFor(s)}»`;
            }).join(', ');
            wrap.appendChild(document.createTextNode(` items: ${counts}.`));
        }
        return wrap;
    }

    function buildCascadeSection(cascadeItems) {
        const section = document.createElement('div');
        section.className = 'form-group';

        const label = document.createElement('label');
        label.className = 'form-label';
        label.textContent = 'Aplicar a:';
        section.appendChild(label);

        const list = document.createElement('div');
        list.className = 'cascade-list';

        cascadeItems.forEach((it) => {
            const row = document.createElement('label');
            row.className = 'cascade-row';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = String(it.id);
            cb.checked = it.checked !== false;
            cb.disabled = !!it.disabled;
            const span = document.createElement('span');
            span.textContent = it.label;
            row.appendChild(cb);
            row.appendChild(span);
            list.appendChild(row);
        });
        section.appendChild(list);

        const warn = buildWarningCallout(
            'Sub-componentes desincronizados',
            'Os sub-itens desmarcados ficarão num estado diferente do pai. '
            + 'Pode causar problemas na cadeia de custódia.',
        );
        warn.classList.add('hidden');
        section.appendChild(warn);

        list.addEventListener('change', () => {
            const anyOff = Array.from(list.querySelectorAll('input[type="checkbox"]:not(:disabled)'))
                .some((cb) => !cb.checked);
            warn.classList.toggle('hidden', !anyOff);
        });

        return section;
    }

    function buildWarningCallout(titleText, bodyText) {
        const callout = document.createElement('div');
        callout.className = 'callout warning';
        callout.setAttribute('role', 'note');

        const svg = document.createElementNS(SVG_NS, 'svg');
        svg.setAttribute('class', 'callout-icon');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '1.8');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        const circle = document.createElementNS(SVG_NS, 'circle');
        circle.setAttribute('cx', '12');
        circle.setAttribute('cy', '12');
        circle.setAttribute('r', '9');
        svg.appendChild(circle);
        const path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute('d', 'M12 8v5M12 16h.01');
        svg.appendChild(path);
        callout.appendChild(svg);

        const body = document.createElement('div');
        body.className = 'callout-body';
        const title = document.createElement('div');
        title.className = 'callout-title';
        title.textContent = titleText;
        body.appendChild(title);
        body.appendChild(document.createTextNode(bodyText));
        callout.appendChild(body);

        return callout;
    }

    async function handleSubmit({ opts, select, obs, cascadeList, submitBtn, errorEl }) {
        const newState = select.value;
        const observations = obs.value.trim();

        let ids;
        if (cascadeList) {
            ids = Array.from(cascadeList.querySelectorAll('input[type="checkbox"]:checked'))
                .map((cb) => parseInt(cb.value, 10))
                .filter((n) => Number.isFinite(n));
        } else {
            ids = opts.items.map((i) => i.id);
        }
        if (ids.length === 0) {
            errorEl.textContent = 'Nenhum item seleccionado para transitar.';
            errorEl.classList.add('visible');
            return;
        }

        errorEl.classList.remove('visible');
        errorEl.textContent = '';
        submitBtn.disabled = true;
        const originalLabel = submitBtn.textContent;
        submitBtn.textContent = 'A registar…';

        try {
            await opts.onSubmit({ ids, newState, observations });
            close();
        } catch (err) {
            errorEl.textContent = formatCascadeError(err);
            errorEl.classList.add('visible');
            submitBtn.disabled = false;
            submitBtn.textContent = originalLabel;
        }
    }

    /**
     * Extrai mensagem legível do payload do endpoint /api/custody/cascade/.
     *
     * Backend devolve em HTTP 400:
     *   {evidence_id, evidence_code, error: {new_state: ['Transição inválida…']}}
     * Para outros 4xx pode devolver {detail: '...'} (DRF padrão).
     */
    function formatCascadeError(err) {
        const fallback = 'Erro ao registar transição.';
        if (!err) return fallback;
        const data = err.data;
        if (data && typeof data === 'object') {
            if (data.evidence_code && data.error) {
                const detail = typeof data.error === 'object'
                    ? Object.values(data.error).flat().join('; ')
                    : data.error;
                return `Falhou em ${data.evidence_code}: ${detail}`;
            }
            if (data.detail) return data.detail;
            if (data.new_state) {
                return Array.isArray(data.new_state) ? data.new_state[0] : data.new_state;
            }
        }
        return err.message || fallback;
    }

    return { open, close, formatCascadeError };
})();
