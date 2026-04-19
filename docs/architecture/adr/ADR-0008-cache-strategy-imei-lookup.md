# ADR-0008: Estratégia de Cache para Lookups Externos (IMEI, VIN)

## Status

Accepted

## Data

2026-04-19

## Context

O ForensiQ passou a integrar duas APIs externas pagas para enriquecimento de prova digital:

1. **imeidb.xyz** — consulta de IMEI para pré-preenchimento de marca, modelo, OS e especificações técnicas de dispositivos móveis. Cobrança por chamada, com saldo limitado.
2. **VIN decoder** (a seleccionar — NHTSA vPIC é gratuita mas limitada; alternativas pagas como VinCheck oferecem mais campos) para veículos apreendidos.

Estas APIs têm três características relevantes:

- **Dados estáveis** — as especificações de hardware associadas a um TAC (primeiros 8 dígitos do IMEI) ou VIN não mudam no tempo. Uma consulta hoje devolve o mesmo resultado que daqui a 6 meses para o mesmo IMEI/VIN.
- **Custo por chamada** — a API imeidb.xyz cobra por consulta. O saldo é limitado e gastar chamadas redundantes é desperdício directo.
- **Disponibilidade crítica** — durante uma apreensão, se a API estiver em baixo ou o saldo esgotado, o agente deve conseguir continuar a registar (manualmente) sem falha do sistema.

A infraestrutura actual tem duas restrições operacionais:

- **Deploy Fly.io em contentor único** — a máquina reinicia em cada deploy, em idle shutdown (≥20 min sem tráfego) e em autoscale. O filesystem é efémero (`/app`), portanto qualquer cache em memória do processo Python ou em ficheiro local perde-se.
- **Base de dados Neon PostgreSQL** — persistente, externa ao contentor Fly.io, com autoscale e branching. Já configurada e em uso produtivo.

O projecto **não tem Redis** nem outro store externo, e adicionar um traria custos recorrentes e uma nova peça de infra a monitorizar.

## Decision

Adopta-se **`django.core.cache.backends.db.DatabaseCache`** como backend de cache para lookups externos (IMEI, VIN e outros que venham a ser adicionados), armazenado em tabela dedicada na base de dados Neon PostgreSQL.

Configuração em `forensiq_project/settings.py`:

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'forensiq_cache',
        'TIMEOUT': 60 * 60 * 24 * 30,  # 30 dias por omissão
        'OPTIONS': {
            'MAX_ENTRIES': 10_000,
            'CULL_FREQUENCY': 3,
        },
    },
}
```

A tabela `forensiq_cache` é criada via `manage.py createcachetable` (executado uma única vez em cada ambiente) e versionada como data migration `core/migrations/0006_create_cache_table.py` para garantir idempotência.

Chaves de cache seguem o padrão `lookup:<source>:<identifier>` (ex: `lookup:imei:353893101224013`, `lookup:vin:WBA3A5C51EF123456`). TTL específico por fonte:

- IMEI (imeidb.xyz): 30 dias — hardware specs estáveis
- VIN (NHTSA/VinCheck): 180 dias — specs de veículo praticamente imutáveis
- Balance check (imeidb.xyz): 5 minutos — para não poluir admin dashboard

Em caso de falha do cache (erro de DB, timeout), o código de lookup **continua** — faz a chamada directa à API, devolve o resultado ao utilizador, e apenas loga o erro de cache. O cache é uma optimização, nunca um caminho crítico.

## Alternatives Considered

### A1: `LocMemCache` (cache em processo Python)

O backend mais simples — guarda no dicionário do processo. **Rejeitada** porque:

- O Fly.io reinicia a máquina em deploy, idle shutdown e autoscale — o cache desaparece em cada restart.
- Com 10 cêntimos de saldo a imeidb.xyz, gastar chamadas repetidas por um mesmo IMEI após um restart é desperdício directo.
- Em workers múltiplos (Gunicorn com `--workers N`), cada worker tem o seu próprio cache — inconsistência e duplicação de chamadas.

### A2: `FileBasedCache` em `/app/.cache/`

Guarda ficheiros de cache no filesystem local. **Rejeitada** porque:

- O filesystem Fly.io é efémero — tudo em `/app` é perdido em cada restart.
- Poderia usar-se um Fly Volume persistente, mas introduz um segundo ponto de estado (para além da DB Neon), complexifica backups e contradiz o ADR-0006 (ISO 27037 requer storage persistente e auditável).

### A3: Upstash Redis via Fly.io marketplace

Redis gerido, plano gratuito até 10k comandos/dia (suficiente para o volume esperado). **Rejeitada** nesta fase porque:

- Adiciona uma terceira peça de infra (Fly.io + Neon + Upstash) sem benefício mensurável ao volume actual (estima-se dezenas de lookups/dia em operação real).
- A complexidade de configuração (secrets, healthchecks, fallback quando Upstash está indisponível) não se justifica para uma operação de polícia municipal de escala pequena.
- Pode ser reconsiderada se o volume ultrapassar ~1000 lookups/dia ou se outros casos de uso (sessões, filas) justificarem.

### A4: Fly Redis self-hosted em contentor separado

Spawn de um contentor Redis no Fly.io (deixou de ter plano gratuito desde 2024). **Rejeitada** porque custo mensal (~5 USD) é superior ao custo total de todas as chamadas à imeidb.xyz previstas para um semestre.

### A5: Sem cache — cada lookup bate sempre na API

**Rejeitada** porque com 10 cêntimos de saldo, 10 consultas e um restart do Fly.io, 10 IMEIs diferentes consomem todo o saldo; se cada IMEI for consultado 2× (primeira entrada + posterior verificação pelo perito), o saldo esgota-se em 5 apreensões.

## Consequences

### Positivas

- **Persistência entre restarts** — a cache sobrevive a deploys, idle shutdowns e autoscales do Fly.io.
- **Zero infra nova** — usa a Neon PostgreSQL já provisionada e paga.
- **Consistência entre workers** — múltiplos workers Gunicorn partilham o mesmo cache através da DB.
- **Auditabilidade** — a tabela de cache é inspecionável via SQL (útil para diagnosticar "porque é que este IMEI não está cached?").
- **Backups incluídos** — a Neon faz backup automático da tabela de cache junto com o resto da DB, sem configuração adicional.
- **Custo marginal ≈ 0** — a Neon não cobra por tabela adicional dentro do plano existente.

### Negativas

- **Latência** — cada leitura de cache é uma query PostgreSQL (tipicamente 5–20ms em rede Fly.io↔Neon Frankfurt), vs <1ms em LocMem ou Redis. Para o uso expectável (1–2 lookups por submissão de evidência), irrelevante.
- **Carga na DB** — cada lookup adiciona uma query à DB. Com MAX_ENTRIES=10000 e o índice automático criado pelo Django na coluna `cache_key`, a query é O(log n). Não se antecipa impacto.
- **Limpeza** — a limpeza automática ocorre em writes (`CULL_FREQUENCY=3` → a cada 3 writes, elimina 1/3 das entradas expiradas). Para garantir limpeza regular mesmo sem escritas, adiciona-se management command `manage.py clearexpiredcache` executado semanalmente via cron.

### Mitigações

- **Index explícito** — a migration cria `CREATE INDEX CONCURRENTLY IF NOT EXISTS forensiq_cache_key_idx ON forensiq_cache (cache_key);` (complementar ao índice UNIQUE default).
- **Monitorização de tamanho** — management command `manage.py cache_stats` reporta nº de entradas, tamanho médio, hit rate (se vier a existir instrumentação), para decidir migração para Redis se o volume crescer.
- **Fallback silencioso** — o serviço de lookup trata excepções de cache (`cache.get()`, `cache.set()`) como warnings e continua a fazer a chamada à API, garantindo que uma falha de cache nunca impede o registo de prova.

## Revisão futura

Reavaliar este ADR quando:

- O volume de lookups ultrapassar 1.000/dia (considerar Upstash Redis).
- For adicionado um segundo caso de uso de cache (sessões, rate limiting distribuído, filas) — aí Redis passa a justificar-se.
- A latência adicional provocar queixas de utilizadores no formulário de evidência móvel.
