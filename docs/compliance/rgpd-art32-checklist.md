# RGPD Art.º 32 — Checklist de Conformidade ForensiQ

**Documento:** mapeamento entre o Regulamento (UE) 2016/679 (RGPD), Artigo 32.º "Segurança do tratamento", e a implementação técnica da aplicação ForensiQ.
**Versão:** 1.0
**Data:** 2026-04-18
**Âmbito:** aplicação web ForensiQ (backend Django 6 + DRF, frontend server-rendered (Django templates + HTMX + Alpine + Leaflet), infra Fly.io + Neon).
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
| a.4 | Cifra de ficheiros de evidência em repouso | Ficheiros gravados em `FileSystemStorage` com `MEDIA_ROOT` configurável para volume persistente do Fly.io (`settings.py:324`). Falta cifra ao nível da aplicação (SSE-KMS) e migração para object storage | `src/backend/forensiq_project/settings.py:303-324` | ❌ **Lacuna crítica** — ver `AUDIT_2026-04-16.md#A4` |
| a.5 | Pseudonimização em logs | `correlation_id` como identificador opaco; `AuditLog` regista `user_id` mas não nome/email | `src/backend/core/audit.py` | ✅ Implementado |
| a.6 | Integridade criptográfica de evidência | `integrity_hash` SHA-256 cobre metadados + bytes da fotografia (`Evidence._compute_photo_hash`), com strip de EXIF prévio para tornar o *hash* invariante a metadados sensíveis; *hash-chain* SHA-256 determinística e reproduzível entre registos `ChainOfCustody` (`compute_record_hash` recebe `previous_hash` explícito, sem *nonce*) | `src/backend/core/models.py:1080-1138,1157-1159,1801-1863` | ✅ Implementado — ver `AUDIT_2026-05-18-delta.md` §1 (S5/S6) |

**Ações pendentes para cumprir a alínea a) sem reservas:**
1. Migrar `media/` para S3/R2 com cifra SSE-KMS (`AUDIT#A4`).

---

### Alínea b) — Confidencialidade, Integridade, Disponibilidade, Resiliência (CIA-R)

#### b.1 — Confidencialidade

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| b.1.1 | Autenticação forte | JWT access 60 min (config. por env `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`), refresh 7 d com rotação + blacklist; rate-limit 5/min nos endpoints de auth | `settings.py:199-208,144` | ✅ |
| b.1.2 | Controlo de acesso por papel (RBAC) | RBAC por função (`User.profile`: `FIRST_RESPONDER`/`FORENSIC_EXPERT`/`EVIDENCE_CUSTODIAN`/`CASE_AUTHORITY`/`CHEFE_SERVICO`/`AUDITOR`) + ABAC por credencial (clearance `NORMAL`/`NACIONAL`) + need-to-know derivado do ledger ao nível do item (ADR-0017) | `core/access.py`; `core/models.py:217-227` | ✅ |
| b.1.3 | Proteção de sessão contra roubo | JWT em cookies HttpOnly + Secure (não-DEBUG) + SameSite=Strict, imune a XSS; CSRF exigido nas mutações | `core/auth.py:14-68` | ✅ |
| b.1.4 | Cabeçalhos de segurança HTTP | CSP Level 3 com *nonce* por request, sem `'unsafe-inline'`/`'unsafe-eval'`; Permissions-Policy, COOP/CORP, nosniff, Referrer-Policy | `core/middleware.py:122-167` | ✅ |
| b.1.5 | Anti-CSRF | CSRF token Django validado nas mutações de API (`auth.enforce_csrf`); cookies SameSite=Strict; cookie JWT HttpOnly e o cookie CSRF deliberadamente legível por JS para `X-CSRFToken` | `core/auth.py:55-56`; `settings.py:288-289` | ✅ |
| b.1.6 | Ocultação do Admin | Prefixo do Admin configurável por env var | `urls.py:43` | ⚠️ Só obscuridade (`AUDIT#S11`) |

#### b.2 — Integridade

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| b.2.1 | Imutabilidade de registos | `http_method_names = ['get', 'post']` em viewsets de prova; sem DELETE/PATCH | `core/views.py` | ✅ |
| b.2.2 | *Hash-chain* de cadeia de custódia | SHA-256 encadeado em `ChainOfCustody.record_hash` (calculado por `compute_record_hash`, que recebe `previous_hash` explícito); determinística e reproduzível por qualquer perito, sem *nonce* | `core/models.py:1801-1863,1929-1934` | ✅ |
| b.2.3 | *Log* de auditoria append-only | `AuditLog` com `correlation_id`, `user_id`, `action`, `timestamp` servidor; IP extraído com whitelist de proxies confiáveis (`TRUSTED_PROXIES`, suporte CIDR), `X-Forwarded-For` só honrado atrás de proxy confiável | `core/audit.py:20-80` | ✅ |
| b.2.4 | Timestamps em UTC, gerados no servidor | `auto_now_add` + `USE_TZ=True` | `settings.py`; modelos | ✅ |
| b.2.5 | Validação de input | DRF *serializers* + `full_clean()` em `Occurrence`, `Evidence` e `ChainOfCustody` no `save()` | `core/serializers.py`; `core/models.py:686,1153,1928` | ✅ |

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
| b.4.3 | Separação de ambientes | `.env.example` + settings condicionais a `DEBUG`; origens CORS/CSRF explícitas numa lista canónica única; `CORS_ALLOW_ALL_ORIGINS` controlado por env var (default `False`), já não acoplado a `DEBUG` | `settings.py:265-289` | ✅ |

---

### Alínea c) — Restabelecimento em caso de incidente

| # | Requisito | Implementação | Evidência | Estado |
|---|---|---|---|---|
| c.1 | Backups automáticos da BD | Neon: *point-in-time recovery* até 7 dias (plano base) | Neon platform | ✅ (via provider) |
| c.2 | Backups de ficheiros de evidência | **Não implementado** — ficheiros em `FileSystemStorage` (`MEDIA_ROOT` configurável para volume persistente do Fly.io, `settings.py:324`); falta object storage com versionamento/backup | — | ❌ **Lacuna crítica** |
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
| d.1 | Suite de testes automatizados | Suite distribuída por 22 ficheiros `tests_*.py` em `core/` (`tests_api.py` ~1600 linhas, mais `access`, `pdf`, `modelo_v2`, `public_verify`, `taxonomy`, etc.); gate de cobertura em CI; `pytest-django` | `src/backend/core/tests_*.py` | ✅ Cobertura quantitativa boa (`AUDIT#T1`) |
| d.2 | Testes de regressão de segurança | Testes de need-to-know/authz item-level (`tests_access.py:111-188`), CSP e rate-limit de auth (`tests_api.py:1387+`); falta DAST/fuzzing | `src/backend/core/tests_access.py`; `src/backend/core/tests_api.py` | ✅ Parcial |
| d.3 | Auditoria de código periódica | Sim — `docs/AUDIT_2026-04-16.md`, `docs/code-review-2026-04-11.md` | `docs/` | ✅ (ad-hoc; falta cadência fixa) |
| d.4 | *Pentest* externo | **Não realizado** | — | ❌ Lacuna |
| d.5 | *SAST/DAST* em CI | CI de segurança (`security.yml`): bandit (SAST) + semgrep no pre-commit (`p/owasp-top-ten`, `p/django`), gitleaks, trivy, com cron semanal | `.github/workflows/security.yml`; `.pre-commit-config.yaml` | ✅ |
| d.6 | Varredura de dependências (SCA) | `pip-audit` em CI (`security.yml`) + trivy (CVEs em deps/OS packages), em cada PR/push e cron semanal | `.github/workflows/security.yml` | ✅ |
| d.7 | Revisão trimestral dos controlos | **Não formalizado** | — | ❌ Lacuna |

**Ações pendentes para cumprir a alínea d):**
1. Acrescentar testes de regressão para as 10 vulnerabilidades do top da auditoria.
2. Documentar cadência trimestral de revisão em `docs/operations/security-review.md`.
3. Planear *pentest* externo antes de pôr em produção real.

---

## 4. Sumário executivo — conformidade global

| Alínea | Descrição | Estado | Lacunas críticas |
|---|---|---|---|
| a) | Pseudonimização e cifra | 🟡 **Parcial** | Cifra de ficheiros de evidência em repouso (`A4`); *hash* da foto e *hash-chain* determinística fechados (ver `AUDIT_2026-05-18-delta.md` §1, S5/S6) |
| b) | CIA-R | 🟡 **Parcial** | S1/S2/S4/B7 fechados (ver `AUDIT_2026-05-18-delta.md` §1); permanecem EXPERT vê tudo (`S17`), obscuridade do Admin (`S11`), throttling anónimo (`S8`), sem APM externo |
| c) | Restabelecimento | 🔴 **Não conforme** | Sem backups de evidências, sem RTO/RPO, sem teste de restauro |
| d) | Avaliação regular | 🟡 **Parcial** | SAST/SCA em CI implementados (`security.yml` + pre-commit); falta *pentest* externo e cadência formalizada |

**Conclusão:** a ForensiQ tem os *building blocks* certos (cifra em trânsito, HSTS, RBAC + ABAC + need-to-know, JWT em cookies HttpOnly, CSP com *nonce*, *hash-chain* determinística, *hash* da foto, audit log com IP fidedigno, imutabilidade tripla, SAST/SCA em CI), mas **não é ainda conforme com o Art.º 32** para operação em ambiente de produção real com dados reais. Dos 10 itens do Top-10 de abril, 9 estão fechados (ver `AUDIT_2026-05-18-delta.md` §8); permanecem em aberto, por opção arquitectural, N4 (PDF assíncrono) e P5 (PurgeCSS). As lacunas reais que faltam encerrar são:

1. **Cifra de ficheiros de evidência em repouso** + object storage com versionamento, para a alínea a)/c).
2. **Plano de DR/BC documentado e testado** com RTO/RPO, para a alínea c).
3. **Pentest externo** antes de *go-live*.

Para fins **académicos** (TFM UC 21184, Universidade Aberta), o estado atual é **defensável** desde que se apresente este checklist como análise honesta das lacunas e plano de mitigação, e não como declaração de conformidade.

---

## 5. Matriz risco × mitigação

Priorização para o plano de mitigação pós-TFM. As entradas do Top-10 de abril já encerradas (sessão JWT em cookie HttpOnly, CSP com *nonce*, *hash* da foto, *hash-chain* determinística, IP fidedigno no audit log, CORS desacoplado de `DEBUG`, `full_clean()` nos três modelos, SAST/SCA em CI) saíram desta matriz — ver `AUDIT_2026-05-18-delta.md` §1 e §8.

| # | Risco RGPD Art.º 32 | Mitigação | Esforço | Prioridade |
|---|---|---|---|---|
| 1 | Evidência sem cifra em repouso nem backup (a.4, c.2) | Migrar `media/` para S3/R2 com SSE-KMS + versionamento | M | 🔴 |
| 2 | Sem DR testado (c.4) | Escrever runbook + agendar teste trimestral | M | 🟠 |

Legenda: S = ≤1 dia; M = 1-3 dias; L = >3 dias.

---

## 6. Declaração de finalidade

Este documento destina-se a:
- Integrar o **relatório do TFM** como análise de conformidade.
- Servir de **baseline** para ciclos futuros de avaliação (alínea d).
- Demonstrar **due diligence** perante orientador e júri quanto à consciência das obrigações legais do Art.º 32 RGPD.

**Não constitui** declaração formal de conformidade RGPD nem substitui parecer de jurista especializado ou avaliação por DPO.
