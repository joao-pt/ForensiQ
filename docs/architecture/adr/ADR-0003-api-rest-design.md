# ADR-0003: Desenho da API REST

## Status: Accepted

## Context
Com os modelos de dados definidos (ADR-0002), é necessário expor uma API REST para que o frontend (e futuramente apps mobile) possa interagir com o backend. A API deve respeitar as regras de negócio definidas: permissões por perfil (AGENT vs EXPERT), imutabilidade da cadeia de custódia e integridade SHA-256.

## Decision

### Tecnologia
- **Django REST Framework (DRF)** com ModelSerializer e ModelViewSet.
- **DefaultRouter** para geração automática de URLs RESTful.
- **JWT (SimpleJWT)** para autenticação stateless.

### Endpoints
| Recurso | URL | Métodos | Quem cria |
|---|---|---|---|
| Users | `/api/users/` | GET, POST (admin) | Admin |
| Users/me | `/api/users/me/` | GET | Qualquer autenticado |
| Occurrences | `/api/occurrences/` | GET, POST, PUT, PATCH, DELETE | AGENT |
| Evidences | `/api/evidences/` | GET, POST, PUT, PATCH, DELETE | AGENT |
| Devices | `/api/devices/` | GET, POST, PUT, PATCH, DELETE | AGENT |
| Custody | `/api/custody/` | GET, POST | AGENT ou EXPERT |
| Timeline | `/api/custody/evidence/<id>/timeline/` | GET | Qualquer autenticado |

### Permissões
- `IsAgent` — escrita apenas para perfil AGENT, leitura para todos autenticados.
- `IsExpert` — escrita apenas para perfil EXPERT.
- `IsAgentOrExpert` — escrita para ambos os perfis.
- `IsOwnerOrReadOnly` — edição apenas pelo criador do recurso.
- Cadeia de custódia: sem PUT/PATCH/DELETE (http_method_names restrito).

### Padrões
- Campo `agent` preenchido automaticamente via `perform_create(serializer.save(agent=request.user))`.
- `integrity_hash` e `record_hash` são read-only nos serializers.
- ValidationError do modelo convertida para DRF ValidationError (HTTP 400).
- Paginação por defeito: 20 itens por página.
- Filtragem por query params: `?occurrence=id`, `?evidence=id`.

## Consequences

### Positivas
- API consistente e previsível (convenções REST).
- Permissões granulares por perfil, testadas automaticamente.
- Swagger UI disponível em `/api/docs/` para documentação interativa.
- 21 testes API cobrem os cenários principais.

### Negativas
- Filtragem por query params é básica — pode ser necessário django-filter no futuro.
- Sem rate limiting por agora (a adicionar em produção).
- Sem versionamento de API (v1/) — a considerar se houver alterações breaking.
