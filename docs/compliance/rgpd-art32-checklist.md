# RGPD Art.º 32 — Checklist de Conformidade ForensiQ

**Documento:** mapeamento entre o Regulamento (UE) 2016/679 (RGPD), Artigo 32.º "Segurança do tratamento", e a implementação técnica da aplicação ForensiQ.
**Versão:** 1.0
**Data:** 2026-04-18
**Âmbito:** aplicação web ForensiQ (backend Django 5 + DRF, frontend vanilla JS, infra Fly.io + Neon).
**Referências cruzadas:**
- Auditoria técnica: [`docs/AUDIT_2026-04-16.md`](../AUDIT_2026-04-16.md)
- Rastreabilidade ISO/IEC 27037: [`docs/scope/iso27037-traceability.tex`](../scope/iso27037-traceability.tex)
- ADR deployment: [`docs/architecture/adr/ADR-0005-deployment-flyio.md`](../architecture/adr/ADR-0005-deployment-flyio.md)

---

## 1. Texto do Artigo (resumo)

> Tendo em conta as técnicas mais avançadas, os custos da sua aplicação, e a natureza, o âmbito, o contexto e as finalidades do tratamento, bem como os riscos, de probabilidade e gravidade variável, para os direitos e liberdades das pessoas singulares, o responsável pelo tratamento e o subcontratante aplicam as medidas técnicas e organizativas adequadas para assegurar um nível de segurança adequado ao risco, incluindo, consoante o que for adequado:
>
> **a)** a pseudonimização e a cifragem dos dados pessoais;
> **b)** a capacidade de assegurar a confidencialidade, integridade, disponibilidade e resiliência permanentes dos sistemas e dos serviços de tratamento;
> **c)** a capacidade de restabelecer a disponibilidade e o acesso aos dados pessoais de forma atempada no caso de um incidente físico ou técnico;
> **d)** um processo para testar, apreciar e avaliar regularmente a eficácia das medidas técnicas e organizativas para garantir a segurança do tratamento.

O n.º 2 exige ainda ponderar os riscos de destruição, perda, alteração, divulgação ou acesso não autorizados, acidentais ou ilícitos, a dados pessoais transmitidos, conservados ou sujeitos a qualquer outro tipo de tratamento.

---

## 2. Contexto de risco da ForensiQ

A ForensiQ trata **dados pessoais sensíveis** enquanto sistema de gestão de prova digital:

| Categoria de dados | Fonte | Sensibilidade |
|---|---|---|
| Identificação de utilizadores (nome, username, email) | Modelo `User` | Média |
| Ocorrências (nome de suspeitos, vítimas, envolvidos; GPS) | Modelo `Occurrence` | **Alta** (dados judiciais) |
| Evidências digitais (fotos, metadados EXIF, IMEI, hashes) | Modelo `Evidence` | **Alta** (prova forense) |
| Cadeia de custódia (quem tocou em quê, quando) | Modelo `ChainOfCustody` | **Alta** (rastreabilidade judicial) |
| Logs de auditoria (IP, correlation_id, user-agent) | Modelo `AuditLog` | Média |

**Nível de risco apurado:** alto. A divulgação, alteração ou perda destes dados pode comprometer investigações criminais, violar direitos de arguidos/vítimas e inviabilizar prova em tribunal.

---

## 3. Mapeamento alínea-a-alínea

### Alínea a) — Pseudonimização e cifragem

| # | Requisito | Implementação | Evidência (código) | Estado |
|---|---|---|---|---|
| a.1 | Cifra de dados pessoais em trânsito | HTTPS forçado (HSTS 1 ano + preload). TLS negociado no edge Fly Proxy (TLS 1.2 mínimo, TLS 1.3 preferencial) | `src/backend/forensiq_project/settings.py:247-261`; `fly.toml:22-24` | ✅ Implementado |
| a.2 | Cifra de *passwords* de utilizadores | Django `PBKDF2-SHA256` por omissão, com *salt* aleatório por utilizador | `PASSWORD_HASHERS` (Django default) | ✅ Implementado |
| a.3 | Cifra de dados em repouso (BD) | Neon Postgres: cifra AES-256 do storage (gerida pelo provider) | [Neon Security Docs](https://neon.tech/docs/security/security-overview) | ✅ Implementado (via provider) |
| a.4 | Cifra de ficheiros de evidência em repouso | **Não implementado.** Fotos guardadas em `media/` sem cifra ao nível da aplicação. Em fs efémero do Fly.io | `src/backend/core/models.py` — campo `photo` | ❌ **Lacuna crítica** — ver `AUDIT_2026-04-16.md#A4` |
| a.5 | Pseudonimização em logs | `correlation_id` como identificador opaco; `AuditLog` regista `user_id` mas não nome/email | `src/backend/core/audit.py` | ✅ Implementado |
| a.6 | Integridade criptográfica de evidência | `integrity_hash` SHA-256 por registo; *hash-chain* entre `ChainOfCustody` para cadeia verificável | `src/backend/core/models.py:250-264, 502-504` | ⚠️ Parcial — *hash* não cobre bytes da foto (`AUDIT#S6`) e *hash-chain* usa *nonce* não gravado (`AUDIT#S5`) |

**Ações pendentes para cumprir a alínea a) sem reservas:**
1. Migrar `media/` para S3/R2 com cifra SSE-KMS (`AUDIT#A4`).
2. Estender `integrity_hash` aos bytes da foto (`AUDIT#S6`).
3. Determinizar a *hash-chain* (`AUDIT#S5`).

---

### Alínea b) — Confidencialidade, Integridade, Disponibilidade, Resiliência (CIA-R)

#### b.1 — Confidencialidade

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| b.1.1 | Autenticação forte | JWT curto (access 30 min, refresh 7 d); rate-limit 5/min em `/api/auth/login/` | `core/auth_views.py`; `settings.py` SIMPLE_JWT | ✅ |
| b.1.2 | Controlo de acesso por papel (RBAC) | Papéis `AGENT`, `EXPERT`, `ADMIN`; *permissions* DRF por viewset | `core/permissions.py` | ⚠️ EXPERT vê tudo (`AUDIT#S17`) |
| b.1.3 | Proteção de sessão contra roubo | HSTS, cookies `Secure` | `settings.py:249-253` | ⚠️ JWT ainda em `localStorage` — XSS exfiltra sessão (`AUDIT#S1`) |
| b.1.4 | Cabeçalhos de segurança HTTP | CSP, X-Content-Type-Options, Referrer-Policy | `core/middleware.py` | ⚠️ CSP permite `'unsafe-inline'` (`AUDIT#S2`) |
| b.1.5 | Anti-CSRF | CSRF token Django em formulários; SameSite em cookies | `settings.py` | ⚠️ Cookie JWT JS-settable rompe modelo (`AUDIT#S7`) |
| b.1.6 | Ocultação do Admin | Prefixo do Admin configurável por env var | `urls.py:43` | ⚠️ Só obscuridade (`AUDIT#S11`) |

#### b.2 — Integridade

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| b.2.1 | Imutabilidade de registos | `http_method_names = ['get', 'post']` em viewsets de prova; sem DELETE/PATCH | `core/views.py` | ✅ |
| b.2.2 | *Hash-chain* de cadeia de custódia | SHA-256 encadeado em `ChainOfCustody.hash_current` ← `hash_previous` | `core/models.py:ChainOfCustody` | ⚠️ *Nonce* não reproduzível (`AUDIT#S5`) |
| b.2.3 | *Log* de auditoria append-only | `AuditLog` com `correlation_id`, `user_id`, `action`, `timestamp` servidor | `core/audit.py` | ⚠️ IP falsificável (`AUDIT#S4`) |
| b.2.4 | Timestamps em UTC, gerados no servidor | `auto_now_add` + `USE_TZ=True` | `settings.py`; modelos | ✅ |
| b.2.5 | Validação de input | DRF *serializers* + `full_clean()` | `core/serializers.py` | ⚠️ `full_clean` só em `ChainOfCustody` (`AUDIT#B7`) |

#### b.3 — Disponibilidade

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| b.3.1 | Alojamento com SLA | Fly.io edge anycast + Neon Postgres (multi-AZ) | `fly.toml`; ADR-0005 | ✅ |
| b.3.2 | Rate-limit anti-DoS | `DRFThrottle` por IP/utilizador | `settings.py` | ⚠️ Anónimo 10/min pode ser restritivo ou permissivo (`AUDIT#S8`) |
| b.3.3 | Monitorização de erros | Django error logging; Fly.io metrics | `settings.py LOGGING` | ⚠️ Sem APM externo (Sentry/Better Stack) |

#### b.4 — Resiliência

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| b.4.1 | Graceful shutdown | Gunicorn + workers configurados | `Dockerfile` | ✅ |
| b.4.2 | Auto-restart em falha | `auto_start_machines = true` | `fly.toml:26` | ✅ |
| b.4.3 | Separação de ambientes | `.env.example` + settings condicionais a `DEBUG` | `settings.py` | ⚠️ `CORS_ALLOW_ALL_ORIGINS = DEBUG` é anti-padrão (`AUDIT#S3`) |

---

### Alínea c) — Restabelecimento em caso de incidente

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| c.1 | Backups automáticos da BD | Neon: *point-in-time recovery* até 7 dias (plano base) | Neon platform | ✅ (via provider) |
| c.2 | Backups de ficheiros de evidência | **Não implementado** (fs efémero do Fly.io) | — | ❌ **Lacuna crítica** |
| c.3 | Procedimento documentado de restauro | **Não documentado** | — | ❌ Lacuna |
| c.4 | Teste periódico de restauro | **Não realizado** | — | ❌ Lacuna |
| c.5 | RTO/RPO definidos | **Não definidos** | — | ❌ Lacuna |

**Ações pendentes para cumprir a alínea c):**
1. Migrar `media/` para objeto storage com versionamento (S3/R2). (`AUDIT#A4`)
2. Escrever `docs/operations/disaster-recovery.md` com procedimento de restauro.
3. Definir RTO (ex: 4h) e RPO (ex: 1h) coerentes com o contexto forense.
4. Agendar teste trimestral de restauro completo.

---

### Alínea d) — Avaliação regular da eficácia

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| d.1 | Suite de testes automatizados | ~2600 linhas em `tests_api.py`; `pytest-django` | `src/backend/core/tests_api.py` | ✅ Cobertura quantitativa boa (`AUDIT#T1`) |
| d.2 | Testes de regressão de segurança | **Parciais** — sem testes explícitos de IDOR/authz bypass | `AUDIT#S14` | ⚠️ Lacuna |
| d.3 | Auditoria de código periódica | Sim — `docs/AUDIT_2026-04-16.md`, `docs/code-review-2026-04-11.md` | `docs/` | ✅ (ad-hoc; falta cadência fixa) |
| d.4 | *Pentest* externo | **Não realizado** | — | ❌ Lacuna |
| d.5 | *SAST/DAST* em CI | **Não configurado** (CI/CD não visível) (`AUDIT#A5`) | — | ❌ Lacuna |
| d.6 | Varredura de dependências (SCA) | **Não configurado** | — | ❌ Lacuna |
| d.7 | Revisão trimestral dos controlos | **Não formalizado** | — | ❌ Lacuna |

**Ações pendentes para cumprir a alínea d):**
1. Adicionar *GitHub Dependabot / Renovate* para SCA.
2. Adicionar *Semgrep* ou *Bandit* em CI para SAST.
3. Acrescentar testes de regressão para as 10 vulnerabilidades do top da auditoria.
4. Documentar cadência trimestral de revisão em `docs/operations/security-review.md`.
5. Planear *pentest* externo antes de pôr em produção real.

---

## 4. Sumário executivo — conformidade global

| Alínea | Descrição | Estado | Lacunas críticas |
|---|---|---|---|
| a) | Pseudonimização e cifra | 🟡 **Parcial** | Cifra de evidências em repouso (`S6`, `A4`); *hash-chain* determinístico (`S5`) |
| b) | CIA-R | 🟡 **Parcial** | JWT em localStorage (`S1`), CSP unsafe-inline (`S2`), IP falsificável (`S4`), validação parcial (`B7`) |
| c) | Restabelecimento | 🔴 **Não conforme** | Sem backups de evidências, sem RTO/RPO, sem teste de restauro |
| d) | Avaliação regular | 🟡 **Parcial** | Sem SAST/DAST/SCA em CI, sem *pentest*, cadência não formalizada |

**Conclusão:** a ForensiQ tem os *building blocks* certos (cifra em trânsito, HSTS, RBAC, *hash-chain*, audit log, imutabilidade tripla), mas **não é ainda conforme com o Art.º 32** para operação em ambiente de produção real com dados reais. A conformidade total requer:

1. **Conclusão das 10 recomendações top da auditoria** (`AUDIT_2026-04-16.md#Top-10-priorizado`).
2. **Plano de DR/BC documentado e testado** para a alínea c).
3. **Pipeline de CI com SAST/SCA** para a alínea d).
4. **Pentest externo** antes de *go-live*.

Para fins **académicos** (TFM UC 21184, Universidade Aberta), o estado atual é **defensável** desde que se apresente este checklist como análise honesta das lacunas e plano de mitigação, e não como declaração de conformidade.

---

## 5. Matriz risco × mitigação (top 10)

Priorização para o plano de mitigação pós-TFM:

| # | Risco RGPD Art.º 32 | Mitigação | Esforço | Prioridade |
|---|---|---|---|---|
| 1 | Sessão JWT exfiltrável via XSS (a.1, b.1.3) | Mover JWT para cookie HttpOnly + Secure + SameSite=Strict | M | 🔴 |
| 2 | XSS viável por CSP permissiva (b.1.4) | Extrair inline JS/CSS; CSP com *nonce* | M | 🔴 |
| 3 | Evidência em fs efémero sem backup (c.2) | Migrar `media/` para S3/R2 com SSE-KMS + versionamento | M | 🔴 |
| 4 | Hash não cobre imagem (a.6) | Incluir `sha256(photo.read())` no `integrity_hash` | S | 🔴 |
| 5 | Hash-chain irreproduzível (a.6) | Remover *nonce* aleatório ou persisti-lo | S | 🔴 |
| 6 | IP falsificável em audit log (b.2.3) | *Whitelist* de proxies confiáveis | S | 🟠 |
| 7 | CORS acoplado a DEBUG (b.1.4) | Variável de ambiente `CORS_ALLOWED_ORIGINS` explícita | S | 🟠 |
| 8 | Validação parcial (b.2.5) | `full_clean()` em `Evidence`/`Occurrence` | S | 🟠 |
| 9 | Sem DR testado (c.4) | Escrever runbook + agendar teste trimestral | M | 🟠 |
| 10 | Sem SAST/SCA em CI (d.5, d.6) | GitHub Actions + Semgrep + Dependabot | S | 🟠 |

Legenda: S = ≤1 dia; M = 1-3 dias; L = >3 dias.

---

## 6. Declaração de finalidade

Este documento destina-se a:
- Integrar o **relatório do TFM** como análise de conformidade.
- Servir de **baseline** para ciclos futuros de avaliação (alínea d).
- Demonstrar **due diligence** perante orientador e júri quanto à consciência das obrigações legais do Art.º 32 RGPD.

**Não constitui** declaração formal de conformidade RGPD nem substitui parecer de jurista especializado ou avaliação por DPO.
