# ADR-0007: Subresource Integrity (SRI) e Referrer-Policy para Recursos Externos

## Status

Accepted (decisão SRI superseded pelo T08)

> **Nota (T08):** Com o Leaflet servido localmente sob WhiteNoise — ficheiro com hash no nome, mesma origin — o SRI tornou-se desnecessário e foi removido. A integridade dos recursos passa a ser garantida pelo controlo da origem, não por um hash declarado no HTML. A decisão sobre Referrer-Policy mantém-se válida e em vigor.

## Data

2026-04-13

## Context

O ForensiQ usa o Leaflet.js 1.9.4 (CSS e JavaScript) para a visualização de mapa de ocorrências. Estes ficheiros são servidos localmente a partir de `static/vendor/leaflet/` via WhiteNoise; a dependência de `cdnjs.cloudflare.com` foi eliminada no T08. O motivo foi de protecção de dados: coordenadas de ocorrências policiais não devem transitar por CDNs de terceiros (requisito GDPR — ver code-review finding #34).

Em fases anteriores estes recursos eram carregados via CDN e protegidos com **Subresource Integrity (SRI)** — um mecanismo W3C que permite ao browser verificar que um ficheiro externo não foi adulterado, comparando um hash criptográfico declarado no HTML com o hash real do ficheiro descarregado. Com o self-hosting, o sintoma de hashes SRI desactualizados (`ReferenceError: L is not defined` por rejeição silenciosa de um ficheiro do CDN recompilado) já não se aplica.

Foi identificado um problema em produção:

1. **Tiles do OpenStreetMap bloqueados por falta de Referer.** O Django `SecurityMiddleware` define por omissão `Referrer-Policy: same-origin`, o que impede o browser de enviar o header `Referer` em pedidos cross-origin. Os servidores voluntários do OpenStreetMap exigem este header para cumprir a sua política de utilização, respondendo com HTTP 403/503 e a mensagem "Access blocked — Referer is required by tile usage policy".

Este problema resultava num mapa completamente inoperacional em produção, apesar de funcionar intermitentemente em desenvolvimento local (latência menor, políticas de segurança menos restritivas).

## Decision

### SRI — Superseded pelo self-hosting (T08)

A decisão original mantinha o **SRI** nos recursos CDN do Leaflet, actualizando os hashes SHA-512 para os valores correctos, com fundamento no contexto forense do ForensiQ: a aplicação gere dados potencialmente sob segredo de justiça, e um ataque de supply chain que comprometesse o CDN poderia injectar código malicioso com acesso ao DOM — incluindo tokens JWT, dados de ocorrências e coordenadas GPS.

No T08 esta abordagem foi **superseded**: o Leaflet passou a ser servido localmente (alternativa A2), pelo que o SRI deixou de ser necessário e foi removido. Com o ficheiro sob WhiteNoise — mesma origin e hash no nome — a integridade é garantida pelo controlo da origem, e o vector de supply chain via CDN deixa de existir.

### Referrer-Policy — strict-origin-when-cross-origin

Adicionou-se `SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'` ao `settings.py` de produção. Esta política envia apenas a origem (`https://forensiq.pt`) — sem path nem query string — em pedidos cross-origin, satisfazendo a exigência do OpenStreetMap sem expor informação sensível de navegação.

## Alternatives Considered

### A1: Remover SRI completamente

Eliminaria o problema de manutenção de hashes e as falhas silenciosas. **Rejeitada** porque o contexto forense do ForensiQ exige defesa em profundidade. A presença de SRI demonstra rigor de segurança na defesa académica e protege contra ataques de supply chain ao CDN.

### A2: Servir o Leaflet localmente (self-hosting)

Copiar `leaflet.min.js` e `leaflet.min.css` para `static/vendor/leaflet/`, eliminando a dependência do CDN. O SRI torna-se desnecessário (o ficheiro está sob controlo do WhiteNoise com hash no nome). **Adoptada no T08.** Originalmente fora preterida por aumentar o tamanho do repositório, exigir gestão manual de actualizações de segurança do Leaflet e renunciar ao edge caching global do Cloudflare. Estes contras foram sobrepostos por um requisito de protecção de dados: coordenadas de ocorrências policiais não devem transitar por CDNs de terceiros (requisito GDPR — `_leaflet_head.html:7-8`, code-review finding #34). O self-hosting passou a ser a abordagem em vigor, tornando o SRI redundante.

### A3: Referrer-Policy no-referrer-when-downgrade

Enviaria o Referer completo (incluindo path) em todos os pedidos HTTPS. **Rejeitada** porque expõe URLs internas da aplicação (ex: `/occurrences/`, `/api/evidence/`) a servidores terceiros, violando o princípio de mínima exposição.

### A4: Referrer-Policy definida apenas via meta tag no template do mapa

Aplicaria a política apenas à página de ocorrências em vez de globalmente. **Rejeitada** porque a meta tag `Referrer-Policy` tem limitações em alguns browsers e não se aplica a recursos carregados antes da sua leitura pelo parser HTML. A configuração via HTTP header (Django `SecurityMiddleware`) é mais fiável e consistente.

## Consequences

### Positivas

- O mapa de ocorrências funciona correctamente em produção com tiles do OpenStreetMap.
- Com o Leaflet self-hosted (T08), elimina-se o vector de supply chain via CDN: o recurso é servido da própria origem, sem hashes SRI a manter.
- A Referrer-Policy `strict-origin-when-cross-origin` é a recomendação actual do W3C e equilibra segurança com funcionalidade.
- O Referer enviado (`https://forensiq.pt`) cumpre a política de utilização do OpenStreetMap sem expor paths internos.

### Negativas

- O self-hosting do Leaflet exige gestão manual das actualizações de segurança da biblioteca: o ficheiro em `static/vendor/leaflet/` tem de ser substituído quando sai uma nova versão, sem o fluxo automático de um CDN.

### Mitigações

- **Integridade pela origem:** Com o Leaflet self-hosted (T08), o risco de adulteração via CDN deixou de aplicar-se — não há hashes SRI a monitorizar nem dependência de um terceiro para servir o recurso. A integridade é garantida pelo controlo da própria origem.
- **Documentação:** Este ADR serve como referência para diagnóstico caso o problema reapareça — o sintoma (`L 