# Changelog — ForensiQ

Uma entrada por semana, até domingo à noite.

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
