# Execução inicial dos testes E2E — 2026-06-02

Snapshot da primeira execução completa da camada de testes de browser, com os
achados que a exercício revelou. Serve de linha de base para comparação futura.

## Resultado

- **28 testes E2E verdes** (Playwright + axe + orçamentos de rapidez), ≈70 s.
  A acessibilidade é validada no tema **claro E escuro**.
- **0 regressões** na suite existente — verifiquei 55 testes de frontend/CSP
  (`tests_frontend`, `tests_templates_static_refs`, `CSPHeaderTest`) após as
  alterações ao `base.html` e ao comentário do middleware: todos verdes.

## Achados

### F1 — HTMX violava a CSP em todas as páginas *(CORRIGIDO)*
O teste de CSP apanhou violações de "inline style" em ≈9 páginas, todas com o
mesmo hash. Origem: o HTMX **injeta automaticamente um `<style>`** com os estilos
de indicador, sem nonce — bloqueado pela CSP estrita (`style-src 'self'
'nonce-…'`) **em produção**, em todas as páginas com HTMX (dashboard, listas,
detalhes, reports, verificações).

Correção: `<meta name="htmx-config" content='{"includeIndicatorStyles":false}'>`
no `base.html`. É seguro — a app tem indicadores próprios
(`.toolbar__busy.htmx-request` em `forensic.css`, servida por `<link>`), não
depende dos do HTMX. O teste `test_no_csp_violations` confirma 0 violações.

Bónus: o comentário do middleware atribuía a injeção ao **Leaflet**; é falso (o
Leaflet traz a CSS por `<link>`). Corrigi o comentário.

### F2 — Contraste WCAG AA *(CORRIGIDO)*
O axe e o Lighthouse mostraram que o texto secundário esbatido (dicas de campo,
timestamps, contagens, cabeçalhos de tabela) e o âmbar sobre tinta âmbar (chips,
avatar, link de menu ativo) falhavam o rácio WCAG AA (4.5:1) — **12–25 nós por
página**. Importante: os testes correm no **tema claro** por omissão (Chrome
headless usa `prefers-color-scheme: light`); ao testar também o **escuro**
confirmei que ambos falhavam (claro ≈2.5:1, escuro ≈3.9:1).

Correção (tokens de cor, sem mexer na estrutura nem na densidade — mediada por
WCAG + critério de design para manter o IBM Plex/âmbar/escuro):
- **Tema claro:** `--text-muted` #6E6D6A→#5C5A55 (≈6:1) e `--text-subtle`
  #9B9A97→#6B6A64 (≈4.9:1), ambos AA também sobre os fundos tintados; placeholder
  mais legível. A hierarquia mantém-se (muted mais escuro que subtle).
- **Tema escuro:** `--text-subtle` #6E737C→#8A8F98 (≈5.2:1 sobre as superfícies).
- **Âmbar sobre tinta:** token novo `--accent-on-tint` (#92400E no claro = 5.6:1;
  #F6AD55 no escuro), aplicado às chips, ao avatar e ao link de menu ativo.

Como o `.form-hint` usa `--text-subtle`, isto resolve diretamente a dificuldade
de ler **o que inserir nos campos**. O gate de a11y passou a **exigir** contraste
(sem exclusões) e está verde nos dois temas.

### F3 — Dashboard é a página mais pesada / dependências externas *(PARCIAL)*
LCP local de ≈5,3 s no dashboard (vs. 2,7 s no login), dominado por (a) o IBM
Plex carregado via Google Fonts — CSS externo **render-blocking** e fuga de IP,
incoerente com o geocoding já ser server-side por RGPD — e (b) os tiles do mapa
direto do OpenStreetMap. São números de servidor **local** (DEBUG, sem
compressão/CDN), não de produção; sem regressão de layout (CLS 0) nem bloqueio
de JS (TBT 0 ms) em lado nenhum.

**Resolvido (a):** o IBM Plex passou a **self-hosted** (`static/fonts/*.woff2` +
`css/fonts.css`, subset latin, pesos 400/500/600/700, `font-display: swap`).
Removidas as `<link>`/preconnect do Google nos 4 templates e **apertada a CSP**
(`style-src`/`font-src` deixaram de permitir `fonts.googleapis.com`/`gstatic.com`).
Validado: `collectstatic` (manifest) reescreve os `url()` para os ficheiros com
hash; os 28 testes E2E mantêm-se verdes (incl. 0 violações de CSP).

**Em aberto (b):** os tiles do mapa continuam a vir do OSM no cliente (mesma
fuga de IP). Mitigar exige um proxy de tiles server-side ou tiles self-hosted —
item mais pesado, adiado.

## Lighthouse — linha de base (servidor local, não produção)

| Página | Performance | Acessibilidade | Best Practices | FCP | LCP | CLS | TBT |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/login/` | 93 | 100 | 96 | 2,5 s | 2,7 s | 0 | 0 ms |
| `/dashboard/` | 72 | 91 | 96 | 3,7 s | 5,3 s | 0 | 0 ms |
| `/occurrences/` | 82 | 92 | 100 | 3,6 s | 3,7 s | 0 | 0 ms |

> Métricas de laboratório local — úteis como linha de base de regressão, não
> como números de produção. Regenerar com `scripts/run_lighthouse.ps1` (ver
> [README.md](README.md) §3.3).

## Seguimentos em aberto

- **CI:** a suite E2E pode entrar no `.github/workflows/ci.yml` (snippet pronto
  no README §7) — fica à decisão por causa do tempo de build (+≈1 min + browser).
- **Lighthouse autenticado:** a receita está documentada; automatizá-la num
  script único (semear + arrancar + auditar + parar) é possível se valer a pena.
- **F2 (contraste) — revisão visual:** os tokens ficaram mais escuros para
  cumprir AA; vale a pena uma vista de olhos para confirmar que a estética densa
  se mantém conforme pretendido (a norma está cumprida; o ajuste fino é uma questão de preferência).
