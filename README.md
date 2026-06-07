# ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders

[![CI](https://github.com/joao-pt/ForensiQ/actions/workflows/ci.yml/badge.svg)](https://github.com/joao-pt/ForensiQ/actions/workflows/ci.yml)
[![Security](https://github.com/joao-pt/ForensiQ/actions/workflows/security.yml/badge.svg)](https://github.com/joao-pt/ForensiQ/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Django 6](https://img.shields.io/badge/django-6.x-092e20.svg)](https://docs.djangoproject.com/)

> Digitalizar e padronizar a recolha, registo e cadeia de custódia de prova digital — do terreno ao laboratório, em conformidade com a ISO/IEC 27037.

**Estudante:** João M. M. Rodrigues · 2203474
**Orientador:** Professor Pedro Duarte Pestana
**UC:** 21184 — Projecto de Engenharia Informática · Universidade Aberta · 2025/26
**Repositório:** <https://github.com/joao-pt/ForensiQ>
**Produção:** <https://forensiq.pt>

---

## Estado actual

🟢 **MVP funcional em produção · Sem. 9 (janela de revisão alargada) · Relatório Intercalar aprovado em 5 mai 2026.**

- Backend Django 6 + DRF com **≈537 testes** (531 a passar + 6 skip de triggers só-PostgreSQL, exercitados no job postgres do CI) e cobertura **~84%** (gate CI a 80%).
- Cadeia de custódia imutável com hash SHA-256 encadeado (blockchain-like) + *cascade endpoint* para transições atómicas.
- 18 tipos taxonómicos de evidência digital com sub-componentes (parent_evidence) e validação anti-ciclos.
- Frontend server-rendered (Django templates + HTMX + Leaflet), mobile-first + **modo tabela densa em desktop** (PR #1+#2) com multi-select.
- Mapa Leaflet/OpenStreetMap; PDF export ReportLab; **demo seed** (`manage.py seed_demo`) com 5 ocorrências PT realistas e fotos placeholder.
- HTTPS A+ no SSL Labs, HSTS preload submetido, Mozilla Observatory A+, CSP nível 3 com nonce por request.
- Auditorias completas (segurança 2026-04-16, design 2026-04-18, taxonomia 2026-04-19, *sweep* UX 2026-05-02, redesign *dashboard*+*custody timeline* 2026-05-03).

### Demonstração

A instância em <https://forensiq.pt> está pré-populada para fins de avaliação académica. **As credenciais para o orientador foram partilhadas por canal privado** — não constam neste repositório por princípio de segurança (ISO/IEC 27037 §5.4 e OWASP A07:2021 *Identification and Authentication Failures*).

Para correr uma instância local com dados realistas, há um único comando interactivo:

```bash
# Modo interactivo (pede em prompt as credenciais do agente e do perito; provisiona
# ainda 4 perfis com password de demonstração conhecida — custódio, MP, chefe de
# serviço e auditor — cobrindo os 6 papéis do ADR-0017):
python manage.py seed_demo --reset

# Só (cria/actualiza) os 6 utilizadores demo, sem mexer em ocorrências:
python manage.py seed_demo --users-only

# Não-interactivo (CI/scripts) — exige todas as credenciais como flags:
python manage.py seed_demo --reset --no-input \
    --agent-username=ag --agent-password=Aa12345! \
    --expert-username=pe --expert-password=Ee12345!
```

O `--reset` apaga TODOS os dados em `core_*` (com `--wipe-media` apaga também as fotos). Sem flags, o comando comporta-se como `--reset` se a base estiver vazia, ou falha com instruções claras se já houver dados (evita destruição acidental).

Para um superuser administrativo (acesso ao `/admin/`), corre o built-in do Django em separado: `python manage.py createsuperuser`. O `seed_demo` nunca cria nem promove superusers — responsabilidades dissociadas por design.

Evidence, ChainOfCustody e AuditLog mantêm `has_change_permission=False` no admin mesmo para superusers, preservando o argumento ISO/IEC 27037 sobre imutabilidade da prova.

---

## Funcionalidades implementadas

### Modelo de dados forense
- `User` — dois eixos independentes (ADR-0017): **função** (`profile`, 6 valores: Agente/Primeiro interveniente, Perito forense, Custódio/Fiel depositário, Autoridade judiciária (MP), Chefe de serviço, Auditor) + **credencial** (`clearance`: NORMAL / NACIONAL); mais `badge_number`, `phone`
- `Occurrence` — caso/cena de crime (NUIPC, GPS, address, agent)
- `Evidence` — item apreendido com taxonomia de **18 tipos digital-first** (ADR-0010): 14 raízes — `MOBILE_DEVICE`, `COMPUTER`, `STORAGE_MEDIA`, `GAMING_CONSOLE`, `GPS_TRACKER`, `SMART_TAG`, `CCTV_DEVICE`, `VEHICLE`, `DRONE`, `IOT_DEVICE`, `NETWORK_DEVICE`, `DIGITAL_FILE`, `RFID_NFC_CARD`, `OTHER_DIGITAL` — e 4 sub-componentes — `SIM_CARD`, `MEMORY_CARD`, `INTERNAL_DRIVE`, `VEHICLE_COMPONENT` — com hierarquia até 3 níveis via `parent_evidence`
- `ChainOfCustody` — **ledger de eventos append-only** (ADR-0015): cada registo é um evento (`event_type` + `custodian_type` + local/GPS) com hash SHA-256 encadeado. O estado legal (à guarda do OPC, em perícia, restituída, perdida a favor do Estado, …) é **derivado** do log, não gravado. Substituiu a antiga máquina de estados linear.
- `AuditLog` com correlation_id por request

### Backend (Django + DRF)
- API REST com 12+ rotas e Swagger UI em `/api/docs/`
- **Autenticação JWT em cookies HttpOnly** (`fq_access` / `fq_refresh`) com CSRF enforcement em métodos não-safe
- Endpoints `/api/auth/{login,refresh,logout}/` (rotação + blacklist)
- Imutabilidade ao nível DB (PostgreSQL trigger `prevent_evidence_modification`) — UPDATE/DELETE bloqueados em Evidence e ChainOfCustody
- Lookup IMEI (imeidb.xyz) e VIN (redirect vindecoder)
- Validadores forenses: IMEI Luhn, VIN ISO 3779, IMSI MCC+MNC
- PDF export forense (`/api/evidences/<id>/pdf/`) com ReportLab + declaração ISO/IEC 27037
- DatabaseCache (PostgreSQL Neon) para `/api/stats/dashboard/` e lookups
- Throttling (5 req/min) em endpoints sensíveis

### Frontend (Django templates + HTMX + Leaflet)
- Mobile-first, touch targets ≥48px (WCAG 2.1 AA)
- Tipografia: IBM Plex Sans (UI) + IBM Plex Mono (hashes/IDs/timestamps/coordenadas), self-hosted (woff2)
- Tokens semânticos para estados forenses (`--state-apreendida` etc.)
- **Páginas:**
  - `/login/` — autenticação JWT (cookie) com fallback de erro e Caps Lock detect
  - `/dashboard/` — saudação, **acções rápidas (Nova Ocorrência / Novo Item proeminentes em mobile)**, últimas ocorrências, stats por estado de custódia (Em perícia, Em trânsito), breakdown por tipo
  - `/occurrences/` — lista + mapa Leaflet com toggle, pesquisa client-side, paginação
  - `/occurrences/new/` — wizard 6-step com GPS automático + reverse geocoding (Nominatim)
  - `/occurrences/<id>/` — hub do caso (resumo, mapa multi-marker com GPS por item, custody summary, lista de itens)
  - `/occurrences/<id>/intake/` — intake/receção formal do caso
  - `/evidences/` — lista com badges por tipo, GPS/foto/sub indicators
  - `/evidences/new/` — wizard com type selector visual, captura de foto (câmara nativa + upload), GPS, lookup IMEI/VIN, sub-componentes recursivos
  - `/evidences/<id>/` — detalhe com hash SHA-256, foto, metadados, sub-componentes integrantes, custódia actual
  - `/evidences/<id>/custody/` — timeline cronológica com state progress, modal de transição (apenas AGENT, próximo estado válido), hashes encadeados
  - `/custodies/` — todas as transições com filtros (mobile compacto, desktop completo)
  - `/stats/` — dashboard agregado
  - `/reports/` — guias de transporte (PDF, ADR-0012)
  - `/settings/` — perfil, **tema dia/noite + tema automático por hora do dia (claro 07h–19h, escuro fora desse intervalo)**, terminar sessão
  - `/audit/investigation/` — relatório de investigação de erros (auditoria)
  - `/verificacoes/` — centro de verificação QR para operador (gestão, não pesquisa pública)
  - `/v/<hash>/` — verificação pública via QR, sem autenticação

### Infraestrutura
- Deploy em **Fly.io (Frankfurt)** com volume persistente para uploads
- HTTPS A+ (Qualys SSL Labs) com Let's Encrypt RSA + ECDSA
- HSTS 1 ano + preload submetido a hstspreload.org
- HTTP Observatory (Mozilla) — pontuação A+
- Dockerfile multi-stage (`python:3.12-slim`, user não-root, Gunicorn + WhiteNoise)
- PostgreSQL gerido em **Neon.tech** com connection pooling (PgBouncer)
- Cache em DB (`forensiq_cache` table)

### Segurança (OWASP ASVS v4)
| Controlo | Implementação |
|---|---|
| **Autenticação** | JWT em HttpOnly + Secure + SameSite=Strict; rotação de refresh; blacklist |
| **CSRF** | Token por sessão (não-HttpOnly), validado em todos os métodos não-safe |
| **CSP Level 3** | `script-src 'self' 'nonce-{nonce}'`; `style-src 'self' 'nonce-{nonce}'` (sem `unsafe-inline`); `frame-ancestors 'none'`; `upgrade-insecure-requests` |
| **OWASP Top 10** | Audit limpo (Semgrep p/owasp-top-ten + p/security-audit) |
| **Imutabilidade** | Trigger PostgreSQL bloqueia UPDATE/DELETE em Evidence/ChainOfCustody |
| **Integridade** | SHA-256 com nonce determinístico (verificável); hash encadeado em ChainOfCustody |
| **IDOR** | `get_queryset()` filtra por `request.user`; ownership validado em writes |
| **Rate limiting** | DRF throttling 5/min em login/refresh/logout |
| **Logging seguro** | Sem PII; correlation_id por request via middleware |
| **Permissões** | RBAC fino por função (ADR-0017): primeiro interveniente cria; perito e custódio operam a custódia; autoridade judiciária (MP), chefe de serviço e auditor em só-leitura; visibilidade modulada pela credencial (NORMAL/NACIONAL) |
| **Trusted proxies** | `TRUSTED_PROXIES` env var (X-Forwarded-For audit integrity) |
| **Admin** | URL com prefixo aleatório via `ADMIN_URL_PREFIX` env var |

### UX e acessibilidade
- **Mobile (perito no terreno)**: dashboard prioriza acções rápidas (Nova Ocorrência / Novo Item) e últimas ocorrências; estatísticas em scroll horizontal compacto
- **Desktop**: stats grid 4 colunas + breakdown + acções + recent
- **Breadcrumb**: chevron SVG mask-image; em mobile colapsa para botão "← {parent}"
- **Tema dia/noite** com toggle persistente em localStorage; **tema automático opcional** por hora do dia (claro entre as 07h e as 19h, escuro fora desse intervalo), client-side
- **A11y**: `aria-busy` em listas, `aria-pressed` no theme toggle, live region para anúncios, roving tabindex em radiogroups (type-btn, occurrences tabs)
- **Acessibilidade WCAG 2.1 AA**: contraste 4.5:1+, touch targets 48px, focus rings consistentes, redução de movimento respeitada

### Testes (≈537 · cobertura ~84%, gate CI 80%)

Snapshot não-exaustivo (há mais ficheiros `tests_*.py`); para o total real corre `pytest -q`.

| Suite | Foco | Cobertura |
|---|---|---|
| `tests.py` | modelos + imutabilidade | User, Occurrence, Evidence, `ChainOfCustody` (ledger de eventos), hash encadeado, triggers PG (camada 3) |
| `tests_api.py` | API REST | auth/JWT cookie, CRUD, IDOR, imutabilidade, eventos de custódia, validação, lookup, fluxo CSRF dedicado |
| `tests_frontend.py` | frontend (server-side) | views, templates, redirect, conteúdo HTML, JWT cookie |
| `tests_pdf.py` | PDF export | geração, sanitização, content-type, 404, com/sem custódia |
| `tests_new_features.py` | cascade + UX | cascade custody, filtros por estado derivado, media serve, audit log |
| `tests_table_mode.py` | modo tabela densa | DataTable, multi-select, sort, paginação, filtros |
| `tests_taxonomy.py` | taxonomia + prioridade | tabelas de referência, `crime_type`, prioridade derivada da Lei 51/2023 |
| `tests_dashboard.py` | dashboard | feed de actividade, deltas 24h, séries 7d, ownership |
| `tests_coverage.py` | cobertura adicional | exception handler, edge cases serializers, PDF content (`pypdf`), throttles |
| `tests_frontend_js_namespace.py` | namespace JS | identificadores top-level + colisões cross-template |
| `tests_access.py` | acesso + receção | gate de receção e papéis/credenciais (ADR-0017) |
| `tests_modelo_v2.py` | identificação v2 | IDs hierárquicos + génese por proveniência (ADR-0016) |
| `tests_intake.py` | intake de ocorrência | fluxo de receção/abertura de caso |
| `tests_public_verify.py` | verificação pública | resolução de hash/QR sem auth (`/v/<hash>/`) |
| `tests_factories.py` | helpers | factory-boy (inclui `AuditLogFactory`); não conta para o total |

```bash
cd src/backend
../../.venv/Scripts/python.exe -m pytest -q
# 531 passed, 6 skipped (triggers só-PostgreSQL)
../../.venv/Scripts/python.exe -m pytest --cov=core --cov-report=term-missing
# Cobertura ~84% global (gate CI: fail_under=80)
```

### Conformidade
- **ISO/IEC 27037:2012** — Integridade da prova digital (SHA-256, hash encadeado, append-only)
- **ISO/IEC 27001:2022** — Gestão de segurança (RBAC, auditoria, HTTPS, rate limiting)
- **WCAG 2.1 AA** — Acessibilidade
- **RGPD (UE 2016/679)** — Minimização de dados; tensão com art. 17.º resolvida pelo n.º 3 alínea e) (defesa em processo judicial)

---

## Estrutura do repositório

```
ForensiQ/
├── docs/
│   ├── scope/                       # § 5 do guia: âmbito + planeamento
│   │   ├── proposta.md              # Sinopse, MVP, critérios de aceitação
│   │   ├── requirements.md          # MoSCoW (RF01-17, RNF01-06)
│   │   ├── risks.md                 # R01-R10 + matriz de controlos forenses
│   │   ├── changelog.md             # Uma entrada por semana (Sem 1-7)
│   │   └── iso27037-traceability.pdf      # Mapeamento à norma
│   ├── architecture/                # § 5 do guia: design
│   │   ├── c4-context.png           # C4 nv 1
│   │   ├── c4-containers.png        # C4 nv 2
│   │   ├── data-model.png           # ER PostgreSQL
│   │   ├── adr/                     # ADRs 0001-0017
│   │   └── diagrams/                # C4 + ER + custody event ledger + hash-chain-flow + immutability-3-layers (Mermaid)
│   ├── design/                      # § 5 do guia: interface
│   │   ├── wireframes.pdf           # Protótipo de navegação (pós-implementação, abordagem code-first justificada via § 7)
│   │   ├── auditoria-de-design.html # Auditoria estruturada (34 achados, 18 abr 2026)
│   │   └── screens/                 # Capturas usadas no wireframes.pdf
│   ├── compliance/external-tests/   # Qualys SSL Labs, HSTS Preload, Mozilla Observatory
│   ├── deployment/                  # Guia Fly.io
│   └── report/                      # PDFs entregáveis (proposta.pdf, intercalar.pdf)
├── src/
│   ├── backend/                     # Django 6 + DRF
│   │   ├── core/                    # App principal (models, views, serializers, tests)
│   │   ├── forensiq_project/        # Settings, URLs raiz, test_settings
│   │   └── manage.py                # comandos `seed_demo` (utilizadores+dados), `seed_crime_taxonomy` (INE/Lei 51/2023, ADR-0014), `purge_audit_logs` (retenção)
│   └── frontend/                    # Templates Django + HTMX + Leaflet + CSS/JS
├── Dockerfile                       # Multi-stage build
├── fly.toml                         # Config Fly.io (region fra)
└── README.md
```

---

## Como instalar e correr (local)

### 1. Clonar e configurar

```bash
git clone https://github.com/joao-pt/ForensiQ.git
cd ForensiQ
python3 -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# Produção (apenas runtime):
pip install -r src/backend/requirements.txt

# Desenvolvimento (runtime + testes + linting + pre-commit):
pip install -r src/backend/requirements.txt -r src/backend/requirements-dev.txt
pre-commit install
```

### 2. Variáveis de ambiente

```bash
cp .env.example .env
# Editar .env: DATABASE_URL, SECRET_KEY, JWT_SIGNING_KEY,
#              ADMIN_URL_PREFIX, IMEIDB_API_TOKEN, TRUSTED_PROXIES
```

### 3. Migrations + cache table + superuser

```bash
cd src/backend
python manage.py migrate              # cria tabelas + cache
python manage.py createsuperuser
```

### 4. Correr

```bash
python manage.py runserver
```

| URL | Descrição |
|---|---|
| <http://localhost:8000/login/> | Autenticação JWT |
| <http://localhost:8000/dashboard/> | Painel principal |
| <http://localhost:8000/api/docs/> | Swagger UI |
| <http://localhost:8000/admin/> | Django Admin (URL com prefixo do `ADMIN_URL_PREFIX`) |

### 5. Testes

```bash
cd src/backend
python -m pytest -q                   # ≈537 testes (531 a passar + 6 skip de triggers só-PostgreSQL)
python -m pytest --cov=core           # com coverage
```

---

## Decisões de arquitectura (ADRs)

| ADR | Tópico | Decisão |
|---|---|---|
| 0001 | Base de dados | Neon.tech (Frankfurt) — gerido, com connection pooling |
| 0002 | Estrutura Django | Projecto `forensiq_project` + app `core` |
| 0003 | API REST | DRF + ViewSets + permissões custom + Spectacular OpenAPI |
| 0004 | Frontend | Server-rendered (Django templates + HTMX + Leaflet), mobile-first |
| 0005 | Deployment | Fly.io (Frankfurt), HTTPS automático, volume persistente |
| 0006 | Sub-componentes | `Evidence.parent_evidence` self-FK; profundidade ≤3 |
| 0007 | SRI + Referrer-Policy | Subresource Integrity em CDN; strict-origin-when-cross-origin |
| 0008 | Cache | DatabaseCache em Neon (sem Redis adicional) |
| 0009 | JWT cookies | HttpOnly cookies + CSRF (Wave 2d) — substitui Authorization Bearer + localStorage |
| 0010 | Taxonomia | 18 tipos digitais hierárquicos (Wave 2c); IMEI/VIN lookups |
| 0011 | Upgrade Django 6 | Migração para Django 6.x |
| 0012 | PDF | PDF como guia de transporte (barcodes/QR), não prova autónoma |
| 0013 | GPS na custódia | Captura de GPS nos eventos de cadeia de custódia |
| 0014 | Taxonomia/prioridade | Tipos de crime (INE) + prioridade derivada da Lei 51/2023 |
| 0015 | Custódia ledger | Ledger de eventos append-only — substitui a máquina de estados |
| 0016 | IDs hierárquicos | Identificação hierárquica + génese por proveniência (aquisição/extração) |
| 0017 | Papéis e acesso | Função + credencial; papéis, instituições e acesso à custódia |

Detalhe completo em `docs/architecture/adr/`.

---

## Contribuir

Projecto académico individual (UC 21184). Os commits seguem Conventional Commits em PT-PT. Reportar vulnerabilidades via [`SECURITY.md`](SECURITY.md) — GitHub Security Advisory privado, não *issue* público.

## Roadmap pós-entrega final

Trabalho assumido como *future work* no relatório, a executar após avaliação da UC 21184:

- **RGPD Art. 32 alínea c)** — migrar `media/` para object storage com SSE-KMS, snapshots automáticos da base de dados Neon e teste de restauro trimestral. Plano mínimo viável documentado em [`docs/operations/disaster-recovery.md`](docs/operations/disaster-recovery.md) (Sem.12); a evolução para object storage + exercício de DR validado fica pós-entrega
- **RGPD Art. 32 alínea d)** — DAST automatizado em CI (OWASP ZAP weekly); SAST/SCA já cobertos por `.github/workflows/security.yml` (pip-audit, bandit, gitleaks, trivy)
- **Pentest externo** de caixa-preta (estudante MIEI ou empresa parceira da UAb)
- **Cobertura ≥85%** — módulos prioritários: `core/serializers.py`, `core/pdf_export.py`
- **i18n** — `gettext` em Django + JSON catalog no frontend; pt-PT por defeito + en-US adicional
- **Novos papéis** — coordenador (visão multi-NUIPC) e magistrado (acesso *read-only* a casos arquivados com justificação)
- **Réguas e multi-foto** em captura de evidência fotográfica (ver `docs/architecture/photo-capture-status.md`)
- **OCR** em ecrãs de telemóvel apreendidos (Tesseract + pré-processamento)

## Referências

- Casey, E. (2011). *Digital Evidence and Computer Crime* (3rd ed.). Academic Press.
- ACPO (2012). *Good Practice Guide for Digital Evidence*.
- ISO/IEC 27037:2012 — Guidelines for identification, collection, acquisition and preservation of digital evidence.
- NIST SP 800-86 (2006). *Guide to Integrating Forensic Techniques into Incident Response*.
- OWASP ASVS v4 — Application Security Verification Standard.
- Pestana, P. D. (Projecto #38 — LEI 2025/26). *Plataforma Modular de Captura e Preservação de Evidência Digital para OSINT*. Universidade Aberta.

---

## Uso de IA generativa

O desenvolvimento foi assistido por modelos de IA generativa (assistentes comerciais, principalmente) em modo *pair programming*: brainstorming arquitectural, geração de boilerplate, escrita inicial de testes, revisão de segurança. Todo o código foi compreendido, validado e adaptado pelo autor antes de entrar no repositório (regra inviolável de desenvolvimento do projecto). Ferramentas e referências serão listadas na secção de Referências do relatório final.

---

*Última actualização: 4 jun 2026 · sincronização da documentação com o código · **≈537 testes** (531 a passar + 6 skip de triggers PG) · cobertura ~84% (gate CI 80%)*
