# Changelog — ForensiQ

Uma entrada por semana, até domingo à noite.

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
