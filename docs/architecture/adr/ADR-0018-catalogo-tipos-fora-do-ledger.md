# ADR-0018: Catálogo de tipos editável fora do ledger imutável (snapshot)

## Status

Accepted — 2026-06-07

Decorre do ADR-0010 (taxonomia de evidência digital-first), do ADR-0014 (tabela de
crimes em base de dados) e do ADR-0015/0016 (ledger de custódia append-only e contrato
de hash). Define como mover os vocabulários de tipo (`EvidenceType`,
`InstitutionType`, `SealCondition`) de enum-em-código para dados editáveis, sem
comprometer a integridade forense.

## Data

2026-06-07

## Contexto

Os três vocabulários de tipo do domínio vivem como `models.TextChoices` em código:

- `Evidence.EvidenceType` (`core/models.py:887`) — 18 tipos de dispositivo/artefacto digital;
- `InstitutionType` (`core/models.py:297`) — 6 categorias de instituição custódia;
- `Evidence.SealCondition` (`core/models.py:916`) — 4 condições de selo.

Acrescentar ou renomear um valor exige alterar código e fazer **deploy**. A pergunta
operacional é legítima: quando a realidade muda (novos tipos de dispositivo ao longo
dos anos), tem de se republicar a aplicação inteira? A resposta deve distinguir
**instância** de **vocabulário**:

- **Instâncias** já são linhas de base de dados, criáveis sem deploy: as próprias
  ocorrências, os itens de prova, as **instituições** (criação manual com pino no mapa)
  e a **taxonomia de crimes** (`CrimeTipo`/`PoliticaCriminalPrioridade`, ADR-0014 — "trocar
  de biénio é operação de dados, sem código", `core/models.py:578`).
- **Vocabulários** (`EvidenceType`/`InstitutionType`/`SealCondition`) é que estão presos
  em código.

O obstáculo não é trivial: o valor do tipo **entra no hash de integridade**. O
`Evidence.compute_integrity_hash` serializa `self.type` cru (`core/models.py:1230`); o
`ChainOfCustody.compute_record_hash` serializa `custodian_type` e
`seal_condition_on_receipt` (`core/models.py:2239`, `:2250`). As tabelas `core_evidence`
e `core_chainofcustody` têm triggers de imutabilidade que bloqueiam `UPDATE`/`DELETE`
por linha (`core/migrations/0002_add_immutability_triggers.py`). Logo, qualquer desenho
do catálogo tem de garantir que **nenhuma edição de vocabulário consegue alcançar um
registo já selado**.

Literatura e prática de referência para sistemas imutáveis/auditáveis:

- **Separação ledger ↔ dados de referência.** Bases de dados-ledger (p.ex. *Azure SQL
  Ledger*) selam criptograficamente o registo de transação e mantêm os dados de
  referência em tabelas normais e mutáveis. O **Git** sela o *conteúdo* de um commit; os
  nomes de ramo/tag são ponteiros mutáveis **fora** do armazém de objetos (renomear um
  ramo não altera nenhum hash). Uma **blockchain** faz hash do conteúdo *escrito na
  transação*, nunca de uma consulta viva a uma tabela editável.
- **Snapshot / denormalização para integridade histórica.** Princípio clássico de
  faturação/ERP e de modelação de dados ponto-no-tempo (*slowly changing dimensions*,
  Kimball): a fatura copia para dentro de si a morada e o preço do momento; não guarda
  uma ligação viva ao cliente, senão a fatura de ontem mudava quando o cliente muda hoje.
- **Contemporaneidade do registo de custódia.** ISO/IEC 27037 §6.1 — o registo guarda o
  que era verdade *no momento* (quem, quando, onde, porquê, autoridade).
- **Código permanente, rótulo revisável.** Os códigos do INE/DGPJ (já usados na
  taxonomia de crimes) e o ICD-10 na saúde: o código é estável; o descritivo evolui.

## Decisão

### 1. Princípio — separar o ledger imutável dos dados de referência

O registo de prova (linha imutável, selada por hash) e o **catálogo de valores possíveis**
são duas coisas distintas, em tabelas distintas. O catálogo é um **dicionário** para
validação, rótulos e UI; **não é prova**.

### 2. Mecanismo — snapshot do slug na linha, nunca referência viva

O valor (o *slug*, ex.: `MOBILE_DEVICE`) é **copiado para a linha imutável** e é essa
string que o hash sela. Isto **já é o comportamento atual**: o enum é apenas um catálogo
em código, e a linha guarda a palavra crua — o hash lê `self.type`, nunca um rótulo. O
catálogo **nunca é lido pelo hash**. Por construção, editar o catálogo é incapaz de
alterar um registo já selado: o rótulo não é sequer *input* do hash.

> Este é o mesmo padrão da migração `0028_custody_handoff_bearer`: o portador entrou na
> cadeia por **snapshot** em colunas de texto na linha imutável, não por uma FK viva à
> tabela (editável) `Portador`.

### 3. O que NÃO se faz — FK das tabelas com trigger para o catálogo

Converter a coluna string (`type`) em `ForeignKey` para uma tabela de tipos é
**rejeitado** para `core_evidence`/`core_chainofcustody`, porque:

- ou o hash passa a serializar a **PK** → **parte todos os hashes já gravados** (rotura
  forense);
- ou serializa o `.code` via **JOIN** → a fonte-da-verdade textual deixa de estar
  materializada na linha imutável e passa a depender de uma tabela editável **sem
  triggers** (editar um `.code` reescreveria, em silêncio, a base do hash de registos
  passados);
- e popular a coluna FK exige `UPDATE` linha-a-linha nas tabelas imutáveis → só com
  `DISABLE TRIGGER`, abrindo a janela de imutabilidade.

### 4. O que se faz — tabela de referência com slug=PK

Criar uma tabela de referência (à semelhança de `CrimeTipo`) cuja **chave natural é o
próprio slug** (`code`, ex.: `MOBILE_DEVICE`), com campos **editáveis**: `label`, `i18n`,
`is_active`, `order` (e, se necessário, *flags* de política — ver §6). Esta tabela:

- **não** tem triggers de imutabilidade (é dado de referência);
- **não** é alvo de `ForeignKey` a partir das tabelas com hash (ou, no máximo, uma FK
  `to_field='code'`, `db_constraint=False`, que não altera o valor guardado nem o
  serializado);
- alimenta `choices`/validação/UI, substituindo `EvidenceType.choices` por um *loader*.

A coluna `Evidence.type` **mantém-se string** e o hash continua a lê-la da própria linha.
Resultado: zero backfill nas tabelas imutáveis, nunca se desliga um trigger, e todos os
hashes `hv1`/`hv2` existentes re-verificam sem alteração.

### 5. Regra de governança — slug *write-once*

O `code` (slug) é **escrito-uma-vez**: editam-se rótulos e *flags*; **nunca se renomeia**
um slug existente. Tipos novos recebem slugs novos; slugs antigos são permanentes (estão
congelados em registos selados e no hash, e há lógica que ramifica por valor — ver §6).
No admin, `code` fica só-leitura após criação. É a mesma disciplina dos códigos INE/ICD.

### 6. Âmbito — só `EvidenceType` por agora

- **`EvidenceType` → tabela de referência.** É o único vocabulário onde a tecnologia
  evolui e há caso real para acrescentar sem deploy. Um tipo novo "normal" (sem
  comportamento legal especial) passa a ser uma linha no admin. **Limite honesto:** um
  tipo que precise de *comportamento* (tipo-folha em `EVIDENCE_LEAF_TYPES`
  `core/models.py:878`, ou rota de génese ligada a `DIGITAL_FILE`) continua a exigir
  código, porque esse comportamento vive em código. Se essas *flags* por-tipo forem
  movidas para a tabela, passam a ser superfície sensível e precisam de guarda própria.
- **`InstitutionType` e `SealCondition` ficam enum.** Uma nova *categoria* de instituição
  é rara, definida por lei, e mexe no *gate* de laboratório (CPP Art. 154.º,
  `LAB_CUSTODIANS` `core/models.py:1602`); novas *instituições* já são deploy-free.
  `SealCondition` são 4 estados legais fixos. Mover qualquer um deles seria superfície a
  mais para benefício quase nulo.
- **`Institution.type`** é o caso tecnicamente fácil (sem trigger, fora do hash), mas
  mantém-se como está por ora para não alargar o âmbito.

### 7. Materialização

A tabela `EvidenceTypeRef` (`code` como chave natural *write-once*, mais `label`,
`is_active` e `order` editáveis) vive em `core/evidence_type_config.py` e é semeada a
partir do conjunto inicial de tipos. O `choices` do campo `Evidence.type` é um *callable*
que lê o catálogo vivo, pelo que `get_type_display`, a validação e o admin reflectem a
tabela; o *callable* é tolerante a tabela ainda inexistente (devolve `[]`), para o
*system check* poder correr numa base de dados vazia. O *loader* não guarda estado em
cache, e os laços leem os rótulos de uma só vez para evitar consultas repetidas. O
`<select>`, a *whitelist* de validação e o filtro da API passam a ler do catálogo; o
`EvidenceSerializer` declara `type` explicitamente e valida em `validate_type`,
desacoplando-se do *callable*. No admin, o `code` fica só-leitura depois de criado.

## Consequências

- **Ganha-se** evolução do vocabulário de dispositivos sem deploy (criar/relabel/ativar
  tipos no admin), alinhada com o que já se faz para os crimes.
- **Mantém-se** intacta a integridade: linhas seladas, hash e triggers inalterados; a
  prova continua **auto-contida e re-verificável a partir de si própria**, sem depender
  do estado atual do catálogo.
- **Custo:** uma tabela nova + *loader* + cache + ~sítios mecânicos de `choices` + seed +
  fixture e2e. Novo eixo de governança (o `code` é write-once; *flags* legais, se
  movidas, exigem guarda).

## Alternativas consideradas

- **FK total (enum → ForeignKey).** Rejeitada — §3 (parte o hash / move a verdade /
  exige desligar triggers).
- **Catálogo em JSON.** Rejeitada **face à tabela**, não por imutabilidade (em ambos os
  casos o catálogo está *fora* do ledger, que fica igualmente selado), mas por
  defensibilidade: a tabela traz constraints, unicidade e auditoria, é consistente com a
  taxonomia de crimes (juridicamente mais sensível e já tabelada), e não levanta a
  pergunta "como se valida/audita o JSON?".
- **Não mexer (manter enum).** Legítima e defensável pela estabilidade dos vocabulários;
  preterida apenas para `EvidenceType` por causa do caso real de evolução de dispositivos.

## Verificação

A propriedade central — *o hash compromete-se com o slug gravado na linha, nunca com o
rótulo do catálogo; e a origem do valor (membro de enum ou string de base de dados) é
indiferente ao hash* — é demonstrada por testes de tabela dedicados. O comportamento do
catálogo (acrescentar um tipo sem deploy, rever um rótulo em tempo de execução, desactivar
um tipo sem afectar itens já registados, o *slug write-once* e a guarda do serializer) é
igualmente coberto por testes.
