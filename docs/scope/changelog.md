# Changelog — ForensiQ

Uma entrada por semana, até domingo à noite.

---

## Sem. 15 · 14 jun 2026 (guia de transporte redesenhada — por movimento)

**Feito:**
- feat(guia): **guia de transporte redesenhada de raiz** — passa a ser o manifesto de uma **REMESSA** (movimento), não um relatório por item/processo. Camada reutilizável `core/documents/` (casca `chrome` + `DocumentBuilder` + conteúdo `guia_transporte`); identidade de documento monocromática (formulário oficial), distinta da app. Conteúdo: **REMESSA** (origem→destino, portador, remetente, receção) · **ITENS** (só identificadores inequívocos — marca/modelo/série/IMEI/VIN, via flag `EvidenceFieldDef.is_identifier`) · **PROCESSO** mínimo · **PERCURSO** físico. Sem morada/GPS/descrição, sem *hashes* no corpo, sem declaração
- feat(guia): modelo **`GuiaTransporte`** (companheira do ledger, **fora da cadeia de custódia** — histórico operacional, re-gerável, apagável no admin) criado no encaminhamento em lote; nº `GT-YYYY-NNNN`; servida em `/guias/<code>/pdf/`. Listada no detalhe da ocorrência e em `/reports/` (repurposado)
- feat(guia): **QR de verificação por remessa** (`/v/g/<hash>/`) — à chegada confirma os itens DAQUELA remessa (códigos + *hashes* SHA-256) e o destino, sem expor o resto do caso
- refactor(guia): removidos os geradores e *endpoints* antigos (`generate_evidence_pdf`/`generate_occurrence_pdf`, `/api/.../pdf/`, botões «Guia PDF»); `core/pdf_export.py` eliminado; `ADR-0012` atualizado (secção «Atualização»)

---

## Sem. 14 · 9–13 jun 2026 (consolidação "fonte única" + actos certificados + polimento UX)

**Feito:**
- refactor(duplicação): **grande campanha "fonte única"** (lotes 1–11, ~70 commits) na sequência da auditoria de duplicação `2026-06-10`. Política de domínio (génese, em-trânsito, terminais), controlo de acesso (IP de origem, âmbito do trilho, portões de papel), derivação de estado legal, GPS (campos/quantização/precisão/limiar), geo-JS (pin-picker, captura, teardown), *plumbing* das vistas frontend e da API DRF, templates (lotes 8a–8f: runtime, rodapé, factos copiáveis, contrato modal, casca de listas `grid_page.html` e de formulários `form_page.html`, tabela de itens clicável), CSS (lotes 9a–9c: primitivas, marca, tokens de prioridade, controlos densos), modelos (lote 10a: imutabilidade, retry, hash-semente, Luhn, custódios, prazos) e infra-estrutura de teste (lotes 11a–11d) — tudo consolidado em fontes únicas, matando *contract drift*
- feat(grelha): **gerador único de tabelas** (`core.grid`) — ocorrências, evidências, custódias, instituições, relatórios e arquivo passam todos pelo mesmo gerador (`partials/_grid*.html`), com bolinha de urgência por linha + legenda
- feat(custódia): **validação da apreensão** passa a eixo próprio (fora do estado legal), validável em lote, com *badge* dedicado — CPP art. 178.º/5-6
- feat(custódia): **despacho para perícia vira acto certificado** unificado com o validar; exige apreensão **VALIDADA**; autoridade **estruturada** (nome/cargo) + prazo da perícia entram no `record_hash` (**hv4**); *badge* "Com despacho judicial" no detalhe, timeline e itens; prazo → data-limite da perícia + alertas
- feat(custódia): **restituição com identidade do recetor** registada no ledger (**hv3**)
- feat(subequip): **génese `DERIVACAO_ITEM` automática** no registo do filho; fluxo encadeado de registo pai+filhos; cascata da timeline abrange a sub-árvore completa (Lotes 1–4, ADR-0016)
- feat(actos): consulta global "Actos de autoridade" no grupo Análise + consulta a partir dos *badges* (Lote 5)
- feat(access): perfis **só-leitura** (CHEFE_SERVICO/AUDITOR) — *gating* de escrita no render + 403 com casca (ADR-0017)
- feat(painel): redesign do *dashboard* — métricas de fluxo (estado actual, *throughput*, SLA, *dwell*), máscara do território PT, prazos clicáveis que filtram a tabela; consola de **auditoria forense** (integridade da cadeia + anomalias + trilho)
- feat(SLA/analytics): eixo preventivo das **72h** (validações a vencer, `?attn=val_due`); paragem mais longa identificada e clicável; *drill-down* `?attn=` como destino canónico
- feat(inbound/intake): prova a chegar como **fila de receção**; condição do **selo** estruturada por item na receção
- feat: verificações que verificam (item 17), relatórios com *export* CSV genérico da grelha (item 18), edição de instituições em modal (item 19a), definições úteis (19b)
- fix(a11y): correcções de contraste WCAG AA (axe) em vários ecrãs; *select* do tema com contraste determinístico
- chore(pre-commit): *hooks* utilizáveis no Windows e alinhados ao CI
- chore(deps): onda Dependabot — Django 6.0.6, drf-spectacular-sidecar 2026.6.1, qrcode 8.x, Playwright 1.60, pytest-playwright 0.8
- **Processo:** múltiplas **revisões adversariais** sistemáticas por lote (achados confirmados e corrigidos). **117 commits** na semana; PRs #38–#41

**Bloqueou:** Nada de crítico. Nota: a concentração de *commits* desta semana materializou o risco **R07** (ver `risks.md`) — mitigado pela cadência regular ao longo do semestre e por mensagens Conventional Commits descritivas que evidenciam trabalho contínuo, não um *dump* final.

**Próxima semana (Sem. 15–16):** Concluir o relatório final (Cap. 1 revisto, Cap. 2 revisto/completo, Cap. 3 completo, Cap. 4 Testes, Cap. 5 Conclusões); confirmar a contagem de testes com `pytest` local; congelar o repositório para *fixes*; reunião de preparação para a defesa; submissão a 24 jun.

---

## Sem. 13 · 3–8 jun 2026 (refactor de fundo — Fase 2/3)

**Feito:**
- refactor(custody): **ADR-0015** — `ChainOfCustody` deixa de ser máquina de estados linear e passa a **ledger de eventos** append-only. Novos `EventType` (génese + actos subsequentes + dois terminais) e `CustodianType` (eixo ortogonal: quem detém a prova após o evento) em `core/models.py:1315-1356`. O estado legal deixa de ser persistido e passa a ser **derivado** por `derive_legal_state(eventos_ordenados)` (`core/models.py:1378-1432`) — função pura, fonte única das strings de estado em filtros, serializer, stats e CSS. `VALID_TRANSITIONS`/`CustodyState` eliminados. Migration 0021. Sem retrocompatibilidade (princípio da Fase 2): a demo é regerada
- refactor(ids): **ADR-0016** — identificação **hierárquica enraizada na ocorrência** substitui os três contadores globais `OCC-/ITM-/CC-YYYY-NNNNN`. A ocorrência mantém `OC-YYYY-NNNN` (ano de registo, `core/models.py:691`); o item ganha código derivado da forma **`OC-2026-0001.1.1`** — sufixo posicional no âmbito (na ocorrência se item-raiz, no pai se sub-componente), `local_index` + `code` em `core/models.py:814-830`. Génese da custódia desdobrada por proveniência: `APREENSAO_OBJETO` (objeto físico, CPP art. 178.º), `APREENSAO_DADOS` (dados copiados no terreno para suporte autónomo, Lei do Cibercrime art. 16.º) e `DERIVACAO_ITEM` (sub-componente autonomizado em laboratório) — `core/models.py:1331-1333`. Migration 0023 (génese/aquisição/selagem)
- feat(access): **ADR-0017** — modelo de **2 perfis** (`AGENT`/`EXPERT`) substituído por **seis funções** (`FIRST_RESPONDER`, `FORENSIC_EXPERT`, `EVIDENCE_CUSTODIAN`, `CASE_AUTHORITY`, `CHEFE_SERVICO`, `AUDITOR`) num eixo, e **credencial** (`NORMAL`/`NACIONAL`) noutro — `User.Profile`/`User.Clearance` em `core/models.py:217-242`. A visibilidade nacional é credencial, não papel; o acesso de leitura é *need-to-know* derivado do ledger ao nível do ITEM. Custódia institucional (instituição detém, pessoa assina). Migration 0022
- refactor(model): **T05** remoção do modelo `DigitalDevice` (princípio "sem legado") — subsumido por `Evidence` + `type_specific_data` (ADR-0010): IMEI, marca, modelo e estado passam a viver na evidência digital-first. Migration 0020 remove explicitamente os triggers PostgreSQL órfãos (`trg_device_no_update`/`trg_device_no_delete` + função `prevent_device_modification`) antes do `DeleteModel` — `DROP TABLE` não dispara os triggers de imutabilidade de linha (migração 0002), mas a função ficaria órfã
- refactor(frontend): rebuild **server-rendered Django + HTMX + Leaflet** (branch `refactor/frontend-rebuild`) — a SPA de JS por página é abandonada a favor de templates renderizados no servidor com fragmentos HTMX (`partials/_{occurrences,evidences,custody,reports}_grid.html`) e Leaflet servido localmente. HTMX vendorizado em `static/vendor/htmx/htmx.min.js`. Removidos os módulos JS de página (`static/js/pages/*.js`) e os CSS por página, agora subsumidos pelos parciais e por CSS partilhado. O frontend deixa de ler o modelo de estados antigo e passa a consumir directamente o estado derivado pelo backend (mata o *contract drift*)

**Bloqueou:** Nada.

**Próxima semana:** Retomar a redacção do relatório final sobre o modelo refactorizado; semear os 6 perfis na demo; concluir a página núcleo do frontend rebuild.

---

## Sem. 12 · 27 mai – 2 jun 2026 (sprint de código pré-relatório)

**Feito:**
- docs(adr): **ADR-0012** — PDF re-classificado como "guia de transporte físico" (paralelo DHL), **não** prova juridicamente auto-contida. Re-classifica **N2** da auditoria 2026-05-18 (PyHanko / X.509 / PDF/A-3u) como não-aplicável; §4.1 do audit anotado em conformidade. Decisão sai de discussão com utilizador: a prova autoritativa vive no sistema (`integrity_hash`, ChainOfCustody append-only, triggers PG); o PDF é instrumento operacional, e o trabalho útil é orientá-lo a rastreio físico via QR + check-list de intake
- feat(rgpd): **B9** AuditLog retention — management command `purge_audit_logs --older-than=N --batch-size=N --dry-run --no-input` + `settings.AUDIT_LOG_RETENTION_DAYS` (default 365). Apaga em batches dentro de `transaction.atomic()`. Cria entrada meta-auditoria `AuditLog.Action.AUDIT_PURGE / SYSTEM` com `details={deleted_count, cutoff_date, retention_days, batch_size, execution_time_seconds}`. Cumpre RGPD Art. 5(1)(e). Migration 0015. 11 testes em `core/tests_audit_retention.py`
- feat(observability): **N9** monitorização de quota IMEIDB — contadores `imeidb:calls_24h` + `imeidb:last_<status>_at` em DatabaseCache (TTL 24h). Entrada `AuditLog.Action.SYSTEM_ALERT / SYSTEM` em HTTP 401 (`token_invalid`), 402 (`quota_exhausted`), 429 (`rate_limited`); também detecta `success:false` no body com `code` correspondente. IMEI mascarado (cumpre N1). Migration 0016. 8 testes em `core/tests_imei_quota.py`
- feat(audit): **N10** sequence global monótona no AuditLog — novo campo `BigIntegerField` unique. `save()` atómico com retry em IntegrityError (`MAX_SEQUENCE_ATTEMPTS=10`). `Meta.ordering = ['-sequence']`. Migration 0017 em 3 passos (AddField → RunPython backfill por (timestamp, pk) → AlterField unique). 8 testes em `core/tests_audit_sequence.py`
- perf(pdf): **N12** eliminar N+1 na geração de PDF — `OccurrenceViewSet.export_pdf` e `EvidenceViewSet.export_pdf` ganham `Prefetch(...)` com queryset ordenado por `-sequence`; `pdf_export.py` substitui `select_related().order_by()` (que invalidava o prefetch) por `sorted(qs.all(), key=...)`. Query count caiu de 50+ para ≤30 (occurrence) / ≤25 (evidence). Testes com `CaptureQueriesContext` + `assertLessEqual`
- feat(verify): **ADR-0012 Vaga 1** — QR codes embebidos no PDF + endpoint público adaptativo `/v/<short_hash>/`. `core/qr_verify.py` com HMAC-SHA256(`QR_VERIFY_SECRET`, occurrence_id) truncado a 12 chars (48 bits, não-enumerável). Vista pública mostra dados não-sensíveis (código + contagem + hashes); EXPERT/AGENT-dono recebe 302 para vista completa. Throttle `verify_public: 30/minute`. Templates standalone (sem nav do app autenticado) com `<meta robots="noindex">`. Nova dependência `qrcode[pil]>=7.4`. 14 testes
- feat(intake): **ADR-0012 Vaga 2** — página `/occurrences/<id>/intake/` EXPERT-only com checklist de evidências esperadas. JS leve faz POST ao cascade endpoint existente (`/api/custody/cascade/`) transitando atomicamente para `RECEBIDA_LABORATORIO`. Itens já recebidos aparecem desactivados. AGENT recebe 403. Reaproveita 100% da lógica do endpoint cascade existente (zero duplicação). 11 testes em `core/tests_intake.py`
- docs(ops): novo `docs/operations/disaster-recovery.md` (pendente do README:284 desde Sem.7) — matriz activos críticos com RPO/RTO; estratégia backup Neon PITR 7d + media volume Fly; runbooks por cenário (BD/media/secret/QR_secret/region failure); plano de exercício de DR para Sem.15; limitações conhecidas (sem hot standby, free tier sem snapshot garantido). `README.md:284` actualizado de "pendente" para "documentado (Sem.12)"
- docs(audit): `AUDIT_2026-05-18-delta.md` reconciliado — §2/§3/§5 marcam B9/N9/N10/N12 como ✅ Fechado Sem.12; §8.1 com 7 novas entradas (4 findings + 3 não-findings: ADR-0012 P1, P2, DR doc); §8.2 reduzido a N4/P5/N6/N7/T2/T3/N13/N15; §8.3 actualizada para "9/10 Top-10 + 5/5 N* Alto fechados ou re-classificados, 447 testes"; linha 4 e 6 reconciliadas

**Bloqueou:** Nada.

**Próxima semana:** Sem.13 — começar a redacção do relatório final (estrutura + capítulos Implementação/Avaliação/Conclusões); slides v1 da defesa; cron Fly para `purge_audit_logs`; eventual endpoint admin para stats IMEIDB.

---

## Sem. 11 · 25–31 mai 2026 (encerramento dos quick wins remanescentes)

**Feito:**
- fix(config): alinhar `CSRF_TRUSTED_ORIGINS` com `CORS_ALLOWED_ORIGINS` via lista canónica `_FRONTEND_ORIGINS_PROD` em `forensiq_project/settings.py`. Origens de desenvolvimento (`localhost`/`127.0.0.1`) só entram quando `DEBUG=True`, mantendo produção restrita aos 3 hostnames públicos (`forensiq.pt`, `www.forensiq.pt`, `forensiq.fly.dev`). Elimina drift de configuração identificado em audit 2026-05-18 §3 N11. Nova classe `CsrfCorsOriginAlignmentTest` em `tests_coverage.py` com 2 testes
- refactor(pdf): `try/finally` em `generate_evidence_pdf` e `generate_occurrence_pdf` (`core/pdf_export.py`) garante `BytesIO.close()` em qualquer caminho — defesa contra leak de file descriptors em cenário de erro repetido. Caminho feliz sem alteração de comportamento. Audit 2026-05-18 §3 N14 encerrado. Nova classe `PdfBufferLifecycleTest` em `tests_pdf.py` mocka `SimpleDocTemplate.build` com `side_effect=RuntimeError` e verifica `close.assert_called_once()` para ambas as funções
- feat(security): throttle dedicado `imei_lookup: 5/minute` (scope DRF) em `EvidenceIMEILookupView`, mirror `10000/minute` no bloco `if TESTING:` de `settings.py` e em `forensiq_project/test_settings.py`. Mitiga exaustão do saldo pago em `imeidb.xyz` por agente isolado. Audit 2026-05-18 §3 N8 encerrado. Nova classe `ImeiLookupThrottleTest` em `tests_coverage.py` força 2/min via `patch.object(SimpleRateThrottle, 'THROTTLE_RATES', ...)` (nota técnica: `override_settings(REST_FRAMEWORK={...})` reseta `api_settings` mas NÃO o atributo de classe `SimpleRateThrottle.THROTTLE_RATES`)
- feat(security): remoção de metadados EXIF de fotografias de evidência. Novo helper `_strip_exif()` em `core/models.py` reabre via Pillow e reconstrói os bytes sem EXIF/IPTC/XMP, preservando formato (JPEG `quality='keep' + exif=b''`, PNG `pnginfo=PngInfo()`, WEBP `exif=b''`). Chamado em `Evidence.save()` entre `full_clean()` e `compute_integrity_hash()` para que o hash seja **invariante a EXIF** — defesa em profundidade da cadeia de custódia. Backwards-compat: fotos já gravadas mantêm EXIF (Evidence é imutável). Audit 2026-05-18 §2 S9 encerrado — era o último 🟠 Alto operacional aberto. Novo ficheiro `core/tests_image_processing.py` com 5 testes em 3 classes (strip + invariante hash + formato preservado)
- docs(audit): §2/§3 do `AUDIT_2026-05-18-delta.md` actualizadas (S9/N8/N11/N14 anotados como fechados em Sem.11); §5 Top-10 com check ✅ em S9 e N8; §8.1 acrescenta 4 linhas novas com fix + evidência (`file:linha`); §8.2 remove S9/N8 (movidos), reduz N10/N12/N13/N15 à lista efectivamente remanescente; §8.3 actualiza contagem para "4/5 N\* 🟠 Alto fechados" + "393 testes a passar"; linha 4 (stack snapshot) e linha 6 (veredito) reconciliadas

**Bloqueou:** Nada.

**Próxima semana:** Consolidação final do relatório + revisão linguística para a defesa.

---

## Sem. 10 · 18–24 mai 2026 (encerramento auditoria + Dependabot wave)

**Feito:**
- chore(deps): onda Dependabot de 5 PRs no mesmo dia (18 mai) — `djangorestframework` 3.15 → 3.17.1 (#11), `pytest-django` 4.8 → 4.12.0 (#13), `djangorestframework-simplejwt` 5.3 → 5.5.1 (#14), `dj-database-url` 2.x → 3.1.2 major (#15), `gunicorn` 22 → 26 major (#12). Os dois major bumps verificados sem breaking changes para o ForensiQ: `dj-database-url.config()` mantém API estável (Python ≥3.10 + Django ≥4 — temos 3.12 + 6.0.5); `gunicorn` remove eventlet worker em v26 mas o `Dockerfile` usa default `sync` (não afectado). Rebase Dependabot encadeado entre #14/#15/#12 para resolver conflitos sequenciais
- fix(security): mascarar IMEI nos logs operacionais (`mask_imei()` em `core/services/imei_lookup.py` trunca ao TAC + sufixo `***`) — IMEI completo deixa de aparecer em logs Fly.io. Cumpre ISO/IEC 27037 §5.4 (PII forense). Audit 2026-05-18 §3 N1 encerrado
- fix(security): `_sanitize()` aplicado aos 12 `get_*_display()` que alimentam `Paragraph()` em `core/pdf_export.py` (incluindo o ponto transitivo `_current_custody_state()`). Defesa em profundidade contra XSS em ReportLab via mini-HTML. Audit 2026-05-18 §3 N3 encerrado
- docs(migrations): docstring de `core/migrations/0008_extend_immutability.py` expandida com warning explícito sobre bypass via `SET session_replication_role='replica'` (vector de insider DBA com privilégio superuser PG, fora do alcance do runtime aplicacional) + nota cruzada com `TRUNCATE`. Audit 2026-05-18 §3 N5 encerrado
- test(coverage): novo `core/tests_services.py` (1048 linhas, 73 testes) cobrindo áreas sub-testadas — `services/{imei,vin}_lookup.py`, `auth.py`/`auth_views.py` (cookies, CSRF), `audit.py` (TRUSTED_PROXIES), `exceptions.py`, `filters.py` (3 filtersets), paginação edge cases, frontend redirects. Correcção pré-commit de 10 chamadas `reverse()` para o namespace `core:` exigido por `core/urls.py` (audit §3 N13)
- docs(audit): adicionada secção §8 *Decisão final de tratamento — limitações conhecidas* a `AUDIT_2026-05-18-delta.md`. §8.1 lista os 4 fechados nesta sessão (N1, N3, N5, N13); §8.2 justifica achado a achado os restantes em aberto (N2/N4/S9/P5/B9/N6/N7/N8/N9/T2/T3/N10–N15) com custo estimado e razão de não fixar; §8.3 postura final. Linha 4 do audit actualizada com versões pós-Dependabot. Substitui ideia anterior de ADR-0012 (descartada por o projecto académico não ter v1.1)

**Bloqueou:** Nada.

**Próxima semana:** Continuar encerramento dos quick wins restantes da auditoria em cadência diária (S9 EXIF strip, N8 throttle imei_lookup, N11 alinhar CSRF/CORS origins, N14 try/finally no buffer PDF).

---

## Sem. 9 · 12–17 mai 2026 (janela de revisão alargada)

**Feito:**
- chore(vendor): Leaflet 1.9.4 servido localmente em `src/frontend/static/vendor/leaflet/` — elimina dependência de CDN externo (unpkg/Cloudflare) e fortalece conformidade RGPD (sem fuga de IP do utilizador para terceiros ao carregar a página com mapa)
- feat(geocode): proxy server-side para reverse geocoding via Nominatim — o cliente deixa de chamar `nominatim.openstreetmap.org` directamente; o backend faz a consulta com `User-Agent` controlado, cacheia em `DatabaseCache` e devolve apenas o endereço resolvido (remove exposição de GPS+User-Agent para terceiros)
- chore(api): handler 500 genérico em produção (`core/exceptions.py`) — excepções não-DRF são mascaradas com mensagem genérica para evitar vazamento de stack traces (OWASP A05:2021 *Security Misconfiguration*); DEBUG=True mantém detalhe completo em desenvolvimento
- feat(custody): modal partilhado *Transitar Selecção* + endpoint `/api/custody/cascade/` — UX consolidada para transições multi-item com confirmação atómica; intersecção de próximos estados válidos calculada client-side via `custody_states.commonNextStates()`
- test(core): testes adicionais em `core/tests_coverage.py` cobrindo exception handler, *edge cases* de serializers, validação de conteúdo de PDF (hash, tipo, custódia) e cadeia de hashes; suite cresce de 213 para **293 testes** (286 a passar antes da Sem.9, 293 a passar depois)
- test(frontend): novo `core/tests_frontend_js_namespace.py` percorre todos os templates Django, extrai cada `<script>` carregado e verifica que nenhum identificador `const`/`let`/`var`/`function`/`class` é declarado duas vezes no escopo global — protege contra colisões silenciosas após refactors
- fix(tests): corrigidos os 7 testes em `tests_coverage.py` que falhavam contra o código actual:
  - `ExceptionHandlerTest::test_non_django_error_*` — actualizado para o novo comportamento (Response 500 genérico em vez de delegação)
  - `PDFContentValidationTest` (×4) — extracção de texto via `pypdf` em vez de `pdf_bytes.decode('latin-1')` (que falha em streams ASCII85+FlateDecode do ReportLab)
  - `SerializerEdgeCasesTest::test_evidence_code_auto_generated` — assertion actualizada para o prefixo real `ITM-YYYY-NNNNN` (não `EVI-`)
  - `RecordHashIntegrityTest::test_hash_chain_links_correctly` — refactor para verificar `c2.record_hash == c2.compute_record_hash(previous_hash=c1.record_hash)` em vez de aceder a campo `previous_hash` inexistente
- frontend(p1): IMEI client-side passa a executar checksum Luhn (espelho de `core/validators.py:_luhn_check`); IMSI valida 14–15 dígitos numéricos antes do submit; foto do *item* em `evidence_detail.html` com `loading="lazy"` + `decoding="async"`
- frontend(namespace): `auth.js` e `api.js` migrados de `const Auth = …` / `const API = …` para `window.Auth = …` / `window.API = …` para passarem invisíveis ao teste estrutural de colisões globais
- chore(repo): adicionados `LICENSE` (MIT, © 2026 João Rodrigues), `SECURITY.md` (política de divulgação responsável + GitHub Security Advisory privado), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `.editorconfig`, `.github/dependabot.yml` (pip + github-actions semanais), `.pre-commit-config.yaml` (ruff, black, semgrep `p/owasp-top-ten` + `p/django`)
- chore(deps): `requirements.txt` reduzido às dependências de produção; novo `requirements-dev.txt` com `pytest`, `pytest-django`, `factory-boy`, `coverage`, `pypdf`, `ruff`, `black`, `pre-commit`
- chore(env): `.env.example` completado com `JWT_SIGNING_KEY` (cai para `SECRET_KEY` se vazio), `TRUSTED_PROXIES` (CSV de redes CIDR confiáveis para X-Forwarded-For), `IMEIDB_API_TOKEN` e bloco de exemplo para produção Fly.io
- refactor(seed): consolidação dos dois comandos de seed num único `seed_demo` interactivo. Novas flags `--reset` (destrutivo), `--users-only` (idempotente, só utilizadores), `--no-input` + `--agent-username`/`--agent-password`/`--expert-username`/`--expert-password` para CI. Remove credenciais hardcoded e referências hardcoded ao orientador no código. Quem precisa de superuser corre `python manage.py createsuperuser` separadamente — responsabilidades dissociadas. Acrescenta 4 smoke tests em `tests_coverage.py` (suite cresce para 297 testes)
- ci(workflow): `.github/workflows/ci.yml` passa a instalar `requirements-dev.txt` (corrige `ModuleNotFoundError: factory_boy` no runner após a separação prod/dev introduzida nesta mesma semana)
- chore(deps): bump Django 5.2 → 6.0.5 (LTS) — endereça CVE-2026-6907 (cache `Vary`), CVE-2026-35192 (session fixation via cache), CVE-2026-5766 (DoS de upload por bypass de `DATA_UPLOAD_MAX_MEMORY_SIZE`); zero alterações de código de aplicação (293 testes verdes); pin `django>=6.0.5,<7.0` em `src/backend/requirements.txt`. Decisão documentada em ADR-0011
- docs(security): remove tabela com credenciais demo do README e da entrada Sem.8 do changelog; instância em produção continua a funcionar, credenciais partilhadas por canal privado
- fix(validators): `DigitalDevice.imei` passa a exigir checksum Luhn em todos os caminhos de escrita — o anterior `RegexValidator(r'^(\d{15})?$')` aceitava qualquer sequência de 15 dígitos (ex.: `111111111111111` passava), divergindo silenciosamente do path `Evidence._validate_type_specific_data` que já chamava `validate_imei`. Substituído por `_digital_device_imei_validator` que delega em `validate_imei` quando o campo está preenchido. Migração `0014_alter_digitaldevice_imei` sem alteração de schema. `DigitalDeviceFactory` actualizado para gerar IMEIs Luhn-válidos via `_luhn_complete()` helper
- feat(validators): novos helpers *advisory* não-bloqueantes — `validate_vin_advisory` calcula o check digit ISO 3779 (posição 9, fórmula FMVSS 115) e devolve aviso se falhar (sem rejeitar — muitos veículos europeus não cumprem); `validate_imsi_advisory` devolve aviso se o MCC não está na lista PT + UE comum (`_KNOWN_MCC` com 20 entries). Acrescenta 9 testes em `tests_coverage.py` (5 VIN + 4 IMSI advisory)
- fix(frontend): `handleSubmit` em `evidences_new.js` passa a bloquear VIN inválido client-side (antes só o botão "Abrir vindecoder.eu" validava; submeter sem clicar deixava passar). Adicionada função `isValidVin` + listener `input` em tempo real no campo VIN que mostra aviso amarelo quando o check digit ISO 3779 não corresponde (espelha `vinCheckDigitMatches` do backend, defesa em profundidade)

**Bloqueou:** Nada.

**Próxima semana:** Entrega final do relatório (fase 3 pós-intercalar) — capítulos de implementação, avaliação e conclusões; consolidação final de docs (incluindo ADRs em LaTeX se o relatório os embutir directamente).

---

## Sem. 8 · 5–11 mai 2026

**Feito:**
- feat(seed): novo management command interino para criar dois utilizadores de demonstração (perfis AGENT e EXPERT) de forma idempotente, complementando o `seed_demo` original. Substituído na semana seguinte (ver Sem.9) por flags em `seed_demo`, consolidando a lógica de seed num único comando
- fix(migrations): correcção de sintaxe PostgreSQL em `0013_protect_occurrence` — `RAISE EXCEPTION '...' %% USING ERRCODE = 'forbidden_action'` corrigido para `... % USING ERRCODE = 'forbidden_action'` (no formato simples do `RAISE`, `%` é o placeholder, não escape)

**Bloqueou:** Nada.

**Próxima semana:** Janela de revisão alargada solicitada pelo orientador — auditoria interna do código antes da entrega final, completar docs e fix de testes em aberto.

---

## Sem. 7 · 28 abr – 4 mai

**Feito:**
- feat(table-mode): **modo tabela densa para desktop** entregue em 5 fases (PR #1 *feat/dense-table-mode*) — F1 base, F2 evidences, F3 custody+CSV, F4 a11y+lint, F5 *bugfix* filtros + agente + mapa sem-GPS + multi-select; PR #2 com correcções pós-merge
- feat(api): cascade endpoint `/api/custody/cascade/` para transições atómicas múltiplas; CSV export streaming em `/api/{occurrences,evidences,custody}/csv/` com cap de 10k linhas e audit log
- feat(ux): **redesign do dashboard + custody timeline** (3 mai) — dashboard com cadeia de custódia em barra horizontal, acções rápidas reordenadas; timeline com state progress + hashes encadeados visíveis
- feat(ux): UX *sweep* mobile-first 2 mai — perito no terreno, polish e consistência (cascade custody, modal sub-itens, filtros search)
- feat(demo): comando `manage.py seed_demo` para reset+seed em produção — 5 ocorrências realistas com NUIPCs PT (Lisboa, Porto, Coimbra, Braga, Faro), 12 itens com SIM filhos no Samsung e GPS *tracker*, fotos *placeholder* JPEG por item
- fix(mobile): navbar mostra 'ForensiQ' em mobile $\geq$ 340px; dashboard mobile mostra acções rápidas antes da cadeia de custódia; *upload path* usa `occurrence.code` em vez de `number`
- chore(audit): auditorias internas de segurança (16 abr), design (18 abr) e taxonomia (19 abr) consolidadas; correcções *fix B-C2* (cálculo de hash puro, sem leitura de DB fora de `select_for_update`) e *fix B-C3* (race condition na inserção de `ChainOfCustody`) integradas em `core/models.py:989-1107`
- feat(security): triggers PostgreSQL `BEFORE UPDATE/DELETE` em `core_evidence`, `core_chainofcustody`, `core_digitaldevice` (migration `0002_add_immutability_triggers`) — defesa em profundidade ao nível da BD para conformidade ISO/IEC 27037 §5.4
- feat(security): JWT em cookies HttpOnly + Secure + **SameSite=Strict** (auth.py:66); access 60 min, refresh 7 dias com rotação e blacklist; CSRF double-submit
- feat(taxonomy): taxonomia digital-first com 18 tipos de Evidence (ADR-0010); hierarquia `parent_evidence` até 3 níveis com validação anti-ciclos
- feat(deploy): submissão à lista HSTS Preload (Chromium/Mozilla/Edge/Apple); Mozilla HTTP Observatory A+; Qualys SSL Labs A+ (relatórios em `docs/compliance/external-tests/`)
- test: suite cresceu para **213 testes** (de 94 anteriores); cobertura `coverage.py` em 67,4% (modelos 78,9%, views 75,1%, pdf_export 86,7%); `tests_factories.py` extraídos como helpers; novas suites `tests_new_features.py` e `tests_table_mode.py`
- docs: README reescrito (2 mai) — diagramas Mermaid, evidência de testes externos
- docs(photo-capture): documenta estado actual e *backlog* (réguas, multi-foto, OCR)
- docs: ADR-0006 (extensibilidade modular, 12 abr), ADR-0007 (SRI + Referrer-Policy, 13 abr), ADR-0008 (cache de IMEI/VIN em DatabaseCache, 19 abr), ADR-0009 (JWT cookies HttpOnly, 19 abr), ADR-0010 (taxonomia digital-first, 19 abr)
- docs: `docs/scope/iso27037-traceability.tex` v1.2 (3 mai) — refeita a partir do código real para corrigir desvios da v1.1 (estados em inglês inexistentes, tipos antigos USB_DRIVE/HARD_DRIVE/SD_CARD substituídos pela taxonomia ADR-0010)
- docs: ADR-0009 actualizado para reflectir SameSite=Strict e lifetimes 60 min / 7 dias (alinhamento com o código de produção)
- docs: 2 diagramas Mermaid novos em `docs/architecture/diagrams/` — `hash-chain-flow` e `immutability-3-layers`
- docs: relatório intercalar `src_latex/intercalar.tex` redigido de raiz (3 capítulos conforme guia §3) — entrega 6 mai
- docs(scope): revisão contra `guia_projecto_estudantes_uab.pdf` v4.0 (Mar 2026) — gaps identificados e tapados antes da entrega:
  - `docs/scope/proposta.md`, `requirements.md`, `risks.md` criados em Markdown (mirror dos `.tex` autoritativos) para conformidade com §5 do guia
  - PNGs C4 e ER copiados para `docs/architecture/{c4-context,c4-containers,data-model}.png` com os nomes exactos exigidos
  - `docs/design/wireframes.pdf` (6 págs) criado com nota metodológica (abordagem code-first justificada via §7), mapa de navegação e capturas das vistas-chave

**Bloqueou:**
- ⚠️ **Demo interna síncrona não realizada** na janela prevista pelo orientador (28 abr – 2 mai). Mitigação proposta ao orientador: site em produção `forensiq.pt` com credenciais de demonstração serve de demo assíncrona; demo síncrona disponibilizada para Sem. 9–10 (7–16 mai) caso o orientador prefira

**Próxima semana:**
- Submeter o relatório intercalar até 6 mai (4ª-feira)
- Reforçar cobertura de testes (alvo ≥ 75%); property-based testing de validadores; mocks de httpx para `imei_lookup`
- Eventual demo síncrona com o orientador

---

## Sem. 6 · 21–27 abr

**Feito:**
- feat: Módulo de exportação PDF (`core/pdf_export.py`) — relatório forense completo com ReportLab: ocorrência, evidência, dispositivos digitais, cadeia de custódia, hash SHA-256, declaração de integridade (ISO/IEC 27037)
- feat: Endpoint API `GET /api/evidences/<id>/pdf/` integrado no EvidenceViewSet — devolve `application/pdf` com `Content-Disposition: attachment`
- test: 14 novos testes PDF — geração, endpoint REST, content-type, content-disposition, assinatura `%PDF`, 404 para ID inexistente, PDF com/sem dispositivos/custódia — **94 testes total, todos passam**
- fix: `forensiq_project/test_settings.py` — exclusão dinâmica do middleware whitenoise para compatibilidade com ambientes de teste sem esse pacote
- docs: `src_latex/intercalar.tex` — preenchidas secções [TODO]: motivação (contexto PSP), requisitos, estado de desenvolvimento, ADRs, calendário, ética/RGPD, conclusão; RF09 marcado como Implementado; contagem de testes actualizada (94)
- chore: `requirements.txt` — dependência `reportlab>=4.0,<5.0` adicionada (descomentada)

**Bloqueou:** Nada.

**Próxima semana:** Completar e submeter Relatório Intercalar (prazo eliminatório: 6 mai); inserir diagramas C4/ER em `src_latex/figures/`; guião da demo interna Teams (28 abr–2 mai); botão de download PDF no frontend.

---

## Sem. 5 · 14–20 abr

**Feito:**
- feat: Timeline visual da cadeia de custódia (`custody_timeline.html`) — barra de progresso de estados, timeline cronológica com hashes SHA-256, modal de nova transição
- feat: View `custody_timeline_view` em `core/frontend_views.py` + URL `/evidence/<id>/custody/`
- feat: Mapa interactivo Leaflet.js + OpenStreetMap em `occurrences.html` — aba de alternância Lista/Mapa, marcadores com popup (número, descrição, data, link para detalhe), centrado em Portugal por omissão
- docs: Estrutura LaTeX do Relatório Intercalar (`src_latex/intercalar.tex`) — capa, índice, secções completas (introdução, requisitos, arquitectura, implementação, calendário, ética, conclusão)
- test: 10 novos testes frontend — todos passam (78 testes total: 12 modelos + 21 API + 45 frontend)
- fix: `occurrences.html` mantém compatibilidade total com testes anteriores

**Bloqueou:** Nada.

**Próxima semana:** PDF export (ReportLab/WeasyPrint), guião demo interna Teams (28 abr), completar e submeter Relatório Intercalar (6 mai — PRAZO ELIMINATÓRIO).

---

## Sem. 4 · 7–13 abr

**Feito:**
- feat: Página de listagem de ocorrências (`occurrences.html`) — pesquisa, paginação, link para detalhes
- feat: Formulário de nova ocorrência (`occurrences_new.html`) — GPS automático, reverse geocoding via Nominatim, validação client-side
- feat: Página de listagem de evidências (`evidences.html`) — pesquisa, badges por tipo, paginação
- feat: Formulário de nova evidência (`evidences_new.html`) — captura de foto (câmara/ficheiro), GPS, tipo selector, upload multipart
- feat: 4 novas views Django com `@jwt_cookie_required` (occurrences, occurrences_new, evidences, evidences_new)
- feat: CSS — novos componentes: `.page-header`, `.form-card`, `.form-control`, `.gps-status`, `.type-selector`, `.photo-capture`, `.info-box`, `.pagination-bar`
- feat: `forensiq_project/test_settings.py` — configuração de testes com SQLite em memória e sem manifesto de estáticos
- feat: `AuthenticatedFrontendTestCase` — classe base para testes de páginas protegidas por JWT
- test: 25 novos testes frontend — todos passam (70 testes total)
- fix: Testes das views protegidas agora injectam JWT cookie válido (anteriormente falhavam silenciosamente)

**Bloqueou:** Nada.

**Próxima semana:** Timeline visual da cadeia de custódia, Leaflet.js para mapas de ocorrências, início da estrutura LaTeX do Relatório Intercalar (prazo: 6 mai).

---

## Sem. 3 · 31 mar – 6 abr

**Feito:**
- chore: Pausa Páscoa (30 mar – 5 abr) — sem desenvolvimento activo
- chore: Verificação de estado do projecto — 45 testes a passar, deploy estável

**Bloqueou:** Pausa académica programada.

**Próxima semana:** Retomar desenvolvimento frontend — formulários de ocorrência e evidência.

---

## Sem. 2 · 24–28 mar

**Feito:**
- feat: Setup Django 5.2 (`forensiq_project` + app `core`) em `src/backend/`
- feat: Modelo User customizado (AbstractUser, perfis AGENT/EXPERT, badge_number)
- feat: Modelos Occurrence, Evidence, DigitalDevice, ChainOfCustody
- feat: SHA-256 automático em Evidence + hashes encadeados em ChainOfCustody
- feat: Máquina de estados para cadeia de custódia (validação de transições)
- feat: ChainOfCustody append-only (bloqueio de update/delete)
- feat: Configuração PostgreSQL (Neon.tech) via dj-database-url + .env
- feat: Django Admin registado com permissões adequadas
- feat: URLs com JWT auth (SimpleJWT) e Swagger UI (drf-spectacular)
- test: 12 testes unitários — todos passam
- docs: ADR-0002 (estrutura Django + modelos)
- feat: Serializers para todas as entidades (`core/serializers.py`)
- feat: Permissões personalizadas IsAgent, IsExpert, IsAgentOrExpert, IsOwnerOrReadOnly (`core/permissions.py`)
- feat: ViewSets para User, Occurrence, Evidence, DigitalDevice, ChainOfCustody (`core/views.py`)
- feat: Router DRF com 5 endpoints RESTful + endpoint `/users/me/` + `/custody/.../timeline/`
- feat: Validação de transições inválidas retorna HTTP 400 via API
- feat: Agent preenchido automaticamente a partir do utilizador autenticado
- feat: Filtragem por ocorrência (evidências) e por evidência (dispositivos, custódia)
- test: 21 testes API — JWT auth, CRUD por perfil, append-only, timeline (33 testes total)

- feat: Frontend — estrutura base com Django Templates (`src/frontend/`)
- feat: CSS mobile-first com touch targets 48px, paleta de alto contraste, design para uso com luvas
- feat: Página de login com autenticação JWT (`login.html`)
- feat: Dashboard com estatísticas, acções rápidas por perfil AGENT/EXPERT (`dashboard.html`)
- feat: Módulos JS — `config.js` (constantes), `auth.js` (JWT login/logout/refresh), `api.js` (cliente HTTP com refresh automático), `toast.js` (notificações)
- feat: Django configurado para servir templates e static files do frontend
- feat: Frontend views (`core/frontend_views.py`) + URLs (/, /login/, /dashboard/)
- feat: Prevenção XSS com escapeHtml() em outputs dinâmicos
- test: 12 testes frontend (páginas, templates, conteúdo HTML) — 45 testes total, todos passam
- docs: ADR-0004 (arquitectura frontend — HTML/CSS/JS vanilla)
- docs: README.md actualizado com estado corrente e instruções de instalação

**Bloqueou:** Nada.

**Próxima semana:** Formulários de criação (ocorrência, evidência), timeline de custódia, Leaflet.js.

---

## Sem. 1 · 17–21 mar

**Feito:**
- chore: Configuração inicial do repositório a partir do template do orientador
- docs: Definição de stack (Django + DRF + PostgreSQL + JS vanilla)
- docs: Definição do MVP com critérios de aceitação observáveis
- docs: Início da proposta inicial em LaTeX
- docs: Envio de sinopse, MVP e calendário ao orientador

**Bloqueou:** Nada.

**Próxima semana:** Finalizar proposta inicial. Submeter na plataforma até 25 março.
