# ADR-0011: Upgrade para Django 6.0.5 (CVE-driven)

## Status

Accepted — **actualiza ADR-0002 §2** ("Framework: Django 5.x + Django REST Framework"). Pin de versão alterado; modelos, URLs, middleware e DRF mantêm-se sem alteração.

## Data

2026-05-17

## Context

O pin original do projecto (`src/backend/requirements.txt`) restringia Django ao ramo 5.x:

```
django>=5.0,<6.0
```

Em maio de 2026 o Django 6.0.5 (LTS) introduz correcções de três CVEs com impacto directo no perfil de exposição do ForensiQ (aplicação Django em produção atrás de TLS terminator Fly.io, com cookies de sessão JWT-HttpOnly, ADR-0009):

| CVE | Severidade | Vector relevante para ForensiQ |
| --- | --- | --- |
| **CVE-2026-6907** | Medium | Cache de respostas quando o header `Vary` está em falta — risco de partilha de respostas sensíveis entre utilizadores em deployments com cache intermédio (CDN/edge). O ForensiQ usa DatabaseCache (ADR-0008) no lookup IMEI (o `/api/stats/dashboard/` é calculado fresco, sem cache HTTP); o fix garante que, em qualquer deployment com cache intermédio, respostas autenticadas nunca caem no escopo errado. |
| **CVE-2026-35192** | Medium | Header `Vary` não era emitido quando se alterava a sessão — abre a porta a *session fixation* via cache de edge. Crítico dado que toda a autenticação ForensiQ vive em cookies HttpOnly servidos pelo Django. |
| **CVE-2026-5766** | High | `DATA_UPLOAD_MAX_MEMORY_SIZE` não era enforced em `MemoryFileUploadHandler` — DoS por upload grande em endpoints multipart. Aplica-se directamente a `/api/evidences/` (upload de fotos até 25 MB, ver `validate_image_max_size` em `core/models.py`). |

Adicionalmente, o ramo 5.x deixa de receber security patches em **abril de 2026**, ao passo que 6.0.x é LTS com suporte estendido até **abril de 2028**. Manter o pin em `<6.0` é dívida de segurança a partir do momento em que o stream 5.x perde EOL.

A migração foi proposta por Dependabot (PR #8) no dia 17 mai 2026 às 03:54 UTC.

## Decision

1. **Alterar o pin** de `django>=5.0,<6.0` para `django>=6.0.5,<7.0` em `src/backend/requirements.txt`. Limite superior `<7.0` preserva o gate manual + ADR para o próximo salto major (Django 7).
2. **Não introduzir alterações de código de aplicação.** A validação (293 testes verdes à data do upgrade; a suite cresceu desde então) com `manage.py check --settings=forensiq_project.test_settings` sem erros demonstrou que nenhum API removido em 6.0 está em uso no ForensiQ. As áreas de risco verificadas:
   - `STORAGES` setting (Django 5+) já estava migrado de `DEFAULT_FILE_STORAGE`/`STATICFILES_STORAGE` (ver `forensiq_project/settings.py:303–318`).
   - `LoginRequiredMiddleware` (novidade 5.1) não foi adoptado — continuamos a usar `@login_required` por view e `JWTCookieAuthentication` para a API (ADR-0009).
   - Composite primary keys (5.2) não aplicáveis ao schema actual.
   - DRF, SimpleJWT, drf-spectacular, django-cors-headers, django-filter, whitenoise, Pillow, psycopg2-binary, reportlab — todos compatíveis com 6.0 nas versões pinadas (verificado via `pip-audit` + `pip check`).
3. **Manter Python 3.12** (já era o mínimo para Django 5.x; Django 6.0 mantém 3.12 como mínimo suportado). Sem necessidade de bump do runtime.
4. **Documentar 7.0 como gate ADR.** Quando o Dependabot abrir PR para Django 7.0, abrir novo ADR e avaliar breaking changes (em particular ASGI default, middleware async, async ORM maturity).

## Alternatives Considered

- **Cherry-pick dos patches no ramo 5.2.** Rejeitado — exige fork interno do Django ou wheel custom, multiplicando a superfície de manutenção e quebrando reproducibilidade do `pip install -r requirements.txt`.
- **Adiar para o próximo *release cycle* (pós-entrega académica).** Rejeitado — duas das três CVEs (35192 e 5766) impactam directamente caminhos quentes do ForensiQ (sessões e upload de evidência) e o projecto está em produção em <https://forensiq.pt>. A janela de exposição não se justifica para um bump que custou zero linhas de código de aplicação.
- **Saltar para 6.1/6.2 (mais recente).** Rejeitado por agora — 6.0.x é LTS com suporte mais longo; 6.1/6.2 são *non-LTS* e introduzem APIs novas (async views, etc.) que pediriam ADR próprio.
- **Pin exacto `==6.0.5`.** Rejeitado — bloqueia patch updates futuras (6.0.6, 6.0.7) que tipicamente trazem mais correcções de segurança. O range `>=6.0.5,<7.0` permite Dependabot continuar a aplicar patches sem novo ADR.

## Consequences

### Positivas
- **Janela CVE fechada.** As três vulnerabilidades acima deixam de aplicar-se.
- **LTS estendido.** Cobertura de patches até abril de 2028 sem novo ADR major.
- **Zero refactor.** O bump confirma que o ForensiQ usa apenas API estável de Django desde a definição inicial — bom sinal de qualidade arquitectural.
- **Pipeline Dependabot validado.** Provou-se que o ciclo *PR automático → CI → merge* funciona end-to-end para bumps major, criando precedente para futuros 6.0.x → 6.0.y.

### Negativas / Trade-offs
- **Coordenação com PRs adjacentes do Dependabot.** O upgrade não passou CI em isolamento — não por incompatibilidade com Django 6, mas porque o workflow `ci.yml` não estava a instalar `requirements-dev.txt` (factory-boy em falta após `21e402c`). A correcção (commit `e2e9a54`) precedeu o merge do PR #8, que foi mergeado por último na onda de 17 mai 2026 (#3 → #5 → #6 → #9 → #4 → #7 → #10 → **#8**) com um *merge commit* explícito para puxar o fix. Não é problema de Django 6, mas é parte da história do upgrade.
- **`drf-spectacular-sidecar` foi bumpado em conjunto** (PR #7) para garantir compat com a versão pinada de drf-spectacular e com a serve-static do Django 6. Listado aqui para rastreabilidade — não justifica ADR próprio.
- **Pequena pressão sobre dependências terceiras.** Bibliotecas que ainda não declararam suporte explícito a Django 6 (alguns pacotes minor do ecossistema DRF) podem precisar de ser substituídas se aparecer regressão. Mitigação: pipeline Security (`security.yml`) corre `pip-audit` semanalmente; qualquer drift aparece em < 7 dias.

### Impactos noutros documentos
- **ADR-0002 §2** — referência a "Django 5.x" passa a "Django 6.x (LTS)".
- **`docs/scope/changelog.md`** — entrada Sem.9 (17 mai 2026) regista o upgrade e os CVE refs (`changelog.md`, concluído).
- **`README.md`** — badge actualizado para "Django 6" (`README.md:7`, concluído).
- **`.github/workflows/ci.yml`** — sem alterações (a versão Django vem do `requirements.txt`); o fix de `requirements-dev.txt` em `e2e9a54` é tratado como bug-fix de CI, não como decisão arquitectural.

> **Nota de actualização (13 jun 2026).** O pin-floor evoluiu de `django>=6.0.5,<7.0`
> para **`django>=6.0.6,<7.0`** (`src/backend/requirements.txt`), aplicado pelo Dependabot
> como patch update — exactamente o comportamento previsto na alternativa "Pin exacto"
> rejeitada acima. A decisão deste ADR (salto 5→6 LTS, range `<7.0` com gate manual no
> próximo major) mantém-se inalterada.

## Referências
- Django 6.0.5 release notes — <https://docs.djangoproject.com/en/6.0/releases/6.0.5/>
- CVE-2026-6907 — Django Vary header caching (PyPA advisory)
- CVE-2026-35192 — Django session Vary header (PyPA advisory)
- CVE-2026-5766 — Django `DATA_UPLOAD_MAX_MEMORY_SIZE` enforcement (PyPA advisory)
- Django supported versions / EOL schedule — <https://www.djangoproject.com/download/#supported-versions>
- Dependabot PR #8 (squash commit `2b2f914`).
