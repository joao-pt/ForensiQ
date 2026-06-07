# Código-fonte

Organizar o código-fonte segundo a arquitectura documentada em `docs/architecture/`.

## Estrutura sugerida

A organização das pastas reflecte a arquitectura documentada no C4 (`docs/architecture/`) — quem leia o C4 deve conseguir encontrar o código correspondente a cada contentor sem esforço.

```
src/
  backend/                   ← contentores "API" e "Web" do C4 (Django)
    manage.py
    forensiq_project/        ← projecto Django (settings, urls, WSGI/ASGI)
    core/                    ← app principal
      models.py              ← modelo de dados
      views.py               ← endpoints da API (DRF)
      serializers.py         ← serialização da API
      frontend_views.py      ← vistas server-rendered (HTMX)
  frontend/                  ← contentor "Web App" do C4
    templates/               ← templates Django
    static/                  ← CSS e JS
```

## Notas

- Incluir um `.env.example` com as variáveis de ambiente necessárias (sem valores reais).
- Não incluir no repositório: ficheiros `.env`, credenciais, chaves de API, dados reais de utilizadores.
- Usar `.gitignore` adequado à stack — [gitignore.io](https://gitignore.io) gera automaticamente.
