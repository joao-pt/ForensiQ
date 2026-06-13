# ForensiQ — Login page — Créditos e linhagem de design

**Ficheiros cobertos por este documento:**
- `src/frontend/templates/login.html`
- `src/frontend/static/css/pages/login.css`
- `src/frontend/static/js/pages/login.js`

**Data:** 2026-04-18
**Autor da integração:** João M. M. Rodrigues (Projeto — UC 21184, Licenciatura em Engenharia Informática, Universidade Aberta)

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
- Cor de realce ao cursor alinhada com o token `--accent` (âmbar
  `#F6AD55`), lido em runtime via `getComputedStyle` (`resolveAccentRgbPrefix`),
  com fallback `rgba(246,173,85)`; nós e ligações em repouso num azul-acinzentado
  discreto. Não usa tokens `--lp-*` (removidos no refactor v2)
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

### 2.3 Estilo visual do formulário (primitivas globais)

O cartão do formulário reutiliza as primitivas globais do design system
(`.card`, `.form-input`, `.btn-primary`) com os tokens v2: superfície
`--surface` (`#181B21` no tema noite), realce âmbar `--accent` (`#F6AD55`) e
bordas ténues. Não há um vocabulário próprio do login — o ecrã herda o mesmo
tratamento visual do resto da aplicação.

A linguagem "Notion-dark" / Linear / Vercel que servira a v1 (paleta escura
arroxeada, realce teal) foi abandonada por comunicar mal o domínio: o produto
é uma ferramenta forense, não um SaaS genérico. A art direction v2 segue uma
densidade de instrumento profissional (referências Bloomberg/Cellebrite), não
o registo de dashboard de produto.

**Conclusão:** o login não traz estética emprestada — assenta nas primitivas
e tokens globais do ForensiQ.

---

## 3. Tipografia

Os ficheiros CSS/HTML referenciam as famílias tipográficas **IBM Plex Sans**
(interface, `--font-sans`) e **IBM Plex Mono** (hashes, IDs, timestamps e
coordenadas, `--font-mono`), carregadas globalmente em `base.html`:

| Família | Autor | Licença | Onde |
|---|---|---|---|
| [IBM Plex Sans](https://www.ibm.com/plex/) | Mike Abbink / IBM | SIL Open Font License 1.1 | `--font-sans` |
| [IBM Plex Mono](https://www.ibm.com/plex/) | Mike Abbink / IBM | SIL Open Font License 1.1 | `--font-mono` |

Ambas são **livres para uso comercial e privado** sob a licença SIL OFL 1.1.
São servidas localmente (self-hosting) em `css/fonts.css` — `woff2`, subset
latino — sem recurso a Google Fonts ou a qualquer CDN, o que evita fugas do IP
do utilizador e cumpre a CSP estrita do projeto. Não carecem de atribuição
obrigatória no produto, mas este documento reconhece a autoria.

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
- `css/fonts.css` (IBM Plex self-hosted)
- `css/main.css` (tokens globais do ForensiQ)
- `css/components/app-shell.css` (casca da aplicação)
- `css/pages/login.css` (estilos do login)
- os scripts internos `config.js`, `auth.js`, `toast.js` e `login.js`

**Zero requests a CDNs externos, zero bibliotecas JavaScript de terceiros,
zero `<script>` inline (respeita a CSP estrita).**

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
> da web sem autoria atribuível. As famílias tipográficas IBM Plex Sans e
> IBM Plex Mono (IBM, SIL OFL 1.1) são software livre e estão alojadas
> localmente (self-hosting), eliminando pedidos a CDNs externos."*

---

## 7. Histórico deste ficheiro

| Data | Alteração |
|---|---|
| 2026-04-18 | Criação inicial após promoção do preview a login oficial. |
| 2026-05 | Atualização para o refactor de art direction v2: login unificado com o design system global (IBM Plex Sans/Mono, accent âmbar, tokens de `main.css`). Removidos os créditos a Inter/JetBrains Mono e à paleta Notion-dark/Vercel, que descreviam a v1. |
