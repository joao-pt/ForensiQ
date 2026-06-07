# ADR-0001: Base de Dados e Alojamento — PostgreSQL + Neon

## Status

Accepted — 2026-03-23.

> **Nota de implementação.** A decisão (PostgreSQL + Neon) mantém-se. Dois pontos do desenho original evoluíram na implementação e ficam aqui corrigidos:
> - O *digest* SHA-256 da prova é calculado **na aplicação** (`hashlib`, em `Evidence.compute_integrity_hash()` e `ChainOfCustody.compute_record_hash()`, `core/models.py`), **não** via `pgcrypto` ao nível da base de dados. A `pgcrypto` foi ponderada mas não é usada (não há `CREATE EXTENSION pgcrypto` em nenhuma migração).
> - A imutabilidade ao nível da BD é garantida por **triggers `BEFORE UPDATE`/`BEFORE DELETE`** (migrações `0002` para Evidence/ChainOfCustody e `0013` para Occurrence), não por hashing na BD.
> - O motor corre hoje no Neon com *connection pooling* (PgBouncer); a migração para o plano *Launch* fica para antes da defesa.

## Data

2026-03-23

## Context

O ForensiQ é uma plataforma web de gestão de prova digital para *first responders* da PSP, construída com Django + Django REST Framework. A aplicação requer:

- **Integridade da cadeia de custódia** — toda a alteração ou eliminação de registos de prova deve ser auditável e imutável, em conformidade com a ISO/IEC 27037.
- **Hashing criptográfico** — os registos de prova são identificados por *digest* SHA-256 (calculado na aplicação; ver nota de implementação).
- **Controlo de acesso granular** — perfis distintos com permissões diferenciadas ao nível da linha (ver [ADR-0017](ADR-0017-papeis-instituicoes-acesso-custodia.md)).
- **Credibilidade forense e legal** — a tecnologia escolhida deve ser reconhecida em contexto judicial e académico.
- **Custo controlado** — projecto académico com orçamento próximo de zero durante o desenvolvimento, mas com necessidade de um ambiente funcional e público para a defesa (julho de 2026).

A escolha da base de dados e do fornecedor de alojamento são decisões interligadas: o motor determina as funcionalidades disponíveis, e o fornecedor determina a sustentabilidade operacional durante e após o desenvolvimento.

## Decision

Utilizar **PostgreSQL** como motor de base de dados, alojado na plataforma **[Neon](https://neon.tech)**.

Durante o desenvolvimento usa-se o plano gratuito do Neon (*Free Tier*), com *connection pooling* (PgBouncer). Para produção, prevê-se a migração para o plano *Neon Launch* (5 USD/mês), para garantir disponibilidade e desempenho.

## Alternatives Considered

| Alternativa | Razão de rejeição |
|---|---|
| **Supabase** | O plano gratuito pausa a BD ao fim de 7 dias de inactividade. O plano pago começa nos 25 USD/mês — desproporcionado para um projecto académico. |
| **Render (PostgreSQL managed)** | O plano gratuito expira ao fim de 30 dias, obrigando a recriar a instância repetidamente durante o desenvolvimento. |
| **Aiven** | Tecnicamente válida, com suporte completo a PostgreSQL. Rejeitada por menor documentação de integração com Django e plano gratuito mais restritivo. Reavaliável em produção futura. |
| **ElephantSQL** | Encerrado em janeiro de 2025. Indisponível. |
| **Railway** | Não oferece *tier* permanente sem custos; requer cartão de crédito e cobra após os créditos iniciais. |
| **SQLite** | Adequado apenas para desenvolvimento local. Não suporta `BEFORE UPDATE`/`DELETE` *triggers* nem acesso concorrente multi-utilizador — incompatível com os requisitos forenses. (Os 6 testes de imutabilidade ao nível da BD correm apenas em PostgreSQL, no *job* dedicado do CI.) |

## Consequences

### Positivas

- Os *triggers* `BEFORE UPDATE`/`BEFORE DELETE` do PostgreSQL implementam a imutabilidade da cadeia de custódia **na própria base de dados** (migrações `0002` e `0013`), independentemente da camada aplicacional — defesa em profundidade alinhada com a ISO/IEC 27037.
- O modelo ACID completo garante consistência transaccional em operações críticas (registo de prova, eventos de custódia), incluindo o cálculo do `record_hash` sob `transaction.atomic()` + `select_for_update()`.
- O RBAC da aplicação ([ADR-0017](ADR-0017-papeis-instituicoes-acesso-custodia.md)) assenta sobre um motor relacional maduro.
- O Neon mantém os dados sem expiração no plano gratuito; o *auto-suspend* é transparente para o utilizador (retoma em milissegundos).
- O plano *Neon Launch* (5 USD/mês) é suficiente para a demo pública e cabe no orçamento.
- PostgreSQL é amplamente reconhecido em contextos forenses, judiciais e académicos, reforçando a credibilidade do projecto na defesa.

### Negativas / trade-offs

- O *auto-suspend* do Neon no plano gratuito pode introduzir latência de arranque (*cold start*) na primeira ligação após inactividade. Aceitável em desenvolvimento; mitigado pela migração para o plano *Launch* antes da defesa.
- A dependência de um fornecedor externo (Neon) introduz risco de disponibilidade. Mitigação: ver [ADR-0005](ADR-0005-deployment-flyio.md) e [disaster-recovery](../../operations/disaster-recovery.md), onde as limitações de *backup* ficam assumidas.
- Os *triggers* de imutabilidade são instalados por SQL explícito (`RunSQL`) nas migrações, e não por migrações automáticas do Django — exige cuidado na gestão de migrações.

## Referências

- [ADR-0002](ADR-0002-django-project-structure.md) — estrutura Django + imutabilidade em 3 camadas.
- [ADR-0005](ADR-0005-deployment-flyio.md) — deploy Fly.io (Frankfurt) + Neon.
- [ADR-0011](ADR-0011-upgrade-django-6.md) — upgrade para Django 6.
- ISO/IEC 27037:2012 — preservação da integridade da prova digital.
