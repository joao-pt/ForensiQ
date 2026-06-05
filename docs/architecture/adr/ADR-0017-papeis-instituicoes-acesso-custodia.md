# ADR-0017: Papéis, credenciais, instituições e controlo de acesso por custódia

## Status

Accepted — 2026-06-01

Complementa o **ADR-0016** (modelo de identificação e génese da prova/custódia) e supera o ponto em aberto #1 desse ADR (papéis). A nomenclatura dos `EventType` é a definida no ADR-0016. Substitui o modelo de **2 perfis** (`AGENT`/`EXPERT`) por um modelo de **função + credencial + instituições**, com controlo de acesso *need-to-know* **derivado do ledger** de custódia. Sem retrocompatibilidade (princípio da Fase 2); a demo é regerada.

## Emenda — 2026-06-05: leitura total do perito forense por função

Revê-se a regra de **leitura** para o papel `FORENSIC_EXPERT`. Na versão original deste ADR (secções 1, 3, 5 e *edge case* 6), a visibilidade total dependia **exclusivamente da credencial** (`NACIONAL`); um perito com `clearance=NORMAL` via apenas os seus itens. Na prática pericial isso é insuficiente: um perito pode ser chamado a pronunciar-se sobre processos de **outras áreas ou divisões**, pelo que necessita de **leitura a toda a prova e a todos os processos**.

Regra revista: o papel `FORENSIC_EXPERT` é, **por si só**, habilitante para **leitura total**, independentemente da credencial. A leitura total passa a ser concedida a: **staff**, credencial **`NACIONAL`** *ou* papel **`FORENSIC_EXPERT`**. A **escrita mantém-se inalterada** (governada pela secção 5: detém o item / *override* do perito / atos de despacho da autoridade do caso / staff; `CHEFE_SERVICO`/`AUDITOR` nunca escrevem). Para os restantes papéis com `clearance=NORMAL` (`EVIDENCE_CUSTODIAN`, `CASE_AUTHORITY` fora dos seus casos) o *need-to-know* mantém-se.

Materialização: `core/access.py::has_full_read(user) = has_national_read(user) or profile == FORENSIC_EXPERT`, consumida por `scope_evidences`/`scope_occurrences`/`scope_custody`/`can_view_evidence`/`can_access_occurrence`. O registo de auditoria (`AuditLog`) permanece em *oversight-tier* (`has_national_read` — staff/`NACIONAL`), por ser metadados de supervisão e não conteúdo de prova.

As afirmações originais "o perito `NORMAL` não vê tudo" (assinaladas abaixo) ficam **superadas por esta emenda** quanto ao papel `FORENSIC_EXPERT`.

## Data

2026-06-01

## Contexto

O modelo de acesso atual é estático e insuficiente: `AGENT` vê as suas ocorrências, `EXPERT`/staff veem tudo. Os requisitos seguintes não são cobertos por este modelo:

- **O acesso deve seguir a cadeia de custódia, ao nível do ITEM** (*need-to-know*): quem recebe a custódia de um item ganha acesso a **esse item e à sua cadeia**, não à ocorrência inteira. O acesso de leitura é **permanente** (para prestar contas pelo período em que teve a prova).
- **A custódia é institucional**, não individual: a prova fica à guarda de uma **instituição** (esquadra/OPC, laboratório, **tribunal**), e uma **pessoa** dessa instituição executa/assina. No tribunal entrega-se sempre a quem assina, mas a guarda é do tribunal.
- **A visibilidade nacional é uma CREDENCIAL, não um papel.** Saber, a nível nacional, onde está cada prova é um acesso elevado a que **peritos e chefes de serviço** são habilitados — não é inerente ao papel "perito". Função (o que faço) e credencial (o que posso ver) são **eixos distintos**.
- **"Agente/perito" não chega** como conjunto de papéis.

Literatura: **ISO/IEC 27037** (DEFR §3.7 — *first responder*; DES §3.8 — especialista; §6.1 — conteúdo mínimo do registo de custódia: "quem acedeu, quando, onde, porquê, autoridade"); **CPP** (art. 178.º/2 — guarda por funcionário de justiça ou depositário/fiel depositário; art. 263.º — direção do inquérito pelo MP; arts. 151.º-152.º — perícia por laboratório oficial ou perito); **ACPO** (4 princípios; *case officer* com responsabilidade global — Princípio 4; trilho auditável por terceiro — Princípio 3); **NJAG Property/Evidence Management** (*property officer*; acesso ao cofre restrito; auditoria obrigatória em cada mudança de custódio); **NIST SP 800-53** AC-3/AC-6 (*least privilege* / *need-to-know*); **NIST SP 800-162** (ABAC — e o aviso de que o seu custo é elevado); **ReBAC/Zanzibar** (permissão pela presença de uma relação); **Axon Evidence** ("evidence belongs to the organization, not individuals"; *access list* aditiva ao nível do item; grupos/agências).

## Decisão

### 1. Dois eixos: FUNÇÃO (papel) e CREDENCIAL (acesso)

Separam-se explicitamente:

- **Função** (`User.profile`) — o que a pessoa **faz** na cadeia. Atributo global base.
- **Credencial** (`User.clearance`) — a **amplitude de visibilidade** a que está habilitada. Atributo independente da função.

Um perito é, em regra, habilitado à credencial nacional — mas é a **credencial** que dá a visibilidade nacional, não o papel. Um chefe de serviço (outra função) também pode ser habilitado.

### 2. Papéis (função) — `User.profile`

| Valor | Papel | Base |
|---|---|---|
| `FIRST_RESPONDER` | Agente / primeiro interveniente (recolhe, abre a cadeia) | ISO 27037 DEFR §3.7; CPP 270.º |
| `FORENSIC_EXPERT` | Perito / especialista forense digital (perícia, *override* operacional) | ISO 27037 DES §3.8; CPP 151.º-152.º |
| `EVIDENCE_CUSTODIAN` | Custódio / fiel depositário (guarda formal por conta da instituição) | CPP 178.º/2; NJAG |
| `CASE_AUTHORITY` | Autoridade judiciária (MP) — autoriza os atos de despacho | CPP 263.º; 178.º/3,6 |
| `CHEFE_SERVICO` | Chefe de serviço — supervisão **só-leitura** com visão nacional | ACPO P3; NJAG |
| `AUDITOR` *(opcional)* | Auditor só-leitura (âmbito restrito) | ACPO P3; NJAG |

`COURT_CLERK` **não** é papel próprio: é um `EVIDENCE_CUSTODIAN` de uma instituição do tipo `TRIBUNAL`. O **chefe de serviço** é papel próprio (`CHEFE_SERVICO`): vê tudo (credencial `NACIONAL`) mas **só consulta** — distingue-se do `FORENSIC_EXPERT`, que vê **e altera**.

### 3. Credencial — `User.clearance`

`NORMAL` | `NACIONAL`.

- **`NACIONAL`** → visibilidade nacional de **leitura** (lê todos os itens/casos). Credencial de peritos com supervisão nacional **e** de chefes de serviço.
- **`NORMAL`** → visibilidade *need-to-know* (secção 5).

A credencial governa a **leitura** (com a exceção do papel `FORENSIC_EXPERT` — ver Emenda 2026-06-05: o perito tem leitura total por função); a capacidade de **alterar** estados vem da **função**: o `FORENSIC_EXPERT` tem *override* operacional de escrita (sobre os itens que vê) e pode nomear intermediários; o `CHEFE_SERVICO` é **só-leitura**. Assim, perito e chefe com `NACIONAL` veem ambos tudo, mas **só o perito altera**.

### 4. Instituições

- **`Institution`** (entidade nova): `id`, `nome`, `type` (enum = o atual `CustodianType` promovido: `OPC`, `LAB_PUBLICO`, `LAB_PRIVADO`, `TRIBUNAL`, `DEPOSITARIO`, opc. `MP`/`PROPRIETARIO`), `sigla`, `is_active`. Conjunto **básico** para a prova de conceito.
- **`InstitutionMembership`** (entidade nova): `user` FK, `institution` FK, `is_active`, `joined_at`; `unique(user, institution)`. Uma pessoa pertence a uma (ou mais) instituições.
- **`ChainOfCustody.custodian_institution`** (FK `Institution`) e **`ChainOfCustody.custodian_user`** (FK `User`, *null*): a instituição **titular** e a **pessoa** que detém ativamente o item após o evento — ao lado do `custodian_type` (mantido) e do `agent` (quem **regista** o evento). **Quando há movimentação de prova, há sempre uma pessoa envolvida.** Se `custodian_user` está preenchido → **custódia pessoal** (em trânsito/manuseamento); se é *null* → **custódia institucional** (armazenado; disponível para qualquer membro da instituição assumir).

### 5. Controlo de acesso — RBAC + ReBAC-mínimo, derivado do ledger

O **ledger append-only de custódia JÁ É o grafo de relações** custódio↔item. Por isso a permissão **deriva da presença de uma relação** (ReBAC mínimo), sem motor ABAC externo — o RBAC puro seria insuficiente (não capta "o custódio *deste* item", tal como o NIST nota que não capta "o médico assistente *deste* doente"); o ABAC completo seria desproporcionado para a PoC.

**LER um item (Evidence) e a sua cadeia** — verdadeiro se qualquer:
0. papel `FORENSIC_EXPERT` (leitura total por função — Emenda 2026-06-05) ou `is_staff`;
1. `clearance == NACIONAL` (visibilidade nacional);
2. é o **titular/recolhedor** — `Evidence.agent` ou o agente da ocorrência;
3. **teve custódia** — foi `agent` em algum evento desse item no ledger (**leitura permanente**, porque o ledger nunca se apaga);
4. **visibilidade institucional** — é membro de uma `Institution` que é/foi `custodian_institution` num evento desse item;
5. `CASE_AUTHORITY` — itens dos seus casos.

**Âmbito**: o acesso de (3) e (4) é **ao item + cadeia**, **não** à ocorrência (a ocorrência tem mais dados; prevalece *need-to-know*/*least privilege*). O *scope* a nível de ocorrência fica reservado ao titular da ocorrência, ao perito com `NACIONAL` e à autoridade do caso.

**ESCREVER (registar evento / alterar estado)** — verdadeiro se qualquer:
1. é o `custodian_user` **atual** do item (detém-no pessoalmente) — inclui o *push* (entrega em pessoa);
2. o item está em **custódia institucional** (`custodian_user` atual *null*) e é **membro** da `custodian_institution` atual — pode **assumir** a custódia (*claim*, secção 6);
3. `FORENSIC_EXPERT` — *override* operacional sobre os itens que vê (alterar estados, nomear intermediários);
4. `CASE_AUTHORITY` — **apenas** os atos de despacho (`VALIDACAO_APREENSAO`, `DESPACHO_PERICIA`, `RESTITUICAO`, `PERDA_FAVOR_ESTADO`), nos casos atribuídos ao seu serviço (secção 6b).

(`CHEFE_SERVICO`/`AUDITOR` **nunca** escrevem.)

### 6. Movimentação: entrega em pessoa (*push*) vs assunção (*pull*)

- **`TRANSFERENCIA_CUSTODIA`** (*push*) — o custódio atual **entrega o item EM PESSOA a alguém concreto**: o evento nomeia o `custodian_user` recetor (e a sua `custodian_institution`). A **pessoa** que recebe ganha custódia pessoal e acesso. Há sempre alguém a receber.
- **Armazenamento institucional** — quando o detentor deposita o item no cofre/depósito da instituição, o evento fica com `custodian_user` *null* e `custodian_institution` = a instituição. O item passa a estar **disponível para qualquer membro** dessa instituição.
- **`ASSUNCAO_CUSTODIA`** (*pull*, novo `EventType`) — um **membro da instituição que detém o item em armazenamento** "chama-o a si", assumindo custódia pessoal (`custodian_user` = ele) para o manusear/remeter. É a exceção em que o **próprio** se torna custódio. Cobre o caso em que o equipamento está guardado no laboratório e o perito (ou quem o remete) o chama a si para a perícia ou para o entregar a outro.

A partir de qualquer destes, **todos os membros da `custodian_institution`** passam a ver o item e a cadeia (visibilidade institucional); o `custodian_user`, quando existe, mantém leitura permanente do item após entregar.

### 6b. Autoridade do caso (`CASE_AUTHORITY`) por atribuição institucional

Ao **submeter a apreensão para validação**, o caso é **atribuído a um serviço do Ministério Público** (uma `Institution` do tipo `MP`). A partir daí, **qualquer membro desse serviço** pode validar e despachar, e vê os itens do caso. A autoridade é **institucional**, não de uma pessoa específica.

### 7. Fora de âmbito (registado, não desenvolvido)

`EvidenceAccessGrant` (lista de acesso aditiva ao nível do item, estilo Axon, para conceder acesso pontual a externos — p.ex. procurador) — **apontamento de design, não se implementa** na prova de conceito.

## Estudos de *edge cases*

1. **Itens em custódia institucional são reclamáveis pelos membros.** Um item com `custodian_user` *null* (armazenado) é visível e reclamável por qualquer membro da `custodian_institution` — é assim que o perito o chama a si para a perícia. A entrega entre pessoas é sempre *push* nominal (em pessoa).
2. **Janela de leitura vs escrita.** **Escrita só enquanto detém** (é o `custodian_user` atual, ou membro da instituição que o tem armazenado). Após entregar, **leitura permanente mas só dos itens que teve à sua custódia** (atribuídos), nunca a ocorrência inteira.
3. **Âmbito do `CASE_AUTHORITY`.** Definido pela **atribuição da ocorrência a um serviço do MP** ao submeter para validação (secção 6b); membros do serviço atribuído têm autoridade e acesso ao caso.
4. **Item sem instituição (génese).** No 1.º evento (apreensão/aquisição), a `custodian_institution` é a instituição do `FIRST_RESPONDER` que recolhe; migração deriva-a do `custodian_type`/agente.
5. **Pessoa em várias instituições.** `InstitutionMembership` é M2M; a visibilidade institucional soma todas as instituições ativas da pessoa.
6. **Perito sem credencial nacional.** ~~Um `FORENSIC_EXPERT` com `clearance=NORMAL` só vê os seus itens~~ — **superado pela Emenda 2026-06-05**: o perito forense tem leitura total **por função**, mesmo com `clearance=NORMAL`. (A visibilidade por credencial mantém-se para os restantes papéis.)
7. **Imutabilidade.** Os eventos do ledger continuam append-only; conceder/retirar acesso **não** edita eventos passados — o acesso é sempre **derivado** do estado atual do ledger + pertenças.

## Consequências

- **Entidades novas:** `Institution`, `InstitutionMembership`; campos `ChainOfCustody.custodian_institution` + `ChainOfCustody.custodian_user`; `User.profile` expandido (inclui `CHEFE_SERVICO`) + `User.clearance`; novo `EventType` `ASSUNCAO_CUSTODIA`; atribuição da ocorrência a serviço do MP na validação.
- **Permissões:** o controlo *need-to-know* foi materializado em `core/access.py` como funções puras de módulo — `scope_evidences`/`scope_occurrences`/`scope_custody` (leitura/*scoping* de querysets) e `can_view_evidence`/`can_access_occurrence`/`can_append_custody` (verificação ao nível do objeto). As classes DRF `IsAgent`/`IsExpert`/`IsAgentOrExpert` mantêm-se em `permissions.py` para o *gating* grosseiro; não se criaram classes `CanViewEvidenceItem`/`CanAppendCustodyEvent` — a lógica vive nas funções de `access.py`.
- **Migração:** derivar `custodian_institution` do `custodian_type` nos dados; criar instituições básicas; mapear utilizadores demo para papéis+credencial+instituição. **Regerar a demo.**
- **Frontend:** o formulário de transferência ganha `custodian_institution` + o fluxo de *claim*; as listas/o detalhe passam a respeitar o *scoping* item-level; ecrã básico de gestão de instituições/membros.
- **Testes (acrescem às 5 famílias do ADR-0016):**
  6. *Acesso item-level* — titular/teve-custódia/membro-instituição/NACIONAL veem; quem nunca tocou no item **não** vê; ex-custódio vê o item mas **não** a ocorrência.
  7. *Escrita por custódio* — só a instituição custódia atual escreve; *push* vs *pull* (`ASSUNCAO_CUSTODIA`); `NACIONAL` *override*; `CASE_AUTHORITY` só atos de despacho.
  8. *Credencial vs função* — `NACIONAL` (qualquer função) vê tudo; `FORENSIC_EXPERT` vê tudo por função mesmo com `NORMAL` (Emenda 2026-06-05); os restantes papéis `NORMAL` continuam *need-to-know*.

## Pontos em aberto

Resolvidos: janela de leitura/escrita; entrega em pessoa (*push*) vs assunção de item armazenado (*pull*); `CASE_AUTHORITY` por atribuição ao serviço do MP; `CHEFE_SERVICO` como papel próprio só-leitura.

Resolvidos **na implementação** — ambos por derivação do ledger, sem coluna mutável nem `EventType` dedicado:
1. A autoridade do caso ("submeter para validação") **deduz-se da `Institution` do tipo `MP` presente na cadeia** de custódia (`core/access.py`, resolução da autoridade do caso em `can_access_occurrence`/`can_append_custody`), em vez de um `EventType` próprio ou campo de atribuição mutável na ocorrência.
2. O **armazenamento institucional** é o estado `custodian_user` *null* num evento de custódia (`ChainOfCustody.custodian_institution` preenchida, `custodian_user` *null*), não um `EventType` `ARMAZENAMENTO` próprio; o *claim* faz-se via `ASSUNCAO_CUSTODIA` por um membro da `custodian_institution` (`can_append_custody` trata a assunção).

## Referências

- ISO/IEC 27037:2012 §3.7 (DEFR), §3.8 (DES), §6.1 (registo de custódia), §6.3-6.4 (papéis/competência).
- CPP (Portugal) art. 178.º/2 (guarda/fiel depositário), art. 263.º (direção do inquérito — MP), arts. 151.º-152.º (perícia), art. 270.º (atos delegados nos OPC).
- ACPO Good Practice Guide for Digital Evidence — 4 princípios; *case officer* (P4); trilho auditável (P3).
- NJAG Property and Evidence Management — *property officer*; acesso ao cofre restrito; auditoria em mudança de custódio.
- NIST SP 800-53 AC-3 / AC-6 (*least privilege* / *need-to-know*); NIST SP 800-162 (ABAC; custo); NIST RBAC FAQ (limites do RBAC para relação sujeito-objeto).
- Modelo ReBAC / Google Zanzibar (permissão por relação).
- Axon Evidence — custódia da organização; *access list* aditiva item-level; grupos/agências.
- ADR-0016 (identificação e génese), ADR-0015 (ledger de eventos), ADR-0013 (GPS + hashes).
