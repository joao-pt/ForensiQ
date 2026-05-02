# ForensiQ — Login page — Créditos e linhagem de design

**Ficheiros cobertos por este documento:**
- `src/frontend/templates/login.html`
- `src/frontend/static/css/pages/login.css`
- `src/frontend/static/js/pages/login.js`

**Data:** 2026-04-18
**Autor da integração:** José Rodrigues (TFM — UC 21184, Universidade Aberta)

---

## 1. Declaração de autoria

Todo o código HTML, CSS e JavaScript do ecrã de login foi **escrito de raiz
para o ForensiQ**. Não foi copiado código — em ficheiro ou em fragmento — de
nenhum repositório público. Não existe dívida de licença.

O que existe, e é justo documentar, são **técnicas e convenções visuais de
linhagem pública** que inspiraram partes do desenho. Estão listadas abaixo.

---

## 2. Técnicas de linhagem pública (inspiração, não código)

### 2.1 Constellation / particle network (animação canvas)

O padrão visual de pontos móveis a ligarem-se por segmentos quando próximos
(incluindo ligações realçadas ao cursor) é uma convenção da web desde 2015.

**Referências de origem bem conhecidas:**

| Projeto | Autor | Ano | Licença |
|---|---|---|---|
| [particles.js](https://github.com/VincentGarreau/particles.js) | Vincent Garreau | 2015 | MIT |
| [tsParticles](https://github.com/tsparticles/tsparticles) | Matteo Bruni | 2020 | MIT |

O ForensiQ **não** usa nenhuma destas bibliotecas nem adapta o seu código
(ambas seriam incompatíveis com a CSP estrita do projeto e adicionariam
dependências externas). A implementação em `login.js` (função
`initConstellation`) usa Canvas 2D em vanilla JS com as seguintes
características próprias:

- Controlo próprio do device-pixel-ratio (DPR) para nitidez em monitores HiDPI
- Debounce de redimensionamento com `setTimeout`
- Pausa automática em `visibilitychange` (poupança de CPU/bateria)
- Fallback estático de uma única frame quando `prefers-reduced-motion: reduce`
- Cores alinhadas com os tokens `--lp-*` do design system ForensiQ
- Parâmetros (densidade, raio de cursor, velocidade) calibrados para o
  painel esquerdo do login

**Conclusão:** inspiração pública reconhecida, **implementação original**.

### 2.2 Hopf link (anéis entrelaçados) — SVG mask interlock

O logotipo ForensiQ neste ecrã ("dois anéis genuinamente entrelaçados") usa a
técnica de máscara SVG para criar a ilusão de que um anel passa por trás do
outro. Esta técnica é **padrão da web**, sem autor único atribuível, e é
usada por, entre outros:

- Logotipo da Mastercard
- Anéis olímpicos em renderizações SVG
- Inúmeros tutoriais sobre SVG masking (MDN, CSS-Tricks, etc.)

O nome matemático é **Hopf link** (o mais simples entrelaçamento de dois
círculos no espaço tridimensional).

A implementação em `login.html` (elementos `<svg class="lp-mark">`) foi
desenhada à mão para este projeto, com o recorte posicionado para dar o
entrelaçamento visual correto na zona de sobreposição dos dois círculos.

**Conclusão:** técnica de domínio público, **implementação original**.

### 2.3 Estilo visual "Notion-dark" do formulário

O cartão do formulário (fundo `#111624`, inputs com `1px` de borda ténue,
botão com gradiente subtil, spinner teal) segue o vocabulário visual
popularizado por:

- **Notion** (notion.so) — cartões dark-mode com bordas muito suaves
- **Linear** (linear.app) — botões com highlight luminoso ao hover
- **Vercel** dashboard — paleta `#05070D` / `#0B0F1A` / `#111624`

Não há código copiado nem componentes reutilizados destas plataformas. A
ForensiQ reconstrói o **vocabulário visual** (não os componentes) com os
tokens `--lp-*` locais, adaptados à paleta institucional do projeto
(teal `#2DD4BF`, âmbar `#F59E0B`).

**Conclusão:** vocabulário estético do setor, **implementação original**.

---

## 3. Tipografia

Os ficheiros CSS/HTML referenciam as famílias tipográficas **Inter** e
**JetBrains Mono**, carregadas globalmente em `base.html`:

| Família | Autor | Licença | Onde |
|---|---|---|---|
| [Inter](https://rsms.me/inter/) | Rasmus Andersson (rsms) | SIL Open Font License 1.1 | `--font-sans` |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) | JetBrains s.r.o. | SIL Open Font License 1.1 | `--font-mono` |

Ambas são **livres para uso comercial e privado** sob a licença SIL OFL 1.1.
Não carecem de atribuição obrigatória no produto, mas este documento
reconhece a autoria.

---

## 4. Ícones SVG

Todos os ícones usados no login (olho/ocultar, cadeado, utilizador, escudo,
cartão, Caps Lock, seta do botão) foram **desenhados à mão** em SVG inline,
com estilo geométrico uniforme (linhas `stroke-width: 1.8`, `stroke-linecap:
round`). Não foram importados de nenhum pack de ícones (Heroicons, Feather,
Lucide, etc.).

A semelhança visual com alguns desses packs existe — é inevitável, pois
todos seguem a mesma convenção **"outline / 24×24 viewBox / 1.5–2 px
stroke"**, que é essencialmente um *dialeto* de ícones web com
dezenas de implementações compatíveis.

---

## 5. Dependências externas em runtime

Nenhuma. O login carrega apenas:

- `base.html` (template Django do próprio ForensiQ)
- `toast.js` (script utilitário interno do ForensiQ)
- `login.js` (script interno)
- `login.css` (folha de estilos interna)
- CSS de `main.css` (tokens globais do ForensiQ)

**Zero requests a CDNs externos, zero bibliotecas JavaScript, zero
`<script>` inline (respeita a CSP estrita).**

---

## 6. Para o relatório do TFM

Se o ecrã de login for mencionado no relatório, uma formulação honesta e
juridicamente adequada é:

> *"O ecrã de autenticação foi desenhado e implementado de raiz para o
> ForensiQ. A animação de rede do painel esquerdo inspira-se numa técnica
> bem conhecida da comunidade web (particle network), popularizada pela
> biblioteca* particles.js *de Vincent Garreau (MIT, 2015), mas a
> implementação em Canvas 2D foi escrita especificamente para este projeto
> de forma a respeitar a política de segurança de conteúdo (CSP) estrita e
> evitar dependências externas. O logotipo usa a técnica SVG de máscara
> para representar dois anéis entrelaçados (Hopf link), convenção padrão
> da web sem autoria atribuível. As famílias tipográficas Inter (SIL OFL)
> e JetBrains Mono (SIL OFL) são software livre."*

---

## 7. Histórico deste ficheiro

| Data | Alteração |
|---|---|
| 2026-04-18 | Criação inicial após promoção do preview a login oficial. |
