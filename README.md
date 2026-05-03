# ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders

> Digitalizar e padronizar a recolha, registo e cadeia de custódia de prova digital — do terreno ao laboratório, em conformidade com a ISO/IEC 27037.

**Estudante:** João M. M. Rodrigues · 2203474
**Orientador:** Professor Pedro Duarte Pestana
**UC:** 21184 — Projecto de Engenharia Informática · Universidade Aberta · 2025/26
**Repositório:** <https://github.com/joao-pt/ForensiQ>
**Produção:** <https://forensiq.pt>

---

## Estado actual

🟢 **MVP funcional em produção · Sem. 7 · Relatório Intercalar pronto para entrega 6 mai 2026.**

- Backend Django 5 + DRF com **213 testes** a passar (cobertura 67,4%).
- Cadeia de custódia imutável com hash SHA-256 encadeado (blockchain-like) + *cascade endpoint* para transições atómicas.
- 18 tipos taxonómicos de evidência digital com sub-componentes (parent_evidence) e validação anti-ciclos.
- Frontend HTML/CSS/JS vanilla, mobile-first + **modo tabela densa em desktop** (PR #1+#2) com multi-select e CSV export streaming (cap 10k).
- Mapa Leaflet/OpenStreetMap; PDF export ReportLab; **demo seed** (`manage.py seed_demo`) com 5 ocorrências PT realistas e fotos placeholder.
- HTTPS A+ no SSL Labs, HSTS preload submetido, Mozilla Observatory A+, CSP nível 3 com nonce por request.
- Auditorias completas (segurança 2026-04-16, design 2026-04-18, taxonomia 2026-04-19, *sweep* UX 2026-05-02, redesign *dashboard*+*custody timeline* 2026-05-03).

---

## Funcionalidades implementadas

### Modelo de dados forense
- `User` (perfis **AGENT** / **EXPERT**, badge_number, phone)
- `Occurrence` — caso/cena de crime (NUIPC, GPS, address, agent)
- `Evidence` — item apreendido com taxonomia de **18 tipos** (`MOBILE_DEVICE`, `COMPUTER`, `STORAGE_MEDIA`, `GAMING_CONSOLE`, `GPS_TRACKER`, `IOT_DEVICE`, `NETWORKING`, `BIOMETRIC`, `WEARABLE`, `VEHICLE_INFO`, `MEDIA_RECORDER`, `OPTICAL_DISC`, `PRINTED_DOCUMENT`, `CRYPTO_HW`, `LICENSE_KEY`, `CLOUD_ACCOUNT`, `EMAIL_ACCOUNT`, `OTHER`) e hierarquia de **sub_components** (parent_evidence)
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

### Testes (213 a passar · cobertura 67,4%)
| Suite | Casos | Cobertura |
|---|---|---|
| `tests.py` | Modelos | User, Occurrence, Evidence, DigitalDevice, ChainOfCustody |
| `tests_api.py` | API | auth, CRUD, IDOR, imutabilidade, transições, validação, lookup, stats, throttle |
| `tests_frontend.py` | Frontend | views, templates, redirect, conteúdo HTML, JWT cookie |
| `tests_pdf.py` | PDF export | geração, sanitização, content-type, 404, com/sem dispositivos |
| `tests_new_features.py` | Cascade + CSV | cascade custody, CSV streaming, audit log |
| `tests_table_mode.py` | Modo tabela densa | DataTable, multi-select, sort, paginação |
| `tests_factories.py` | Helpers | factory-boy fixtures partilhadas |

Cobertura por módulo: modelos 78,9% · views 75,1% · pdf_export 86,7%.

```bash
cd src/backend
../../.venv/Scripts/python.exe -m pytest -q
# 213 passed
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
pip install -r src/backend/requirements.txt
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
python -m pytest -q                   # 169 testes
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

## Referências

- Casey, E. (2011). *Digital Evidence and Computer Crime* (3rd ed.). Academic Press.
- ACPO (2012). *Good Practice Guide for Digital Evidence*.
- ISO/IEC 27037:2012 — Guidelines for identification, collection, acquisition and preservation of digital evidence.
- NIST SP 800-86 (2006). *Guide to Integrating Forensic Techniques into Incident Response*.
- OWASP ASVS v4 — Application Security Verification Standard.
- Pestana, P. D. (Projecto #38 — LEI 2025/26). *Plataforma Modular de Captura e Preservação de Evidência Digital para OSINT*. Universidade Aberta.

---

## Uso de IA generativa

O desenvolvimento foi assistido por modelos de IA generativa (Claude, principalmente) em modo *pair programming*: brainstorming arquitectural, geração de boilerplate, escrita inicial de testes, revisão de segurança. Todo o código foi compreendido, validado e adaptado pelo autor antes de entrar no repositório (regra inviolável definida em `INSTRUCOES_GLOBAIS.md`). Ferramentas e referências serão listadas na secção de Referências do relatório final.

---

*Última actualização: 3 mai 2026 · Sem. 7 (28 abr - 4 mai) · 213 testes a passar · cobertura 67,4%*
