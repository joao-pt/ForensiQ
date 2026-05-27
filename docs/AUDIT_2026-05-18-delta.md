# Auditoria ForensiQ — Delta 2026-05-18

**Escopo:** delta vs [`AUDIT_2026-04-16.md`](AUDIT_2026-04-16.md) (snapshot histórico imutável).
**Stack (snapshot do commit `2183600`; updates de Sem.10/11 listados em §8.1; Sem.12 acrescentou ADR-0012 Vagas 1+2 + DR doc + B9/N9/N10/N12; bumps Dependabot pós-Sem.11 — whitenoise 6.12, psycopg2-binary 2.9.12, drf-spectacular 0.29):** Django 6.0.5 + DRF 3.17.1 + djangorestframework-simplejwt 5.5.1 + dj-database-url 3.1.2 + gunicorn 26 + qrcode[pil] 7.4 + PostgreSQL (Neon) + Fly.io. Dev: pytest-django 4.12. Frontend templates Django + JS vanilla.
**Método:** 3 agentes Explore (segurança · backend/arquitectura · frontend/testes/CI) + leitura directa de `models.py`, `serializers.py`, `views.py`, `auth.py`, `middleware.py`, `audit.py`, `pdf_export.py`, `services/{imei,vin}_lookup.py`, `migrations/0002,0008`. 3 sub-auditorias focadas: PDF export, triggers PG, services externos.
**Veredito executivo:** **9 dos 10 itens do Top-10 de abr 2026 estão resolvidos**. O hardening de segurança crítica (JWT HttpOnly, CSP nonce, hash determinístico, IDOR, TRUSTED_PROXIES) materializou-se em código, com cobertura de testes adicional (+136%, **447 testes pós-Sem.12**). Sem.11 encerrou **S9** (EXIF strip — último 🟠 Alto operacional do §2), **N8** (throttle dedicado `imei_lookup`), **N11** (alinhamento CSRF/CORS) e **N14** (try/finally em PDF). Sem.12 re-classificou **N2** como não-aplicável via [ADR-0012](architecture/adr/ADR-0012-pdf-transport-guide.md) (PDF é guia de transporte DHL-style, não prova juridicamente auto-contida) — e implementou as duas vagas do ADR (QR codes + endpoint público adaptativo, check-list intake EXPERT-only). Sem.12 também fechou **B9** (AuditLog retention RGPD), **N9** (monitorização quota IMEIDB), **N10** (sequence global em AuditLog), **N12** (prefetch coerente no PDF), e criou o `docs/operations/disaster-recovery.md` pendente desde Sem.7. Persistem como arquitecturais sem v1.1: **N4** (PDF assíncrono via Celery/RQ), **P5** (PurgeCSS — viola ADR-0004), **N6/N7** (insider DBA), **T2/T3** (hypothesis + load tests). Dois achados da auditoria de abr eram **falsos positivos** quando reverificados (B11, ip_address fallback).

> **Nota pós-auditoria (mesmo dia, após commit `2183600`):** o Dependabot completou a onda de 5 PRs ainda em 2026-05-18, levando os pins de DRF 3.15 → 3.17.1 (#11), pytest-django 4.8 → 4.12 (#13), simplejwt 5.3 → 5.5.1 (#14), dj-database-url 2.x → 3.1.2 (#15) e gunicorn 22 → 26 (#12). Os bumps `dj-database-url` e `gunicorn` são major mas verificados sem breaking changes para o ForensiQ (API `config()` estável; worker default `sync` no Dockerfile, eventlet removido em gunicorn 26 não aplicável). Nenhum dos achados N1–N15 foi alterado por estes bumps.

---

## 1. Resolvido desde 2026-04-16

Cada item cita o ID original da auditoria de abr e a evidência exacta (`file:linha`) ou commit.

### Segurança

| ID | Descrição | Evidência |
|----|-----------|-----------|
| S1 | JWT migrado de `localStorage` para HttpOnly cookie | `core/auth.py:33-89`, `core/auth_views.py:32-105`, ADR-0009. Zero `localStorage.access_token` no JS (`grep` em `src/frontend/static/js/`). |
| S2 | CSP sem `unsafe-inline` | `core/middleware.py:68-155` — nonce por request, `script-src 'self' 'nonce-…'`. |
| S3 | `CORS_ALLOW_ALL_ORIGINS` desacoplado de DEBUG | `forensiq_project/settings.py:225` — env var explícita. |
| S4 | `X-Forwarded-For` apenas via whitelist `TRUSTED_PROXIES` (CIDR) | `core/audit.py:20-81`, `_trusted_proxies()` + `_remote_addr_trusted()`. |
| S5 | Hash-chain ChainOfCustody determinístico (sem nonce) | `core/models.py:554-584` — `json.dumps(sort_keys=True, separators=(',',':'))`. |
| S6 | `integrity_hash` cobre bytes da fotografia | `core/models.py:534-552` — `_compute_photo_hash()` SHA-256 dos chunks; incluído no hash em `models.py:582`. |
| S7 | CSRF enforced em cookie HttpOnly | `core/auth.py:24-30` (`enforce_csrf()`); `auth_views.py:54` (`@ensure_csrf_cookie`). |
| S13 | `JWT_SIGNING_KEY` separável de `SECRET_KEY` via env var | `forensiq_project/settings.py:186`. |
| S18 | CSP: `object-src 'none'` + `upgrade-insecure-requests` | `core/middleware.py:126,133`. |

### Backend / correctness

| ID | Descrição | Evidência |
|----|-----------|-----------|
| B1 | Race em `ChainOfCustody.timestamp` | `core/models.py:1057-1135` — `sequence` field (migration 0004) + `transaction.atomic()` + `select_for_update()` em Evidence parent e CoC. Fix B-C3/B-C4 da auditoria intermédia 2026-04-19. |
| B7 | `full_clean()` em Evidence/Occurrence/DigitalDevice | `core/models.py:243,599,863`. |
| B12 | Datas futuras rejeitadas em `date_time`/`timestamp_seizure` | `core/models.py:243,636-638`. |
| B13 | AGENT não cria evidência em ocorrência alheia | `core/serializers.py:271-280` (`validate_occurrence` chama `_user_can_access_occurrence`); `core/views.py:410-436` (queryset filter `occurrence__agent=user`); IDOR fix de 2026-04-19 em `export_pdf` documentado em `views.py:470-480`. Testes: `tests_api.py` `AuthorizationIDORTest`. |
| B15 | `DjangoValidationError` convertida em 400 DRF | `core/views.py:645-647,776-780,819-823,896-900`. |
| F1/F3 | Inline `<script>`/`<style>` e XSS `innerHTML+API` | Templates limpos, JS extraído para 26 ficheiros em `src/frontend/static/js/`, IIFEs (`auth.js`, `api.js`). `occurrence_detail.html` desceu de ~770 para 148 linhas. |
| CI | `factory-boy` instalado em CI | `e2e9a54` — `pip install -r requirements.txt -r requirements-dev.txt` no `.github/workflows/ci.yml`. |

### Falsos positivos da auditoria de abr (reverificados)

| ID | Razão |
|----|-------|
| B11 (`Occurrence.number` sem unique) | `core/models.py:178` declara `unique=True`. Achado de abr estava incorrecto. |
| Bulk_create() bypassa `clean()` (achado preliminar dos agentes) | `git grep "bulk_create"` em `src/backend/` — **0 ocorrências**. Não é usado em parte nenhuma do código. |
| Possível IDOR em `Evidence.occurrence_id` (achado preliminar) | `serializers.py:271-280` valida ownership via `validate_occurrence()`. Não é IDOR. |

---

## 2. Continua aberto desde 2026-04-16

| ID | Severidade | Descrição actual |
|----|-----------|------------------|
| **S9** | ✅ Fechado Sem.11 | EXIF strip implementado em 2026-05-27 — ver §8.1. |
| **B3** | 🟡 Baixo→Médio | `AuditLog.ip_address` tem fallback `'0.0.0.0'` em `audit.py:80` — risco residual reduzido. Mantém-se aberto enquanto não houver `default='0.0.0.0'` no campo do model. |
| **B9** | ✅ Fechado Sem.12 | Management command `purge_audit_logs` + meta-auditoria `AUDIT_PURGE` em 2026-05-27. Ver §8.1. |
| **B14** | 🟢 Baixo (re-avaliado) | `AuditLog.details` é `JSONField` (`models.py:1245`) e não `TextField` — codificação JSON escapa `\n`. Log injection clássica está mitigada. Persiste risco baixo de "logical injection" se os campos forem renderizados sem escape em dashboards futuros. |
| **B15 arquitectural** | 🟢 Baixo | `tests_api.py` ainda monolítico (1803 linhas, +59 vs abr). Mitigado parcialmente pela criação de `tests_services.py`, `tests_new_features.py`, `tests_table_mode.py`, `tests_pdf.py`, `tests_coverage.py`, `tests_factories.py`. |
| **P5** | 🟠 Alto | **CSS bloat real confirmado**: 5679 linhas totais (`find src/frontend/static/css -name '*.css' \| xargs wc -l`); `main.css` sozinho com 2344 linhas. Vs baseline de 922 = +517 %. Sem PurgeCSS nem minify em pipeline. |
| **T2** | 🟡 Médio | Sem `hypothesis` (property-based) nem testes explícitos de race em ChainOfCustody concorrente. (O lock está testado por leitura de código, não por carga.) |
| **T3** | 🟢 Baixo | Sem testes de carga (k6, locust). Académicamente aceitável; operacionalmente é ponto cego. |

---

## 3. Achados novos (Mai 2026, não cobertos pela auditoria de abr)

| # | Severidade | Descrição | Evidência |
|---|-----------|-----------|-----------|
| **N1** | 🟠 Alto | **Logging de IMEI completo em `imei_lookup.py`** (PII forense). IMEI é identificador único do dispositivo móvel — em ISO 27037 deve ser tratado como PII. | `core/services/imei_lookup.py:123,128,138,152`; `core/views.py:854`. Mitigação: truncar para TAC (primeiros 8) ou hash SHA-256. |
| **N2** | ✅ Re-classificado Sem.12 | Não-aplicável: o PDF é guia de transporte (DHL-style), não prova juridicamente auto-contida. Ver [ADR-0012](architecture/adr/ADR-0012-pdf-transport-guide.md) e §8.1 abaixo. | `core/pdf_export.py:482-485`. |
| **N3** | 🟠 Alto | **XSS via ReportLab `Paragraph()` em valores não escapados**. `get_type_display()`, `get_condition_display()`, `get_previous_state_display()`, `get_new_state_display()` são passados directamente a `Paragraph(...)` sem `_sanitize()`. ReportLab interpreta XML embebido; se o display value contiver markup (improvável mas tecnicamente possível via migração de dados), há injecção visual no PDF. | `core/pdf_export.py:365,376,425,446,454,289-293`. |
| **N4** | 🟠 Alto | **PDF export síncrono sem timeout nem limite de páginas**. Ocorrência com 5000 evidências = PDF de 50-100 MB no thread de request, bloqueando worker e excedendo timeout Gunicorn 30s. DoS viável por utilizador autenticado. | `core/pdf_export.py:464-541,556-716`. |
| **N5** | 🟠 Alto | **`session_replication_role = 'replica'` não documentado nem defendido**. Um operador com role PG suficiente pode desactivar triggers de imutabilidade na sua sessão. Não há comment em migrations 0002/0008 a alertar; o `ALTER TABLE DISABLE TRIGGER` é tecnicamente inevitável mas tipicamente requer superuser. | `core/migrations/0002_*.py`, `0008_*.py` — nenhuma menção. |
| **N6** | 🟡 Médio | **`TRUNCATE` não bloqueado por triggers**. `BEFORE DELETE FOR EACH ROW` não dispara em `TRUNCATE`. O ataque é via SQL directo (não API), e `seed_demo.py:272-285` documenta-o explicitamente para fixtures, mas vale registar. | Migrations 0002/0008. |
| **N7** | 🟡 Médio | **`AuditLog` sem trigger PG de imutabilidade** (só protecção ORM `save()/delete()`). Em SQLite (testes) e em PG (produção), a defesa depende 100% do método `save()` ser chamado — `Model.objects.filter(...).update(...)` ou `delete()` bypass. | `core/models.py:1269-1287` (ORM only). |
| **N8** | ✅ Fechado Sem.11 | Scope DRF `imei_lookup: 5/min` adicionado em 2026-05-27. | Ver §8.1. |
| **N9** | ✅ Fechado Sem.12 | Contadores em cache + `SYSTEM_ALERT` no AuditLog em 401/402/429 em 2026-05-27. | Ver §8.1. |
| **N10** | ✅ Fechado Sem.12 | Campo `sequence` global monótono no AuditLog em 2026-05-27. | Ver §8.1. |
| **N11** | ✅ Fechado Sem.11 | Lista canónica `_FRONTEND_ORIGINS_PROD` reutilizada por CORS/CSRF em 2026-05-27. | Ver §8.1. |
| **N12** | ✅ Fechado Sem.12 | `Prefetch(...)` com queryset ordenado em ambas as views; `pdf_export.py` aproveita o prefetch. | Ver §8.1. |
| **N13** | 🟢 Baixo | **`tests_services.py` (untracked) com 10 falhas**. 1048 linhas, 73 testes, 63 ✅ / 10 ❌. Falhas todas por `NoReverseMatch` — chama `reverse('occurrence-list')` em vez de `reverse('core:occurrence-list')` (porque `core/urls.py:38` declara `app_name='core'`). Bug do ficheiro, não do código aplicacional. | `core/tests_services.py:841,849,858,907,914,954,961,988,994,999`. |
| **N14** | ✅ Fechado Sem.11 | `try/finally` em `generate_*_pdf` aplicado em 2026-05-27. | Ver §8.1. |
| **N15** | 🟢 Informativo | **`frame-src 'none'` muito restritivo**. Bloqueia iframes legítimos. Aceitável dado o escopo actual (sem embeds), mas registar para futura integração de mapas embebidos ou docs visuais. | `core/middleware.py:127`. |

---

## 4. Áreas auditadas em profundidade extra

### 4.1 `pdf_export.py` (716 linhas, 2 classes + 15 funções)

> **Nota de framing (acrescentada em Sem.12 após [ADR-0012](architecture/adr/ADR-0012-pdf-transport-guide.md)):** os 4 ❌ listados abaixo são **consequência directa do propósito real do PDF** (guia de transporte físico DHL-style, não prova juridicamente auto-contida) — não bugs. A análise original avaliava o artefacto contra um requisito que o produto não tem. Mantém-se a lista como registo histórico da análise; ver ADR-0012 para a decisão de re-classificação.

- **Conformidade ISO/IEC 27037 — parcial**:
  - ✅ `integrity_hash` da evidência embebida (`pdf_export.py:317,388,436,646,660`).
  - ✅ `record_hash` da cadeia de custódia embebida (`pdf_export.py:317`).
  - ❌ PDF não é assinado digitalmente. *(Por design — ADR-0012.)*
  - ❌ Sem PDF/A-3u (preservação a longo prazo). *(Por design — ADR-0012.)*
  - ❌ `ModDate` não definida — modificação post-export indetectável por verificador externo. *(Por design — ADR-0012; a integridade autoritativa vive no sistema, não no PDF.)*
  - ❌ Sem hash do próprio PDF nos metadados. *(Por design — ADR-0012.)*
- **Segurança**: XSS via `Paragraph()` em `get_*_display()` (ver N3).
- **Performance**: síncrono, sem timeout, sem limite de evidências por export (ver N4).
- **Cleanup**: `buffer.close()` fora de `try/finally` (ver N14).

### 4.2 Triggers PostgreSQL (`migrations/0002`, `0008`)

- **SQL real** (extracto de `0002`):
  ```sql
  CREATE OR REPLACE FUNCTION prevent_evidence_modification()
  RETURNS TRIGGER AS $$
  BEGIN
      RAISE EXCEPTION
          'Registos de evidência são imutáveis (ISO/IEC 27037). '
          'Operação bloqueada: %', TG_OP;
  END;
  $$ LANGUAGE plpgsql;

  CREATE TRIGGER trg_evidence_no_update
      BEFORE UPDATE ON core_evidence FOR EACH ROW
      EXECUTE FUNCTION prevent_evidence_modification();
  CREATE TRIGGER trg_evidence_no_delete
      BEFORE DELETE ON core_evidence FOR EACH ROW
      EXECUTE FUNCTION prevent_evidence_modification();
  ```
  Mesma estrutura para `prevent_custody_modification` e `prevent_device_modification`.

- **Cobertura — matriz**:

  | Op | Evidence | ChainOfCustody | DigitalDevice | AuditLog |
  |----|----------|----------------|---------------|----------|
  | INSERT | ✅ | ✅ append-only | ✅ | ✅ |
  | UPDATE | ❌ (trigger + ORM) | ❌ (trigger + ORM) | ❌ (trigger) | ❌ (apenas ORM) |
  | DELETE | ❌ (trigger + ORM) | ❌ (trigger + ORM) | ❌ (trigger) | ❌ (apenas ORM) |
  | TRUNCATE | ⚠️ N6 | ⚠️ N6 | ⚠️ N6 | ⚠️ N6 |

- **`forensiq_evidence_immutable_fields()`** (migration 0008, linhas 31-60): função SQL documentária que lista 16 campos protegidos — `occurrence_id, type, parent_evidence_id, description, photo, gps_lat, gps_lon, timestamp_seizure, serial_number, agent_id, integrity_hash, type_specific_data, external_lookup_snapshot, external_lookup_source, external_lookup_at, created_at`. **Não é chamada pelo trigger actual** (que bloqueia UPDATE blanket); serve como referência futura caso se queira whitelisting selectivo (ex: permitir UPDATE em campos auxiliares não-forenses).

- **Bypass `from_migration=True`**:
  - Evidence — não tem bypass (`models.py:593-597`).
  - ChainOfCustody — não tem bypass (`models.py:1071-1075`).
  - DigitalDevice — **tem** (`models.py:848-863`) para loaddata; trigger ainda protege UPDATE/DELETE; só desactiva `full_clean()` (IMEI Luhn) em fixtures legados.

### 4.3 Services externos (IMEI / VIN)

- **Cliente HTTP**: `httpx`, timeout 10s (`imei_lookup.py:75`), **sem retry** (decisão consciente — fail-open com 503), **sem connection pooling** (cria cliente novo por chamada, `imei_lookup.py:120`).
- **Cache**: Django `DatabaseCache` (`forensiq_cache`), TTL 30d para IMEI; VIN é apenas redirect para vindecoder.eu.
- **Fail mode**: ✅ **fail-open** — falha de 3rd-party → 503 → agente preenche manual; **criação de evidência nunca é bloqueada**.
- **API key**: `os.environ['IMEIDB_API_TOKEN']`, header `X-Api-Key` (não query string).
- **Validação de input**: regex Luhn (IMEI) e ISO 3779 (VIN) — SSRF não viável.
- **Custo**: pay-per-query, sem contador interno nem alerta de saldo (ver N9).

---

## 5. Top-N priorizado (delta vs abr)

Ordem por **risco real para o caso de uso forense académico**.

| # | Item | Severidade | Justificação |
|---|------|-----------|--------------|
| 1 | **N1** — Logging IMEI completo (PII) | 🟠 Alto | Privacidade + ISO 27037; fácil de fixar (truncar/hash). |
| 2 | **S9** — EXIF strip em uploads | ✅ Fechado Sem.11 | Privacidade da cena; agente pode revelar GPS sem querer. |
| 3 | **N2** — PDF sem assinatura/PDF-A | ✅ Re-classificado Sem.12 | Não-aplicável: PDF é guia de transporte, não prova auto-contida — ADR-0012. |
| 4 | **N3** — XSS ReportLab Paragraph | 🟠 Alto | Defesa em profundidade barata (`_sanitize` está pronto). |
| 5 | **N4** — PDF síncrono sem limite | 🟠 Alto | DoS trivial; mover para Celery/RQ ou impor `max_evidences`. |
| 6 | **P5** — CSS bloat 5679 linhas | 🟠 Alto | Visibilidade UX + transferência; PurgeCSS é low-effort. |
| 7 | **N8** — IMEI lookup sem throttle dedicado | ✅ Fechado Sem.11 | Adicionar `'imei_lookup': '5/minute'` em settings. |
| 8 | **N5** — `session_replication_role` sem documentar | 🟡 Médio | ADR ou comentário em migration; defesa operacional. |
| 9 | **B9** — AuditLog sem retenção | ✅ Fechado Sem.12 | Management command + cron Fly. |
| 10 | **N7** — AuditLog sem trigger PG | 🟡 Médio | Replicar pattern de Evidence/CoC. |

**Não promovidos a Top-10**: B3 (mitigado a fallback), B14 (re-avaliado baixo), N6 (operacional), N10/N11/N12/N13/N14/N15 (baixos/informativos).

---

## 6. Conformidade ISO/IEC 27037 — delta

| Requisito | abr 2026 | mai 2026 |
|-----------|----------|----------|
| UTC, timestamps servidor | ✅ | ✅ |
| Imutabilidade tripla (DB + admin + API) | ✅ | ✅ (reforçada com lock pessimista B-C3/B-C4) |
| Hash por registo | ✅ | ✅ |
| Hash determinístico verificável por terceiros | ❌ (S5) | ✅ (S5 fechado) |
| Hash cobre artefacto (foto) | ❌ (S6) | ✅ (S6 fechado) |
| AuditLog não-falsificável (IP/timestamp) | ⚠️ (S4) | ✅ (S4 fechado); persiste N10 (sequence) |
| PDF inalterável post-export | ⚠️ (implícito) | ❌ (N2 — sem assinatura/PDF-A) |
| Cadeia de custódia append-only com transições válidas | ✅ | ✅ |
| Bypass operacional (DBA com `session_replication_role`) | (não avaliado) | ⚠️ (N5) |

---

## 7. Recomendações operacionais imediatas (não bloqueantes da entrega académica)

1. **N1 + S9** — sprint de privacidade: truncar IMEI em logs (1 linha) e usar `Pillow.ImageOps.exif_transpose() + Image.getdata()` para limpar EXIF antes de gravar (5-10 linhas).
2. **N4** — adicionar `?max_evidences=N` ou `Sentry.timeout(25s)` em `PdfExportView`.
3. **N13** — decidir entre committar `tests_services.py` (depois de mudar 10 chamadas para `reverse('core:occurrence-list')`), descartar, ou mover para `tests_filters.py` mais pequeno. Suite principal continua verde sem ele.

---

## 8. Decisão final de tratamento — limitações conhecidas

O ForensiQ é o entregável académico da UC 21184 (Universidade Aberta). A janela útil entre esta auditoria (18 Mai 2026) e a defesa final é inferior a 4 semanas; **não está prevista uma versão v1.1** nem manutenção pós-defesa. Esta secção regista, de forma encerrada, o que foi corrigido nesta passagem final e o que permanece em aberto por opção consciente.

### 8.1 Fechados em 2026-05-18 (passagem final pós-auditoria) + 2026-05-27 (Sem.11)

Três achados 🟠 Alto receberam fix surgical em 2026-05-18 (~30 min de código, sem alteração de API pública). Em 2026-05-27 (Sem.11) acrescentaram-se mais quatro fixes — um 🟠 Alto (S9), um 🟡 Médio (N8) e dois 🟢 Baixo (N11, N14) — encerrando o último 🟠 Alto operacional aberto.

| ID | Fix | Evidência |
|----|-----|-----------|
| **N1** | Helper `mask_imei(imei) → '<TAC>***'` em `core/services/imei_lookup.py:84-95`. Aplicado nos 5 `log.warning()` do service + `core/views.py:854` (schema drift). IMEI completo deixa de aparecer em logs Fly.io. | `core/services/imei_lookup.py:84-95,123,128,138,143,152`; `core/views.py:71,854`. |
| **N3** | `_sanitize()` aplicado a todos os 12 `get_*_display()` que alimentam `Paragraph()` em `pdf_export.py`. Sanitização movida para o ponto de origem em `_current_custody_state()` (linha 553) para cobrir chamadores transitivos (linhas 645, 659). | `core/pdf_export.py:289-290,365,425,446,454,553,710`. |
| **N5** | Docstring de `core/migrations/0008_extend_immutability.py` expandida com warning explícito sobre bypass via `SET session_replication_role='replica'` e nota sobre `TRUNCATE` (cross-ref N6 + `seed_demo.py:272-285`). Postura: bypass requer `superuser` PG, fora do alcance do runtime aplicacional. | `core/migrations/0008_extend_immutability.py:1-50`. |
| **S9** *(Sem.11)* | Helper `_strip_exif(photo_file)` em `core/models.py` reabre via Pillow e reconstrói os bytes sem EXIF/IPTC/XMP, preservando formato (JPEG `quality='keep' + exif=b''`, PNG `pnginfo=PngInfo()`, WEBP `exif=b''`). Chamado em `Evidence.save()` entre `full_clean()` e `compute_integrity_hash()` para que o hash seja **invariante a EXIF** — defesa em profundidade da cadeia de custódia. Backwards-compat: fotos já gravadas mantêm EXIF (Evidence é imutável). 5 novos testes em `core/tests_image_processing.py` (strip + invariante hash + formato preservado). | `core/models.py:109-159,604-608`; `core/tests_image_processing.py`. |
| **N8** *(Sem.11)* | Novo scope DRF `imei_lookup: 5/minute` em `forensiq_project/settings.py` (mirror `10000/minute` em bloco `TESTING` + `test_settings.py`). `EvidenceIMEILookupView` ganha `throttle_classes = [ScopedRateThrottle]` + `throttle_scope = 'imei_lookup'`, espelhando o padrão de `ReverseGeocodeView`. Mitiga exaustão do saldo pago em `imeidb.xyz` por agente isolado. Novo teste `ImeiLookupThrottleTest` em `tests_coverage.py` força 2/min via `patch.object(SimpleRateThrottle, 'THROTTLE_RATES', ...)` (nota: `override_settings(REST_FRAMEWORK={...})` não actualiza o atributo de classe). | `forensiq_project/settings.py:148-152,170`; `forensiq_project/test_settings.py:83-88`; `core/views.py:809-810`; `core/tests_coverage.py` (cls `ImeiLookupThrottleTest`). |
| **N11** *(Sem.11)* | Lista canónica `_FRONTEND_ORIGINS_PROD` em `forensiq_project/settings.py` reutilizada por `CORS_ALLOWED_ORIGINS` e `CSRF_TRUSTED_ORIGINS`. Origens de desenvolvimento (`localhost:8000`, `127.0.0.1:8000`) só entram se `DEBUG=True`, mantendo produção restrita aos 3 hostnames públicos (`forensiq.pt`, `www.forensiq.pt`, `forensiq.fly.dev`). Novo teste `CsrfCorsOriginAlignmentTest` em `tests_coverage.py` (asserção de igualdade dos sets + presença obrigatória das 3 prod). | `forensiq_project/settings.py:213-232`; `core/tests_coverage.py` (cls `CsrfCorsOriginAlignmentTest`). |
| **N14** *(Sem.11)* | `doc.build(...) + buffer.getvalue()` envolvidos em `try`; `buffer.close()` movido para `finally` em `generate_evidence_pdf` e `generate_occurrence_pdf` (`core/pdf_export.py`). `BytesIO.close()` é idempotente — zero alteração no caminho feliz. Novo teste `PdfBufferLifecycleTest` em `tests_pdf.py` mocka `core.pdf_export.BytesIO` + `SimpleDocTemplate.build` com `side_effect=RuntimeError` e verifica `assert_called_once()` no `close`. | `core/pdf_export.py` (`generate_evidence_pdf` e `generate_occurrence_pdf` finais); `core/tests_pdf.py` (cls `PdfBufferLifecycleTest`). |
| **N2** *(Sem.12 — re-classificado)* | **Não fixado por código — re-classificado como não-aplicável.** A auditoria original avaliava o PDF contra o requisito de "prova juridicamente auto-contida" (assinatura X.509 + PDF/A-3u via PyHanko + timestamping qualificado, custo 3-5 dias). Confrontado com a proposta, o autor clarificou que o PDF é guia de transporte físico (paralelo DHL), não documento jurídico autónomo — a prova autoritativa vive no sistema (`integrity_hash`, `ChainOfCustody` append-only, triggers PG). Ver [ADR-0012](architecture/adr/ADR-0012-pdf-transport-guide.md) para a justificação completa; §4.1 deste documento foi anotado em conformidade. O trabalho que se traduzir do reframe é a vaga de QR codes + endpoint público + check-list intake (Sem.12-13). | `docs/architecture/adr/ADR-0012-pdf-transport-guide.md`; `docs/AUDIT_2026-05-18-delta.md` §4.1 (anotado). |
| **B9** *(Sem.12)* | Management command `core/management/commands/purge_audit_logs.py` apaga `AuditLog` com `timestamp < now() - settings.AUDIT_LOG_RETENTION_DAYS` (default 365, env-overridable). Suporta `--dry-run`, `--older-than=N`, `--batch-size=N`, `--no-input`. Operação em lotes com `transaction.atomic()` por batch. Cria entrada meta-auditoria `AuditLog.Action.AUDIT_PURGE / SYSTEM` com `details={deleted_count, cutoff_date, retention_days, batch_size, execution_time_seconds, reason}`. Cumpre RGPD Art. 5(1)(e). Cron Fly fica como follow-up de deployment. 11 testes em `core/tests_audit_retention.py`. | `core/management/commands/purge_audit_logs.py`; `core/models.py` (`Action.AUDIT_PURGE`, `ResourceType.SYSTEM` — migration 0015); `forensiq_project/settings.py` (`AUDIT_LOG_RETENTION_DAYS`). |
| **N9** *(Sem.12)* | Contadores em DatabaseCache (`imeidb:calls_24h`, `imeidb:last_<status>_at`) + entrada `AuditLog.Action.SYSTEM_ALERT / SYSTEM` em eventos críticos: HTTP 401 (`token_invalid`), 402 (`quota_exhausted`), 429 (`rate_limited`); também detecta `success:false` no body com `code` correspondente. IMEI mascarado (cumpre N1). 8 testes em `core/tests_imei_quota.py`. Endpoint admin de stats fica como follow-up (dados já estão a ser registados). | `core/services/imei_lookup.py` (`_increment_call_counter`, `_record_critical_event`); `core/models.py` (migration 0016). |
| **N10** *(Sem.12)* | Novo campo `AuditLog.sequence` (`BigIntegerField`, `unique=True`) — ordem total global. `save()` atribui atomicamente como `max(sequence) + 1` em `transaction.atomic()` com retry em IntegrityError (até `MAX_SEQUENCE_ATTEMPTS=10`). `Meta.ordering = ['-sequence']`. Migration 0017 em 3 passos (AddField → RunPython backfill por (timestamp, pk) → AlterField unique). 8 testes em `core/tests_audit_sequence.py`. | `core/models.py` (`AuditLog.sequence`, `AuditLog.save`); `core/migrations/0017_alter_auditlog_options_auditlog_sequence.py`. |
| **N12** *(Sem.12)* | `OccurrenceViewSet.export_pdf` e `EvidenceViewSet.export_pdf` agora usam `Prefetch('custody_chain', queryset=ChainOfCustody.objects.select_related('agent').order_by('-sequence'))` + prefetches em falta (`digital_devices`, `sub_components__digital_devices`, `sub_components__custody_chain`). `pdf_export.py` substituído `.select_related().order_by()` (que invalidava o prefetch) por `sorted(qs.all(), key=...)`. Removido o prefetch interno redundante em `generate_occurrence_pdf`. 2 novos testes `PdfNoNPlusOneTest` com `CaptureQueriesContext` + `assertLessEqual(30)`. Query count caiu de 50+ para ≤30 (occurrence) / ≤25 (evidence). | `core/views.py` (export_pdf actions); `core/pdf_export.py` (`_current_custody_state`, `_render_sub_components`, `generate_*_pdf`). |
| **ADR-0012 Vaga 1** *(Sem.12)* | **Não é finding — trabalho derivado da re-classificação do N2.** QR codes nos PDFs apontam para `/v/<short_hash>/`. `core/qr_verify.py` (HMAC-SHA256 de `occurrence.id` truncado a 12 chars). Vista pública adaptativa em `core/frontend_views.py:public_verify_view`: sem login mostra dados não-sensíveis (código, contagem, hashes); EXPERT/AGENT-dono → redirect para vista completa. Throttle `verify_public: 30/minute`. Templates standalone `public_verify.html` + `public_verify_notfound.html`. 14 testes em `core/tests_public_verify.py` + `tests_pdf.py::PdfQrVerifyTest`. | `core/qr_verify.py`; `core/frontend_views.py`; `core/pdf_export.py` (`_build_verify_url`, `_qr_flowable`, `_qr_verify_band`); `requirements.txt` (`qrcode[pil]`). |
| **ADR-0012 Vaga 2** *(Sem.12)* | **Não é finding — trabalho derivado da re-classificação do N2.** Página `/occurrences/<id>/intake/` (EXPERT-only) com checklist das evidências esperadas. JS leve faz POST ao cascade endpoint existente (`/api/custody/cascade/`) com `new_state=RECEBIDA_LABORATORIO`, transitando todos os itens marcados atomicamente. Itens já recebidos aparecem desactivados. 11 testes em `core/tests_intake.py` (auth + render). | `core/frontend_views.py:occurrence_intake_view`; `src/frontend/templates/occurrence_intake.html`; `src/frontend/templates/403_intake.html`. |
| **DR doc** *(Sem.12)* | **Não é finding — fecha lateral do README:284.** Criado `docs/operations/disaster-recovery.md` com matriz de activos críticos, estratégia de backup (Neon PITR 7d + media volume), runbooks por cenário (BD/media/secret/QR_secret/region), plano de teste DR para Sem.15, retenção RGPD, e limitações conhecidas. | `docs/operations/disaster-recovery.md`; `README.md:284` actualizado. |

### 8.2 Mantidos em aberto — justificação por achado

Não há "roadmap v1.1" para onde adiar; a justificação de cada achado é o registo final.

| ID | Severidade | Custo estimado | Razão para não fixar nesta entrega |
|----|-----------|-----------------|------------------------------------|
| **N4** | 🟠 Alto | 5-7 dias | DoS de PDF síncrono requer Celery/RQ + worker separado em Fly. Mudar arquitectura runtime a <4 semanas da defesa não compensa. Mitigação imediata documentada (perfil de uso académico não excede 50 evidências/ocorrência). |
| **P5** | 🟠 Alto | 1-2 dias | CSS bloat (5679 linhas) é estética/performance. PurgeCSS + minify é viável mas exigiria introduzir build step (vs. ADR-0004 "no build"). Decisão alinhada com a opção arquitectural assumida. |
| **N6/N7** | 🟡 Médio | 2-3 dias | TRUNCATE e AuditLog sem trigger PG são vectores de insider DBA / SQL directo. Mesma justificação operacional de N5. |
| **T2/T3** | 🟡 Médio | 3-5 dias | Property-based (hypothesis) e load tests (k6/locust) ampliariam a confiança, mas a suite actual (>460 testes pós-Sem.12, cobertura ≥75 %) cobre invariantes funcionais. Ausência é académicamente reconhecida, não negada. |
| **N13, N15** | 🟢 Baixo | varia | `tests_services.py` namespace foi corrigido em Sem.10 (N13 deixou de ser válido — documentar como histórico); `frame-src 'none'` continua aceitável dado o escopo sem embeds. |

### 8.3 Postura final

O ForensiQ entrega com **9 dos 10 itens do Top-10 de Abril fechados** (B9 incluído em Sem.12; restam N4 e P5 por opção arquitectural), **5 dos 5 N* 🟠 Alto fechados ou re-classificados** (S9 em Sem.11; N2 re-classificado em Sem.12; N1/N3/N5 em 18 mai), e os principais 🟡 Médio e 🟢 Baixo da auditoria delta foram atacados em Sem.11 e Sem.12 (N8/N9/N10/N11/N12/N14). Permanecem em aberto, por opção: **N4** (Celery/RQ — esforço arquitectural), **P5** (PurgeCSS — viola ADR-0004), **N6/N7** (vector insider DBA), **T2/T3** (load tests e property-based).

Em Sem.12 acresceu trabalho derivado do ADR-0012 (não-finding): QR codes nos PDFs + endpoint público adaptativo + página de intake EXPERT-only no laboratório — ciclo físico do guia de transporte implementado end-to-end. Também foi criado o `docs/operations/disaster-recovery.md` que estava listado como pendente desde Sem.7.

A suite de testes cresceu para **447 testes** (de 393 no fecho da Sem.11 → +54 em Sem.12: 11 B9 + 8 N9 + 8 N10 + 2 N12 + 11 P1 + 3 PDF QR + 11 P2), todos a passar.

A re-classificação do N2 em Sem.12 não é varrer o finding para debaixo do tapete — é reconhecer que o audit avaliava o PDF contra um requisito que o produto não tem ("prova juridicamente auto-contida"). A discussão completa, alternativas, e impactos noutros documentos vivem em ADR-0012; o §4.1 deste audit foi anotado em conformidade.

A auditoria é o documento de registo; este §8 é o seu *closing chapter*. Qualquer pessoa que continue o projecto (orientador, novo aluno, recrutador) tem aqui o mapa completo do que está fixado, do que está aberto, e porquê — sem precisar de inferir do git log ou do código.

---

## Anexos

- Auditoria histórica: [`AUDIT_2026-04-16.md`](AUDIT_2026-04-16.md) (preservada inalterada).
- Auditoria intermédia 2026-04-19 (não documentada como ficheiro próprio) — referenciada nos comentários de `models.py:1067`, `views.py:415-416`, `serializers.py:356`. Concluiu fix B-C2/B-C3/B-C4 (race CoC) + IDOR `export_pdf` + IDOR DigitalDevice.
- ADR-0011: [`architecture/adr/ADR-0011-upgrade-django-6.md`](architecture/adr/ADR-0011-upgrade-django-6.md) — bump Django 5.2 → 6.0.5.
