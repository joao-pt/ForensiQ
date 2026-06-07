# ADR-0019: Política de domínio numa fonte única, fora do modelo e da view (core/policy/)

## Status

Accepted — 2026-06-07

Decorre do ADR-0015 (ledger de custódia append-only e estado legal derivado), do
ADR-0016 (génese por proveniência e movimentação em dois tempos) e do ADR-0017
(papéis/acesso). Fecha a tarefa #22 — "extrair as regras comportamentais para um
módulo próprio" — definindo **o que** se extrai, **para onde**, e **o que nunca sai**
do modelo.

## Data

2026-06-07

## Contexto

As regras de **lei e processo** que classificam a custódia — que evento é válido a
seguir, o *gate* do laboratório, a derivação do estado legal, os conjuntos canónicos
de eventos/estados — estavam escritas no meio de ficheiros que também fazem
persistência (`core/models.py`) e HTTP (`core/frontend_views.py`). Duas consequências
concretas, verificadas na fonte:

- **Duplicação que pode divergir.** A fonte de verdade das guardas de transição é o
  `ChainOfCustody.clean()` (`core/models.py`). Mas o frontend mantém um **espelho** —
  `_valid_next_events` (`core/frontend_views.py:1481`) — que **re-deriva as mesmas
  guardas por valor** para decidir que botões oferecer. São dois sítios; se divergirem,
  a UI passa a **oferecer uma transição que a lei proíbe** (p.ex. encaminhar para o
  laboratório sem `DESPACHO_PERICIA` prévio — CPP Art. 154.º).
- **Constantes de política soltas e inconsistentes.** `received_states`
  (`core/frontend_views.py:1901`) é um literal inline (`{encaminhada, em_pericia,
  pericia_concluida, restituida, perdida_favor_estado, destruida}`) que exprime um
  conceito de domínio ("já no laboratório ou além") sem nome nem sítio canónico — não é
  redundante com `TERMINAL_LEGAL_STATES` (é um superconjunto), mas anda à parte dos
  outros conjuntos de estado.

A prática já mostrava o caminho: `core/validators.py` (IMEI/VIN/GPS), `core/labels.py`
(rótulos/CSS), `core/access.py` (acesso ReBAC) e `core/evidence_field_config.py`
(campos por tipo) **já são fontes únicas** dos seus domínios. Faltava o mesmo às regras
de evento/estado/transição.

Referência de desenho (sistemas auditáveis): a regra de negócio ganha em ficar
**isolada da infraestrutura** — testável por tabela de casos, sem base de dados, e
legível por um auditor numa página. É também o argumento de defesa mais forte: *a lei
vive num só sítio e nenhuma camada a pode contrariar*.

## Decisão

### 1. Princípio — a política de domínio é uma camada própria

As regras de lei/processo que classificam a custódia vivem num pacote `core/policy/`,
separado da persistência, da apresentação e da API. Quem precisar de uma regra
**consulta** a `policy/`; nenhuma camada guarda cópia própria. O pacote está no **fundo
do grafo de dependências** — importa apenas o Django, nunca `core.models`.

### 2. O que migra — vocabulário, conjuntos canónicos e derivação do estado

`core/policy/event_states.py` passa a ser a casa de:

- `EventType` / `CustodianType` (vocabulário processual e de detenção);
- `TERMINAL_EVENTS`, `GENESIS_EVENTS`, `SEIZURE_GENESIS_EVENTS`, `LAB_CUSTODIANS`,
  `HANDOFF_EVENTS` (conjuntos que ramificam por valor — CPP 178.º/154.º);
- `derive_legal_state` (a máquina pura que traduz a sequência do ledger no estado
  legal) e os conjuntos de estado `LEGAL_STATES` / `TERMINAL_LEGAL_STATES`.

### 3. Os predicados das guardas — fonte única que o `clean()` e o frontend chamam

`core/policy/custody_transitions.py` passa a conter os **predicados puros** das guardas
de transição (terminal fecha o ledger; `INICIO_PERICIA` exige `DESPACHO_PERICIA`; o
*gate* de laboratório; `VALIDACAO_APREENSAO` exige apreensão prévia, uma só vez; génese
coerente com a proveniência), a função `next_events(...)` (que evento é válido a
seguir), `genesis_event_for(...)` e o mapa de promoção de custódio por instituição. O
`ChainOfCustody.clean()` **chama** estes predicados (continua a fazer o I/O, a mutar
`self` e a levantar `ValidationError`); `_valid_next_events`/`_genesis_event_for`/
`_CUSTODIAN_TYPE_BY_INSTITUTION` deixam de re-derivar e passam a delegar na **mesma**
fonte. Frontend e modelo deixam de poder divergir.

### 4. O que NÃO migra (e é deliberado dizê-lo)

- **As fórmulas de hash** (`compute_record_hash` `hv1`/`hv2`, `compute_integrity_hash`
  e os helpers `_hash_escape`/`_hash_str`/`_strip_exif`) — contrato forense
  irreversível e versionado. Mover arrisca a ordem/posição dos segmentos e parte hashes
  históricos, sem ganho.
- **`save()`/`delete()` append-only** sob `select_for_update`/`atomic` — coração
  transacional do ledger, entrelaçado com a persistência.
- **O corpo do `clean()`** — faz `prior = list(ChainOfCustody.objects...)`, um `exists()`
  sobre o ledger do pai, muta `self` (herança de destino/custódio/GPS, `validation_overdue`)
  e levanta `ValidationError`. A `policy/` extrai o **predicado puro**; o `clean()`
  continua a ser a **fonte de verdade** que o chama. É mais honesto do que fingir que a
  guarda inteira é pura: ela lê o ledger e sela o objeto.
- **`core/access.py`** (acesso ReBAC, querysets `Q()`, estado de sessão) e
  **`core/validators.py`** (normas técnicas ISO/3GPP) — já são fontes únicas próprias e
  não ganham defesa por mudar de pasta.

### 5. Topologia (sem ciclo de imports)

`EventType`/`CustodianType` são `TextChoices` sem dependências de `core`, pelo que
descem para `event_states.py` sem ciclo. `core/models.py` importa daí no topo e
**re-exporta** (`from core.policy.event_states import EventType, derive_legal_state, ...`
com alias intencional para os nomes que re-exporta), pelo que todo o
`from core.models import EventType, derive_legal_state, GENESIS_EVENTS, ...` (em
`frontend_views`, `filters`, `serializers`, `views`, `pdf_export`, testes e seed)
continua válido sem alterações. As migrações não importam estes enums (têm os `choices`
inline), por isso mover as classes **não gera migração** nem toca no `record_hash` (o
valor serializado é a mesma string). Verificado: `makemigrations --check` sem alterações.

## Consequências

- **Ganha-se** uma fonte única, citável e testável sem ORM para os conceitos ancorados
  no CPP (178.º/6, 154.º, 158.º) e nos ADR-0015/0016 — e, no fim da §3, a impossibilidade
  de o frontend contradizer o `clean()`.
- **Mantém-se** intacta a integridade (hash, triggers, append-only) e o comportamento
  observável (mesmos estados, mesmas guardas, mesmas mensagens).
- **Custo:** um pacote novo + re-exportação; e, na §3, refatorar o `clean()` para chamar
  predicados (guarda-a-guarda, cada um coberto por teste de tabela antes de ser cablado).
- **Novo princípio permanente:** código novo que seja regra de lei/processo entra na
  `policy/`; nunca se duplica inline numa view/serializer.

## Alternativas consideradas

- **Não fazer (manter tudo no modelo/view).** Legítima, risco zero — mas mantém a
  duplicação `clean()`↔`_valid_next_events` e o literal `received_states` soltos, e não
  melhora a testabilidade isolada das guardas (o argumento de defesa). Preterida.
- **Só mover constantes + `derive_legal_state` (sem unificar as guardas).** É o primeiro
  passo desta decisão (§2), mas deixar a §3 por fazer mantém o espelho do frontend a
  re-derivar a lei. Adotada como **etapa**, não como fim.
- **Absorver `access.py` e `validators.py` num "pacote policy" único.** Rejeitada:
  misturaria acesso ReBAC ORM-bound, validação técnica ISO/3GPP e política de domínio sob
  um rótulo que perde significado; tornaria a separação *menos* defensável, não mais.

## Materialização

- **Etapa 1 (§2) — FEITA.** Criado `core/policy/event_states.py` (vocabulário + conjuntos
  canónicos + `derive_legal_state`) e `core/policy/__init__.py` (re-exporta a API pública).
  `core/models.py` importa e re-exporta. Sem ciclo, `makemigrations --check` sem
  alterações, `ruff` limpo, 658 testes core verdes.
- **Etapa 2 (§3) — em curso.** `core/policy/custody_transitions.py` com os predicados das
  guardas + `next_events`/`genesis_event_for`/mapa de custódio; `clean()` e o espelho do
  frontend passam a delegar; cada predicado coberto por teste de tabela, 0 regressões
  exigidas (baterias `tests_custody_v2`, `tests_encaminhar`, `tests_access`, e os casos de
  `derive_legal_state` em `tests.py`), mais imutabilidade contra PostgreSQL e e2e.

## Verificação

A invariância do comportamento é dada pelas baterias existentes (que importam
`derive_legal_state` e os conjuntos de `core.models` — caminho preservado pela
re-exportação) e, na Etapa 2, por testes de tabela por predicado. Verificação da Etapa 1:
658 testes core verdes; `makemigrations --check` sem alterações; `ruff` limpo.
