# ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders

> Digitalizar e padronizar a recolha, registo e cadeia de custódia de prova digital — do terreno ao laboratório.

**Estudante:** João Rodrigues · 2203474
**Orientador:** Professor Pedro Duarte Pestana
**UC:** 21184 — Projecto de Engenharia Informática · Universidade Aberta · 2025/26
**Repositório:** https://github.com/joao-pt/ForensiQ
**Produção:** https://forensiq.pt

---

## Estado actual

🟢 **Verde** — Fase 2 em curso. Backend funcional e reforçado com segurança (CSP, HSTS, rate limiting, IDOR protection, immutability triggers, select_for_update). API REST completa com 10+ rotas. Frontend completo com timeline de custódia e mapa Leaflet. 142 testes a passar. Código review concluída (11 abr). Aplicação deployed em produção.

---

## O que está implementado

### Backend (Django + DRF)
- [x] Django 5.2 com projecto `forensiq_project` e app `core`
- [x] Modelo User customizado (AbstractUser, perfis AGENT/EXPERT, badge_number)
- [x] Modelos: Occurrence, Evidence, DigitalDevice, ChainOfCustody, AuditLog
- [x] Hash SHA-256 automático em Evidence (ISO/IEC 27037)
- [x] Hashes encadeados (blockchain-like) em ChainOfCustody
- [x] Máquina de estados para cadeia de custódia (validação de transições)
- [x] ChainOfCustody append-only (bloqueio de update/delete)
- [x] PostgreSQL (Neon.tech, Frankfurt) via dj-database-url + .env
- [x] API REST com 5 endpoints + acções personalizadas (10+ rotas)
- [x] Serializers para todas as entidades
- [x] Permissões por perfil (IsAgent, IsExpert, IsAgentOrExpert, IsOwnerOrReadOnly)
- [x] JWT authentication (SimpleJWT: login, refresh, verify)
- [x] Swagger UI via drf-spectacular (/api/docs/)
- [x] Django Admin configurado (com prefixo secreto)
- [x] 142 testes (14 modelos + 69 API + 45 frontend + 14 PDF) — todos passam
- [x] `test_settings.py` — configuração de testes isolada (SQLite em memória)
- [x] Cobertura de testes (backend + frontend)

### Frontend (HTML/CSS/JS vanilla)
- [x] CSS mobile-first com touch targets de 48px (WCAG 2.1 AA)
- [x] Página de login com autenticação JWT
- [x] Dashboard com estatísticas e acções rápidas por perfil
- [x] Módulos JS: auth.js (JWT), api.js (cliente HTTP), config.js, toast.js
- [x] Página de listagem de ocorrências (`/occurrences/`) com pesquisa e paginação
- [x] Formulário de nova ocorrência (`/occurrences/new/`) com GPS automático + reverse geocoding
- [x] Página de listagem de evidências (`/evidences/`) com filtros por tipo
- [x] Formulário de nova evidência (`/evidences/new/`) com captura de foto e GPS
- [x] Timeline visual da cadeia de custódia (`/evidences/<id>/chain_of_custody/`)
- [x] Mapa com Leaflet.js (marcadores de ocorrências)
- [x] Exportação PDF de relatório forense (`/api/evidences/{id}/pdf/`)

### Infraestrutura
- [x] Deploy em produção (Fly.io, Frankfurt) — `forensiq.pt`
- [x] HTTPS com certificado Let's Encrypt (RSA + ECDSA)
- [x] Dockerfile multi-stage (python:3.12-slim, user não-root, Gunicorn)
- [x] WhiteNoise para servir ficheiros estáticos
- [x] Segurança em produção (HSTS, SSL redirect, secure cookies)
- [x] DNS com IPv4/IPv6 dedicados

### Segurança
- [x] **Imutabilidade de prova:** ChainOfCustody append-only, sem UPDATE/DELETE
- [x] **Integridade de metadados:** SHA-256 automático em cada Evidence
- [x] **Cadeia de custódia encadeada:** Hash anterior referenciado (blockchain-like)
- [x] **Autenticação JWT:** SimpleJWT com tokens acessíveis apenas via HTTPS
- [x] **RBAC granular:** Permissões por perfil (Agent, Expert)
- [x] **Proteção IDOR:** Filtro de queryset por utilizador (`get_queryset()`)
- [x] **Rate limiting:** 5 requisições/minuto em endpoints de auth (JWT token, refresh, verify)
- [x] **HSTS:** 1 ano + preload (HTTP Strict-Transport-Security)
- [x] **Content Security Policy (CSP):** default-src 'self'; script-src 'self' cdn.leafletjs.com; img-src 'self' data: https:
- [x] **Race condition:** Lock pessimista (select_for_update) na transição de custódia
- [x] **Admin Django secreto:** Prefixo aleatório via variável de ambiente
- [x] **Auditoria transversal:** AuditLog com correlation_id em cada requisição
- [x] **Logging seguro:** Sem PII em logs (mascarar email, IP anónimo)

### Testes
- [x] **Testes de modelos:** 14 casos (User, Occurrence, Evidence, DigitalDevice, ChainOfCustody)
- [x] **Testes de API:** 69 casos (autenticação, CRUD, permissões, IDOR, imutabilidade, validação de entrada, transições de estado)
- [x] **Testes de frontend:** 45 casos (dashboard, formulários, templates)
- [x] **Testes de PDF:** 14 casos (geração, sanitização, metadados, endpoints)
- [x] **Comando:** `python manage.py test core --settings=forensiq_project.test_settings --verbosity=2`

### Conformidade
- [x] **ISO/IEC 27037:2012** — Integridade de prova digital (SHA-256, cadeia encadeada, append-only logs)
- [x] **ISO/IEC 27001:2022** — Gestão de segurança da informação (RBAC, auditoria, HTTPS, rate limiting)
- [x] **WCAG 2.1 AA** — Acessibilidade (mobile-first, touch targets 48px, contraste, teclas de navegação)

---

## O que está pendente

- [ ] **GitHub Actions CI:** Executar testes automaticamente em cada push
- [ ] **Dashboard de auditoria:** Página para visualizar AuditLog com filtros e pesquisa

---

## Como instalar e correr

```bash
# 1. Clonar o repositório
git clone https://github.com/joao-pt/ForensiQ.git
cd ForensiQ

# 2. Criar virtualenv e instalar dependências
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r src/backend/requirements.txt

# 3. Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com DATABASE_URL, SECRET_KEY, etc.

# 4. Aplicar migrations
cd src/backend
python manage.py migrate

# 5. Criar superutilizador
python manage.py createsuperuser

# 6. Correr o servidor
python manage.py runserver

# 7. Aceder
# Login: http://localhost:8000/login/
# Dashboard: http://localhost:8000/dashboard/
# Swagger UI: http://localhost:8000/api/docs/
# Admin: http://localhost:8000/admin/
```

### Correr testes

```bash
cd src/backend
# Testes isolados (SQLite em memória — sem necessidade de Neon.tech)
python manage.py test core --settings=forensiq_project.test_settings --verbosity=2

# Testes com BD real (requer .env configurado)
python manage.py test core --verbosity=2
```

---

## Decisões de arquitectura principais

| Decisão | Alternativa considerada | Razão da escolha |
|---------|------------------------|-----------------|
| Django + DRF | FastAPI | Estrutura convencional; autenticação built-in; ORM; mais fácil de defender |
| PostgreSQL | SQLite / MongoDB | Integridade referencial; append-only para logs de custódia |
| HTML/CSS/JS vanilla | React / Vue | Mobile-first sem overhead de framework; suficiente para MVP |
| SHA-256 nos metadados | Hash do ficheiro completo | Conforme ISO/IEC 27037; detecta alteração de qualquer campo do registo |
| Django Templates | SPA separado | Deploy simplificado; sem build step; fácil de manter |
| Fly.io (Frankfurt) | Render / Railway | Única plataforma PaaS com região Frankfurt; latência mínima para BD Neon.tech |
| BD separada (Neon.tech) | Fly Postgres | Neon.tech é gerido (backups automáticos); independência entre app e dados |

Decisões detalhadas em `docs/architecture/adr/`.

---

## Referências

- Casey, E. (2011). *Digital Evidence and Computer Crime* (3rd ed.). Academic Press.
- ACPO (2012). *Good Practice Guide for Digital Evidence*.
- ISO/IEC 27037:2012 — Guidelines for identification, collection, acquisition and preservation of digital evidence.
- NIST SP 800-86 (2006). *Guide to Integrating Forensic Techniques into Incident Response*.
- Pestana, P. D. (Projecto #38 — LEI 2025/26). *Plataforma Modular de Captura e Preservação de Evidência Digital para OSINT*. Universidade Aberta.

---

## Documentação Adicional

- **Arquitectura:** `docs/architecture/adr/` — 7 decisões documentadas (DB, estrutura Django, API REST, frontend, deployment, extensibilidade, SRI/Referrer-Policy)
- **Plano de Teste:** `docs/scope/` — scope de testes, changelog de versões
- **Código Review:** `docs/code-review-2026-04-11.md` — análise de segurança completa
- **Guia de Deploy:** `docs/deployment/deploy-guide.md` — procedimento de produção em Fly.io

---

*Última actualização: 13 abr 2026 · Sem. 7*
