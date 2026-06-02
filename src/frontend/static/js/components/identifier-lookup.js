/**
 * ForensiQ — Identificadores específicos do tipo + lookups externos.
 * CSP-safe: ficheiro estático, sem eval/inline. Usa fetch com cookie JWT
 * (credentials same-origin) contra os endpoints DRF já existentes.
 *
 *  - Mostra só os campos de identificador relevantes ao tipo de evidência
 *    selecionado (IMEI→telemóvel, IMSI+ICCID→SIM, VIN→veículo, MAC→rede).
 *    Limpa os campos escondidos (não guardar identificadores trocados).
 *  - [data-lookup="imei"] → GET /api/evidences/lookup/imei/<imei>/ e mostra
 *    o enriquecimento (render genérico das chaves devolvidas — sem assumir
 *    o schema exacto do imeidb.xyz).
 *  - [data-lookup="vin"]  → GET /api/evidences/lookup/vin/<vin>/ e abre o URL
 *    do vindecoder.eu numa nova aba (sem scraping, ADR-0010).
 *  - Pista de formato MAC ao vivo.
 */
(function () {
    'use strict';

    var typeSel = document.getElementById('f-type');
    var section = document.querySelector('[data-id-section]');
    var fields = Array.prototype.slice.call(document.querySelectorAll('[data-id-field]'));

    function syncVisibility() {
        if (!typeSel) return;
        var t = typeSel.value;
        var any = false;
        fields.forEach(function (f) {
            var on = f.getAttribute('data-id-type') === t;
            f.classList.toggle('is-on', on);
            // Desativar (não só esconder) os campos dos outros tipos: inputs/selects
            // disabled não são submetidos, evitando colisão de nomes entre tipos
            // (ex.: 'imei' existe em MOBILE_DEVICE e GPS_TRACKER; 'mac' em
            // NETWORK_DEVICE e IOT_DEVICE). Assim só o tipo escolhido é persistido.
            f.querySelectorAll('input, select').forEach(function (i) { i.disabled = !on; });
            if (on) {
                any = true;
            } else {
                var r = f.querySelector('.lookup-result');
                if (r) { r.hidden = true; r.innerHTML = ''; }
            }
        });
        if (section) section.classList.toggle('is-on', any);
    }
    if (typeSel) {
        typeSel.addEventListener('change', syncVisibility);
        syncVisibility();
    }

    // --- Render do enriquecimento (genérico, robusto ao schema do upstream) ---
    var HIDDEN = {
        raw: 1, _cached_at: 1, normalised_complete: 1,
        cached: 1, cached_at: 1, source: 1, detail: 1
    };
    var LABELS = {
        brand: 'Marca', model: 'Modelo', commercial_name: 'Nome comercial',
        os: 'SO', storage: 'Armazenamento', release_date: 'Lançamento',
        color: 'Cor', tac: 'TAC', type: 'Tipo'
    };

    function esc(s) {
        return String(s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    function renderEnrichment(data) {
        var rows = '';
        Object.keys(data).forEach(function (k) {
            if (HIDDEN[k]) return;
            var v = data[k];
            if (v === null || v === '' || typeof v === 'object') return;
            rows += '<div class="facts__row"><dt>' + esc(LABELS[k] || k) +
                '</dt><dd class="mono">' + esc(v) + '</dd></div>';
        });
        if (!rows) return '<p class="lookup-error">Sem dados de enriquecimento.</p>';
        var src = data.source
            ? '<p class="facts__src">Fonte: ' + esc(data.source) + (data.cached ? ' · em cache' : '') + '</p>'
            : '';
        return '<dl class="facts">' + rows + '</dl>' + src;
    }

    document.body.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('[data-lookup]') : null;
        if (!btn) return;
        ev.preventDefault();
        var kind = btn.getAttribute('data-lookup');
        var input = document.querySelector(btn.getAttribute('data-target'));
        if (!input) return;
        var val = input.value.trim();
        if (!val) { input.focus(); return; }

        if (kind === 'vin') {
            val = val.toUpperCase();
            // Feedback de progresso visível: o VIN só abre uma aba no fim, sem destino
            // de resultado, por isso o rótulo do botão sinaliza a consulta em curso.
            var vinLabel = btn.textContent;
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
            btn.textContent = 'A consultar…';
            fetch('/api/evidences/lookup/vin/' + encodeURIComponent(val) + '/',
                { credentials: 'same-origin', headers: { Accept: 'application/json' } })
                .then(function (r) {
                    return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || 'VIN inválido.'); return d; });
                })
                .then(function (d) { if (d.url) window.open(d.url, '_blank', 'noopener,noreferrer'); })
                .catch(function (e) { window.alert(e.message || 'Falha na consulta VIN.'); })
                .finally(function () {
                    btn.disabled = false;
                    btn.removeAttribute('aria-busy');
                    btn.textContent = vinLabel;
                });
            return;
        }

        // imei
        var out = document.querySelector(btn.getAttribute('data-result'));
        if (out) {
            // Garante anúncio do estado/resultado a leitores de ecrã, mesmo que o
            // contentor não traga os atributos no servidor.
            if (!out.getAttribute('role')) out.setAttribute('role', 'status');
            out.setAttribute('aria-live', 'polite');
            out.setAttribute('aria-atomic', 'true');
            out.setAttribute('aria-busy', 'true');
            out.hidden = false;
            out.innerHTML = '<p class="lookup-pending">A consultar imeidb.xyz…</p>';
        }
        btn.disabled = true;
        btn.setAttribute('aria-busy', 'true');
        fetch('/api/evidences/lookup/imei/' + encodeURIComponent(val) + '/',
            { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); })
            .then(function (res) {
                if (!out) return;
                if (res.ok) {
                    out.innerHTML = renderEnrichment(res.d);
                } else if (res.status === 503) {
                    out.innerHTML = '<p class="lookup-error">Consulta indisponível. Preencha manualmente.</p>';
                } else if (res.status === 429) {
                    out.innerHTML = '<p class="lookup-error">Demasiadas consultas. Tente novamente mais tarde.</p>';
                } else {
                    out.innerHTML = '<p class="lookup-error">' + esc((res.d && res.d.detail) || 'IMEI inválido.') + '</p>';
                }
            })
            .catch(function () { if (out) out.innerHTML = '<p class="lookup-error">Erro de rede. Tente novamente.</p>'; })
            .finally(function () {
                btn.disabled = false;
                btn.removeAttribute('aria-busy');
                if (out) out.removeAttribute('aria-busy');
            });
    });
})();
