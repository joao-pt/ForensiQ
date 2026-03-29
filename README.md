# ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders

> Digitalizar e padronizar a recolha, registo e cadeia de custódia de prova digital — do terreno ao laboratório.

**Estudante:** João Rodrigues · 2203474
**Orientador:** Professor Pedro Duarte Pestana
**UC:** 21184 — Projecto de Engenharia Informática · Universidade Aberta · 2025/26
**Repositório:** https://github.com/joao-pt/ForensiQ
**Produção:** https://forensiq.pt

---

## Estado actual

🟡 **Amarelo** — Fase 1 (Proposta Inicial) aprovada. Backend funcional (modelos, API REST, 45 testes), frontend em desenvolvimento. Aplicação deployed em produção.

---

## O que está implementado

### Backend (Django + DRF)
- [x] Django 5.2 com projecto `forensiq_project` e app `core`
- [x] Modelo User customizado (AbstractUser, perfis AGENT/EXPERT, badge_number)
- [x] Modelos: Occurrence, Evidence, DigitalDevice, ChainOfCustody
- [x] Hash SHA-256 automático em Evidence (ISO/IEC 27037)
- [x] Hashes encadeados (blockchain-like) em ChainOfCustody
- [x] Máquina de estados para cadeia de custódia (validação de transições)
- [x] ChainOfCustody append-only (bloqueio de update/delete)
- [x] PostgreSQL (Neon.tech, Frankfurt) via dj-database-url + .env
- [x] API REST com 5 endpoints + acções personalizadas (10+ rotas)
- [x] Serializers para todas as entidades
- [x] Permissões por perfil (IsAgent, IsExpert, IsOwnerOrReadOnly)
- [x] JWT authentication (SimpleJWT: login, refresh, verify)
- [x] Swagger UI via drf-spectacular (/api/docs/)
- [x] Django Admin configurado
- [x] 45 testes (12 modelos + 21 API + 12 frontend) — todos passam

### Frontend (HTML/CSS/JS vanilla)
- [x] CSS mobile-first com touch targets de 48px (WCAG 2.1 AA)
- [x] Página de login com autenticação JWT
- [x] Dashboard com estatísticas e acções rápidas por perfil
- [x] Módulos JS: auth.js (JWT), api.js (cliente HTTP), config.js, toast.js
- [ ] Formulário de registo de ocorrência (em curso)
- [ ] Formulário de registo de evidência com foto + GPS
- [ ] Timeline de cadeia de custódia
- [ ] Mapa com Leaflet.js

### Infraestrutura
- [x] Deploy em produção (Fly.io, Frankfurt) — `forensiq.pt`
- [x] HTTPS com certificado Let's Encrypt (RSA + ECDSA)
- [x] Dockerfile multi-stage (python:3.12-slim, user não-root, Gunicorn)
- [x] WhiteNoise para servir ficheiros estáticos
- [x] Segurança em produção (HSTS, SSL redirect, secure cookies)
- [x] DNS com IPv4/IPv6 dedicados

---

## O que está pendente

- [ ] Formulários de criação (ocorrência, evidência, dispositivo)
- [ ] Timeline visual da cadeia de custódia
- [ ] Integração Leaflet.js para mapas / geolocalização
- [ ] Exportação de relatório em PDF (ReportLab/WeasyPrint)
- [ ] Testes de integração com BD Neon.tech
- [ ] GitHub Actions CI
- [ ] Testes Postman/Newman para API

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

*Última actualização: 29 mar 2026 · Sem. 2*
