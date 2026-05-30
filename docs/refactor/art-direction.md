# ForensiQ — Art Direction v2 (manifesto do refactor)

> Spec resultante de 20 iterações de mockup (V1 → V20).
> Referência canónica: `docs/refactor/mockup-dashboard.html`.
> Ponto de partida para a branch `refactor/art-direction-v2`.

## Premissa

O frontend actual está tecnicamente bem construído (tokens, ADRs, mobile-first
parcial, base.html, login) mas comunica "SaaS startup genérico" (Notion / Linear
/ Vercel) em vez de **ferramenta forense profissional**. O backend mantém-se —
mexe-se só na pele e na disposição da informação. Não é reescrita; é redirecção
de estética e reorganização de layout.

## Estética alvo

**Não:** Notion / Linear / Vercel / Stripe Dashboard.
**Sim:** Bloomberg Terminal, IDE em debug, Cellebrite / Magnet AXIOM, sala de
comando policial.

Características:
- Densidade alta (informação por pixel)
- Restrição cromática (cor é semântica, nunca decorativa)
- Monospace abundante (códigos, hashes, IDs, timestamps)
- Hierarquia por tipografia + densidade (não por tamanho de cards)
- Microinterações de polish, não gimmicks
- Footer técnico (versão / commit / região / latência / uptime / CSP)
- Header de contexto operacional (papel, turno, zona, dispositivo, relógio)

## Tipografia

- **Sans:** IBM Plex Sans 400/500/600/700
  - `font-feature-settings: "zero" 1, "tnum" 1, "ss05" 1`
- **Mono:** IBM Plex Mono 400/500/600/700
  - `font-feature-settings: "zero" 1, "tnum" 1, "ss01" 1, "ss02" 1, "ss03" 1`
  - Slashed zero (`0`) obrigatório — assinatura terminal/forense
  - Tabular numbers obrigatórios em colunas

Removido: Inter + JetBrains Mono (Vercel default).

## Paleta

Mantém os tokens do `main.css` real, com **um override de accent**:

```css
:root, [data-theme="dark"] {
  --accent: #F6AD55;        /* warm forensic, Bloomberg-adjacent */
  --accent-hover: #FBD38D;
  --accent-tint: rgba(246, 173, 85, 0.14);
}
[data-theme="light"] {
  --accent: #B45309;        /* amber-700 escurecido (5.8:1 sobre #FAFAF9) */
  --accent-hover: #92400E;
  --accent-tint: rgba(180, 83, 9, 0.10);
}
```

Removido: accent teal `#2DD4BF` (Vercel default).
Mantido: `--state-*` (7 estados forenses) mas **só usados onde classificam de
facto** (listas, badges, timelines) — **não** como decoração na cadeia do hero.

## Regra de cor (separação semântica)

- **Cor classifica:** P1-P4 (prioridade), estados de log (hash / create / state
  / alert / pdf), accent (seleccionado / CTA), delta (verde sobe / vermelho desce)
- **Cor não decora:** estado da cadeia no hero **não usa cor por estado** — é
  informacional, não classificatório.

## Layout: three-pane com painel push

Inspirado em `digital.forensiq.pt` (Starlight). Padrão Linear / VS Code /
Cellebrite.

```
┌──────────────────────────────────────────────────────────────────────┐
│ app-top (sticky)  AGENTE · J. Rodrigues · turno · zona · clock       │
├──────────┬──────────────────────────────────────┬────────────────────┤
│ Sidebar  │  Main (page)                         │ Painel direito     │
│ (240px)  │                                      │ (push, 3 estados)  │
│          │  ┌──────────────────────────────────┐│  ─ closed          │
│ PRINCIPAL│  │ Hero — 3 cols, altura 400px      ││  ─ minimized 44px  │
│  Painel  │  │ ┌─────┬─────────┬────────────┐  ││  ─ open 360px      │
│  Ocor.   │  │ │Cust.│ Mapa    │ Ilhas + CTA│  ││                    │
│  ...     │  │ │vert.│ continen│            │  ││  EMPURRA conteúdo  │
│ LAB      │  │ │     │ tal     │  Madeira   │  ││  (não overlay)     │
│  Intake  │  │ │ tile│         │  Açores    │  ││                    │
│  ...     │  │ │ tile│         │  [Nova ⌘N] │  ││  Em mobile:        │
│ ANÁLISE  │  │ │ ... │ colorbar│            │  ││  overlay 100vw     │
│ SISTEMA  │  │ └─────┴─────────┴────────────┘  ││                    │
│          │  │ Tabela ocorrências (densa)       ││                    │
│          │  │ Feed actividade (log)            ││                    │
├──────────┴──┴──────────────────────────────────┴┴────────────────────┤
│ app-bottom · v0.2.0-rc.1 · 448 testes · fly fra · 37ms · uptime …    │
└──────────────────────────────────────────────────────────────────────┘
```

### Sidebar esquerda (240px)
- 4 grupos: Principal, Laboratório, Análise, Sistema
- Item activo: bg `--accent-tint` + border-left 3px `--accent`
- Atalhos `Ctrl+N` (Windows) / `⌘+N` (Mac) — JS detecta plataforma
- Badges de contagem opcionais (`42`, `378`)
- Em mobile: oculta. Em produção: drawer com hamburger.

### Painel direito — 3 estados (push, não overlay)
- **closed:** `display: none` (não ocupa espaço)
- **minimized:** 44px com 2 botões verticais (`>` expandir, `X` fechar)
- **open:** 360px com header (`─` `X`) + conteúdo
- Em desktop ≥1024: empurra o conteúdo principal (push)
- Em mobile: fixed overlay fullscreen
- `Esc` fecha sempre
- `Leaflet.invalidateSize()` chamado em cada transição

### Hero (3 colunas, altura comum 400px)
- **Coluna 1 (220px):** Estado da cadeia · 24h
  - Header compacto (título + meta `50 activos · +3 ▲ −1 ▼ · há Xs`)
  - 7 tiles distribuídos verticalmente (`flex: 1`)
  - **Sem cor por estado** (neutralizado V19)
  - Layout interno: `[num] [LABEL mono UPPER] [delta]` / sparkline largura 100%
  - Deltas mantêm verde/vermelho (tendência)
- **Coluna 2 (1fr):** Mapa continental + colorbar
  - Leaflet com tiles CartoDB (Voyager light / Dark Matter dark)
  - Auto-switch quando tema muda (MutationObserver em `data-theme`)
  - Bounds Portugal continental `[[36.95, -9.55], [42.15, -6.18]]`
  - Colorbar abaixo (não sobre): `menor prioridade ━━━━ maior prioridade`
- **Coluna 3 (300px):** Insets + CTA
  - Madeira `[[32.40, -17.40], [33.10, -16.50]]` (não-arrastável)
  - Açores `[[36.85, -31.40], [39.85, -24.70]]` (não-arrastável)
  - Label "Madeira" / "Açores" no **rodapé** (não topo, evita conflict com popup)
  - CTA "Nova ocorrência" (Ctrl+N) abaixo dos insets

### Mapa: SEMPRE panorâmico
- O mapa hero **nunca muda de modo** — sempre todas as ocorrências.
- O mini-mapa do painel direito é o que muda (toggle Local / Cadeia).

## Mini-mapa do painel direito (2 modos)

- **Local** (default ao abrir o painel): pin único da ocorrência
- **Cadeia** (auto quando se clica num item EV): polyline tracejada amber +
  pins coloridos por estado em cada vértice + tooltip
  "1. Apreendida · 09:14 · jrodrigues · ±8m"
- Toggle por baixo do mini-mapa: 2 botões "Local" / "Cadeia"

## Feature distintiva: cadeia geo-rastreável

**Implicação no modelo:**

```python
# core/models.py — ChainOfCustody
gps_lat = DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
gps_lng = DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
gps_accuracy_m = PositiveIntegerField(null=True, blank=True)
```

**Captura:** `navigator.geolocation.getCurrentPosition()` ao submeter
transição. Permissão pedida ao utilizador. Fallback: campo manual ou null.

**Privacidade:** AGENT → arredondar a 3 decimais (~110m); PERITO em lab →
4 decimais (~11m). Configurável.

**Auditoria espacial:** `±50m` num lab = red flag visual.

**ADR a criar:** `ADR-0013-gps-em-cadeia-de-custodia.md`.

## Cabeçalho (app-top)

- Brand (logo SVG)
- Chips: AGENTE / J. Rodrigues / Turno / Zona / Dispositivo
- Spacer
- Hora + relógio em tempo real (`:` pisca cada segundo)
- Botão `Ctrl+K comandos`
- Botão tema (sol/lua)

## Rodapé técnico (app-bottom)

- Dot pulsante online
- `v0.2.0-rc.1` (versão)
- `448 testes verdes`
- `commit dc95608`
- `fly fra/784415`
- `api p50 37ms`
- `db neon-eu`
- `uptime 14d 03h`
- `CSP strict`

Cada métrica com tooltip via Popover API explicando o significado.

## Acessibilidade

- `:focus-visible` em todos os interactivos (outline accent 2px)
- `prefers-reduced-motion`: suprime pulse / count-up / blink / fresh-in
- Tabela com `role="grid"`, `role="row"`, `role="gridcell"`, `aria-selected`,
  navegação ↑/↓/Enter/Space
- `--text-subtle` calibrado para passar WCAG AA (#828790 light)
- Tooltips ricos via Popover API nativa (substitui `title=""` que tem latência
  1.5s e não funciona em touch/keyboard)

## Mobile-first (a sério)

Decisão: **1 codebase web responsive mobile-first + PWA básica**.
Não fazer 2 apps web separadas (antipattern).

Hoje o `main.css` tem 111 media queries mas usa `max-width` (desktop-first).
Reescrever para `min-width` (mobile-first), mantendo a estrutura.

PWA: adicionar `manifest.json` + service worker mínimo. Instalável como app no
telemóvel, funciona offline para vistas chave.

## Decisões de produto associadas

- **Remover** export CSV (endpoint + UI + testes)
- **Reformular** PDF de transporte (conteúdo + layout) — sessão dedicada
- **Consolidar nomenclatura**: "evidência" em todo o lado, deprecar
  `DigitalDevice` (legacy)
- **Marcar como v2**: `/stats/`, `/investigation_report` (fora de âmbito v1)

## Próximos passos (implementação real)

1. Branch `refactor/art-direction-v2` a partir de `main` (clean)
2. Aplicar tokens primeiro:
   - Trocar Inter/JetBrains Mono → IBM Plex Sans/Mono
   - Trocar accent teal → amber
   - Activar `font-feature-settings` global
3. Aplicar layout three-pane no `base.html`:
   - Sidebar esquerda como parcial
   - Painel direito como parcial (3 estados via JS)
4. Aplicar hero ao `dashboard.html` (esta página primeiro)
5. Replicar para outras páginas (ocorrências, evidências, custódia, intake)
6. Adicionar mapa real (Leaflet) ao painel direito + hero
7. Adicionar campos GPS ao `ChainOfCustody` + migration + ADR-0013
8. Remover CSV export + testes
9. Mobile-first rewrite do `main.css` (min-width em vez de max-width)
10. PWA básica (manifest + service worker)

Cada passo = 1-3 commits PT-PT em cadência diária.

---

**Mockup canónico:** `docs/refactor/mockup-dashboard.html` (V20).
**Defesa académica:** primeira semana de Julho 2026.
**Janela de execução:** ~5 semanas.
