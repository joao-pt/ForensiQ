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

## Decision
1. **Framework:** Django 5.x + Django REST Framework
2. **Estrutura:** Projeto `forensiq_project` com app `core` em `src/backend/`
3. **User model:** `AbstractUser` customizado com campo `profile` (AGENT/EXPERT) e `badge_number`
4. **Modelos core:** User, Occurrence, Evidence, DigitalDevice, ChainOfCustody
5. **Integridade:** `Evidence.save()` calcula SHA-256 automaticamente; `ChainOfCustody` encadeia hashes
6. **Imutabilidade:** `ChainOfCustody.save()` bloqueia updates; `delete()` lança `ValidationError`
7. **State machine:** Transições de custódia validadas por dicionário `VALID_TRANSITIONS`
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
- Django é síncrono por defeito (assíncrono parcial em Django 5.x, mas não prioritário para MVP)
- Overhead de configuração inicial maior que FastAPI para APIs simples
- Necessidade de manter `python-dotenv` para carregar `.env` (Django não o faz nativamente)
