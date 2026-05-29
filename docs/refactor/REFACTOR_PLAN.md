# ForensiQ — Refactor Plan (meta-plano)

> Documento-âncora do refactor sério do ForensiQ (Sem.13+).
> Sequência **backend → BD → frontend**, decidida em 2026-05-30
> após reconhecermos que a "stage 1: art direction" (4 commits visuais
> em `refactor/art-direction-v2`) estava a pintar fachada antes de
> arrumar a casa.

## Contexto

- **Projecto:** ForensiQ (UC 21184, Universidade Aberta)
- **Defesa académica:** primeira semana de Julho 2026 (~5 semanas)
- **Branch actual:** `refactor/art-direction-v2` (4 commits visuais,
  448 testes verdes, não merge'd para `main`)
- **Razão do refactor:** O dono descreveu o frontend como "reles" /
  "falso" / "sem alma" e o código como tendo inconsistências sistémicas
  ("não está bem construído"). Pediu refactor total preservando
  histórico GitHub.

## Direcção

A v2 visual estabeleceu **o destino** (pro-tool forense, IBM Plex +
amber, three-pane shell, hero geo). Mas vimos que se o backend mudar
durante o refactor, parte do frontend tem de ser refeito. Logo a
sequência correcta é:

1. **Saber o que está mal** (inventário)
2. **Arrumar o backend e a BD** (refactor + migrations)
3. **Refazer o frontend sobre o backend arrumado** (replicar a casca
   + hero + páginas restantes)

## As 3 fases

### Fase 1 — Inventário

**Output:** `docs/refactor/REFACTOR_MANIFEST.md`

**Método:** Workflow `forensiq-refactor-inventory` orquestra 8+ agentes
`Explore` em paralelo, cada um varrendo uma dimensão distinta do
codebase, mais um agente de *gap analysis* que compara o frontend v2
desejado (mockup V20) com o backend actual.

**Dimensões varridas:**

| # | Dimensão | Âmbito principal |
|---|----------|------------------|
| 1 | Backend — Modelos & BD | `models.py`, `migrations/`, `validators.py`, `admin.py` |
| 2 | Backend — APIs & Serializers | `views.py`, `serializers.py`, `urls.py`, `pagination.py`, throttles |
| 3 | Backend — Services & lógica | `services/`, `pdf_export.py`, `qr_verify.py`, `audit.py`, custody FSM |
| 4 | Backend — Auth, security, observability | `auth.py`, `auth_views.py`, `middleware.py`, CSP, logging |
| 5 | Frontend — JS arquitectura | `static/js/`, IIFE compliance, fetch/auth padrões, contract drift |
| 6 | Frontend — CSS & templates | `static/css/`, `templates/`, mobile-first reality, a11y, tokens |
| 7 | Testes — cobertura & padrões | `core/tests_*.py`, flakes, skipped, duplicação |
| 8 | Docs, CI, ops | `docs/`, `.github/workflows/`, `fly.toml`, `pre-commit`, ADRs vs código |
| 9 | Gap analysis (v2 frontend) | O que falta no backend para suportar mockup V20 + art-direction.md |

Cada agente devolve findings estruturados (schema rígido) com:
`{file, line, category, severity, title, current, desired, blast_radius, dependencies}`.

Síntese final consolida tudo em `REFACTOR_MANIFEST.md` (PT-PT).

**Critério de fecho:** Manifesto em disco + commitado + dono aprovou
âmbito (decisões registadas em §6 do manifesto).

**Não-fazer durante a Fase 1:** Nenhuma alteração de código. Só leitura.

### Fase 2 — Backend & DB migration

**Pré-requisito:** Manifesto aprovado.

**Branch:** Nova `refactor/backend-cleanup` a partir de
`refactor/art-direction-v2`.

**Método:** Trabalho temático em lotes pequenos (1-3 commits por
sessão, cadência diária — coerente com [[feedback_incremental_fixes]]).

**Temas prováveis** (a confirmar pelo manifesto):
- Remover endpoints/módulos mortos (CSV export, `/stats/` legacy se
  decidido, `DigitalDevice` se decidido)
- Normalizar convenções de URLs/serializers/erros
- Adicionar campos GPS ao `ChainOfCustody` + migration + ADR-0013
- Outros campos novos identificados pelo gap analysis
- Limpeza de migrations cumulativas (squash se justificar)
- Testes flakey, skipped, ou duplicados

**Critério de fecho:** Todos os temas executados, 100% testes verdes,
manifesto reconciliado (cada finding marcado como ✅ ou justificado
como adiado).

### Fase 3 — Frontend reinventado

**Pré-requisito:** Fase 2 merge'd para `refactor/art-direction-v2`.

**Branch:** Nova `refactor/frontend-rebuild` a partir de
`refactor/art-direction-v2`.

**Método:** Aplicar a casca + hero geo a TODAS as páginas restantes,
agora encaixando no backend já limpo. Cada página em 1-2 commits.

**Páginas a refazer** (pelo menos):
- `/occurrences/` (lista + filtros + mapa)
- `/occurrences/<id>/` (detalhe)
- `/occurrences/new/` (wizard)
- `/occurrences/<id>/intake/` (recepção)
- `/evidences/` (lista)
- `/evidences/<id>/` (detalhe)
- `/evidences/new/` (wizard)
- `/evidences/<id>/custody/` (timeline)
- `/custodies/` (lista)
- `/reports/` (PDF)
- `/settings/`

**Trabalho adicional:**
- Drawer direito: ligar a clicks na tabela de ocorrências; mostrar
  Local / Cadeia (mini-mapa com toggle)
- Cadeia geo-rastreável: captura `navigator.geolocation` no UI das
  transições; arredondamento por papel
- Mobile-first rewrite do `main.css` (`min-width` em vez de `max-width`)
- PWA básica (`manifest.json` + service worker mínimo)
- Footer técnico: ligar a métricas reais (p50 latency via `/api/health/`,
  uptime, contadores via stats endpoint)

**Critério de fecho:** Todas as páginas com casca + hero geo; mobile
real testado; PWA instalável; 100% testes verdes.

## Restrições inquestionáveis (das memórias)

- **Commits em nome solo `joao-pt`** — zero trailers Claude/AI/Anthropic.
- **PT-PT em tudo** — código, comentários, commits, ADRs, docs.
- **Nunca `--no-verify`** nem force-push para `main`.
- **Pre-commit hooks correm sempre** — corrigir, não bypassar.
- **Imutabilidade forense** — triggers DB + admin readonly + API
  POST-only continuam em vigor; refactor não compromete isto.

## Tools a usar (política — ver memória dedicada)

- `frontend-design` (skill) — sempre em CSS/HTML não-trivial
- `Explore` (subagent) — varreduras de codebase
- `Plan` (subagent) — tarefas com >3 passos
- `Workflow` (com ultracode) — fan-outs paralelos / sínteses
- `neon_tech` (MCP) — introspectar schema antes de migrations
- `Mermaid Chart` (MCP) — diagramas para ADRs
- `general-purpose` (subagent) — review adversarial pré-commit em
  zonas sensíveis (modelos, custódia, hashing, auditoria, migrations)

Tools **ignoradas** (não relevantes): Figma, Supabase, Gmail, Calendar,
Drive, Jotform, Magic Patterns, Superhuman.

**Limitação:** sem Playwright/screenshot — o dono é os olhos do
"isto está bonito ou não".

## Estado actual (snapshot)

- Branch: `refactor/art-direction-v2` @ commit `a202af7`
- 4 commits visuais (docs+tokens+casca+hero) — manter
- Testes: 448 verdes (Django + pytest)
- `docs/refactor/`: `art-direction.md`, `mockup-dashboard.html`,
  `REFACTOR_PLAN.md` (este), `REFACTOR_MANIFEST.md` (será gerado)

## Próximos passos imediatos

1. Lançar workflow `forensiq-refactor-inventory` (a seguir a este commit)
2. Aguardar conclusão (~15-30 min)
3. Escrever `REFACTOR_MANIFEST.md` a partir do output
4. Commitar manifesto na branch
5. Conversa com o dono — decidir âmbito (Fase 2 só arranca após esta
   conversa)

---

> **Para sessões pós-`/compact`:** Ler este ficheiro primeiro,
> depois `REFACTOR_MANIFEST.md`, depois as memórias auto-memory.
> Não avançar para Fase 2 sem aprovação explícita do dono.
