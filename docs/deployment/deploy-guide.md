# ForensiQ — Guia de Deploy

> Documentação operacional para deploy, manutenção e troubleshooting da aplicação ForensiQ em produção.

## Arquitectura de produção

```
Browser ──HTTPS──► forensiq.pt (Fly.io, Frankfurt)
                       │
                       ▼
              Django + Gunicorn
              WhiteNoise (estáticos)
                       │
                   SSL/TLS
                       │
                       ▼
              PostgreSQL (Neon.tech, Frankfurt)
```

| Componente | Serviço | Região | Custo |
|------------|---------|--------|-------|
| Aplicação Django | Fly.io | Frankfurt (fra) | ~2$/mês |
| IPv4 dedicado | Fly.io | Global | 2$/mês |
| Base de dados PostgreSQL | Neon.tech | Frankfurt (eu-central-1) | Free tier |
| Domínio forensiq.pt | dominios.pt | — | Renovação anual |
| Certificado HTTPS | Let's Encrypt (via Fly.io) | — | Grátis |

## Pré-requisitos

- [Fly CLI](https://fly.io/docs/flyctl/install/) instalado (`fly version` para confirmar)
- Conta Fly.io autenticada (`fly auth login`)
- Acesso ao repositório ForensiQ
- Variáveis de ambiente: `DATABASE_URL`, `SECRET_KEY`

## Deploy — operação normal

Após alterar código, na pasta `ForensiQ/`:

```bash
# 1. Deploy (build + release)
fly deploy

# 2. Se houver alterações nos modelos (novas migrations)
fly ssh console -C "cd backend && python manage.py migrate"

# 3. Verificar que está online
fly status
```

O Fly.io faz automaticamente:
- Build do Dockerfile (multi-stage)
- collectstatic (WhiteNoise)
- Substituição da versão anterior (zero-downtime)

## Gestão de secrets

As credenciais **nunca** entram no repositório. São definidas como secrets no Fly.io:

```bash
# Definir secrets (primeira vez ou alteração)
fly secrets set DATABASE_URL="postgresql://user:pass@host:5432/db?sslmode=require"
fly secrets set SECRET_KEY="a-tua-chave-secreta"

# Listar secrets (mostra nomes, não valores)
fly secrets list

# Remover um secret
fly secrets unset NOME_DO_SECRET
```

Após alterar secrets, o Fly.io faz redeploy automático.

## DNS e domínio

O domínio `forensiq.pt` está registado em dominios.pt. DNS gerido em: **Extras → Gestão de DNS → Gerir**.

### Registos DNS configurados

| Tipo | Nome | Valor |
|------|------|-------|
| A | forensiq.pt | 168.220.82.90 |
| AAAA | forensiq.pt | 2a09:8280:1::ec:828c:0 |
| A | www.forensiq.pt | 168.220.82.90 |
| AAAA | www.forensiq.pt | 2a09:8280:1::ec:828c:0 |

### Certificados HTTPS

```bash
# Verificar estado dos certificados
fly certs check forensiq.pt
fly certs check www.forensiq.pt

# Adicionar novo certificado (se necessário)
fly certs add forensiq.pt
```

Os certificados Let's Encrypt são renovados automaticamente pelo Fly.io.

## Monitorização e logs

```bash
# Logs em tempo real
fly logs

# Estado da aplicação
fly status

# Lista de máquinas (VMs)
fly machine list

# Métricas
fly dashboard
```

## Rollback

Se um deploy introduzir um problema:

```bash
# Ver releases anteriores
fly releases

# Reverter para a versão anterior
fly releases rollback
```

## Troubleshooting

### A aplicação não arranca

```bash
# Ver logs de arranque
fly logs

# Abrir consola SSH para depuração
fly ssh console
cd backend
python manage.py check
python manage.py showmigrations
```

### Erro 502 / Bad Gateway

Normalmente indica que o Gunicorn não arrancou:
- Verificar se `DATABASE_URL` está definido (`fly secrets list`)
- Verificar logs (`fly logs`)
- Testar localmente com Docker: `docker build -t forensiq . && docker run -p 8000:8000 forensiq`

### Cold start lento (~5-10s)

Comportamento normal quando `min_machines_running = 0` (a VM desliga após inactividade). Para eliminar:
- Alterar `min_machines_running = 1` no `fly.toml` (custo permanente)

### Domínio não resolve

1. Verificar registos DNS: `nslookup forensiq.pt`
2. Verificar certificados: `fly certs check forensiq.pt`
3. Propagação DNS pode demorar até 1 hora após alteração

## Ficheiros de configuração

| Ficheiro | Localização | Função |
|----------|-------------|--------|
| `Dockerfile` | `ForensiQ/Dockerfile` | Build multi-stage (builder + runtime), user não-root |
| `fly.toml` | `ForensiQ/fly.toml` | Configuração Fly.io (região, VM, auto-stop) |
| `.dockerignore` | `ForensiQ/.dockerignore` | Exclui .env, _cowork/, docs do container |
| `settings.py` | `src/backend/forensiq_project/settings.py` | WhiteNoise, segurança prod (HSTS, SSL) |
| `requirements.txt` | `src/backend/requirements.txt` | gunicorn + whitenoise para produção |

## Segurança em produção

O `settings.py` activa automaticamente quando `DEBUG=False`:
- **HSTS:** 1 ano, incluindo subdomínios, preload
- **SSL redirect:** Todos os pedidos HTTP redireccionados para HTTPS
- **Cookies secure:** Session e CSRF cookies só via HTTPS
- **Proxy SSL header:** `X-Forwarded-Proto` do Fly.io
- **CORS:** Apenas `forensiq.pt` e `www.forensiq.pt`
- **CSRF trusted origins:** Apenas `forensiq.pt` e `www.forensiq.pt`
- **Container:** Corre como utilizador `forensiq` (não-root)
