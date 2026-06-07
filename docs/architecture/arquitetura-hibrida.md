# Arquitetura híbrida: interface server-rendered + API REST

> Nota de arquitetura para o relatório final. Decisões de suporte: [ADR-0003](adr/ADR-0003-api-rest-design.md) (API REST), [ADR-0004](adr/ADR-0004-frontend-architecture.md) (frontend), [ADR-0015](adr/ADR-0015-custodia-ledger-eventos.md) (ledger de custódia), [ADR-0017](adr/ADR-0017-papeis-instituicoes-acesso-custodia.md) (acesso). Figura: `diagrams/c4-container-hibrido.png`.

## Visão geral

O ForensiQ expõe **duas camadas de apresentação sobre um único núcleo de domínio**:

- uma **interface web *server-rendered*** (Django Templates + HTMX), para utilização humana no *browser*;
- uma **API REST** (Django REST Framework, documentada em OpenAPI/Swagger em `/api/docs/`), para consumo por máquinas — a PWA instalável, uma futura aplicação móvel nativa, *scripts* de integração e a verificação pública de autenticidade.

As duas camadas não competem nem se duplicam: assentam sobre os mesmos *serializers* de validação, o mesmo controlo de acesso *need-to-know* e os mesmos modelos imutáveis. O servidor é a fonte única de verdade; o que muda é o formato em que cada camada o devolve — HTML pronto a apresentar, ou JSON.

## As duas camadas

| Camada | Destinatário | Tecnologia | Devolve |
|---|---|---|---|
| Apresentação web | Humanos no *browser* | `frontend_views.py` + Templates Django + HTMX + Leaflet | HTML (e fragmentos HTML via HTMX) |
| API REST | Máquinas (PWA, móvel, integração, verificação pública) | DRF *ViewSets* + *Serializers* + drf-spectacular | JSON |

A interface web é montada no servidor e enviada pronta; o HTMX troca apenas fragmentos (filtros, paginação, *drawers* de detalhe) sem recarregar a página. A API mantém-se como interface paralela, orientada a integração programática.

## Porquê híbrida — e não uma *Single-Page Application*

A iteração anterior consumia a API por JSON e construía o DOM no cliente (uma SPA em JavaScript). Esse modelo trazia dois custos estruturais:

1. **Divergência API↔interface (*contract drift*):** qualquer alteração no contrato da API exigia uma alteração correspondente no cliente; quando uma das pontas mudava sem a outra, a interface partia silenciosamente.
2. **Duplicação de lógica:** regras de validação e de apresentação de estado ficavam repetidas no servidor e no cliente, com risco de se desalinharem.

A renderização no servidor elimina a divergência pela raiz — o ORM e o *template* são a mesma fonte —, oferece *first paint* imediato, e degrada com elegância quando o JavaScript falha. A API **não foi removida**: continua a servir os consumidores que precisam mesmo de JSON. A decisão está registada em [ADR-0004](adr/ADR-0004-frontend-architecture.md).

## Núcleo partilhado — uma só fonte de validação

O ponto de elegância do desenho: as vistas *server-rendered* **reutilizam os mesmos *serializers* do DRF** (`OccurrenceSerializer`, `EvidenceSerializer`, `ChainOfCustodySerializer`) para validar e auditar as submissões. A mesma regra serve o formulário HTML e o *endpoint* JSON — sem lógica duplicada, sem duas verdades. Abaixo dos *serializers*, o controlo de acesso *need-to-know* e os modelos imutáveis (Evidence e o *ledger* `ChainOfCustody`, com *triggers* PostgreSQL) são partilhados por ambas as camadas.

## Superfície da API

```
/api/auth/login/  /refresh/  /logout/        autenticação JWT em cookie HttpOnly
/api/occurrences/  /evidences/  /custody/  /users/    ViewSets CRUD
/api/occurrences/{id}/pdf/   /evidences/{id}/pdf/      guia de transporte PDF
/api/crime-categories/  /-subcategories/  /-types/     taxonomia de crimes
/api/reverse-geocode/   /nearby-pois/                  geo (proxy Nominatim)
/api/activity-feed/   /stats/   /stats/dashboard/      agregações
/api/schema/   /api/docs/                              OpenAPI + Swagger UI
/v/<hash>/                                             verificação pública (HTML)
```

## Consequências

**A favor:** sem divergência API↔interface; *first paint* rápido; resiliência (a UI essencial não exige JavaScript); validação única partilhada; API pronta para a PWA e para uma aplicação móvel nativa, tal como previsto na proposta (*backend* Django + DRF).

**Custo:** duas camadas de apresentação para manter — mitigado por partilharem todo o núcleo (serializers, acesso e modelos). A complexidade adicional fica contida na fronteira de apresentação, não no domínio.
