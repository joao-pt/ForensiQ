# ForensiQ — REFACTOR_MANIFEST.md

> **Fase 1 do refactor: Inventário.** Output do plano-âncora `REFACTOR_PLAN.md`.
> Documento que decide o **âmbito** das Fases 2 (backend+BD) e 3 (frontend).
> **Estado:** rascunho para aprovação do dono (ver §6 — Decisões abertas).
> **Âmbito desta fase:** SÓ LEITURA — nenhuma alteração de código foi feita.

## 0. Como foi gerado

Inventário produzido pelo workflow `forensiq-refactor-inventory`: **9 varreduras
paralelas de profundidade total** (8 dimensões de codebase + 1 gap analysis
mockup V20 ⟷ backend), seguidas de **síntese** (consolidação em temas) e
**crítica adversarial de completude**. Os factos load-bearing foram depois
**verificados directamente** nos ficheiros (ver §7).

- **Escala varrida:** ~34k LOC (backend 7k · testes 7.5k · migrations 1.7k · CSS 6.5k · JS 8k · templates 3.3k), 17 migrations, 12 ADRs, mockup V20 (129KB).
- **Custo:** 11 agentes · 1.39M tokens · 366 tool-uses · ~19 min.
- **Resultado:** **151 findings** (3 blocker · 24 high · 53 medium · 55 low · 16 info), consolidados em **17 temas**.
- **Distribuição por fase:** 77 fase-2-backend · 31 fase-3-frontend · 30 ambas · 13 fora-de-âmbito.

> Nota de nomenclatura: o plano refere-se a este ficheiro como
> `REFACTOR_MANIFEST.md` (correcto); o documento-âncora chama-se `REFACTOR_PLAN.md`.

---

## 1. Diagnóstico global

**O núcleo forense está sólido e os invariantes inquebráveis estão intactos e
bem testados.** Confirmado nos ficheiros: imutabilidade em 3 camadas (triggers
PG `0002`/`0008`/`0013` + admin readonly + API POST-only via `http_method_names`),
FSM da custódia centralizada no modelo (não duplicada nas views), e hash-chain
SHA-256 puro e determinístico (`compute_record_hash` recebe `previous_hash`
injectado dentro de `transaction.atomic()`+`select_for_update`). A suite de 448
testes é honestamente forte (FSM com 8 ramos cobertos, hash-chain testado em
pureza e encadeamento). **O frontend v2 já tem a base certa**: a casca three-pane
e os tokens (IBM Plex + amber + font-features) já vivem globalmente.

**A dívida divide-se em três naturezas que não devem ser confundidas:**

1. **REMOÇÃO de código morto** alinhada com decisões de produto já tomadas — CSV (3 ViewSets + helpers + scope + frontend + 8 testes), DigitalDevice (~5 ficheiros backend + frontend + ~38 testes).
2. **LACUNAS ESTRUTURAIS de backend** que o frontend v2 pressupõe — GPS na `ChainOfCustody`, `priority` em `Occurrence`, endpoint de feed de actividade sobre `AuditLog`, deltas/sparklines no `/stats/dashboard/`, CSP para tiles CartoDB.
3. **DOC-DRIFT / cosmético** — README a chamar o PDF "relatório forense", falta ADR-0013, ADR-0007 desactualizado, paleta teal do PDF, nome de volume Fly errado no runbook de DR.

**O que é estrutural e bloqueante concentra-se quase todo na Fase 2** e gravita
em torno de duas decisões forenses-sensíveis: o GPS entrar (ou não) no hash-chain
de forma versionada, e a convenção `gps_lon` vs `gps_lng`. **Nada do inventário
compromete invariantes.** As únicas exposições de segurança reais: o scope
`verify_public` órfão (vista pública `/v/<hash>` sem throttle aplicado) e — apanhado
na verificação (§7) — a **incoerência API/BD na `Occurrence`** (BD imutável, mas a
API expõe PUT/PATCH/DELETE).

---

## 2. Estado por dimensão

### 2.1 Backend — Modelos & BD (15 findings)
Núcleo de dados sólido e documentado; 3 camadas de imutabilidade intactas; ledger
hash-chained puro. Temas: deprecar `DigitalDevice` (blast radius grande mas
mapeado), acrescentar GPS à custódia sem partir o hash, inconsistências de
nomenclatura (`gps_lng` vs `gps_lon`; `EVIDENCE_LEAF_TYPES` vs "4 sub-componentes").
Migrations com cruft de bumps de choices do `AuditLog` (0012/0015/0016).

### 2.2 Backend — APIs & Serializers (21 findings)
Camada madura; imutabilidade correctamente aplicada (Evidence/Custody POST-only;
ownership e IDOR fechados). Grosso do trabalho é remoção (CSV em 3 actions +
helpers + enum + scope) e marcação de âmbito (`/stats/` e `investigation_report`
→ v2). GPS na custódia é o finding de maior blast radius (toca o hash-chain).
Drift de contrato menor (campos `external_lookup_*` da Wave 2d nunca concluída).

### 2.3 Backend — Services & Lógica (14 findings)
FSM vive no modelo (não duplicada). Hash-chain determinístico e puro. Serviços
IMEI/VIN com erros/timeouts/masking maduros. Temas: estender `compute_record_hash`
para GPS (com ADR-0013 a fixar a ordem dos campos), falta utilitário de
verificação da cadeia inteira, PDF com bug de hemisfério em `_fmt_gps` (imprime
sempre °N/°E — Portugal é longitude W) e paleta teal antiga. Cache IMEI e snapshot
vivem na view, não no serviço.

### 2.4 Backend — Auth, Segurança, Observabilidade (12 findings)
Auth alinhada com ADR-0009 (JWT cookies HttpOnly, SameSite=Strict, rotação com
blacklist, CSRF double-submit). CSP com nonce, sem unsafe-inline. Problemas são
drift de config (allowlist `cdnjs` morta, ADR-0007 desactualizado por self-hosting
do Leaflet) e lacunas que a v2 expõe (CSP sem CartoDB, sem fonte para métricas do
footer). Única exposição real: `verify_public` sem throttle.

### 2.5 Frontend — JS (18 findings)
Núcleo sólido (`api.js` centraliza fetch+CSRF+refresh; `data-table.js` reutilizado).
Encapsulamento inconsistente: ~metade dos page-scripts declaram dezenas de globais,
e o teste de namespace **não segue `{% extends %}`** (falsa segurança). Bug de
contrato real e bloqueante: `dashboard_geo_hero.js` lê `occ.latitude/longitude`
mas o serializer dá `gps_lat/gps_lon` → mapa-herói nunca pinta marcadores. Código
morto alinhado com decisões (CSV, `/api/devices/`, `stats.js` com taxonomia obsoleta).

### 2.6 Frontend — CSS & Templates (18 findings)
Casca three-pane e tokens v2 já globais e sólidos. Migração ficou na casca +
dashboard: páginas internas arrastam markup/CSS v1 (`.navbar` inteiro órfão, hero
v1 em `dashboard.css`, `.fab-label` indefinido, offsets sticky a apontar para
`--navbar-h-desktop` 60px em vez de `--app-top-h` 52px). A11y acima da média mas
falham 2 requisitos do manifesto: roles de grelha na tabela e Popover API.
**Mobile-first menos grave do que temido**: 54 `min-width` vs 11 `max-width` — o
trabalho é re-activar hero/sidebar em mobile, não inverter breakpoints em massa.

### 2.7 Testes (15 findings)
Suite forte e honesta (FSM completa, hash-chain, imutabilidade ORM+API). Sem
skips/flakes genuínos. Lacunas reais: (1) **camada de triggers PG nunca exercida**
(esperado em SQLite, mas é a 3ª camada sem teste); (2) fronteira CSRF por cookie
real sem teste dedicado; (3) cruft/duplicação (classes repetidas entre catch-alls
datados). Decisões v2: CSV parte 8 testes; DigitalDevice ~38 ocorrências em 5
ficheiros; GPS será adição pura mas fica sem teste. Falta `AuditLogFactory`.

### 2.8 Docs, CI, Ops (18 findings)
ADRs maduros mas com drift nas zonas que mudaram. **Falta ADR-0013.** README ainda
descreve PDF como "relatório forense ISO 27037" (contra ADR-0012) e anuncia
CSV/DigitalDevice. CI só corre testes+coverage; ruff/black/semgrep só no pre-commit
(bypassável) e com pins muito desactualizados. Erros operacionais que partem
runbooks: nome do volume Fly (`forensiq_data` no DR vs `forensiq_media` no
`fly.toml`), `.env.example` sem `QR_VERIFY_SECRET`/`AUDIT_LOG_RETENTION_DAYS`.
Checklist RGPD Art.32 d) factualmente errado ("sem SAST/SCA/CI").

### 2.9 Gap Analysis — Frontend v2 (20 findings)
O mockup V20 pressupõe dados que o backend não fornece. Lacunas estruturais: (1)
`ChainOfCustody` sem GPS → mini-mapa "Cadeia" sem fonte; (2) `Occurrence` sem
`priority` → colorbar e coluna "Pri." decorativas. Mais: deltas 24h + sparklines
(só há contagens correntes), feed de actividade (sem endpoint sobre `AuditLog`),
footer técnico com métricas hardcoded/ausentes. Bug já presente: o do hero geo.
**Quase tudo se resolve na Fase 2.**

---

## 3. Temas de refactor (17)

| Tema | Título | Fase | Pri | Esforço | Risco |
|------|--------|------|-----|---------|-------|
| **T01** | GPS na custódia + hash versionado + arredondamento por papel (ADR-0013) | 2-backend | P1 | L | **ALTO** |
| **T02** | Normalizar longitude para `gps_lng` (rename migration + JS) | 2-backend | P1 | M | Baixo-Médio |
| **T03** | `Occurrence`: `crime_type` + `priority` binária (lei) + `evidences_count` | 2-backend | P1 | M | Baixo |
| **T04** | Remover export CSV por completo | ambas | P1 | M | Baixo |
| **T05** | Deprecar/remover `DigitalDevice`, consolidar em "evidência" | ambas | P1 | L | Médio |
| **T06** | Endpoint read-only de feed de actividade sobre `AuditLog` | 2-backend | P1 | M | Médio |
| **T07** | Enriquecer `/api/stats/dashboard/` (deltas 24h + séries + activos) | 2-backend | P2 | M | Baixo |
| **T08** | Limpar CSP: remover `cdnjs` morto + autorizar CartoDB | 2-backend | P1 | S | Médio |
| **T09** | Corrigir bug do hero geo (`gps_lat/gps_lon`) + helper de mapas partilhado | 3-frontend | P1 | M | Baixo |
| **T10** | Replicar casca v2 às páginas internas + limpar CSS órfão v1 | 3-frontend | P2 | L | Baixo-Médio |
| **T11** | Marcar `/stats/` legacy e `investigation_report` como v2 | ambas | P2 | S | Baixo |
| **T12** | Throttle real na vista pública `/v/<hash>` + endurecimento de superfície | 2-backend | P2 | M | Baixo |
| **T13** | Endurecer pipeline: lint/format/semgrep em CI + versões + threshold | 2-backend | P2 | M | Baixo |
| **T14** | Corrigir doc-drift e erros operacionais (README/ADR/DR/RGPD/`.env`) | ambas | P2 | M | Baixo |
| **T15** | Uniformizar IIFE no JS + consolidar fontes-de-verdade + a11y grelha/Popover | 3-frontend | P2 | L | Baixo-Médio |
| **T16** | Consolidar testes duplicados + `AuditLogFactory` + teste de triggers PG + CSRF cookie | 2-backend | P3 | M | Baixo |
| **T17** | Coerência de contrato API (shapes de erro, snapshot lookup, auditar Occurrence) | 2-backend | P3 | L | Baixo |
| **T18** | *(novo — §7)* Coerência API/BD da `Occurrence` (imutável em PG vs ViewSet mutável) + Intake | ambas | **P1** | M | **Médio-Alto** |
| **T19** | *(novo — 2026-05-30)* Taxonomia oficial de crimes + prioridade por Política Criminal + alertas | ambas | **P1** | L | Médio |
| **T20** | *(novo — 2026-05-30)* Custódia como **ledger de eventos** (CPP Art. 154/158/178) + localização/custódio (OSM) | ambas | **P1** | XL | **ALTO** |

### Detalhe dos temas

**T01 — GPS na ChainOfCustody, entrada versionada no hash-chain e arredondamento por papel (ADR-0013).** `[P1 · fase-2-backend · L · risco ALTO]`
Lacuna estrutural #1: o mini-mapa "Cadeia" (polyline + pins por estado + tooltip ±Nm) e a timeline não têm fonte. Adicionar `gps_lat`/`gps_lng`/`gps_accuracy_m` + serializer + write no `perform_create`. **Ponto crítico forense:** o hash NÃO inclui GPS hoje; a fórmula tem de ser estendida de forma **aditiva/versionada** (anexar segmento GPS só quando não-nulo, ou `hash_version`) para registos históricos continuarem recalculáveis. **Decisão D5:** captura com **precisão máxima** (sem arredondamento por papel) + `gps_accuracy_m`; o GPS marca a localização da *evidência*, não vigia o agente. **Ajuste manual** da posição permitido pelo agente **antes** de submeter (pré-hash, porque o registo é imutável ao gravar). Para estados de laboratório, **localização de armazenamento textual** (armário/sala) complementa o GPS. Campos com convenção `gps_lng` (decisão D2). Triggers de linha já cobrem os campos novos. *Findings:* `coc-gps-hash-versionado`, `coc-gps-campos`, `coc-gps-trigger-imutabilidade`, `bd-chainofcustody-sem-gps`, `api-gps-hash-chain`, `coc-hash-sem-gps`, `coc-arredondamento-por-papel-inexistente`, `adr-0013-gps-custody-em-falta`, `gps-custody-rounding-privacidade`, `gap-gps-chain-model`, `gap-gps-chain-serializer`, `gap-gps-chain-rounding`, `gap-timeline-gps-fields`, `gps-custodia-sem-teste`, `gps-no-hash-chain-risco`, `verificacao-cadeia-inteira-inexistente`. *Depende de:* T02.
**Risco:** se o GPS entrar no hash sem versionamento, a cadeia histórica fica inverificável; se entrar sem teste de determinismo, regride silenciosamente (factories gravam GPS=None e o teste continua verde). O ADR-0013 TEM de fixar a ordem dos campos e a regra None/precisão **antes** de ir a produção.

**T02 — Normalizar longitude para `gps_lng`.** `[P1 · fase-2-backend · M · baixo-médio]`
Pré-requisito de T01 e do fix do hero. `Occurrence`/`Evidence` usam `gps_lon` (confirmado `serializers.py:139`); a spec/mockup usam `gps_lng`. **Decisão D2: normalizar tudo para `gps_lng`** (convenção única em todo o schema). Migration de rename `gps_lon`→`gps_lng` em `Occurrence` e `Evidence`; actualizar `filters.py`, serializers, `pdf_export._fmt_gps`, `config.js`, `dashboard_geo_hero.js` e restantes pages. O rename **não** altera o `integrity_hash` da `Evidence` (usa o valor, não o nome). A `ChainOfCustody` nova nasce já com `gps_lng`. *Findings:* `coc-gps-nome-lng-vs-lon`, `gps-lon-vs-lng-nomenclatura`, `gap-gps-lon-vs-lng-naming`. → §6 D2.

**T03 — `Occurrence`: `crime_type` + `priority` binária + contagem.** `[P1 · fase-2-backend · M · baixo]`
Lacuna estrutural #2. **Decisão 2026-05-30 (ver T19):** a `priority` deixa de ser P1-P4 arbitrária e passa a **binária `prioritária`/`normal` derivada da Lei de Política Criminal** a partir do `crime_type` (FK à taxonomia oficial), com override manual. Adicionar `crime_type` FK + `priority` (2 valores) + `priority_source` (lei/manual) + serializer; anotar `evidences_count` no queryset. *Findings:* `gap-occurrence-priority`, `gap-occurrence-priority-serializer`, `gap-table-priority-feed-source`.
⚠️ **Ver T18/§7:** a `Occurrence` é imutável em PG (0013), logo `crime_type` e `priority` só podem ser definidos **na criação** (POST).

**T04 — Remover export CSV por completo.** `[P1 · ambas · M · baixo]`
Decisão fechada (mockup V20 sem CSV). Remover 3 `@action export_csv` (`views.py:280/539/707`), helpers `_CsvEcho`/`_csv_streaming_response`/`_check_csv_size`/`_csv_filename` + `CSV_EXPORT_MAX_ROWS` + imports, scope `csv_export`, `refreshExportLink` em 3 page-scripts + botões em 3 templates, `CsvExportTest` (8 testes), menções no README. *Findings:* `csv-remocao-auditlog-choice`, `api-csv-export-{occurrence,evidence,custody}-morto`, `api-csv-helpers-orfaos`, `api-csv-scope-orfao`, `api-csv-config-js-ausente`, `csv-export-a-remover-services`, `csv-throttle-scope-a-remover`, `csv-frontend-morto`, `tpl-csv-export-morto`, `csv-tests-a-remover`, `readme-csv-export-anunciado`, `gap-csv-removal-impact`.
**Único cuidado forense:** **NÃO** remover o choice `AuditLog.Action.EXPORT_CSV` (registos históricos imutáveis podem tê-lo; remover partiria `get_action_display`). Documentar como legacy.

**T05 — Deprecar e remover `DigitalDevice`.** `[P1 · ambas · L · médio]`
A taxonomia de 18 tipos de `Evidence` já cobre a função; `seed_demo` já não o cria. Remover: modelo + serializer + `DigitalDeviceViewSet` + rota `/api/devices/` + admin + secção legacy do PDF + count em `StatsView` + prefetch + `config.js ENDPOINTS.DEVICES` + `renderDevices` em 2 detail.js + secções em templates + ~38 testes em 5 ficheiros (incl. `DigitalDeviceFactory` + validação Luhn). *Findings:* `digitaldevice-deprecacao-blast`, `digitaldevice-trigger-remocao`, `digitaldevice-resourcetype-orfao`, `digitaldevice-imei-luhn-divergencia-historica`, `api-digitaldevice-deprecar`, `api-digitaldevice-viewset-inconsistente`, `digitaldevice-legacy-no-pdf`, `digitaldevice-evidence-detail-legacy`, `digitaldevice-occurrence-detail-legacy`, `tpl-digitaldevice-seccoes`, `digitaldevice-tests-deprecacao`. *Depende de:* T11.
**Risco:** a migration de drop TEM de dropar `trg_device_no_update` + função (`0002`) **antes** do `DeleteModel`, com `DROP ... IF EXISTS` (no-op SQLite). **Confirmar dados em produção (Neon) antes do `DROP TABLE`.** **Manter** `ResourceType.DEVICE` no enum (histórico AuditLog).

**T06 — Endpoint read-only de feed de actividade sobre `AuditLog`.** `[P1 · fase-2-backend · M · médio]`
Lacuna estrutural #3: o feed "Actividade recente" do dashboard não tem fonte — não existe `AuditLogViewSet`. Criar endpoint read-only paginado por `-sequence`, respeitando ownership (AGENT só vê o seu). *Findings:* `gap-activity-feed-endpoint`.
**Risco:** superfície nova sobre o `AuditLog` (PII/IPs). Garantir GET-only estrito (não compromete imutabilidade desde que não adicione escrita) e filtro de ownership.

**T07 — Enriquecer `/api/stats/dashboard/` com deltas 24h, total de activos e mini-séries.** `[P2 · fase-2-backend · M · baixo]`
O hero já consome o endpoint mas `buildTile`/`buildSparkline` recebem `delta=null` e desenham onda falsa. Adicionar por estado `{count, delta_24h, series[~7-9 pts]}` e agregado `{active_total, delta_up, delta_down}`. **Distinto do `/stats/` legacy** (que é v2). *Findings:* `gap-stats-24h-deltas`, `gap-stats-sparkline-timeseries`. Aditivo, há fallback no JS (não bloqueia, só torna os dados reais).

**T08 — Limpar CSP: remover `cdnjs` morto e autorizar CartoDB.** `[P1 · fase-2-backend · S · médio]`
Confirmado `middleware.py:121-125`: `cdnjs.cloudflare.com` em 4 directivas mas o Leaflet é self-hosted (allowlist morta), e CartoDB (`basemaps.cartocdn.com`) que o V20 usa **não está autorizado** — em produção (CSP enforced) os tiles do hero falham; em dev passa (Report-Only mascara). Acção: remover `cdnjs` + adicionar `https://*.basemaps.cartocdn.com` a `img-src`, com ADR (regra do projecto exige middleware+ADR juntos; superseder ADR-0007). *Findings:* `csp-cartodb-tiles-em-falta`, `csp-cdnjs-allowlist-morta`, `adr-0007-drift-sri-cdnjs`.

**T09 — Corrigir bug do hero geo + helper de mapas partilhado.** `[P1 · fase-3-frontend · M · baixo]`
`dashboard_geo_hero.js` lê `occ.latitude/longitude` mas o serializer dá `gps_lat/gps_lon` → NaN → zero marcadores. Fix trivial mas é a peça central da v2. Extrair `geoOf(obj)` e módulo `fq-map.js` (tile layer, bounds PT/Madeira/Açores, `makeMarkerIcon`, hook `fq:drawer-state`+resize→`invalidateSize` debounced) para as 3 páginas com mapa. *Findings:* `geo-hero-lat-lng-contract-drift`, `gap-geohero-latlng-bug`, `invalidatesize-helper-duplicado`, `casca-v2-so-no-dashboard`, `gap-occurrences-pagesize`, `gap-occurrence-region-insets`. *Depende de:* T02, T03, T08.

**T10 — Replicar casca v2 às páginas internas + limpar CSS órfão v1.** `[P2 · fase-3-frontend · L · baixo-médio]`
⚠️ **Reclassificado (§7/§8):** a casca v2 **já é global** (`base.html` carrega `app-shell.js`; todas as páginas fazem `{% extends %}`). Dashboard-only é só o hero geo + hook `invalidateSize`. O trabalho real: páginas internas herdam primitives v1 e arrastam CSS morto (`.navbar` ~300 LOC, hero v1 em `dashboard.css`, offsets sticky desalinhados 8px, `.fab-label` indefinido) + navegação mobile (hamburger/drawer da sidebar) + re-activar hero em mobile. *Findings:* `css-navbar-orfa`, `css-sticky-offset-stale`, `css-dashboard-hero-v1-orfa`, `css-fab-label-indefinido`, `gap-v20-hero-mobile`, `css-mobile-first-max-width-residual`, `css-leaflet-duplicado`, `css-segmented-page-local`, `css-state-cores-vs-neutralizacao`. *Depende de:* T09, T04, T05.

**T11 — Marcar `/stats/` legacy e `investigation_report` como v2.** `[P2 · ambas · S · baixo]`
`StatsView` (`/api/stats/` legacy) + `stats.js` (taxonomia obsoleta) + `investigation_report_view`. Marcar testes com skip/marker v2, esconder nav, congelar CSS. **NÃO apagar** (existe), só sinalizar a fronteira. **`DashboardStatsView` (`/api/stats/dashboard/`) FICA** (alimenta o hero — ver T07). *Findings:* `api-stats-legacy-v2`, `api-investigation-report-v2`, `stats-page-morta-taxonomia-obsoleta`, `stats-js-sem-iife-globais`, `stats-tests-v2`, `investigation-report-cobertura`, `css-stats-investigation-orfaos`, `readme-digitaldevice-stats-drift`.

**T12 — Throttle real na vista pública `/v/<hash>` + endurecimento.** `[P2 · fase-2-backend · M · baixo]`
Única exposição real: `verify_public` definido em settings (30/min) mas `public_verify_view` é vista Django pura **sem throttle** → superfície pública não-auth sem freio (mitigado só pelo HMAC 48 bits). Aplicar django-ratelimit por IP ou mover para endpoint DRF com `ScopedRateThrottle`. Mesma família: healthcheck sem throttle, correlation-id aceite sem validação, `SIGNING_KEY` com fallback para `SECRET_KEY`, CSP Report-Only sem coletor, login não revoga refresh anterior. *Findings:* `verify-public-throttle-orfao`, `healthcheck-sem-throttle-info-leak`, `correlation-id-aceita-input-cliente`, `jwt-signing-key-fallback-secret`, `csp-report-only-sem-report-uri`, `resolve-occurrence-scan-linear`, `login-nao-revoga-refresh-anterior`.

**T13 — Endurecer pipeline.** `[P2 · fase-2-backend · M · baixo]`
CI só corre testes+coverage; ruff/black/semgrep só no pre-commit (bypassável) com pins ~10 minor desactualizados (black 24.8 vs 26.3.1 que fecha CVE). Coverage nunca passa `--fail-under`. Três alvos divergentes (85/75/68). Alinhar versões → enforçar em CI → fixar UM número real. Fixar `trivy-action@master`. *Findings:* `ci-sem-lint-format-semgrep`, `precommit-versoes-desactualizadas`, `cobertura-tres-numeros-divergentes`, `ci-coverage-nao-enforca-threshold`, `pyproject-ignores-wave2e-obsoletos`, `trivy-action-pin-master`, `ci-matriz-python-unica`.

**T14 — Corrigir doc-drift e erros operacionais.** `[P2 · ambas · M · baixo]`
README chama PDF "relatório forense ISO 27037" (ADR-0012 diz guia de transporte) e anuncia CSV/DigitalDevice; nome de volume Fly errado no DR (`forensiq_data` vs `forensiq_media`); `.env.example` sem `QR_VERIFY_SECRET`/`AUDIT_LOG_RETENTION_DAYS`; checklist RGPD Art.32 d) errado; imutabilidade de `Occurrence` (0013) e ausência de trigger no `AuditLog` (N7) sub-documentadas; paleta teal do PDF; bug `_fmt_gps` (°N/°E sempre — corrigir antes do GPS aparecer no PDF). *Findings:* `readme-pdf-relatorio-forense-drift`, `readme-digitaldevice-stats-drift`, `dr-volume-nome-errado`, `env-example-faltam-segredos`, `rgpd-art32-alinea-d-stale`, `invariante-occurrence-imutavel-nao-documentado`, `auditlog-sem-trigger-pg-n7-aberto`, `fly-toml-release-command-sem-rollback`, `adr-reverse-geocode-nominatim-sem-registo`, `pdf-fmt-gps-hemisferio-errado`, `pdf-paleta-teal-navy-antiga`. *Depende de:* T04/T05 (README só depois de executados).
**Nota:** os findings `pdf-barcode-conflito-adr0012` e `pdf-sem-barcode-vs-brief` **NÃO são trabalho pendente** — ADR-0012 §6 rejeita Code128 e o QR já satisfaz o brief (ver §8).

**T15 — Uniformizar JS (IIFE), consolidar fontes-de-verdade, a11y.** `[P2 · fase-3-frontend · L · baixo-médio]`
~Metade dos page-scripts declaram dezenas de globais; o teste de namespace não segue `{% extends %}` (falsa segurança). 4 fontes-de-verdade para os 7 rótulos de estado (com drift visível). Download de PDF duplicado em 3 sítios. `getCsrfToken` reimplementado. Refresh 401 sem single-flight. Adoptar `role=grid/row/gridcell/aria-selected` na tabela e Popover API. Adicionar Ctrl+K e métricas do footer. *Findings:* `padrao-iife-inconsistente-listagens`, `namespace-test-nao-segue-extends`, `state-labels-duplicados-vs-config`, `pdf-download-duplicado-3-sitios`, `csrf-token-duplicado-occurrences-new`, `401-refresh-loop-sem-guarda-concorrencia`, `datatable-const-global-em-base`, `config-endpoints-mortos-pos-decisoes`, `a11y-tabela-sem-grid-roles`, `a11y-popover-api-ausente`, `gap-v20-app-top-cmdk`, `gap-v20-app-bottom-metricas`, `css-text-subtle-contraste`, `tpl-login-versao-desalinhada`, `frontend-tests-fragquanteis-ids`, `gps-sem-arredondamento-por-papel`, `gap-cmd-palette-search`. *Depende de:* T04/T05, T01, T06/T07/T03.

**T16 — Consolidar testes + `AuditLogFactory` + triggers PG + CSRF cookie.** `[P3 · fase-2-backend · M · baixo]`
Classes duplicadas entre catch-alls; ficheiros-gaveta por data; sem `AuditLogFactory`. Duas lacunas reais de invariante: (1) triggers PG nunca exercitados — `skipUnless(vendor=postgresql)` com cursor bruto; (2) fronteira CSRF por cookie real sem teste (`enforce_csrf_checks=True`). *Findings:* `classes-teste-duplicadas`, `catchall-coverage-cruft`, `factory-auditlog-em-falta`, `trigger-layer-untested`, `csrf-cookie-flow-sem-teste-dedicado`, `imei-throttle-cache-isolamento`, `fsm-cobertura-completa-confirmada`. *Depende de:* T04/T05.

**T17 — Coerência de contrato de API.** `[P3 · fase-2-backend · L · baixo]`
Shapes de erro divergentes (`{error}` vs `{detail}` no cascade e export_pdf vs handler global); `external_lookup_*` nunca materializados (Wave 2d — decidir escrever-no-create ou remover); cache/snapshot IMEI na view e não no serviço; escrita de `AuditLog` dispersa por 3 sítios; `EVIDENCE_LEAF_TYPES` vs "4 sub-componentes"; métricas do footer. *Findings:* `api-cascade-shape-inconsistente`, `api-pdf-export-shape-erro`, `api-evidence-external-lookup-drift`, `cache-imei-na-view-nao-no-servico`, `imei-record-critical-event-import-tardio`, `audit-escrita-dispersa`, `api-schema-scope-orfao`, `api-lookup-url-fora-router`, `api-basename-singular-vs-plural`, `api-immutability-confirmada`, `fsm-bem-localizada-confirmacao`, `gap-header-shift-zone-device`, `gap-occurrence-detail-composite`, `gap-health-metrics`, `gap-footer-build-binding`, `api-metricas-p50-footer-gap`, `footer-metricas-v2-sem-fonte`, `evidence-leaf-types-vs-subcomponentes`, `evidence-type-validacao-parcial`, `evidence-photo-hash-no-code`, `code-unique-state-vs-db-0009`, `migrations-auditlog-choice-cruft`.
**Invariante a guardar:** NUNCA mudar a classe base dos ViewSets POST-only nem `http_method_names`.

**T18 — *(novo, da verificação §7)* Coerência API/BD da `Occurrence` + classificar o fluxo de Intake.** `[P1 · ambas · M · médio-alto]`
Dois itens que os 9 agentes não conectaram e a verificação directa expôs:
- **`Occurrence` imutável em PG (0013) mas `OccurrenceViewSet` sem `http_method_names`** → a API expõe PUT/PATCH/DELETE que o trigger da BD recusa. Em produção dá 500; **em SQLite de teste passa silenciosamente a mutar prova**. Decidir tornar o ViewSet POST-only (coerente com os outros 3 e com a BD) — ver §6. *Findings:* `api-occurrence-mutavel-sem-audit` (elevado de info→**high**), `invariante-occurrence-imutavel-nao-documentado`, `api-occurrence-mutavel-sem-audit`.
- **Fluxo de Intake omitido pelo inventário** — `occurrence_intake_view` (`frontend_views.py:192-270`) é feature EXPERT real (ADR-0012 Vaga 2): checklist de recepção que submete para `/api/custody/cascade/` (que **fica**). Verificado: é v1, autenticada, par natural do PDF/QR. Precisa de re-skin v2 na Fase 3 (`occurrence_intake.html` + `403_intake.html`); não depende de endpoints removidos. Classificar explicitamente em ambas as fases.

**T19 — *(novo, 2026-05-30)* Taxonomia oficial de crimes + prioridade por Política Criminal + alertas.** `[P1 · ambas · L · médio]`
Torna a `priority` **semântica** (ancorada na lei) e acelera/normaliza a entrada de dados. Decisões do dono (2026-05-30):
- **Taxonomia = dados de referência (3 tabelas):** `CrimeCategoria` (N1, 6) → `CrimeSubcategoria` (N2) → `CrimeTipo` (N3, código oficial), semeadas da **Tabela de Crimes Registados 2024** (DGPJ/SIEJ Modelo 262 + INE/CSE; a de 2008 está desactualizada). Não é prova → é lookup admin-editável/versionável. Selector em cascata na criação; estatística por categoria alinhada com o INE.
- **`Occurrence.crime_type` FK→`CrimeTipo`** (obrigatório, definido na criação — coerente com a imutabilidade T18).
- **Prioridade binária `prioritária`/`normal`** (decisão: fiel à lei, **não** P1-P4), **derivada** de config versionada por biénio (`PoliticaCriminalPrioridade`) semeada da **Lei 51/2023**. Eixo operativo = **Art. 5.º (investigação prioritária)**; Art. 4.º (prevenção) guardado como flag informativa. **Override manual** pelo agente (`priority_source`: lei/manual). Nova lei = nova versão de config, zero código (a Lei 2025-2027 está só aprovada na generalidade em 2026-03-20, ainda não promulgada — modelar como versão futura).
- **Alertas na consola:** criar ocorrência com crime prioritário → evento no feed (liga a T06) + badge no hero.
- **Mapeamento curado** lei↔tabela (frases da lei → códigos N3/N2; ex.: "homicídio"→1, "violência doméstica"→194/195/196, "burla informática"→53, "cibercriminalidade"→subcat. 43) — trabalho bounded, candidato a workflow de mapeamento + verificação adversarial.

**Implicação Fase 3 (`art-direction.md`):** a colorbar/legenda do hero deixa de ser P1-P4 e passa a **2 estados (prioritária/normal)** — actualizar `art-direction.md` §Hero e o `geo-hero`. *Estende:* T03 (priority), T06 (feed/alertas). *Findings relacionados:* `gap-occurrence-priority`, `gap-occurrence-priority-serializer`, `gap-table-priority-feed-source`. *Depende de:* obter a Tabela 2024 (1.ª tarefa de dados da Fase 2).

**T20 — *(novo, 2026-05-30; redesenhado para ledger de eventos)* Custódia como ledger de eventos.** `[P1 · ambas · XL · risco ALTO]`
Substitui a máquina de estados linear por um **ledger de eventos** (trajetória documentada). Largou-se o grafo rígido: a custódia real é **não-linear** — a prova move-se livremente entre OPC / lab / lab privado / tribunal, com **múltiplas perícias** (CPP Art. 158.º) e encaminhamentos em **ordem livre** (Art. 154.º; cadeia de custódia = documentar o percurso, não impor sequência). É a maior mudança da Fase 2 e toca o núcleo forense. Modelo (ADR-0015):
- **Registo = evento.** Sai `previous_state/new_state` + `VALID_TRANSITIONS`. Entra `event_type`: `APREENSAO` · `VALIDACAO` · `DESPACHO_PERICIA` · `TRANSFERENCIA` · `INICIO_PERICIA` · `CONCLUSAO_PERICIA` · `RESTITUICAO`⛔ · `PERDA_FAVOR_ESTADO` · `DESTRUICAO`⛔.
- **Dois eixos:** evento + `custodian_type` (`LOCAL_CRIME`/`OPC`/`LAB_PUBLICO`/`LAB_PRIVADO`/`TRIBUNAL`/`DEPOSITARIO`/`PROPRIETARIO`) + `location_name` (POI OSM) + `storage_location` (armário/sala) + GPS (de T01).
- **Validador = guardas mínimas** no `clean()` (não grafo): apreensão é o 1.º evento; validação ≤72h, uma vez; perícia exige despacho prévio; terminais fecham; **tudo o resto é ordem livre e repetível**.
- **Estado legal derivado** do log (não gravado): à_guarda_OPC / validada / em_perícia / perícia_concluída / encaminhada / restituída⛔ / perdida_a_favor_do_Estado / destruída⛔ — para filtros, colorbar e timeline.
- **Estabelecimentos via OSM/Nominatim** (sem tabela curada): reusa o reverse-geocode + throttle `reverse_geocode`, estendido a POIs próximos (Overpass); CSP a coordenar com T08.

**Nota forense:** **sem legado/retrocompatibilidade** (greenfield — substituição limpa de colunas, não migração aditiva). Hash **único e limpo** fixado no ADR-0013 (todos os campos sempre incluídos; null→vazio; texto livre escapado; coordenadas quantizadas a 7 casas). Append-only / imutabilidade 3 camadas / POST-only / validador-no-modelo intactos. *Estende:* T01 (GPS), liga-se a T18 (intake = `TRANSFERENCIA`→lab). *Depende de:* T01 + **ADR-0015 (escrito: `ADR-0015-custodia-ledger-eventos.md`)**. Verificação adversarial feita (workflow).
**Implicação Fase 3:** o `transition_modal` passa a `event_type` + custódio + GPS + POI; o mini-mapa "Cadeia" mostra a trajetória.

---

## 4. Blockers da v2 (têm de ser feitos na Fase 2)

1. **GPS na `ChainOfCustody`** (modelo + serializer + write) — sem isto o mini-mapa "Cadeia", a polyline e os tooltips ±Nm não têm fonte. (T01)
2. **Entrada do GPS no `compute_record_hash` de forma versionada**, fixada no ADR-0013 **antes** de produção — decisão forense irreversível. (T01)
3. **`Occurrence.crime_type` + `priority` binária (da Política Criminal)** + serializer — sem isto a colorbar/legenda e a cor dos pins são decorativas; é também a base dos alertas de crime prioritário. (T03/T19)
4. **Endpoint read-only de feed sobre `AuditLog`** — o feed do dashboard é 100% estático no mockup. (T06)
5. **CSP autorizar CartoDB** — em produção o mapa-herói falha silenciosamente. (T08)
6. **Fix do contrato `gps_lat/gps_lon`** no hero — a peça mais visível não funciona hoje. (T09)
7. **Convenção única de longitude** decidida e registada no ADR-0013 antes de criar os campos. (T02)
8. **Deltas 24h + mini-séries** no `/stats/dashboard/` — sem isto deltas e sparklines são falsos (não bloqueia o ecrã, mas mina a demo). (T07)

---

## 5. Sequenciamento recomendado da Fase 2

**PASSO 0 — decisões + docs (desbloqueia tudo).** T02 (decidir `gps_lon`/`gps_lng`) + escrever **ADR-0013** com a fórmula de hash versionada e a tabela de arredondamento por papel. **Nada de GPS toca código antes do ADR.** Decidir aqui também o âmbito de stats (T11), a coerência da `Occurrence` (T18) e a manutenção do choice `EXPORT_CSV`.

**PASSO 1 — remoções limpas (encolhem o blast radius).** T04 (CSV) e T05 (DigitalDevice). Fazer cedo reduz a superfície que tudo o resto toca e simplifica `StatsView`. T05 mexe em triggers PG — `DROP IF EXISTS` e **confirmar dados em Neon primeiro**.

**PASSO 2 — a peça forense crítica (sobre o ADR já fechado).** T01 (GPS + hash versionado + arredondamento server-side + verificador de cadeia). Escrever o **teste de determinismo do hash com GPS preenchido ao mesmo tempo que o código** (não depois), para a invariante não regredir silenciosamente.

**PASSO 3 — lacunas estruturais aditivas (paralelizáveis).** T03 (`priority` + `evidences_count`), T06 (feed `AuditLog`), T07 (deltas/séries). Nenhum toca invariantes; T06 exige ownership + read-only estrito.

**PASSO 4 — habilitar a Fase 3 do lado do backend.** T08 (CSP CartoDB + superseder ADR-0007). Pode correr em paralelo com o PASSO 3.

**PASSO 5 — segurança P2 (isolado).** T12. Sem dependências; encaixa em qualquer altura.

**Transversais (P2/P3, ao longo da Fase 2, sem bloquear o caminho crítico):** T13, T14 (README só depois de T04/T05), T16, T17, e a parte backend de T18.
**Abre a Fase 3:** T09 (depende de T02/T03/T08), depois T10, T15 e o re-skin do intake/públicas.

**Tracks novos desta sessão (2026-05-30):**
- **T19 (taxonomia de crimes + prioridade):** track independente do GPS. Arranca por **obter a Tabela 2024** + redigir **ADR-0014**; depois 3 tabelas de referência + `crime_type`/`priority` na Occurrence (com T03/T18) + alertas (com T06). Paralelizável com o PASSO 2/3.
- **T20 (custódia como ledger de eventos + localização):** o maior e mais sensível. **Depende de T01** (campos GPS/localização) + **ADR-0015**. Entra **depois** do PASSO 2 (GPS no hash fechado), com validação adversarial por workflow antes de tocar o validador (guardas mínimas no `clean()`). Liga-se a T18 (intake = `TRANSFERENCIA`→lab).

**Invariante a guardar em todos os passos:** nunca mudar a classe base dos ViewSets POST-only nem `http_method_names` (reabriria PUT/PATCH/DELETE); nunca squashar migrations de imutabilidade (`0002`/`0008`/`0013`) nem RunPython de dados; **nunca reescrever registos da cadeia** (estados/campos novos são sempre aditivos); qualquer processamento de GPS (incl. ajuste manual) é **sempre** pré-hash, server-side.

---

## 6. Decisões de âmbito

Esta secção fecha a Fase 1. **Estado (2026-05-30):** D1, D2, D5 e D8
(forensicamente irreversíveis) **DECIDIDAS** pelo dono — ver cada bloco.
D3, D4, D6 e D7 (P2/P3, reversíveis) **seguem a recomendação por defeito**
até decisão em contrário.

**D1 — O GPS entra no `compute_record_hash`? Como tratar registos históricos?** ✅ **DECIDIDO (2026-05-30): (c) aditiva/versionada.**
Opções: (a) não entra (fica fora do ledger, mas o trigger de linha protege-o de UPDATE); (b) entra sempre (partiria o recálculo de todos os hashes históricos); (c) **entra de forma aditiva/versionada** (anexa segmento só quando não-nulo, ou `hash_version`).
**Decisão: (c).** Mantém o recálculo idêntico para o histórico (GPS=None) e cobre transições novas. Fixar a ordem dos campos e a regra de serialização no ADR-0013. **É a decisão forense mais crítica do refactor — irreversível depois de em produção.**

**D2 — `gps_lon` (já em produção) ou normalizar para `gps_lng` (spec/mockup)?** ✅ **DECIDIDO (2026-05-30): (b) normalizar tudo para `gps_lng`.**
**Decisão: (b).** Convenção única `gps_lng` em todo o schema (Occurrence/Evidence/ChainOfCustody) + spec/mockup. **Implica:** migration de rename `gps_lon`→`gps_lng` em `Occurrence` e `Evidence` + actualizar `filters.py`, serializers, `pdf_export._fmt_gps`, e todo o JS de mapas (`config.js`, `dashboard_geo_hero.js`, pages). **Nota forense:** o rename **não** altera o `integrity_hash` da `Evidence` (o hash usa o *valor*, não o nome do campo). Confirmar que nenhum índice/constraint depende do nome antigo. Efeito colateral positivo: elimina a raiz do bug do hero (uma só convenção).

**D3 — Squash de migrations: agora ou adiar?**
**Recomendação: (a) limitado** — só o bloco de choices do `AuditLog` (0012/0015/0016, puro ruído), e **só depois** de estabilizar o schema da Fase 2. **Nunca** squashar 0002/0008/0013 nem RunPython de dados. É P3, não bloqueia.

**D4 — Remover `/stats/` legacy e `investigation_report` já, ou só marcar v2?**
**Recomendação: (b) marcar v2.** Apagar agora é trabalho desperdiçado se voltarem; marcar deixa a fronteira explícita sem custo. **Separar `/stats/dashboard/` (FICA) do `/stats/` legacy (sai).**

**D5 — Granularidade do GPS / arredondamento por papel?** ✅ **DECIDIDO (2026-05-30): precisão máxima, SEM arredondamento por papel, com ajuste manual.**
**Reenquadramento do dono:** o GPS na custódia regista **onde está a evidência** em cada transição (apreensão, transporte, armazenamento no laboratório), **não** é vigilância da posição do agente. É necessidade estrita para a prova ("need to know"). A inferência da posição do agente é incidental e aceitável (acontece em qualquer registo de campo).
**Decisão:** capturar a posição com **a precisão máxima possível** (`gps_lat`/`gps_lng` com casas suficientes — `decimal_places=7` como `Occurrence`/`Evidence`) + `gps_accuracy_m` (precisão reportada pelo dispositivo, metadado, não arredondamento). **Sem** tabela de arredondamento por papel. O agente pode **ajustar a posição manualmente** antes de submeter a transição (correcção de drift de GPS) — o ajuste tem de ser **pré-hash** (o registo torna-se imutável ao gravar). Adicionar ainda **localização de armazenamento textual** (ex.: "Armário B-12, Sala 3") para os estados de laboratório (`RECEBIDA_LABORATORIO`/`EM_PERICIA`) — o GPS dá o sítio, o armário dá a gaveta. O ADR-0013 documenta a base legal (necessidade/finalidade probatória; minimização satisfeita pela limitação de finalidade, não por coarsening de coordenadas).

**D6 — Fechar N7 (trigger PG de imutabilidade no `AuditLog`) agora?**
Refinado pela verificação (§7): `seed_demo` usa **TRUNCATE** (não dispara `BEFORE DELETE` — seguro), mas `purge_audit_logs` usa `QuerySet.delete()` (**DELETE SQL — seria bloqueado**).
**Recomendação: (a) adicionar o trigger** *se* o `purge_audit_logs` for adaptado a `session_replication_role` no caminho de retenção controlado; caso contrário **(b) manter defesa ORM** e documentar honestamente. P2/P3, não bloqueia a v2.

**D7 — Métricas do footer técnico v2 (p50, uptime, testes, db) — dinâmicas ou build-time?**
**Recomendação: (b)** — `uptime` (process start) e `db` label triviais e reais; `commit`/`region`/`CSP` já existem no context_processor; `p50` (middleware de amostragem) e nº de testes como literais build-time honestos (`env FQ_TEST_COUNT`/`FQ_VERSION`) em vez de fingir runtime. Tornar `app_csp_label` dinâmico (Report-Only dev vs enforced prod).

**D8 — *(novo)* A `Occurrence` deve ser POST-only na API (coerente com a BD imutável)?** ✅ **DECIDIDO (2026-05-30): (a) tornar POST-only.**
A BD bloqueia qualquer UPDATE/DELETE de `Occurrence` (0013), mas `OccurrenceViewSet` não restringe métodos.
Opções: (a) **tornar POST-only** (`http_method_names = ['get','post','head','options']`, como os outros 3) — coerente com a BD; `priority` define-se só na criação; (b) manter mutável e remover o trigger 0013 (enfraquece a imutabilidade — **não recomendado**); (c) permitir edição de um subconjunto de campos não-forenses (exige relaxar o trigger por coluna — complexo).
**Decisão: (a).** É a única opção coerente com a imutabilidade já em vigor na BD e fecha a janela de mutação silenciosa em testes SQLite. Acção em T18: adicionar `http_method_names` ao `OccurrenceViewSet` + teste que confirme 405 em PUT/PATCH/DELETE. Confirmar que nenhuma funcionalidade legítima edita `Occurrence` hoje (`crime_type`/`priority` passam a ser campos de criação).

### Decisões de produto adicionais (2026-05-30, parte 2 — taxonomia & prioridade, ver T19)

**D9 — Taxonomia de crimes:** ✅ obter a **Tabela de Crimes Registados 2024** (DGPJ/SIEJ Modelo 262 + INE/CSE) e modelar em **3 tabelas de referência** (`CrimeCategoria`→`CrimeSubcategoria`→`CrimeTipo`, com código oficial). A de 2008 fica como referência histórica.

**D10 — Escala de prioridade:** ✅ **binária** `prioritária`/`normal`, fiel à Lei de Política Criminal (**não** P1-P4), derivada de config versionada por biénio + override manual. **Eixo operativo = Art. 5.º (investigação prioritária)**; Art. 4.º (prevenção) como flag informativa. **Implica:** colorbar/legenda do hero a 2 estados — actualizar `art-direction.md` na Fase 3.

**D11 — `crime_type` + alertas:** ✅ `Occurrence.crime_type` FK obrigatória à taxonomia, definida na criação (coerente com a imutabilidade T18). Ao registar crime prioritário → alerta na consola (feed T06 + badge no hero). Mapeamento curado lei↔tabela a produzir (workflow de mapeamento + verificação).

> Lei sucessora: a **Lei de Política Criminal 2025-2027** foi aprovada na generalidade (2026-03-20) mas **não está promulgada** — a config de prioridade fica semeada com a 51/2023 e pronta a receber a 2025-2027 quando publicada (sem código novo).

---

## 7. Correções e verificações pós-varredura

Factos load-bearing **verificados directamente nos ficheiros** após a síntese
(corrigem ou refinam o output dos agentes):

1. **`Occurrence` imutável em PG vs ViewSet mutável** — `0013_protect_occurrence` cria triggers `BEFORE UPDATE/DELETE` que bloqueiam **toda** a linha. `EvidenceViewSet`/`DigitalDeviceViewSet`/`ChainOfCustodyViewSet` têm `http_method_names = ['get','post','head','options']`, mas **`OccurrenceViewSet` (`views.py:203`) não tem** → expõe PUT/PATCH/DELETE. A síntese assumiu "Occurrence é mutável por desenho" — **incorrecto**. Elevado para T18/D8. (high)
2. **Intake confirmado e classificado** — `occurrence_intake_view` (`frontend_views.py:192-270`) é feature EXPERT real que submete para `/api/custody/cascade/` (que fica). v1, precisa de re-skin v2 (Fase 3), não depende de endpoints removidos. Estava ausente dos 151 findings; adicionado em T18. (high)
3. **N7 refinado** — `seed_demo.py:277` usa `TRUNCATE` (comentário explícito: "TRUNCATE não dispara [DELETE triggers]"), logo um trigger no `AuditLog` **não** o parte. Mas `purge_audit_logs.py:149` usa `AuditLog.objects.filter(...).delete()` (DELETE SQL) → **seria bloqueado**. D6 actualizada.
4. **Casca v2 é global, não dashboard-only** — `base.html` carrega `app-shell.js` e o shell (app-top/app-grid/app-drawer) aplica-se a todas as páginas via `{% extends %}`. Só o hero geo + hook `invalidateSize` são dashboard-only. `casca-v2-so-no-dashboard` (high) está **sobre-severizado** → tratado como medium em T10.
5. **Bug do hero geo confirmado** — `dashboard_geo_hero.js:217-218` lê `occ.latitude/longitude`; `serializers.py:138-139` expõe `gps_lat/gps_lon` → NaN → zero marcadores. (real, T09)
6. **CSP confirmada** — `middleware.py:121-125`: `cdnjs` em 4 directivas (Leaflet self-hosted via `_leaflet_head.html`/`_leaflet_js.html` — morto), CartoDB ausente. (real, T08)
7. **Hash sem GPS confirmado** — `models.py:1085-1094`: `previous_hash|seq|evidence_id|previous_state|new_state|agent_id|timestamp|observations`. (real, T01)

---

## 8. Crítica de completude e riscos de falso-positivo

**Cobertura estimada ~85% do código relevante; o caminho crítico da Fase 2 está
completo e correcto.** Zonas bem cobertas: modelos/imutabilidade, hash-chain, FSM,
CSV, DigitalDevice, CSP, GPS, stats. Zonas sub-varridas (agora endereçadas em §7
ou registadas abaixo):

- **Intake** — endereçado em T18/§7.
- **Wizard de criação de evidência** (`wizard.js`/`evidences_new.js`, ~1130 LOC) e `tests_image_processing.py`/`tests_table_mode.py` mal apareceram — candidatos a churn forte no re-skin (captura GPS com `toFixed(7)`). A afinar em T15.
- **Páginas públicas** (`public_verify.html`/`public_verify_notfound.html`) fora do plano de Fase 3 — são as únicas que um perito externo vê (destino dos QR). Decidir re-skin (provavelmente minimalista/standalone, não shell completo) na Fase 3.
- **Captura GPS de custódia é código NOVO** — `transition_modal.js` só manipula `{ids,newState,observations}`; **não captura GPS hoje**. T01 inclui criar essa UI de raiz (não é "afinar arredondamento existente"). O `gps-sem-arredondamento-por-papel` aponta para os wizards de Occurrence/Evidence, não para a transição.

**Riscos de falso-positivo a verificar antes de agir:**

- `casca-v2-so-no-dashboard` (high → **medium**): shell é global (ver §7.4).
- `css-leaflet-duplicado` (low): parcialmente FP — o vendor Leaflet já está deduplicado via partials; o que está em `occurrences.css` é só o theme override.
- `invalidatesize-helper-duplicado` (low): confirmar se são 2 ou 3 implementações antes de dimensionar `fq-map.js`.
- `gps-sem-arredondamento-por-papel` (medium): correcto no alvo, FP no enquadramento (ver acima).
- `resolve-occurrence-scan-linear` (low): dívida assumida e documentada (`qr_verify.py:46-54`), fora de âmbito v1, mitigada pelo throttle de T12.
- `pdf-barcode-conflito-adr0012` / `pdf-sem-barcode-vs-brief`: **NÃO são trabalho pendente** — ADR-0012 §6 rejeita Code128 e o QR já satisfaz o brief. Marcar como não-aplicável.

---

## 9. Critério de fecho da Fase 1

- [x] Inventário em disco (`docs/refactor/REFACTOR_MANIFEST.md`).
- [x] Manifesto commitado na branch `refactor/art-direction-v2` (`0fcd970`).
- [x] **Dono aprovou o âmbito** — D1/D2/D5/D8 decididas (2026-05-30); D3/D4/D6/D7 seguem a recomendação por defeito (§6).

> **Fase 1 fechada.** Fase 2 em curso na branch `refactor/backend-cleanup`.

## 10. Progresso da Fase 2

**PASSO 0 — ADRs (concluído; escritos em `5798b01`, reescritos em `eaa63e7`):**
- ✅ **ADR-0013** — `ADR-0013-gps-cadeia-custodia.md`. GPS na cadeia; **dono único da fórmula do hash** (única e limpa: todos os campos sempre incluídos, null→vazio, texto livre escapado, coordenadas quantizadas a 7 casas); convenção `gps_lng`; precisão máxima; ajuste manual pré-hash.
- ✅ **ADR-0014** — `ADR-0014-taxonomia-crimes-prioridade.md`. 3 tabelas (Tabela 2024) + prioridade binária da Lei 51/2023 Art. 5.º (config versionada, override manual, alertas).
- ✅ **ADR-0015** — `ADR-0015-custodia-ledger-eventos.md`. **Custódia como ledger de eventos** (CPP Art. 154/158/178): `event_type` + custódio + local; validador = guardas mínimas; estado legal derivado; OSM/Overpass.
- **3 correcções do dono aplicadas na reescrita (`eaa63e7`):** (1) **sem legado/retrocompatibilidade** — greenfield, substituição pura (hash limpo, sem versionamento); (2) **ADR-0015 refeito de raiz** como ledger de eventos (largou a FSM rígida); (3) **voz na 1.ª pessoa** do projecto (zero "o dono decidiu"). Redigidos por workflow + **verificação adversarial** (`voice_ok`/`no_legacy_ok`/`model_coherent` = true; invariantes intactos).

> **Princípio global da Fase 2 (decisão do projecto):** **sem legado, sem retrocompatibilidade.** A aplicação é construída de raiz; substitui-se código/campos/formatos sem preservar nada antigo. Aplica-se a todo o refactor.

**Reserva de numeração de migrations** (evita colisão entre tracks paralelos):
- Track GPS (T01/T02): **`0018`** (rename `gps_lng`) + **`0019`** (GPS na custódia).
- Track taxonomia (T19): **`0020`** (taxonomia) + **`0021`** (`crime_type`/`priority` na Occurrence).

**Próximo:** obter o seed da **Tabela de Crimes 2024** (1.ª tarefa de dados, fundamenta o seed de T19) + arrancar o código do PASSO 1/2 (T02 rename → T04/T05 remoções → T01 GPS). T20 (FSM) por último, com verificação adversarial antes de tocar o validador.

---

## Anexo A — Findings (151)

Cada finding é rastreável por `id`. Severidade: `blocker` > `high` > `medium` >
`low` > `info`. Fase: resolve-se em `fase-2-backend`, `fase-3-frontend`, `ambas`,
ou `fora-de-ambito`.

#### Backend — Modelos & BD (15)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | fase-2-backend | `coc-gps-hash-versionado` | Adicionar GPS à ChainOfCustody exige estender compute_record_hash de forma aditiva/versionada | `src/backend/core/models.py:1052-1094` |
| high | ambas | `digitaldevice-deprecacao-blast` | DigitalDevice (legacy) a deprecar — mapa completo do blast radius | `src/backend/core/models.py:790-911` |
| medium | fase-2-backend | `coc-gps-campos` | ChainOfCustody não tem campos GPS (gps_lat/gps_lng/gps_accuracy_m a adicionar) | `src/backend/core/models.py:955-1012` |
| medium | fase-2-backend | `coc-gps-nome-lng-vs-lon` | Nomenclatura GPS divergente: decisão usa gps_lng, mas a base usa gps_lon em todo o lado | `src/backend/core/models.py:251-258` |
| medium | fase-2-backend | `coc-gps-trigger-imutabilidade` | Novos campos GPS da custódia ficam cobertos pelo trigger de linha, mas a função documental de campos imutáveis não os lista | `src/backend/core/migrations/0008_extend_immutability.py:55-85` |
| medium | fase-2-backend | `code-unique-state-vs-db-0009` | Campo code: unicidade criada por índice manual (PG) vs UniqueConstraint declarado no state — divergência state/DB potencial | `src/backend/core/migrations/0009_human_codes.py:235-289` |
| medium | ambas | `csv-remocao-auditlog-choice` | Remover CSV deixa AuditLog.Action.EXPORT_CSV e migrations 0012/0015/0016 com referência morta | `src/backend/core/models.py:1219` |
| medium | fase-2-backend | `digitaldevice-trigger-remocao` | Remover DigitalDevice obriga a dropar trigger PG prevent_device_modification antes do DROP TABLE | `src/backend/core/migrations/0002_add_immutability_triggers.py:90-141` |
| medium | ambas | `evidence-leaf-types-vs-subcomponentes` | EVIDENCE_LEAF_TYPES (4) não coincide com os '4 sub-componentes' declarados na taxonomia | `src/backend/core/models.py:373-402` |
| low | fase-2-backend | `digitaldevice-imei-luhn-divergencia-historica` | Histórico de validação IMEI do DigitalDevice (regex sem Luhn → Luhn) deixou registos legados possivelmente inválidos | `src/backend/core/migrations/0003_alter_digitaldevice_evidence_and_more.py:21-25` |
| low | fase-2-backend | `digitaldevice-resourcetype-orfao` | AuditLog.ResourceType.DEVICE fica órfão após deprecar DigitalDevice | `src/backend/core/models.py:1228` |
| low | fora-de-ambito | `evidence-photo-hash-no-code` | integrity_hash da Evidence não inclui o code nem o pk — apenas metadados de conteúdo | `src/backend/core/models.py:603-633` |
| low | fase-2-backend | `evidence-type-validacao-parcial` | type_specific_data só é validado para 3 dos 18 tipos (IMEI/VIN/IMSI) | `src/backend/core/models.py:736-769` |
| low | fase-2-backend | `migrations-auditlog-choice-cruft` | Cruft de migrations: 0012/0015/0016 são bumps cumulativos das choices de AuditLog.action | `src/backend/core/migrations/0012_alter_auditlog_action.py:1-35` |
| info | fora-de-ambito | `pdf-barcode-conflito-adr0012` | Briefing pede 'barcodes/QR' no PDF, mas ADR-0012 rejeita explicitamente Code128 — QR já implementado | `docs/architecture/adr/ADR-0012-pdf-transport-guide.md:57` |

#### Backend — APIs & Serializers (21)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | fase-2-backend | `api-gps-hash-chain` | Decidir se o GPS novo entra na fórmula compute_record_hash (impacto forense) | `src/backend/core/models.py:1085-1094` |
| high | ambas | `bd-chainofcustody-sem-gps` | ChainOfCustody não tem campos GPS — decisão de produto exige adicioná-los | `src/backend/core/models.py:919-1004` |
| medium | fase-2-backend | `api-csv-export-custody-morto` | Action export_csv em ChainOfCustodyViewSet — remover por completo | `src/backend/core/views.py:706-766` |
| medium | fase-2-backend | `api-csv-export-evidence-morto` | Action export_csv em EvidenceViewSet — remover por completo | `src/backend/core/views.py:538-596` |
| medium | fase-2-backend | `api-csv-export-occurrence-morto` | Action export_csv em OccurrenceViewSet — remover por completo | `src/backend/core/views.py:279-324` |
| medium | fase-2-backend | `api-digitaldevice-deprecar` | DigitalDeviceViewSet — modelo legacy a deprecar, consolidar em evidência | `src/backend/core/views.py:604-635` |
| low | fase-2-backend | `api-cascade-shape-inconsistente` | Formato de erro do endpoint cascade diverge do handler global | `src/backend/core/views.py:848-862` |
| low | fase-2-backend | `api-csv-helpers-orfaos` | Helpers e constante CSV ficam órfãos após remoção do export | `src/backend/core/views.py:83-134` |
| low | fase-2-backend | `api-csv-scope-orfao` | Scope de throttle csv_export fica órfão após remoção do CSV | `src/backend/forensiq_project/settings.py:146` |
| low | fase-2-backend | `api-digitaldevice-viewset-inconsistente` | DigitalDeviceViewSet diverge dos restantes ViewSets (sem ordering/DjangoFilter) | `src/backend/core/views.py:604-617` |
| low | fase-2-backend | `api-evidence-external-lookup-drift` | Campos external_lookup_* read-only nunca materializados (Wave 2d incompleta) | `src/backend/core/serializers.py:251-268` |
| low | ambas | `api-investigation-report-v2` | investigation_report — marcar v2 / fora de âmbito v1 | `src/backend/core/frontend_views.py:174-183` |
| low | fase-3-frontend | `api-metricas-p50-footer-gap` | Gap v2: não há endpoint de métricas (p50/latência) para o footer pro-tool | `src/backend/core/urls.py:63` |
| low | fase-2-backend | `api-pdf-export-shape-erro` | Erros de geração de PDF usam chave 'error' em vez de 'detail' | `src/backend/core/views.py:365-369` |
| low | fase-2-backend | `api-schema-scope-orfao` | Scope de throttle 'schema' definido mas nunca aplicado | `src/backend/forensiq_project/settings.py:147` |
| low | ambas | `api-stats-legacy-v2` | StatsView (/api/stats/ legacy) — marcar v2 / fora de âmbito v1 | `src/backend/core/views.py:1096-1136` |
| info | fora-de-ambito | `api-basename-singular-vs-plural` | Basenames singulares vs prefixos de rota plurais (cosmético) | `src/backend/core/urls.py:41-45` |
| info | fase-3-frontend | `api-csv-config-js-ausente` | URLs CSV estão hardcoded no JS, não em CONFIG.ENDPOINTS | `src/frontend/static/js/config.js:21-34` |
| info | fase-2-backend | `api-immutability-confirmada` | Confirmação: EvidenceViewSet e ChainOfCustodyViewSet são POST-only (OK) | `src/backend/core/views.py:401` |
| info | fase-2-backend | `api-lookup-url-fora-router` | Lookups IMEI/VIN são APIViews fora do router, sob prefixo evidences/ | `src/backend/core/urls.py:49-59` |
| info | fase-2-backend | `api-occurrence-mutavel-sem-audit` | OccurrenceViewSet permite PUT/PATCH/DELETE sem auditar a edição (ver §7/T18 — incoerente com BD imutável) | `src/backend/core/views.py:203-214` |

#### Backend — Services & Lógica (14)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | fase-2-backend | `coc-hash-sem-gps` | Fórmula do hash-chain da custódia não inclui GPS — adicionar GPS muda a integridade | `src/backend/core/models.py:1085-1094` |
| medium | fase-2-backend | `adr-0013-gps-custody-em-falta` | ADR-0013 (GPS na cadeia de custódia) ainda não existe | `docs/architecture/adr/` |
| medium | fase-2-backend | `coc-arredondamento-por-papel-inexistente` | Arredondamento de GPS por papel (AGENT 3 casas / PERITO 4 casas) não existe | `src/backend/core/models.py:919-1012` |
| medium | ambas | `csv-export-a-remover-services` | Export CSV (3 endpoints + helpers + enum) a remover por decisão de produto | `src/backend/core/views.py:280-324` |
| medium | ambas | `digitaldevice-legacy-no-pdf` | DigitalDevice legado ainda renderizado no PDF (a deprecar) | `src/backend/core/pdf_export.py:550-635` |
| medium | fase-2-backend | `verificacao-cadeia-inteira-inexistente` | Não existe utilitário para verificar a cadeia inteira nem recomputar integrity_hash | `src/backend/core/models.py:1052-1102` |
| low | fase-2-backend | `audit-escrita-dispersa` | Criação de AuditLog dispersa por 3 sítios (audit.py, imei_lookup, purge_audit_logs) | `src/backend/core/audit.py:83-134` |
| low | fase-2-backend | `cache-imei-na-view-nao-no-servico` | Cache de IMEI e persistência do snapshot vivem na view, não no serviço | `src/backend/core/views.py:907-951` |
| low | fase-2-backend | `pdf-fmt-gps-hemisferio-errado` | _fmt_gps imprime sempre °N/°E — hemisfério errado para Portugal (longitude W) | `src/backend/core/pdf_export.py:338-341` |
| low | fase-3-frontend | `pdf-paleta-teal-navy-antiga` | Paleta do PDF ainda é teal/navy — desalinhada do art direction v2 (amber) | `src/backend/core/pdf_export.py:99-110` |
| low | fase-2-backend | `pdf-sem-barcode-vs-brief` | Brief pede 'barcodes' mas ADR-0012 §6 decidiu explicitamente NÃO usar Code 128 | `docs/architecture/adr/ADR-0012-pdf-transport-guide.md:57` |
| low | fora-de-ambito | `resolve-occurrence-scan-linear` | resolve_occurrence faz full-table scan recomputando HMAC por ocorrência | `src/backend/core/qr_verify.py:46-61` |
| info | fora-de-ambito | `fsm-bem-localizada-confirmacao` | FSM da custódia está bem centralizada no modelo (não duplicada nas views) — manter | `src/backend/core/views.py:689-704` |
| info | fase-2-backend | `imei-record-critical-event-import-tardio` | _record_critical_event usa import tardio de AuditLog para evitar ciclo models→services→models | `src/backend/core/services/imei_lookup.py:141-162` |

#### Backend — Auth, Segurança, Observabilidade (12)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | ambas | `csp-cartodb-tiles-em-falta` | CSP img-src não autoriza tiles CartoDB que o mapa hero v2 usa | `src/backend/core/middleware.py:124` |
| high | fase-2-backend | `verify-public-throttle-orfao` | Scope de throttle 'verify_public' definido mas nunca aplicado à vista pública não autenticada | `src/backend/forensiq_project/settings.py:153-155` |
| medium | fase-2-backend | `adr-0007-drift-sri-cdnjs` | ADR-0007 documenta SRI+cdnjs para Leaflet, mas a implementação já fez self-hosting (alternativa A2 'rejeitada') | `docs/architecture/adr/ADR-0007-sri-integrity-e-referrer-policy.md:13-46` |
| medium | fase-2-backend | `csp-cdnjs-allowlist-morta` | Allowlist cdnjs.cloudflare.com na CSP é dead code (Leaflet já é self-hosted) | `src/backend/core/middleware.py:121-125` |
| medium | ambas | `footer-metricas-v2-sem-fonte` | Footer v2 pede p50/uptime/testes verdes mas não há fonte de dados nem endpoint de métricas | `src/backend/core/context_processors.py:31-36` |
| medium | ambas | `gps-custody-rounding-privacidade` | GPS por papel (arredondamento de privacidade) a adicionar à ChainOfCustody — decisão com vertente de segurança | `src/backend/core/models.py:919` |
| low | fase-2-backend | `correlation-id-aceita-input-cliente` | CorrelationIDMiddleware aceita X-Correlation-ID do cliente sem validar formato | `src/backend/core/middleware.py:46-48` |
| low | fase-2-backend | `csp-report-only-sem-report-uri` | CSP em DEBUG é Report-Only mas sem report-uri/report-to — violações não são recolhidas | `src/backend/core/middleware.py:144-150` |
| low | fase-2-backend | `csv-throttle-scope-a-remover` | Scope de throttle 'csv_export' acompanha o export CSV decidido para remoção | `src/backend/forensiq_project/settings.py:147` |
| low | fase-2-backend | `healthcheck-sem-throttle-info-leak` | Healthcheck público sem throttle e sem nenhum dos throttle scopes globais | `src/backend/core/views.py:1344-1357` |
| low | fase-2-backend | `jwt-signing-key-fallback-secret` | JWT SIGNING_KEY faz fallback para SECRET_KEY (acoplamento de rotação) | `src/backend/forensiq_project/settings.py:192` |
| info | fora-de-ambito | `login-nao-revoga-refresh-anterior` | Login emite novo par sem revogar refresh anterior do mesmo utilizador | `src/backend/core/auth_views.py:40-55` |

#### Frontend — JS (18)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | fase-3-frontend | `casca-v2-so-no-dashboard` | Casca v2 (drawer 3-estados + invalidateSize) só está ligada ao dashboard (ver §7.4 — shell é global; sobre-severizado) | `src/frontend/static/js/app-shell.js:56-117` |
| high | fase-3-frontend | `geo-hero-lat-lng-contract-drift` | Hero geo lê occ.latitude/longitude mas serializer devolve gps_lat/gps_lon — mapa nunca pinta marcadores | `src/frontend/static/js/pages/dashboard_geo_hero.js:217-218` |
| medium | ambas | `csv-frontend-morto` | Lógica de export CSV (refreshExportLink) presente em 3 listagens — remover (decisão de produto) | `src/frontend/static/js/pages/occurrences.js:148-156` |
| medium | ambas | `digitaldevice-evidence-detail-legacy` | evidence_detail.js consome /api/devices/ (DigitalDevice legacy) — consolidar em Evidence | `src/frontend/static/js/pages/evidence_detail.js:27-44, 64-68, 225-274` |
| medium | ambas | `digitaldevice-occurrence-detail-legacy` | occurrence_detail.js mantém cache devicesByEvidence + LEGACY_DEVICE_ICON (DigitalDevice) | `src/frontend/static/js/pages/occurrence_detail.js:26-38, 46-47, 770-778` |
| medium | ambas | `gps-sem-arredondamento-por-papel` | Captura GPS usa toFixed(7) fixo — falta arredondamento por papel e gps_accuracy_m (nos wizards; ver §8) | `src/frontend/static/js/pages/evidences_new.js:957-958` |
| medium | fase-3-frontend | `namespace-test-nao-segue-extends` | Teste de namespace só lê o template literal — não segue {% extends base.html %} | `src/backend/core/tests_frontend_js_namespace.py:166-169, 252-281` |
| medium | fase-3-frontend | `padrao-iife-inconsistente-listagens` | Páginas de listagem/detalhe não usam IIFE — dezenas de identificadores no global | `src/frontend/static/js/pages/occurrences.js:13-21` |
| medium | fora-de-ambito | `stats-page-morta-taxonomia-obsoleta` | stats.js (página /stats/ v2) usa taxonomia obsoleta DIGITAL_DEVICE/DOCUMENT/PHOTO e devices | `src/frontend/static/js/pages/stats.js:11-27` |
| low | fase-3-frontend | `401-refresh-loop-sem-guarda-concorrencia` | Refresh em 401 não desduplica pedidos concorrentes | `src/frontend/static/js/api.js:34-42` |
| low | ambas | `config-endpoints-mortos-pos-decisoes` | config.js mantém ENDPOINTS.DEVICES e STATS_LEGACY/STATS_DASHBOARD que saem com as decisões v1 | `src/frontend/static/js/config.js:26-31` |
| low | fase-3-frontend | `csrf-token-duplicado-occurrences-new` | occurrences_new.js reimplementa getCsrfToken() em vez de usar Auth.getCsrfToken() | `src/frontend/static/js/pages/occurrences_new.js:163-168` |
| low | fase-3-frontend | `datatable-const-global-em-base` | data-table.js expõe `const DataTable` global (não window.DataTable) carregado em base.html | `src/frontend/static/js/components/data-table.js:38` |
| low | fase-3-frontend | `invalidatesize-helper-duplicado` | Lógica de invalidateSize/init de Leaflet duplicada entre páginas | `src/frontend/static/js/pages/occurrences.js:252-257` |
| low | fase-3-frontend | `pdf-download-duplicado-3-sitios` | Lógica de download de PDF (fetch blob + revokeObjectURL) repetida em 3 ficheiros | `src/frontend/static/js/pages/evidence_detail.js:306-327` |
| low | fase-3-frontend | `state-labels-duplicados-vs-config` | Mapas de rótulos de estado (STATE_LABELS/stateLabels) duplicados em 4 ficheiros vs CONFIG/CustodyStates | `src/frontend/static/js/pages/evidences.js:207-215` |
| low | fora-de-ambito | `stats-js-sem-iife-globais` | stats.js declara constantes e funções no escopo global (sem IIFE) | `src/frontend/static/js/pages/stats.js:11-122` |
| info | ambas | `gps-lon-vs-lng-nomenclatura` | Nomenclatura GPS divergente: gps_lon (Occurrence/Evidence) vs gps_lng planeado para ChainOfCustody | `src/frontend/static/js/config.js` |

#### Frontend — CSS & Templates (18)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | ambas | `tpl-csv-export-morto` | Botão Exportar CSV presente em 3 templates (decisão: remover CSV por completo) | `src/frontend/templates/occurrences.html:51-58` |
| medium | fase-3-frontend | `a11y-popover-api-ausente` | Tooltips via title= em vez da Popover API que o manifesto e o mockup V20 especificam | `src/frontend/templates/base.html:83, 330-336` |
| medium | fase-3-frontend | `a11y-tabela-sem-grid-roles` | Tabela densa usa role=table + linhas role=link, falta role=grid/row/gridcell/aria-selected do manifesto | `src/frontend/static/js/components/data-table.js:408, 563` |
| medium | fase-3-frontend | `css-dashboard-hero-v1-orfa` | dashboard.css ainda estiliza o hero v1 (.custody-flow-card/.custody-river/.flow-state-card) que o template já não tem | `src/frontend/static/css/pages/dashboard.css:17-170` |
| medium | fase-3-frontend | `css-navbar-orfa` | Bloco .navbar (v1) inteiro órfão — substituído por .app-top mas não removido | `src/frontend/static/css/main.css:564-878` |
| medium | fase-3-frontend | `css-sticky-offset-stale` | Offsets sticky ancoram a --navbar-h-desktop (60px) mas o header real é --app-top-h (52px) | `src/frontend/static/css/main.css:1613, 2005-2006` |
| medium | fase-3-frontend | `gap-v20-app-top-cmdk` | app-top sem paleta de comandos Ctrl+K e com chips de contexto a placeholder | `src/frontend/templates/base.html:76-96` |
| medium | fase-3-frontend | `gap-v20-hero-mobile` | Hero geo e sidebar ocultos/degradados em mobile (<768/<1024) por implementar mobile-first | `src/frontend/static/css/components/geo-hero.css:348-360` |
| medium | ambas | `tpl-digitaldevice-seccoes` | Secções 'Dispositivos digitais' (DigitalDevice legacy) em evidence_detail, occurrence_detail e stats | `src/frontend/templates/evidence_detail.html:140-148` |
| low | fase-3-frontend | `css-fab-label-indefinido` | Classe .fab-label usada nos templates mas nunca definida no CSS | `src/frontend/templates/evidences.html:99` |
| low | fase-3-frontend | `css-leaflet-duplicado` | Override de tema Leaflet (popup/controls/attribution) só vive em occurrences.css mas Leaflet é usado em 3+ páginas (ver §8 — parcialmente FP) | `src/frontend/static/css/pages/occurrences.css:99-163` |
| low | fase-3-frontend | `css-mobile-first-max-width-residual` | Dívida desktop-first menor do que o manifesto afirma — 11 max-width vs 54 min-width | `src/frontend/static/css/main.css:640, 672, 805, 2011, 2152` |
| low | fase-3-frontend | `css-segmented-page-local` | Componente .segmented vive em occurrences.css mas é um primitive reutilizável | `src/frontend/static/css/pages/occurrences.css:9-49` |
| low | fora-de-ambito | `css-stats-investigation-orfaos` | stats.css e investigation_report.css servem páginas marcadas como v2 (fora de âmbito v1) | `src/frontend/static/css/pages/stats.css:1-113` |
| low | fase-3-frontend | `css-text-subtle-contraste` | Confirmar contraste WCAG AA de --text-subtle (usado em micro-labels mono de 9-10px) | `src/frontend/static/css/main.css:119, 205` |
| low | fase-3-frontend | `gap-v20-app-bottom-metricas` | app-bottom só tem 5 itens; mockup V20 e manifesto pedem 9 (testes, api p50, db, uptime) | `src/frontend/templates/base.html:324-337` |
| info | fase-3-frontend | `css-state-cores-vs-neutralizacao` | Tokens --state-* com cor por estado coexistem com a regra V19 de neutralização no hero | `src/frontend/static/css/pages/dashboard.css:163-170` |
| info | fase-3-frontend | `tpl-login-versao-desalinhada` | login.html mostra 'v0.1' mas a casca/mockup usam 'v0.2.0-rc.1' | `src/frontend/templates/login.html:196` |

#### Testes (15)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | fase-2-backend | `csv-tests-a-remover` | 8 testes de CSV (CsvExportTest) a remover com a decisão de matar o export CSV | `src/backend/core/tests_table_mode.py:246-339` |
| high | fase-2-backend | `digitaldevice-tests-deprecacao` | Testes de DigitalDevice (~38 ocorrências em 5 ficheiros) a reavaliar com a depreciação do modelo | `src/backend/core/tests_api.py:284-315, 681-771` |
| high | fase-2-backend | `gps-custodia-sem-teste` | GPS na ChainOfCustody será adição pura mas ficará sem qualquer teste | `src/backend/core/tests_factories.py:227-238` |
| high | fase-2-backend | `gps-no-hash-chain-risco` | Adicionar GPS ao hash da custódia exige novo teste de determinismo do hash-chain | `src/backend/core/tests_coverage.py:764-789` |
| medium | fase-2-backend | `classes-teste-duplicadas` | Nomes de classe de teste duplicados entre ficheiros (drift entre catch-alls) | `src/backend/core/tests_services.py:567, 809, 872, 1034` |
| medium | fase-2-backend | `csrf-cookie-flow-sem-teste-dedicado` | Fronteira CSRF em métodos não-seguros via cookie real não tem teste dedicado | `src/backend/core/tests_api.py:59-61` |
| medium | fase-3-frontend | `frontend-tests-fragquanteis-ids` | Testes de frontend assertam IDs/strings HTML literais que o refactor v2 vai mover | `src/backend/core/tests_frontend.py:88-126, 367-391` |
| medium | ambas | `stats-tests-v2` | Testes de /stats/ e /stats/dashboard/ a marcar como v2 (separar o que fica) | `src/backend/core/tests_coverage.py:540-609` |
| medium | fase-2-backend | `trigger-layer-untested` | 3ª camada de imutabilidade (triggers PostgreSQL) sem qualquer teste | `src/backend/core/tests.py:121-143, 242-267` |
| low | fase-2-backend | `asserts-fragquanteis-idor-405` | Asserts permissivos com assertIn de múltiplos status mascaram regressões de contrato | `src/backend/core/tests_api.py:516, 758-767` |
| low | fase-2-backend | `catchall-coverage-cruft` | tests_coverage.py e tests_new_features.py são catch-alls datados — bom conteúdo, má organização | `src/backend/core/tests_coverage.py:1-17` |
| low | fase-2-backend | `factory-auditlog-em-falta` | Não há factory para AuditLog — criado sempre à mão | `src/backend/core/tests_factories.py:240-250` |
| low | fase-2-backend | `imei-throttle-cache-isolamento` | Risco de flakiness por cache partilhada nos testes de throttle/quota IMEI | `src/backend/core/tests_coverage.py:1040-1099` |
| low | fora-de-ambito | `investigation-report-cobertura` | Confirmar se investigation_report (marcado v2) tem testes que dependem dele | `src/backend/core/tests_pdf.py:234-263` |
| info | fora-de-ambito | `fsm-cobertura-completa-confirmada` | FSM de custódia: cobertura completa confirmada (sem lacuna) | `src/backend/core/tests_api.py:777-1069` |

#### Docs, CI, Ops (18)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| high | fase-2-backend | `adr-0013-gps-custody-em-falta` | Falta ADR-0013 para GPS na ChainOfCustody (decisão de produto já tomada) | `docs/architecture/adr/` |
| high | fase-2-backend | `ci-sem-lint-format-semgrep` | CI não corre ruff/black/semgrep — qualidade depende só do pre-commit local (bypassável) | `.github/workflows/ci.yml:62-69` |
| high | ambas | `dr-volume-nome-errado` | DR doc refere volume 'forensiq_data' mas fly.toml usa 'forensiq_media' — runbook partido | `docs/operations/disaster-recovery.md:10` |
| high | ambas | `env-example-faltam-segredos` | .env.example não documenta QR_VERIFY_SECRET nem AUDIT_LOG_RETENTION_DAYS | `.env.example:33` |
| medium | fase-2-backend | `auditlog-sem-trigger-pg-n7-aberto` | AuditLog sem trigger PG de imutabilidade (N7) — defesa só ORM, fica aberto | `docs/AUDIT_2026-05-18-delta.md:77` |
| medium | fase-2-backend | `invariante-occurrence-imutavel-nao-documentado` | Imutabilidade de Occurrence (migration 0013) ausente dos invariantes canónicos | `CLAUDE.md` |
| medium | fase-2-backend | `precommit-versoes-desactualizadas` | Pre-commit pina ruff 0.5.7 / black 24.8.0; dev pina ruff >=0.15.13 / black >=26.3.1 | `.pre-commit-config.yaml:22-35` |
| medium | ambas | `readme-csv-export-anunciado` | README anuncia CSV export como feature, mas decisão é removê-lo por completo | `README.md:26` |
| medium | ambas | `readme-digitaldevice-stats-drift` | README documenta DigitalDevice e /stats/ sem marcar deprecação/v2 | `README.md:64` |
| medium | ambas | `readme-pdf-relatorio-forense-drift` | README ainda descreve o PDF como 'relatório forense ISO 27037', contra ADR-0012 | `README.md:75` |
| medium | ambas | `rgpd-art32-alinea-d-stale` | Checklist RGPD Art.32 d) afirma 'sem SAST/DAST/SCA em CI' — já não é verdade | `docs/compliance/rgpd-art32-checklist.md:129-131` |
| low | fora-de-ambito | `adr-reverse-geocode-nominatim-sem-registo` | Proxy reverse-geocode via Nominatim/OSM não tem ADR nem nota CSP no inventário de origens | `docs/architecture/adr/` |
| low | fase-2-backend | `ci-coverage-nao-enforca-threshold` | CI gera relatório de cobertura mas não falha abaixo de threshold | `.github/workflows/ci.yml:68` |
| low | fase-2-backend | `cobertura-tres-numeros-divergentes` | Três alvos de cobertura divergentes nos docs: 85% / 75% / ~68% | `src/backend/pyproject.toml:124-130` |
| low | fase-2-backend | `fly-toml-release-command-sem-rollback` | release_command corre migrate --noinput sem estratégia de rollback documentada | `fly.toml:12-13` |
| low | fase-2-backend | `pyproject-ignores-wave2e-obsoletos` | per-file-ignores justificados por 'Wave 2e / spawn_task' — dívida técnica que a Fase 2 pode limpar | `src/backend/pyproject.toml:47-63` |
| low | ambas | `trivy-action-pin-master` | trivy-action fixado em @master (não-reprodutível e supply-chain) | `.github/workflows/security.yml:66` |
| info | fora-de-ambito | `ci-matriz-python-unica` | Matriz CI tem um único Python (3.12) — matriz com 1 entrada é overhead vazio | `.github/workflows/ci.yml:23-24` |

#### Gap Analysis — Frontend v2 (20)

| Sev | Fase | ID | Título | Local |
|-----|------|----|--------|-------|
| blocker | fase-2-backend | `gap-gps-chain-model` | ChainOfCustody não tem campos GPS — mini-mapa Cadeia sem fonte | `src/backend/core/models.py:919-1012` |
| blocker | fase-2-backend | `gap-gps-chain-serializer` | ChainOfCustodySerializer não expõe GPS da transição | `src/backend/core/serializers.py:404-415` |
| blocker | fase-2-backend | `gap-occurrence-priority` | Occurrence não tem campo de prioridade (P1-P4) | `src/backend/core/models.py:217-272` |
| high | fase-2-backend | `gap-activity-feed-endpoint` | Sem endpoint API para o feed de actividade (AuditLog) | `src/backend/core/urls.py:40-64` |
| high | ambas | `gap-geohero-latlng-bug` | Hero lê occ.latitude/occ.longitude mas o serializer dá gps_lat/gps_lon | `src/frontend/static/js/pages/dashboard_geo_hero.js:216-223` |
| high | fase-2-backend | `gap-gps-chain-rounding` | Falta arredondamento de GPS por papel na criação de custódia | `src/backend/core/views.py:689-704` |
| high | fase-2-backend | `gap-occurrence-priority-serializer` | OccurrenceSerializer não expõe prioridade ao mapa/tabela | `src/backend/core/serializers.py:135-143` |
| high | fase-2-backend | `gap-stats-24h-deltas` | DashboardStatsView não dá deltas 24h nem 'activos' por estado | `src/backend/core/views.py:1139-1244` |
| high | fase-2-backend | `gap-timeline-gps-fields` | Timeline de custódia não traz GPS por transição | `src/backend/core/views.py:768-777` |
| medium | fase-2-backend | `gap-gps-lon-vs-lng-naming` | Inconsistência gps_lon (modelo actual) vs gps_lng (spec/mockup) | `src/backend/core/models.py:251-258` |
| medium | fase-2-backend | `gap-header-shift-zone-device` | Header operacional: turno/zona/dispositivo sem fonte no backend | `src/backend/core/models.py:168-209` |
| medium | fase-2-backend | `gap-health-metrics` | /api/health/ não expõe métricas do footer técnico | `src/backend/core/views.py:1344-1357` |
| medium | fase-2-backend | `gap-occurrence-detail-composite` | Painel direito precisa de detalhe da ocorrência com itens + estado | `src/backend/core/views.py:203-259` |
| medium | fase-2-backend | `gap-stats-sparkline-timeseries` | Sem série temporal para as sparklines dos 7 tiles | `src/backend/core/views.py:1225-1229` |
| medium | ambas | `gap-table-priority-feed-source` | Tabela de ocorrências e feed do dashboard sem wiring de dados real | `src/frontend/static/js/pages/dashboard_geo_hero.js:204-224` |
| low | fase-2-backend | `gap-footer-build-binding` | Footer: versão/commit/região reais existem mas falta versão semver e nº testes | `src/backend/core/context_processors.py:14-41` |
| low | fase-3-frontend | `gap-occurrence-region-insets` | Insets Madeira/Açores: sem tag de região (derivável de lat/lng) | `src/backend/core/serializers.py:126-143` |
| low | ambas | `gap-occurrences-pagesize` | Hero pede page_size=100 — confirmar que a paginação DRF aceita | `src/frontend/static/js/pages/dashboard_geo_hero.js:209` |
| info | fase-3-frontend | `gap-cmd-palette-search` | Paleta de comandos (Ctrl+K) reutiliza search existente — sem gap de backend | `src/backend/core/views.py:204-221` |
| info | fase-2-backend | `gap-csv-removal-impact` | Mockup não usa CSV — confirma decisão de remover export CSV | `src/backend/core/views.py:279-324` |
</content>
</invoke>
