# ADR-0002: Estrutura do Projeto Django e Modelos de Dados

## Status
Accepted

## Data
2026-03-25

## Context
O ForensiQ necessita de uma estrutura de backend que suporte:
- Autenticação JWT com dois perfis (Agente e Perito Forense)
- Modelo de dados relacional para ocorrências, evidências, dispositivos digitais e cadeia de custódia
- API REST com documentação automática (Swagger/OpenAPI)
- Hashing SHA-256 para integridade de metadados (ISO/IEC 27037)
- Cadeia de custódia imutável (append-only, sem UPDATE/DELETE)

A stack inicialmente considerada incluía FastAPI, mas foi revista para Django + DRF por ser mais convencional, com ORM maduro e sistema de autenticação integrado — facilitando a defesa do projeto perante o júri.

> _Nota: a versão do Django foi bumpada para 6.0.5 (LTS) em 17 mai 2026 — ver [ADR-0011](ADR-0011-upgrade-django-6.md)._
>
> _Nota: a máquina de estados de custódia aqui prevista foi substituída por um ledger de eventos append-only — ver [ADR-0015](ADR-0015-custodia-ledger-eventos.md)._

## Decision
1. **Framework:** Django 6.x (LTS) + Django REST Framework
2. **Estrutura:** Projeto `forensiq_project` com app `core` em `src/backend/`
3. **User model:** `AbstractUser` customizado com dois eixos independentes (ADR-0017): `profile` (função na cadeia de custódia — `FIRST_RESPONDER`, `FORENSIC_EXPERT`, `EVIDENCE_CUSTODIAN`, `CASE_AUTHORITY`, `CHEFE_SERVICO`, `AUDITOR`) e `clearance` (credencial de visibilidade de leitura — `NORMAL`/`NACIONAL`), mais `badge_number` e `phone`
4. **Modelos core:** User (`profile` + `clearance`, ADR-0017), Institution e InstitutionMembership, taxonomia de crime (CrimeCategoria, CrimeSubcategoria, CrimeTipo), Occurrence, Evidence, ChainOfCustody e AuditLog. O antigo DigitalDevice foi descontinuado no T05 — subsumido por Evidence + `type_specific_data` (ADR-0010)
5. **Integridade:** `Evidence.save()` calcula SHA-256 automaticamente; `ChainOfCustody` encadeia hashes
6. **Imutabilidade:** garantida em três camadas para Occurrence, Evidence e ChainOfCustody — (1) validação no modelo, (2) guarda em `save()`/`delete()` que bloqueia UPDATE/DELETE com `ValidationError` e (3) triggers PostgreSQL (migrações 0002, para Evidence e ChainOfCustody, e 0013, para Occurrence). Os ViewSets expõem apenas `GET`/`POST` (`http_method_names`), sem `PUT`/`PATCH`/`DELETE`
7. **Cadeia de custódia:** ledger append-only de eventos (`event_type` + custódio + local), sem máquina de estados; o estado legal é derivado da sequência de eventos. Ver [ADR-0015](ADR-0015-custodia-ledger-eventos.md)
8. **Auth:** SimpleJWT para tokens, configurável via `.env`
9. **API docs:** drf-spectacular para Swagger UI em `/api/docs/`
10. **BD:** PostgreSQL via Neon.tech (conforme ADR-0001), configuração via `dj-database-url` + `.env`

## Alternatives Considered
- **FastAPI:** Mais rápido (async), mas sem ORM integrado nem admin. Requer SQLAlchemy separado. Menos convencional para projetos académicos.
- **Flask + SQLAlchemy:** Flexível, mas requer mais configuração manual para auth, admin, e API docs.

## Consequences

### Positivas
- ORM do Django facilita migrações e queries complexas
- Django Admin funcional de imediato para gestão de dados
- Ecossistema maduro (SimpleJWT, drf-spectacular, django-cors-headers)
- `AUTH_USER_MODEL` definido antes da primeira migração — sem problemas futuros
- Testes integrados com `django.test.TestCase`

### Negativas
- Django é síncrono por defeito (assíncrono parcial desde Django 5.x e mantido em 6.x, mas não prioritário para MVP)
- Overhead de configuração inicial maior que FastAPI para APIs simples
- Necessidade de manter `python-dotenv` para carregar `.env` (Django não o faz nativamente)
