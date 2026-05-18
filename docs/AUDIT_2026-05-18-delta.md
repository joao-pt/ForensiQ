# Auditoria ForensiQ — Delta 2026-05-18

**Escopo:** delta vs [`AUDIT_2026-04-16.md`](AUDIT_2026-04-16.md) (snapshot histórico imutável).
**Stack:** Django 6.0.5 + DRF 3.15 + PostgreSQL (Neon) + Fly.io. Frontend templates Django + JS vanilla.
**Método:** revisão por dimensões (segurança · backend/arquitectura · frontend/testes/CI) + leitura directa de `models.py`, `serializers.py`, `views.py`, `auth.py`, `middleware.py`, `audit.py`, `pdf_export.py`, `services/{imei,vin}_lookup.py`, `migrations/0002,0008`. 3 sub-auditorias focadas: PDF export, triggers PG, services externos.
**Veredito executivo:** **8 dos 10 itens do Top-10 de abr 2026 estão resolvidos**. O hardening de segurança crítica (JWT HttpOnly, CSP nonce, hash determinístico, IDOR, TRUSTED_PROXIES) materializou-se em código, com cobertura de testes adicional (+121%, 382 testes). Persistem riscos **operacionais** (EXIF em uploads, retenção AuditLog, custo IMEI sem quota) e **forenses de nível superior** (PDF sem assinatura/PDF-A, TRUNCATE não bloqueado, `session_replication_role`). Dois achados da auditoria de abr eram **falsos positivos** quando reverificados (B11, ip_address fallback).

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
| Bulk_create() bypassa `clean()` (achado preliminar) | `git grep "bulk_create"` em `src/backend/` — **0 ocorrências**. Não é usado em parte nenhuma do código. |
| Possível IDOR em `Evidence.occurrence_id` (achado preliminar) | `serializers.py:271-280` valida ownership via `validate_occurrence()`. Não é IDOR. |

---

## 2. Continua aberto desde 2026-04-16

| ID | Severidade | Descrição actual |
|----|-----------|------------------|
| **S9** | 🟠 Alto | **EXIF strip ausente em uploads de fotografia**. `grep -i "exif|getexif|exif_transpose"` em `src/backend/` → 0 ocorrências. `Pillow.verify()` é chamado para validar formato (`core/models.py:69-109`), mas os metadados EXIF (GPS, modelo de câmara, timestamp original) **permanecem na foto gravada**. Impacto forense: dados sensíveis de cena podem ser exfiltrados de relatórios PDF/exports legítimos. |
| **B3** | 🟡 Baixo→Médio | `AuditLog.ip_address` tem fallback `'0.0.0.0'` em `audit.py:80` — risco residual reduzido. Mantém-se aberto enquanto não houver `default='0.0.0.0'` no campo do model. |
| **B9** | 🟡 Médio | `AuditLog` sem política de retenção. Não há management command, cron Fly nem campo `expires_at`. PostgreSQL acumula indefinidamente. |
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
| **N2** | 🟠 Alto | **PDF export não assinado nem PDF/A**. PDFs forenses gerados pelo ReportLab embebem `integrity_hash` mas **não são assinados** (X.509) nem em formato PDF/A-3u (preservação a longo prazo). Um perito externo não consegue verificar inalterabilidade do PDF post-export. | `core/pdf_export.py:482-485`. |
| **N3** | 🟠 Alto | **XSS via ReportLab `Paragraph()` em valores não escapados**. `get_type_display()`, `get_condition_display()`, `get_previous_state_display()`, `get_new_state_display()` são passados directamente a `Paragraph(...)` sem `_sanitize()`. ReportLab interpreta XML embebido; se o display value contiver markup (improvável mas tecnicamente possível via migração de dados), há injecção visual no PDF. | `core/pdf_export.py:365,376,425,446,454,289-293`. |
| **N4** | 🟠 Alto | **PDF export síncrono sem timeout nem limite de páginas**. Ocorrência com 5000 evidências = PDF de 50-100 MB no thread de request, bloqueando worker e excedendo timeout Gunicorn 30s. DoS viável por utilizador autenticado. | `core/pdf_export.py:464-541,556-716`. |
| **N5** | 🟠 Alto | **`session_replication_role = 'replica'` não documentado nem defendido**. Um operador com role PG suficiente pode desactivar triggers de imutabilidade na sua sessão. Não há comment em migrations 0002/0008 a alertar; o `ALTER TABLE DISABLE TRIGGER` é tecnicamente inevitável mas tipicamente requer superuser. | `core/migrations/0002_*.py`, `0008_*.py` — nenhuma menção. |
| **N6** | 🟡 Médio | **`TRUNCATE` não bloqueado por triggers**. `BEFORE DELETE FOR EACH ROW` não dispara em `TRUNCATE`. O ataque é via SQL directo (não API), e `seed_demo.py:272-285` documenta-o explicitamente para fixtures, mas vale registar. | Migrations 0002/0008. |
| **N7** | 🟡 Médio | **`AuditLog` sem trigger PG de imutabilidade** (só protecção ORM `save()/delete()`). Em SQLite (testes) e em PG (produção), a defesa depende 100% do método `save()` ser chamado — `Model.objects.filter(...).update(...)` ou `delete()` bypass. | `core/models.py:1269-1287` (ORM only). |
| **N8** | 🟡 Médio | **Sem rate-limit interno para IMEI lookup** (existe `reverse_geocode: 10/min`; falta `imei_lookup` scope). Um agente pode esgotar o saldo `imeidb.xyz` com 60 reqs/min (limite `user`). | `forensiq_project/settings.py:143-152` — sem scope `imei_lookup`. |
| **N9** | 🟡 Médio | **Sem monitorização de quota/saldo IMEIDB**. Resposta 402 "payment required" → apenas log warning. Sem contador interno nem alerta Fly.io. | `core/services/imei_lookup.py:174`. |
| **N10** | 🟢 Baixo | **`AuditLog.timestamp` sem `sequence` field**. Dois inserts concorrentes podem ter mesmo microssegundo. Correlação por `correlation_id` mitiga, mas subóptimo forensicamente vs ChainOfCustody que tem `sequence`. | `core/models.py:1238`. |
| **N11** | 🟢 Baixo | **CSRF/CORS origin divergência**. `CSRF_TRUSTED_ORIGINS` (3 entradas) ≠ `CORS_ALLOWED_ORIGINS` (5 entradas). Ambas restritivas — risco baixo, mas indica drift de configuração. | `forensiq_project/settings.py:218-232`. |
| **N12** | 🟢 Baixo | **N+1 latente em `pdf_export.py`**. `evidence.digital_devices.all()` no loop (`pdf_export.py:683`) e `custody_chain.order_by('-sequence').first()` em sub-componentes (`pdf_export.py:550,648-649`). Mitigado se a view fizer `prefetch_related` — verificar `views.py:336,605-606`. | `core/pdf_export.py:550,683`; `core/views.py:336,605-606`. |
| **N13** | 🟢 Baixo | **`tests_services.py` (untracked) com 10 falhas**. 1048 linhas, 73 testes, 63 ✅ / 10 ❌. Falhas todas por `NoReverseMatch` — chama `reverse('occurrence-list')` em vez de `reverse('core:occurrence-list')` (porque `core/urls.py:38` declara `app_name='core'`). Bug do ficheiro, não do código aplicacional. | `core/tests_services.py:841,849,858,907,914,954,961,988,994,999`. |
| **N14** | 🟢 Baixo | **`buffer.close()` não garantido em `pdf_export.py` se `doc.build()` falhar**. Risco de leak de file descriptors em cenário de erro repetido. | `core/pdf_export.py:538-540,713-715`. |
| **N15** | 🟢 Informativo | **`frame-src 'none'` muito restritivo**. Bloqueia iframes legítimos. Aceitável dado o escopo actual (sem embeds), mas registar para futura integração de mapas embebidos ou docs visuais. | `core/middleware.py:127`. |

---

## 4. Áreas auditadas em profundidade extra

### 4.1 `pdf_export.py` (716 linhas, 2 classes + 15 funções)

- **Conformidade ISO/IEC 27037 — parcial**:
  - ✅ `integrity_hash` da evidência embebida (`pdf_export.py:317,388,436,646,660`).
  - ✅ `record_hash` da cadeia de custódia embebida (`pdf_export.py:317`).
  - ❌ PDF não é assinado digitalmente.
  - ❌ Sem PDF/A-3u (preservação a longo prazo).
  - ❌ `ModDate` não definida — modificação post-export indetectável por verificador externo.
  - ❌ Sem hash do próprio PDF nos metadados.
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
| 2 | **S9** — EXIF strip em uploads | 🟠 Alto | Privacidade da cena; agente pode revelar GPS sem querer. |
| 3 | **N2** — PDF sem assinatura/PDF-A | 🟠 Alto | Falha de "prova inalterável" para auditor externo. |
| 4 | **N3** — XSS ReportLab Paragraph | 🟠 Alto | Defesa em profundidade barata (`_sanitize` está pronto). |
| 5 | **N4** — PDF síncrono sem limite | 🟠 Alto | DoS trivial; mover para Celery/RQ ou impor `max_evidences`. |
| 6 | **P5** — CSS bloat 5679 linhas | 🟠 Alto | Visibilidade UX + transferência; PurgeCSS é low-effort. |
| 7 | **N8** — IMEI lookup sem throttle dedicado | 🟡 Médio | Adicionar `'imei_lookup': '5/minute'` em settings. |
| 8 | **N5** — `session_replication_role` sem documentar | 🟡 Médio | ADR ou comentário em migration; defesa operacional. |
| 9 | **B9** — AuditLog sem retenção | 🟡 Médio | Management command + cron Fly. |
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

## Anexos

- Auditoria histórica: [`AUDIT_2026-04-16.md`](AUDIT_2026-04-16.md) (preservada inalterada).
- Auditoria intermédia 2026-04-19 (não documentada como ficheiro próprio) — referenciada nos comentários de `models.py:1067`, `views.py:415-416`, `serializers.py:356`. Concluiu fix B-C2/B-C3/B-C4 (race CoC) + IDOR `export_pdf` + IDOR DigitalDevice.
- ADR-0011: [`architecture/adr/ADR-0011-upgrade-django-6.md`](architecture/adr/ADR-0011-upgrade-django-6.md) — bump Django 5.2 → 6.0.5.
