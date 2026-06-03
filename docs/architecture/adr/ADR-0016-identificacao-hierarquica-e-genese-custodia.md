# ADR-0016: Identificação hierárquica da prova e génese da cadeia de custódia (apreensão de dados, derivação de item, selagem)

## Status

Accepted — 2026-05-31

Amplia e ajusta o **ADR-0015** (ChainOfCustody como ledger de eventos) e o **ADR-0013** (GPS na custódia + fórmula única do `record_hash`). **Substitui** o esquema de códigos `OCC-/ITM-/CC-YYYY-NNNNN` (três contadores globais independentes) pelo esquema **hierárquico enraizado na ocorrência**. Sem retrocompatibilidade (princípio da Fase 2); os dados de demonstração são regerados (`seed_demo --reset`).

## Data

2026-05-31

## Contexto

A revisão da atribuição de identificadores expôs inconsistências reais:

1. **Dupla numeração na custódia.** Cada `ChainOfCustody` tinha um `code` global (`CC-YYYY-NNNNN`, ordem de criação no sistema) **e** um `sequence` por evidência (1..N). Os dois divergem visualmente — p.ex. os eventos de um item podiam ler-se `CC-…-00001`, `00002`, `00041` (o terceiro evento foi criado muito depois). Não é corrupção, mas confunde.
2. **Origem do ano divergente.** `OCC` usava o ano de `date_time` (crime), `ITM` o ano de `timestamp_seizure` (apreensão) e `CC` o ano de `timezone.now()` (registo) — três semânticas diferentes.
3. **Itens numerados globalmente**, não por ocorrência — contrário à convenção forense de *exhibit reference* por processo.

A literatura consultada (normas e sistemas) aponta um modelo coerente:

- **ISO/IEC 27037:2012** distingue formalmente **`collection`** (§3.3 — apreender o item físico) de **`acquisition`** (§3.1 — criar uma *cópia* dos dados; "the product of an acquisition is a potential digital evidence copy"), e exige verificação `source == copy` (§5.4.4), com exceção documentada quando a imagem não pode ser verificada (sistema vivo/móvel).
- **SWGDE 17-F-002 / 18-F-002 (2025)** distinguem **acquisition hash** (carimbado uma vez, sobre os dados-fonte) de **verification hash** (recalculado em cada reexame), e fixam o conteúdo mínimo da cadeia de custódia, incluindo a coluna **"Sealed? (Y/N)"** por transferência.
- **NIST SP 800-101r1** confirma que aquisições *back-to-back* de um dispositivo vivo produzem hashes globais diferentes (relógio), mas o hash **por ficheiro/item** mantém-se — justifica o hash por-item e o carimbo único do acquisition hash.
- **ACPO Good Practice Guide** e o princípio **ISAD(G)** de não-repetição sustentam a **referência hierárquica** (cada nível guarda só o seu sufixo; o código completo deriva-se da posição na árvore).
- **CPP (Portugal)** — a **apensação** (art. 29.º, na sequência da conexão dos arts. 24.º-25.º) **não é fusão**: cada processo mantém o seu **NUIPC original** (Portaria 1223-A/91, art. 13.º — NUIPC imutável) e é reversível (separação, art. 30.º). O processo **principal** é designado por lei (art. 28.º — crime mais grave), **não** por antiguidade.
- **LIMS (SENAITE)** separa em dois eixos a *partição física* da *derivação lógica* de uma amostra.

**Âmbito.** O ForensiQ trata a **execução da cadeia de custódia de contentores físicos** — dispositivos, itens e sub-componentes — **e** de **dados apreendidos no terreno** e remetidos ao laboratório (numa cópia materializada num suporte físico que se sela). **Fica fora** (vai para relatório pericial ou auto de mandado): prova **criada no laboratório** (imagens forenses derivadas), os **detalhes jurídicos da apensação**, e **buscas infrutíferas** (sem equipamento nem dados a apreender).

## Decisão

### 1. Identificadores hierárquicos (substitui OCC/ITM/CC globais)

Identificador legível **enraizado na ocorrência**, com o ano = **ano de registo** (a data do crime/apreensão fica como campo de dados):

```
Ocorrência          OC-2026-0001
└─ Item              OC-2026-0001.1
   └─ Sub-item        OC-2026-0001.1.1        (≤ 3 níveis — MAX_TREE_DEPTH)
Movimento de custódia do item .1:   OC-2026-0001.1-M01, -M02, …
```

- O `.` marca **estrutura** (item/sub-item); o `-M` marca **movimento de custódia**.
- **Não existe identificador próprio para "a cadeia de custódia"** — a cadeia é o conjunto de movimentos de um item; a sua identidade **é a identidade do item**. O número de movimento (`-Mxx`) **é** o `sequence` que já existe (1..N por evidência).
- **Persistência mínima + derivação:** guarda-se o sufixo **local** de cada nível (índice do item na ocorrência; índice do sub-item no pai). O código completo é **derivado** subindo a árvore `parent_evidence` e concatenando (padrão ISAD(G)/AtoM). Como a prova é **imutável** após criação, o código completo é estável e pode ser materializado no campo `code` no momento da criação.
- **Os códigos NÃO entram em nenhum hash** (`integrity_hash`/`record_hash` não serializam o `code` — confirmado no código atual). Logo a mudança de esquema **não invalida** a integridade.
- **Contadores independentes e seguros à concorrência:** o índice local de item é **por ocorrência**; o de sub-item é **por pai**; o de movimento é o `sequence` **por evidência**. Cada um tem `UniqueConstraint` no seu âmbito + `select_for_update` + retry (como o gerador atual). O contador de sub-itens **nunca** consome o contador da ocorrência (evita a regressão tipo SENAITE #1327).

### 2. Proveniência e génese (o 1.º movimento da cadeia)

A guarda "1.º evento = APREENSÃO" passa a depender da forma como o item entra:

| Como o item entra | 1.º movimento (génese) | A seguir |
|---|---|---|
| Objeto físico apreendido | `APREENSAO_OBJETO` | fluxo normal |
| **Dados adquiridos no terreno** | `APREENSAO_DADOS` | fluxo normal |
| **Sub-componente** (nasce, em regra no laboratório) | `DERIVACAO_ITEM` ("autonomizado no laboratório") | transferências normais |

- **`EventType`:** `APREENSAO` passa a `APREENSAO_OBJETO`; juntam-se `APREENSAO_DADOS` e `DERIVACAO_ITEM`. **Nenhum evento adicional no item-pai** (a separação documenta-se *só* na génese do filho — sistema leve; a narrativa lê-se na cadeia do sub-item).
- `APREENSAO_DADOS` só é válida como **génese** (M01) e **só** para evidência do tipo `DIGITAL_FILE`. A cópia em suporte autónomo **é**, juridicamente, a apreensão dos dados (Lei do Cibercrime art. 16.º/7-b) — não há um segundo ato de apreensão a seguir.
- `DERIVACAO_ITEM` só é válida como **génese** de uma evidência **com `parent_evidence`** (sub-componente). Etiqueta de apresentação: **"Autonomizado no laboratório"**.
- A **proveniência é derivada**, não armazenada: deduz-se de `parent_evidence` + tipo do 1.º evento (coerente com a filosofia "estado legal derivado" do ADR-0015). Sem nova coluna de estado.

### 3. Aquisição de dados no terreno

- O **exhibit é a cópia materializada no suporte** (`Evidence` do tipo `DIGITAL_FILE`), **não** o dispositivo-fonte (que fica com o proprietário e **não** entra no sistema) nem a imagem abstrata.
- **`acquisition_hash` + `acquisition_hash_algo`** — coluna(s) dedicada(s), **obrigatórias** para dados; é o hash carimbado **uma vez** sobre os dados copiados (distinto do `integrity_hash`, que é o hash de verificação do *registo*).
- **`acquisition_verification_status` + `acquisition_verification_note`** — para a exceção ISO 27037 §5.4.4 (aquisição live/móvel onde a verificação não é possível: documentar e justificar).
- **Metadados da fonte e da aquisição** em `type_specific_data` (mínimo extensível): `source_make`, `source_model`, `source_identifier` (serial/IMEI), `acquisition_tool`, `acquisition_datetime`, `acquisition_level` (`physical|logical|file_system|targeted`).

### 4. Selagem e embalagem

Repartido por papel (confirma a literatura do formulário CoC):

- **Por-item (inicial, na génese — em `Evidence`):** `bag_number`, `initial_seal_number`, `seal_packaging_description`, `initial_condition`, `sealed_by`.
- **Por-movimento (a cada handover — em `ChainOfCustody`):** `sealed` (bool), `seal_condition_on_receipt` (`intacto|partido|violado|ausente`), `new_seal_number` (re-selagem gera **novo** número — o número de selo **não** é fixo por item), `relinquished_by`.

### 5. Apensação (adiada)

**Não** se implementa o modelo legal agora. Prevê-se apenas, no futuro, um **alerta ao utilizador** + uma **associação simples** ao novo NUIPC (sem fundamento de conexão, fase, despacho — esses detalhes vão no relatório pericial). Quando for implementada, será uma relação **append-only** entre `Occurrence` (tabela separada, porque a `Occurrence` é imutável), preservando NUIPC e códigos originais e **sem nunca mover a prova**.

### 6. Hashes (versão da fórmula)

- O `integrity_hash` da `Evidence` passa a incluir os novos campos **nucleares**: `acquisition_hash` e os campos de selo **inicial**.
- O `record_hash` do `ChainOfCustody` passa a incluir os campos de selo **por-evento** (`sealed`, `seal_condition_on_receipt`, `new_seal_number`, `relinquished_by`).
- Os **códigos continuam fora** das fórmulas (derivados/apresentação).
- Mudança de fórmula ⇒ **regerar os dados de demonstração** (sem migração de dados reais — princípio da Fase 2).

## Estudos de *edge cases*

1. **Génese `DERIVACAO_ITEM` — custódio/local de M01.** O sub-item herda, por defeito, o **custódio atual do pai** no instante da derivação (em regra `LAB_PUBLICO`, "autonomizado no laboratório"). A UI pré-preenche; o utilizador pode ajustar.
2. **Derivação de pai "fechado".** **Proibida** a criação de sub-item cuja génese seja sobre um pai com evento **terminal** (`RESTITUICAO`/`DESTRUICAO`) — não se autonomiza um componente de prova já restituída/destruída. Guarda no `clean()`.
3. **Profundidade.** O gerador de código respeita `MAX_TREE_DEPTH = 3` (item → sub → sub-sub: `…0001.1`, `…0001.1.1`, `…0001.1.1.1`), em coerência com a validação já existente.
4. **Ano do item/movimento.** Não têm ano próprio — **herdam** o ano da ocorrência via o código hierárquico. Um item adicionado em 2027 a uma ocorrência de 2026 é `OC-2026-0001.N`. Elimina a divergência de ano.
5. **`APREENSAO_DADOS` só em `DIGITAL_FILE`.** A apreensão de dados (cópia em suporte autónomo) só é génese válida para evidência do tipo `DIGITAL_FILE`; objetos físicos usam `APREENSAO_OBJETO`. Guarda no `clean()`.
6. **Verificação de hash impossível (live/móvel).** Permitida com `acquisition_verification_status = nao_verificavel` + justificação obrigatória (ISO 27037 §5.4.4). Não bloqueia.
7. **Re-selagem sem quebra de selo.** Nem todo o movimento parte o selo; quando não há handover físico, `sealed` e `seal_condition_on_receipt` ficam vazios/`intacto` e não há `new_seal_number`. Campos de selo **opcionais por evento**.
8. **Concorrência nos contadores.** Dois itens criados em simultâneo na mesma ocorrência não podem partilhar índice local — `UniqueConstraint` no âmbito + `select_for_update` + retry, espelhando o `ChainOfCustody.save()` atual.
9. **Erro de registo.** A prova é imutável (sem `delete`); um registo errado **não** se apaga — fica documentado e, se necessário, anotado por um evento subsequente. (Limitação assumida; tratamento de "anulação" fica fora deste ADR.)
10. **Múltiplas fontes numa só cópia.** Uma aquisição = uma `Evidence`. Imagens de fontes distintas geram evidências distintas (não se acumulam fontes num só registo).

## Consequências

- **Migração.** `core/models.py` (novos `EventType`; novos campos em `Evidence` e `ChainOfCustody`; gerador de código hierárquico; guardas no `clean()`; fórmulas de hash). Migração nova (no-op em SQLite; triggers PG espelhados onde aplicável). **Regenerar a demo** (`seed_demo`).
- **Frontend.** Todos os templates que mostram `ITM-/CC-` passam a mostrar o código hierárquico; o formulário de evidência ganha o ramo "apreensão de dados" (hash + fonte + selo) e o default de `DERIVACAO_ITEM` ao criar sub-item; o formulário de evento de custódia ganha os campos de selo.
- **Papéis e competências.** O *gating* dos atos por papel, credencial e instituição é definido no ADR-0017; não está preso ao tipo de evento.
- **Testes (5 famílias, conforme a estratégia adotada):**
  1. *Append-only ao nível BD* — `UPDATE`/`DELETE` recusados (PostgreSQL; os triggers são no-op em SQLite — a CI de invariantes corre contra PG).
  2. *Hash-chain* — recomputar `record_hash` encadeado e detetar adulteração de 1 campo.
  3. *Continuidade per-item / bifurcação* — pai e filho com cadeias independentes; `DERIVACAO_ITEM` como génese do filho; estados derivados divergentes.
  4. *Guardas de génese/sequência* — 1.º evento ∈ {`APREENSAO_OBJETO`, `APREENSAO_DADOS`(DIGITAL_FILE), `DERIVACAO_ITEM`(parent≠∅)}; terminais fecham; `VALIDACAO_APREENSAO`/`INICIO_PERICIA` condicionais; derivação de pai fechado proibida.
  5. *Geração de IDs hierárquicos* — código derivado correto, índice local por âmbito, sem consumir o contador da ocorrência, e estável sob concorrência.

## Decisões complementares

- O `acquisition_hash` e os campos de selo inicial integram a fórmula do `integrity_hash`; os campos de selo por-evento integram a fórmula do `record_hash`. Ficam assim à prova de adulteração, ao custo de regerar os dados de demonstração.
- Os metadados de aquisição (fonte, ferramenta, nível) ficam em `type_specific_data`, num conjunto mínimo extensível, e não no esquema SWGDE completo.
- O *gating* de atos por papel e competência é tratado no ADR-0017 (papéis, credenciais e controlo de acesso).

## Referências

- ISO/IEC 27037:2012 §3.1/§3.3/§3.6 (acquisition vs collection vs digital evidence copy), §5.4.4 (verificação source==copy; exceção documentada), §7.1.3/§7.1.4 (selagem do suporte).
- SWGDE 17-F-002-2.1 (2025) §8/§9/§10 (verificação; documentação da fonte; original selado vs working copy); SWGDE 18-F-002-2.0 (2025) §13 (acquisition vs verification hash), §14 (conteúdo mínimo CoC).
- NIST SP 800-101r1 (2014) — níveis de aquisição; hash por-item estável; *back-to-back* diferem.
- ACPO Good Practice Guide for Digital Evidence v5 — referência de exhibit por produtor + sub-exhibit; continuidade per-item.
- CPP (Portugal) arts. 24.º-25.º (conexão), 28.º (processo principal), 29.º (apensação), 30.º (separação); Portaria 1223-A/91 art. 13.º (NUIPC único e imutável).
- ISAD(G) — código de referência por herança + não-repetição; numeração de acessão (ano de registo).
- SENAITE LIMS — eixos distintos de partição física vs derivação lógica de amostra.
- ADR-0013 (GPS + fórmula do `record_hash`), ADR-0015 (ledger de eventos), ADR-0014 (taxonomia de crimes/prioridade).
