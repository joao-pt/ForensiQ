# ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders

[![CI](https://github.com/joao-pt/ForensiQ/actions/workflows/ci.yml/badge.svg)](https://github.com/joao-pt/ForensiQ/actions/workflows/ci.yml)
[![Security](https://github.com/joao-pt/ForensiQ/actions/workflows/security.yml/badge.svg)](https://github.com/joao-pt/ForensiQ/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Django 5](https://img.shields.io/badge/django-5.x-092e20.svg)](https://docs.djangoproject.com/)

> Digitalizar e padronizar a recolha, registo e cadeia de custódia de prova digital — do terreno ao laboratório, em conformidade com a ISO/IEC 27037.

**Estudante:** João M. M. Rodrigues · 2203474
**Orientador:** Professor Pedro Duarte Pestana
**UC:** 21184 — Projecto de Engenharia Informática · Universidade Aberta · 2025/26
**Repositório:** <https://github.com/joao-pt/ForensiQ>
**Produção:** <https://forensiq.pt>

---

## Estado actual

🟢 **MVP funcional em produção · Sem. 9 (janela de revisão alargada) · Relatório Intercalar aprovado em 5 mai 2026.**

- Backend Django 5 + DRF com **293 testes a passar (100%)** (cobertura ≥75%).
- Cadeia de custódia imutável com hash SHA-256 encadeado (blockchain-like) + *cascade endpoint* para transições atómicas.
- 18 tipos taxonómicos de evidência digital com sub-componentes (parent_evidence) e validação anti-ciclos.
- Frontend HTML/CSS/JS vanilla, mobile-first + **modo tabela densa em desktop** (PR #1+#2) com multi-select e CSV export streaming (cap 10k).
- Mapa Leaflet/OpenStreetMap; PDF export ReportLab; **demo seed** (`manage.py seed_demo`) com 5 ocorrências PT realistas e fotos placeholder.
- HTTPS A+ no SSL Labs, HSTS preload submetido, Mozilla Observatory A+, CSP nível 3 com nonce por request.
- Auditorias completas (segurança 2026-04-16, design 2026-04-18, taxonomia 2026-04-19, *sweep* UX 2026-05-02, redesign *dashboard*+*custody timeline* 2026-05-03).

### Credenciais de demonstração

Em <https://forensiq.pt> (e em qualquer instância populada via `python manage.py seed_demo` seguido de `python manage.py seed_mobile_users`):

| Username | Perfil | Password | Uso |
|---|---|---|---|
| `perito` | EXPERT | `1234` | Consulta, perícia, cadeia de custódia, exportação PDF |
| `agente` | AGENT | `1234` | Criação de ocorrências e itens no terreno, captura de foto/GPS |
| `pedro.pestana` | EXPERT + superuser | (definida pelo orientador) | Edição via `/admin/` para User/Occurrence/DigitalDevice |

As credenciais demo são para avaliação académica e demo do orientador; **não usar em instalações reais**. Evidence, ChainOfCustody e AuditLog mantêm `has_change_permission=False` no admin mesmo para o superuser, preservando o argumento ISO/IEC 27037 sobre imutabilidade da prova.

---

## Funcionalidades implementadas

### Modelo de dados forense
- `User` (perfis **AGENT** / **EXPERT**, badge_number, phone)
- `Occurrence` — caso/cena de crime (NUIPC, GPS, address, agent)
- `Evidence` — item apreendido com taxonomia de **18 tipos digital-first** (ADR-0010): 14 raízes — `MOBILE_DEVICE`, `COMPUTER`, `STORAGE_MEDIA`, `GAMING_CONSOLE`, `GPS_TRACKER`, `SMART_TAG`, `CCTV_DEVICE`, `VEHICLE`, `DRONE`, `IOT_DEVICE`, `NETWORK_DEVICE`, `DIGITAL_FILE`, `RFID_NFC_CARD`, `OTHER_DIGITAL` — e 4 sub-componentes — `SIM_CARD`, `MEMORY_CARD`, `INTERNAL_DRIVE`, `VEHICLE_COMPONENT` — com hierarquia até 3 níveis via `parent_evidence`
- `DigitalDevice` (legacy, coexiste com `Evidence.sub_components`)
- `ChainOfCustody` — máquina de estados linear (APREENDIDA → EM_TRANSPORTE → RECEBIDA_LABORATORIO → EM_PERICIA → CONCLUIDA → DEVOLVIDA / DESTRUIDA)
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

### Frontend (HTML5/CSS3/JavaScript vanilla)
- Mobile-first, touch targets ≥48px (WCAG 2.1 AA)
- Tipografia: Inter (UI) + JetBrains Mono (hashes/IDs/timestamps)
- Tokens semânticos para estados forenses (`--state-apreendida` etc.)
- **Páginas:**
  - `/login/` — autenticação JWT (cookie) com fallback de erro e Caps Lock detect
  - `/dashboard/` — saudação, **acções rápidas (Nova Ocorrência / Novo Item proeminentes em mobile)**, últimas ocorrências, stats por estado de custódia (Em perícia, Em trânsito), breakdown por tipo
  - `/occurrences/` — lista + mapa Leaflet com toggle, pesquisa client-side, paginação
  - `/occurrences/new/` — wizard 6-step com GPS automático + reverse geocoding (Nominatim)
  - `/occurrences/<id>/` — hub do caso (resumo, mapa multi-marker com GPS por item, custody summary, lista de itens)
  - `/evidences/` — lista com badges por tipo, GPS/foto/sub indicators
  - `/evidences/new/` — wizard com type selector visual, captura de foto (câmara nativa + upload), GPS, lookup IMEI/VIN, sub-componentes recursivos
  - `/evidences/<id>/` — detalhe com hash SHA-256, foto, metadados, sub-componentes integrantes, custódia actual
  - `/evidences/<id>/custody/` — timeline cronológica com state progress, modal de transição (apenas AGENT, próximo estado válido), hashes encadeados
  - `/custodies/` — todas as transições com filtros (mobile compacto, desktop completo)
  - `/stats/` — dashboard agregado
  - `/reports/` — relatórios PDF
  - `/settings/` — perfil, **tema dia/noite + tema automático ao entardecer (geolocation + sunset NOAA)**, terminar sessão

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
| **Permissões** | RBAC fino (AGENT cria; EXPERT consulta; staff vê tudo) |
| **Trusted proxies** | `TRUSTED_PROXIES` env var (X-Forwarded-For audit integrity) |
| **Admin** | URL com prefixo aleatório via `ADMIN_URL_PREFIX` env var |

### UX e acessibilidade
- **Mobile (perito no terreno)**: dashboard prioriza acções rápidas (Nova Ocorrência / Novo Item) e últimas ocorrências; estatísticas em scroll horizontal compacto
- **Desktop**: stats grid 4 colunas + breakdown + acções + recent
- **Breadcrumb**: chevron SVG mask-image; em mobile colapsa para botão "← {parent}"
- **Tema dia/noite** com toggle persistente em localStorage; **tema automático opcional** ativa modo noite 1h após pôr-do-sol (cálculo NOAA via geolocation, client-side)
- **A11y**: `aria-busy` em listas, `aria-pressed` no theme toggle, live region para anúncios, roving tabindex em radiogroups (type-btn, occurrences tabs)
- **Acessibilidade WCAG 2.1 AA**: contraste 4.5:1+, touch targets 48px, focus rings consistentes, redução de movimento respeitada

### Testes (293 a passar · cobertura ≥75%)

| Suite | Casos | Cobertura |
|---|---|---|
| `tests.py` | 14 modelos | User, Occurrence, Evidence, DigitalDevice, ChainOfCustody |
| `tests_api.py` | 83 API | auth, CRUD, IDOR, imutabilidade, transições, validação, lookup, stats, throttle |
| `tests_frontend.py` | 54 frontend (server-side) | views, templates, redirect, conteúdo HTML, JWT cookie |
| `tests_pdf.py` | 18 PDF export | geração, sanitização, content-type, 404, com/sem dispositivos |
| `tests_new_features.py` | 22 cascade + CSV | cascade custody, CSV streaming, audit log |
| `tests_table_mode.py` | 22 modo tabela densa | DataTable, multi-select, sort, paginação |
| `tests_coverage.py` | 69 cobertura adicional | exception handler, edge cases serializers, PDF content (via `pypdf`), hash chain, dashboard stats, IMEI lookup |
| `tests_frontend_js_namespace.py` | 11 namespace JS | extracção de identificadores top-level + detecção de colisões cross-template |
| `tests_factories.py` | — helpers | factory-boy fixtures partilhadas (não conta para o total) |

```bash
cd src/backend
../../.venv/Scripts/python.exe -m pytest -q
# 293 passed
../../.venv/Scripts/python.exe -m pytest --cov=core --cov-report=term-missing
# Cobertura ≥75% global em core/
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
│   │   ├── proposta.md / .tex       # Sinopse, MVP, critérios de aceitação
│   │   ├── requirements.md / .tex   # MoSCoW (RF01-17, RNF01-06)
│   │   ├── risks.md / .tex          # R01-R10 + matriz de controlos forenses
│   │   ├── changelog.md             # Uma entrada por semana (Sem 1-7)
│   │   └── iso27037-traceability.tex/pdf  # Mapeamento à norma
│   ├── architecture/                # § 5 do guia: design
│   │   ├── c4-context.png           # C4 nv 1
│   │   ├── c4-containers.png        # C4 nv 2
│   │   ├── data-model.png           # ER PostgreSQL
│   │   ├── adr/                     # ADRs 0001-0010
│   │   └── diagrams/                # C4 + ER + state machine + hash-chain-flow + immutability-3-layers (Mermaid)
│   ├── design/                      # § 5 do guia: interface
│   │   ├── wireframes.pdf           # Protótipo de navegação (pós-implementação, abordagem code-first justificada via § 7)
│   │   ├── auditoria-de-design.html # Auditoria estruturada (34 achados, 18 abr 2026)
│   │   └── screens/                 # Capturas usadas no wireframes.pdf
│   ├── compliance/external-tests/   # Qualys SSL Labs, HSTS Preload, Mozilla Observatory
│   ├── deployment/                  # Guia Fly.io
│   └── report/                      # PDFs entregáveis (proposta.pdf, intercalar.pdf)
├── src/
│   ├── backend/                     # Django 5 + DRF
│   │   ├── core/                    # App principal (models, views, serializers, tests)
│   │   ├── forensiq_project/        # Settings, URLs raiz, test_settings
│   │   └── manage.py                # + comando seed_demo
│   └── frontend/                    # Templates Django + CSS/JS vanilla
├── src_latex/                       # Fonte LaTeX (proposta, intercalar) + figuras
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
python -m pytest -q                   # 213 testes
python -m pytest --cov=core           # com coverage
```

---

## Decisões de arquitectura (ADRs)

| ADR | Tópico | Decisão |
|---|---|---|
| 0001 | Base de dados | Neon.tech (Frankfurt) — gerido, com connection pooling |
| 0002 | Estrutura Django | Projecto `forensiq_project` + app `core` |
| 0003 | API REST | DRF + ViewSets + permissões custom + Spectacular OpenAPI |
| 0004 | Frontend | HTML/CSS/JS vanilla — sem build, mobile-first |
| 0005 | Deployment | Fly.io (Frankfurt), HTTPS automático, volume persistente |
| 0006 | Sub-componentes | `Evidence.parent_evidence` self-FK; profundidade ≤3 |
| 0007 | SRI + Referrer-Policy | Subresource Integrity em CDN; strict-origin-when-cross-origin |
| 0008 | Cache | DatabaseCache em Neon (sem Redis adicional) |
| 0009 | JWT cookies | HttpOnly cookies + CSRF (Wave 2d) — substitui Authorization Bearer + localStorage |
| 0010 | Taxonomia | 18 tipos digitais hierárquicos (Wave 2c); IMEI/VIN lookups |

Detalhe completo em `docs/architecture/adr/`.

---

## Contribuir

Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) para o workflow de Conventional Commits em PT-PT, política de *branches* e processo de Pull Request. Reportar vulnerabilidades via [`SECURITY.md`](SECURITY.md) (GitHub Security Advisory privado, não issue público). Código de conduta em [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1).

## Roadmap pós-entrega final

Trabalho assumido como *future work* no relatório, a executar após avaliação da UC 21184:

- **RGPD Art. 32 alínea c)** — migrar `media/` para object storage com SSE-KMS, snapshots automáticos da base de dados Neon e teste de restauro trimestral (`docs/operations/disaster-recovery.md` pendente)
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

O desenvolvimento foi assistido por modelos de IA generativa (assistentes comerciais, principalmente) em modo *pair programming*: brainstorming arquitectural, geração de boilerplate, escrita inicial de testes, revisão de segurança. Todo o código foi compreendido, validado e adaptado pelo autor antes de entrar no repositório (regra inviolável definida em `INSTRUCOES_GLOBAIS.md`). Ferramentas e referências serão listadas na secção de Referências do relatório final.

---

*Última actualização: 17 mai 2026 · Sem. 9 (janela de revisão alargada) · **293 testes a passar (100%)** · cobertura ≥75%*
