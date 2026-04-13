# ADR-0007: Subresource Integrity (SRI) e Referrer-Policy para Recursos Externos

## Status

Accepted

## Data

2026-04-13

## Context

O ForensiQ carrega duas dependências externas via CDN (cdnjs.cloudflare.com): o Leaflet.js 1.9.4 (CSS e JavaScript) para a visualização de mapa de ocorrências. Estas dependências estavam protegidas com **Subresource Integrity (SRI)** — um mecanismo W3C que permite ao browser verificar que um ficheiro externo não foi adulterado, comparando um hash criptográfico declarado no HTML com o hash real do ficheiro descarregado.

Foram identificados dois problemas em produção:

1. **Hashes SRI desactualizados.** O CDN do Cloudflare recompilou os ficheiros do Leaflet 1.9.4 (mantendo a mesma versão semântica), o que alterou os hashes SHA-512. O browser descarregava os ficheiros com sucesso (HTTP 200), mas rejeitava silenciosamente a sua execução por falha na verificação de integridade. O erro manifestava-se como `ReferenceError: L is not defined` — sem qualquer mensagem explícita de SRI na consola, tornando o diagnóstico não-trivial.

2. **Tiles do OpenStreetMap bloqueados por falta de Referer.** O Django `SecurityMiddleware` define por omissão `Referrer-Policy: same-origin`, o que impede o browser de enviar o header `Referer` em pedidos cross-origin. Os servidores voluntários do OpenStreetMap exigem este header para cumprir a sua política de utilização, respondendo com HTTP 403/503 e a mensagem "Access blocked — Referer is required by tile usage policy".

Ambos os problemas resultavam num mapa completamente inoperacional em produção, apesar de funcionar intermitentemente em desenvolvimento local (latência menor, políticas de segurança menos restritivas).

## Decision

### SRI — Manter com hashes actualizados

Optou-se por **manter o SRI** nos recursos CDN do Leaflet, actualizando os hashes SHA-512 para os valores correctos. Esta decisão fundamenta-se no contexto forense do ForensiQ: a aplicação gere dados potencialmente sob segredo de justiça, e um ataque de supply chain que comprometa o CDN poderia injectar código malicioso com acesso ao DOM — incluindo tokens JWT, dados de ocorrências e coordenadas GPS.

Os hashes foram recalculados a partir do conteúdo actual do CDN:

- **CSS:** `sha512-h9FcoyWjHcOcmEVkxOfTLnmZFWIH0iZhZT1H2TbOq55xssQGEJHEaIm+PgoUaZbRvQTNTluNOEfb1ZRy6D3BOw==`
- **JS:** `sha512-puJW3E/qXDqYp9IfhAI54BJEaWIfloJ7JWs7OeD5i6ruC9JZL1gERT1wjtwXFlh7CjE7ZJ+/vcRZRkIYIb6p4g==`

### Referrer-Policy — strict-origin-when-cross-origin

Adicionou-se `SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'` ao `settings.py` de produção. Esta política envia apenas a origem (`https://forensiq.pt`) — sem path nem query string — em pedidos cross-origin, satisfazendo a exigência do OpenStreetMap sem expor informação sensível de navegação.

## Alternatives Considered

### A1: Remover SRI completamente

Eliminaria o problema de manutenção de hashes e as falhas silenciosas. **Rejeitada** porque o contexto forense do ForensiQ exige defesa em profundidade. A presença de SRI demonstra rigor de segurança na defesa académica e protege contra ataques de supply chain ao CDN.

### A2: Servir o Leaflet localmente (self-hosting)

Copiar `leaflet.min.js` e `leaflet.min.css` para `static/js/` e `static/css/`, eliminando a dependência do CDN. O SRI tornar-se-ia desnecessário (o ficheiro está sob controlo do WhiteNoise com hash no nome). **Rejeitada nesta fase** porque aumenta o tamanho do repositório, exige gestão manual de actualizações de segurança do Leaflet, e o CDN do Cloudflare oferece melhor performance global (edge caching). Pode ser reconsiderada em fase posterior se o projecto necessitar de operação offline.

### A3: Referrer-Policy no-referrer-when-downgrade

Enviaria o Referer completo (incluindo path) em todos os pedidos HTTPS. **Rejeitada** porque expõe URLs internas da aplicação (ex: `/occurrences/`, `/api/evidence/`) a servidores terceiros, violando o princípio de mínima exposição.

### A4: Referrer-Policy definida apenas via meta tag no template do mapa

Aplicaria a política apenas à página de ocorrências em vez de globalmente. **Rejeitada** porque a meta tag `Referrer-Policy` tem limitações em alguns browsers e não se aplica a recursos carregados antes da sua leitura pelo parser HTML. A configuração via HTTP header (Django `SecurityMiddleware`) é mais fiável e consistente.

## Consequences

### Positivas

- O mapa de ocorrências funciona correctamente em produção com tiles do OpenStreetMap.
- A protecção SRI mantém-se activa, demonstrando defesa em profundidade contra ataques de supply chain.
- A Referrer-Policy `strict-origin-when-cross-origin` é a recomendação actual do W3C e equilibra segurança com funcionalidade.
- O Referer enviado (`https://forensiq.pt`) cumpre a política de utilização do OpenStreetMap sem expor paths internos.

### Negativas

- Os hashes SRI exigem manutenção: se o CDN recompilar novamente os ficheiros, o mapa voltará a falhar silenciosamente.
- A dependência de um CDN externo (Cloudflare) permanece — se o CDN estiver indisponível, o mapa não funciona.

### Mitigações

- **Monitorização de SRI:** O pipeline de autopilot diário pode incluir uma verificação dos hashes SRI contra o CDN, alertando se divergirem.
- **Fallback futuro:** Se a estabilidade dos hashes se revelar um problema recorrente, migrar para self-hosting (alternativa A2) sem impacto na arquitectura.
- **Documentação:** Este ADR serve como referência para diagnóstico caso o problema reapareça — o sintoma (`L is not defined`) e a causa (hash SRI desactualizado) ficam documentados.
