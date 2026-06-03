# Disaster Recovery — ForensiQ

> **Estado:** documento operacional inicial, em vigor desde 2026-05-27 (Sem.12). Cobre o plano mínimo viável para o âmbito académico do ForensiQ (UC 21184, UAb) em produção em `https://forensiq.pt` sobre Fly.io + Neon PostgreSQL. **Não substitui** um BCP/DR completo de produção comercial (ausentes: hot standby cross-region, runbook validado por exercício de DR, contractos SLA com fornecedores).

## 1. Activos críticos

| Activo | Onde vive | Sensibilidade | Perda aceitável |
|---|---|---|---|
| Base de dados PostgreSQL | Neon (Frankfurt, `eu-central-1`) | **Crítico** — toda a prova, custody chain, AuditLog, integridade SHA-256 dos artefactos | RPO ≤ 24h (perda diária) |
| Fotografias de evidência | `MEDIA_ROOT/` no volume Fly.io `forensiq_media` | **Crítico** — bytes da prova; o hash na BD remete para estes ficheiros | RPO ≤ 24h |
| Aplicação (código + config) | Repositório GitHub `joao-pt/ForensiQ` | Médio — reproduzível via `git pull` + `fly deploy` | RTO ≤ 1h |
| Segredos (`DATABASE_URL`, `SECRET_KEY`, `JWT_SIGNING_KEY`, `QR_VERIFY_SECRET`, `IMEIDB_API_TOKEN`) | Fly secrets (vault gerido) | **Alto** — exposição compromete autenticação | Sem perda aceitável; rotação possível |

## 2. Estratégia de backup

### 2.1 PostgreSQL (Neon)

- **PITR (Point-In-Time Recovery)** activo no plano Neon Free: retenção **7 dias** de WAL contínuo.
- **Snapshots** automáticos diários do branch `main` (tier Free dá 1 backup retido).
- Nada activo por nós — o Neon faz autonomamente. Verificar mensalmente em <https://console.neon.tech/app/projects>.
- Restauro: via dashboard Neon, criar branch a partir de um timestamp arbitrário dentro da janela PITR (zero downtime) ou restaurar para o branch existente.

### 2.2 Ficheiros media (fotografias de evidência)

- **Hoje:** persistidos no volume Fly `forensiq_media` montado em `/data/media/`. Fly faz snapshots diários automáticos dos volumes pagos; o plano académico actual usa volume gratuito (sem snapshot automático garantido).
- **Mitigação manual:** `fly ssh sftp shell` + `get /data/media` mensalmente para arquivo local cifrado. Documentar data e hash do dump.
- **Plano futuro (RGPD Art. 32 c, roadmap pós-entrega):** migrar para object storage S3-compatible com SSE-KMS, snapshots versionados, e retention policy alinhada com `AUDIT_LOG_RETENTION_DAYS`.

### 2.3 Repositório de código

- Origin: GitHub `joao-pt/ForensiQ` (público).
- Clones locais: máquina do autor + máquina backup.
- Releases tagged a cada entrega (`v0.x-intercalar`, `v1.0-final`).

## 3. Cenários de incident + runbooks

### 3.1 BD corrompida ou eliminada (Neon)

**Sintomas:** 500 em todos os endpoints autenticados; logs Fly com `psycopg2.OperationalError` ou `relation does not exist`.

**Passos (RTO alvo: 1h):**

1. Confirmar que **não** é problema do Fly (network, DNS) — `fly status -a forensiq` + ping ao endpoint Neon.
2. Aceder ao dashboard Neon → escolher projecto ForensiQ → tab **Branches**.
3. Criar **novo branch** a partir do snapshot mais recente antes do incidente (Restore from snapshot).
4. Copiar a nova connection string.
5. `fly secrets set DATABASE_URL='<nova_string>' -a forensiq`.
6. `fly deploy --app forensiq` (re-arranca app com nova URL).
7. Smoke test: login com credenciais conhecidas + leitura de uma ocorrência. Verificar `integrity_hash` na UI.
8. Comunicar incidente no `docs/scope/changelog.md` da semana corrente.

**Limitação:** se o incidente é > 7 dias antigo (fora da janela PITR Free), os dados são irrecuperáveis. **Não há fallback** para esse cenário — o ForensiQ académico não tem backup off-site da BD.

### 3.2 Volume `forensiq_media` perdido (fotografias)

**Sintomas:** PDFs geram sem fotos; `MediaServeView` retorna 404 para todos os paths; `Evidence.photo.size` levanta `FileNotFoundError`.

**Passos:**

1. Confirmar via `fly ssh console -a forensiq` → `ls /data/media/` (vazio ou ausente).
2. Restaurar do último arquivo manual (ver §2.2): `fly ssh sftp shell` → `put -r ./media-backup-YYYY-MM-DD /data/`.
3. Re-verificar integridade: management command (não existe ainda, follow-up) que itera `Evidence`, recomputa `_compute_photo_hash()` e compara com `integrity_hash` na BD. Itens mismatched marca-se em `AuditLog` com `SYSTEM_ALERT`.
4. Se sem arquivo recente: registar perda no `changelog.md` + entrada `AuditLog SYSTEM_ALERT` com lista de evidências afectadas para futura recuperação parcial (campos sem `photo` ainda têm cadeia de custódia válida).

**Limitação:** volume Fly gratuito sem snapshot automático = perda permanente se sem backup manual.

### 3.3 Comprometimento de `SECRET_KEY` ou `JWT_SIGNING_KEY`

**Sintomas:** suspeita de fuga (commit acidental, screenshot público, log de erro shared).

**Passos (URGENTE, RTO < 15 min):**

1. Gerar novas chaves: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` (2× — uma para SECRET_KEY, outra para JWT_SIGNING_KEY).
2. `fly secrets set SECRET_KEY='...' JWT_SIGNING_KEY='...' -a forensiq` (atomic, restart automático).
3. **Todas as sessões JWT são invalidadas** — utilizadores precisam de re-login.
4. `git log --all --source -- '<ficheiro_suspeito>'` para confirmar exposição; se foi commitado, `git filter-repo --invert-paths --path <ficheiro>` + force-push + abrir pedido ao GitHub Support para invalidar caches de blobs expostos.
5. Auditoria: criar `AuditLog SYSTEM_ALERT` com `details={'event': 'secret_rotation', 'reason': '...'}`.

### 3.4 Comprometimento de `QR_VERIFY_SECRET`

**Sintomas:** suspeita de fuga (impacto: terceiro pode enumerar URLs `/v/<hash>/` de qualquer ocorrência).

**Passos:**

1. `fly secrets set QR_VERIFY_SECRET='<novo>' -a forensiq`.
2. **Todos os QR codes impressos perdem validade imediatamente** — vai aparecer 404 quando scaneados.
3. Re-imprimir PDFs para os talões ainda em trânsito (consultar `ChainOfCustody` com `event_type=TRANSFERENCIA_CUSTODIA` cujo evento subsequente de `ASSUNCAO_CUSTODIA`/conclusão ainda não foi registado — i.e., custódia em movimento no ledger; ADR-0015/0016).
4. Comunicar a peritos no laboratório que talões antigos precisam de ser reemitidos.

**Mitigação:** o `QR_VERIFY_SECRET` é deliberadamente separado de `SECRET_KEY` (decisão ADR-0012) para permitir rotação independente sem invalidar sessões JWT.

### 3.5 Fly.io app down (region failure)

**Sintomas:** `https://forensiq.pt` devolve 502/timeout; `fly status` mostra `unreachable` na região Frankfurt.

**Passos:**

1. Confirmar status global Fly em <https://status.flyio.net>.
2. Se incidente regional: `fly scale count 0 -a forensiq` + `fly regions add ams -a forensiq` (Amsterdam, mais próximo) + `fly scale count 1 -a forensiq`.
3. Verificar que o volume `forensiq_media` está disponível na nova região (se não estiver, ver §3.2).
4. DNS: `forensiq.pt` aponta para `forensiq.fly.dev` (CNAME) — sem mudança DNS necessária.

## 4. Teste de DR

**Estado actual:** sem exercício de DR formalizado (limitação académica reconhecida).

**Mínimo viável a fazer antes da entrega final (Sem.15):**

1. Criar branch experimental no Neon a partir de snapshot de ontem.
2. Apontar instância local de desenvolvimento para esse branch via env var.
3. Correr suite de testes contra esse DB de restauro.
4. Documentar resultado (tempo + sucesso) em entrada de `changelog.md`.

## 5. Retenção e RGPD

- `AuditLog` é purgado automaticamente após `settings.AUDIT_LOG_RETENTION_DAYS` (default 365). Ver `core/management/commands/purge_audit_logs.py` e auditoria 2026-05-18 §2 B9. Conforme RGPD Art. 5(1)(e).
- `Evidence` e `ChainOfCustody` **nunca são apagados** por design (ISO/IEC 27037 — imutabilidade + ADR-0009/0010). Sem `purge` aplicacional.
- Backups do Neon estão sujeitos à mesma janela de retenção do PITR (7 dias) — não há replicação para fora da EU.

## 6. Limitações conhecidas (não-DR)

Documentadas para reconhecimento explícito na defesa:

- **Sem hot standby cross-region.** Restauro requer downtime de ~30-60 min.
- **Sem teste de DR validado por exercício real.** O runbook acima é teórico (escrito em 2026-05-27).
- **Volume Fly free tier sem snapshot automático garantido** — média de fotos depende de backup manual mensal.
- **Sem cifra at-rest do volume** (Fly free tier). O Neon cifra at-rest por defeito (AES-256).
- **Janela PITR limitada a 7 dias** no plano Free do Neon. Corrupção subtil descoberta tardiamente é irrecuperável.

Para uma adopção produção real (post-académica), o RGPD Art. 32 c) exige plano DR validado, cifra at-rest comprovada, e teste documentado de restauro trimestral. Listado no `README.md` § "Roadmap pós-entrega final" como trabalho futuro.

## 7. Manutenção deste documento

Rever sempre que:

- A versão do plano Neon mudar (Free → Pro = mudança da janela PITR).
- Mover `media/` para object storage (anula §3.2).
- Adicionar staging environment (anula assumption de single-environment).
- Houver mudança de fornecedor (Fly → outro PaaS).

Última actualização: **2026-05-27** (Sem.12 — criação inicial). Autor: João M. M. Rodrigues.
