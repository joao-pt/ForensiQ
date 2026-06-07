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
| Occurrences | `/api/occurrences/` | GET, POST | AGENT |
| Occurrences/PDF | `/api/occurrences/<id>/pdf/` | GET (ação de detalhe) | Qualquer autenticado |
| Evidences | `/api/evidences/` | GET, POST | AGENT |
| Evidences/lookup IMEI | `/api/evidences/lookup/imei/<imei>/` | GET | Qualquer autenticado |
| Evidences/lookup VIN | `/api/evidences/lookup/vin/<vin>/` | GET | Qualquer autenticado |
| Custody | `/api/custody/` | GET, POST | AGENT ou EXPERT |
| Timeline | `/api/custody/evidence/<id>/timeline/` | GET | Qualquer autenticado |
| Reverse-geocode | `/api/reverse-geocode/` | GET | Qualquer autenticado |
| Nearby POIs | `/api/nearby-pois/` | GET | Qualquer autenticado |
| Crime categories | `/api/crime-categories/` | GET | Qualquer autenticado |
| Crime subcategories | `/api/crime-subcategories/` | GET | Qualquer autenticado |
| Crime types | `/api/crime-types/` | GET | Qualquer autenticado |
| Activity feed | `/api/activity-feed/` | GET | Qualquer autenticado |
| Stats | `/api/stats/` | GET | Qualquer autenticado |
| Stats/dashboard | `/api/stats/dashboard/` | GET | Qualquer autenticado |
| Health | `/api/health/` | GET | Público |

> O recurso `Devices` foi descontinuado no T05. Os dados de dispositivo passaram a viver em `Evidence.type_specific_data` (ver ADR-0010), pelo que não existe `/api/devices/`.
>
> A geração de PDF da ocorrência (ADR-0012) é exposta como uma `@action` de detalhe no `OccurrenceViewSet` — `/api/occurrences/<id>/pdf/` — e não como rota standalone independente.

> `Occurrence` e `Evidence` são imutáveis na BD após criação (ADR-0014, triggers 0013): os ViewSets restringem `http_method_names` a `GET`/`POST`, pelo que não há `PUT`/`PATCH`/`DELETE`. Correções fazem-se por novo registo/evento, não por edição.

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
- Paginação por defeito: 50 itens por página (`page_size_query_param` permite ao cliente pedir 20/50/100; `max_page_size` corta em 100).
- Filtragem por query params: `?occurrence=id`, `?evidence=id`.

## Consequences

### Positivas
- API consistente e previsível (convenções REST).
- Permissões granulares por perfil, testadas automaticamente.
- Swagger UI disponível em `/api/docs/` para documentação interativa.
- `tests_api.py` cobre os cenários principais (>60 casos); a suite total do core ronda os ~537 testes.

### Negativas
- Sem versionamento de API (v1/) — a considerar se houver alterações breaking.

### Notas de implementação
- Filtragem por query params apoiada em `django-filter` (`DjangoFilterBackend`), já adotado nos ViewSets.
- Throttling por scope (`ScopedRateThrottle` do DRF) aplicado nas views, complementado por throttles dedicados em `core/throttles.py` (`AuthRateThrottle`, `HealthcheckRateThrottle`).
