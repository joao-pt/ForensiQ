# ADR-0004: Arquitectura do Frontend — HTML/CSS/JS Vanilla com Django Templates

## Status
Superseded

> **Nota de superseding (Fase 3 — reconstrução do frontend):**
> Esta decisão foi substituída. O frontend deixou de ser uma camada vanilla que consome a API REST via JWT a partir do browser e passou a ser **server-rendered** com **Django Templates + HTMX + Leaflet**, com autenticação por **cookies HttpOnly** servidos pelo Django (ver ADR-0009). A renderização passou a ser feita no servidor (ORM → template), eliminando o *drift* entre o contrato da API e a UI.
>
> Em concreto:
> - A **alternativa 2** considerada abaixo (Django Templates com HTMX), na altura rejeitada por adicionar dependência, foi precisamente a adoptada na reconstrução.
> - A organização "um CSS/JS por página" (`src/frontend/static/css/pages/*` e `src/frontend/static/js/pages/*`) foi descontinuada; subsistem apenas os módulos `login` e `error`. A direcção de arte do novo frontend assenta em IBM Plex Sans/Mono, acento âmbar e densidade de ferramenta forense.
> - A **API DRF** mantém-se, mas para PWA, acesso público (verificação) e mobile — não como camada de consumo do frontend web.
>
> O corpo seguinte preserva-se como registo histórico da decisão original.

## Context
O ForensiQ precisa de uma interface web mobile-first para first responders (agentes) e peritos forenses. Os utilizadores podem estar no terreno (cenas de crime), com luvas, em condições de iluminação adversa, a operar com uma só mão. Não é necessário um SPA complexo — a prioridade é robustez, velocidade de carregamento e usabilidade em condições difíceis.

As alternativas consideradas foram:
1. **React/Vue SPA** — mais flexível, mas overhead de build, bundle size, e complexidade desnecessária para o MVP
2. **Django Templates com HTMX** — interessante, mas adiciona dependência extra e curva de aprendizagem
3. **HTML/CSS/JS vanilla com Django Templates** — simples, sem dependências, fácil de manter e testar

## Decision
Implementar o frontend com HTML5, CSS3 e JavaScript vanilla, servido pelo Django via templates. A autenticação e interacção com dados são feitas inteiramente via API REST (JWT) a partir do frontend.

Estrutura:
```
src/
├── backend/         ← Django (API REST + serve templates)
│   ├── core/
│   └── forensiq_project/
└── frontend/        ← HTML/CSS/JS (sem build step)
    ├── templates/   ← Django templates (.html)
    └── static/      ← CSS, JS, imagens
        ├── css/
        ├── js/
        └── img/
```

Princípios de design:
- **Mobile-first:** CSS escrito para ecrã pequeno primeiro, media queries para tablet/desktop
- **Touch targets:** Mínimo 48px para botões e inputs (WCAG 2.1 AA)
- **Contraste elevado:** Paleta com bom contraste para uso em exteriores
- **Sem build step:** Sem webpack, vite, ou npm — ficheiros JS servidos directamente
- **Módulos JS:** Padrão IIFE/module para evitar poluição do scope global

## Consequences

### Positivas
- Zero dependências de build no frontend
- Fácil de compreender e manter (requisito académico — o João tem de explicar tudo)
- Carregamento rápido — sem bundles pesados
- Compatível com qualquer browser moderno sem transpilação
- Django serve tudo — deploy simplificado

### Negativas
- Sem componentes reutilizáveis (como React) — alguma duplicação de HTML
- Gestão de estado manual (localStorage + variáveis JS)
- Sem type-checking (poderia mitigar com JSDoc)
- Reutilização de UI limitada em comparação com frameworks
