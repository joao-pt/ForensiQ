# ADR-0004: Arquitectura do Frontend — HTML/CSS/JS Vanilla com Django Templates

## Status
Accepted

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
