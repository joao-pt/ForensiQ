# ADR-0005: Deployment em Fly.io com Base de Dados Separada (Neon.tech)

## Status
Accepted

## Data
2026-03-29

## Context
O ForensiQ precisa de um ambiente de produção acessível via `forensiq.pt`, com HTTPS, para:
- Demonstrar a aplicação ao orientador e ao júri em ambiente real
- Testar a API e o frontend mobile em condições de produção
- Validar a integração com a base de dados PostgreSQL remota (Neon.tech, Frankfurt)

Requisitos de infraestrutura:
- Região europeia (Frankfurt), próxima da BD Neon.tech para latência mínima
- Suporte a domínio personalizado (`forensiq.pt`) com certificado HTTPS
- Custo reduzido (projecto académico, orçamento ≤ 5€/mês)
- Deploy simples a partir do repositório GitHub
- Segurança: utilizador não-root, secrets separados do código

## Decision

### Plataforma de hosting
**Fly.io** com região Frankfurt (fra), a única plataforma PaaS avaliada com data center em Frankfurt.

### Arquitectura de produção
1. **Aplicação Django** no Fly.io (Frankfurt) — VM shared-cpu-1x, 256MB RAM
2. **Base de dados PostgreSQL** no Neon.tech (Frankfurt) — mantida separada, não migrada
3. **Ficheiros estáticos** servidos via WhiteNoise (sem CDN externo no MVP)
4. **Domínio** `forensiq.pt` com DNS gerido no dominios.pt, registos A/AAAA a apontar para IPs dedicados do Fly.io
5. **HTTPS** via Let's Encrypt, gerido automaticamente pelo Fly.io

### Configuração de deploy
- **Dockerfile multi-stage:** builder (compilação psycopg2, Pillow) + runtime (python:3.12-slim, user não-root)
- **Gunicorn:** 2 workers, timeout 120s, logs para stdout/stderr
- **fly.toml:** auto-stop após inactividade, auto-start com pedidos HTTP, min_machines=0
- **Secrets:** DATABASE_URL e SECRET_KEY definidos via `fly secrets set` (nunca no código)
- **Segurança em produção (settings.py):** HSTS (1 ano), SSL redirect, secure cookies, CSRF trusted origins

### DNS e certificados
- IPv4 dedicado: 168.220.82.90 (2$/mês)
- IPv6 dedicado: 2a09:8280:1::ec:828c:0
- Registos A + AAAA para `forensiq.pt` e `www.forensiq.pt`
- Certificado Let's Encrypt (RSA + ECDSA) emitido e activo

### Workflow de deploy
```bash
# Actualizar aplicação
fly deploy

# Aplicar migrações de base de dados
fly ssh console -C "cd backend && python manage.py migrate"

# Rollback se necessário
fly releases rollback
```

## Alternatives Considered

### Render.com
- **Prós:** Tier gratuito com domínio custom, deploy automático via GitHub
- **Contras:** Sem região Frankfurt (latência elevada para BD Neon.tech Frankfurt), serviço gratuito adormece após 15 min com cold start de ~30s
- **Custo:** Grátis (free) ou 7$/mês (Starter)

### Railway.app
- **Prós:** Auto-detecção Django, $5 créditos incluídos no plano Hobby
- **Contras:** Região europeia apenas em Amesterdão (não Frankfurt), custo base 1$/mês + consumo
- **Custo:** ~5-6$/mês

### PythonAnywhere
- **Prós:** Focado em Python/Django, fácil de usar
- **Contras:** Whitelist de ligações externas (Neon.tech possivelmente bloqueado no plano gratuito), sem Frankfurt
- **Custo:** Grátis ou 5$/mês (Hacker)

## Consequences

### Positivas
- Latência mínima entre app e BD (ambos em Frankfurt)
- Auto-stop/start reduz custos quando não há tráfego
- Deploy com um único comando (`fly deploy`)
- HTTPS automático, sem configuração manual de certificados
- Utilizador não-root no container (segurança)
- WhiteNoise elimina necessidade de Nginx/CDN para estáticos no MVP
- Separação app/BD permite mover cada componente independentemente

### Negativas
- IPv4 dedicado obrigatório para DNS (2$/mês extra)
- Cold start de ~5-10s quando a VM está parada (aceitável para projecto académico)
- Fly.io Postgres não é usado — se Neon.tech alterar o free tier, é necessário reavaliar
- WhiteNoise não é ideal para grande volume de estáticos (CDN seria melhor em produção real)
