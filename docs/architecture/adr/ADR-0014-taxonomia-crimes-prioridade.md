# ADR-0014: Taxonomia oficial de crimes + prioridade por Política Criminal

## Status

Accepted — 2026-05-30. Formaliza o tema **T19** e as decisões de produto **D9, D10 e D11** do `o plano interno de refactor` (§3, §6). Estende **T03** (campos da `Occurrence`) e liga-se a **T06** (feed de actividade) e **T18/D8** (`Occurrence` POST-only). Acompanha o ADR-0013 (GPS na custódia) como segundo ADR estrutural da Fase 2 do refactor.

## Data

2026-05-30

## Context

Hoje a `Occurrence` (`core/models.py:217-315`) **não classifica o crime nem a urgência**. Os seus campos são `code`, `number` (NUIPC), `description` (texto livre), `date_time`, `gps_lat`/`gps_lon`, `address` e `agent` — nada que diga *que tipo de crime* é a ocorrência, nem se merece tratamento prioritário. A descrição é prosa não-estruturada: impossível de agregar, de comparar com estatística oficial, ou de usar para encaminhar a investigação.

Esta lacuna tem três consequências concretas:

1. **O frontend v2 pressupõe dados que não existem.** O mockup V20 desenha uma colorbar/legenda de prioridade no hero geo-territorial e uma coluna "Pri." na tabela de ocorrências. Sem um campo de prioridade na `Occurrence`, **a colorbar e a coluna são decorativas** — o gap analysis registou-o (`gap-occurrence-priority`, `gap-occurrence-priority-serializer`, `gap-table-priority-feed-source`, manifest §2.9).

2. **Não há linguagem comum com a estatística oficial.** Um projecto de gestão de prova para forças de segurança que não fala a língua da **Tabela de Crimes Registados** (a nomenclatura do Conselho Superior de Estatística / DGPJ-SIEJ que estrutura toda a estatística criminal portuguesa) não consegue produzir números comparáveis com o INE/DGPJ. A `description` em texto livre não agrega.

3. **A `Occurrence` é imutável na BD, mas a classificação tem de ser definida algures.** A migração `0013_protect_occurrence` instala em PostgreSQL os triggers `trg_occurrence_no_update`/`trg_occurrence_no_delete` (`core/migrations/0013_protect_occurrence.py:33-41`) que bloqueiam **qualquer** `UPDATE`/`DELETE` da linha. Logo, qualquer campo de classificação que se acrescente só pode ser preenchido **na criação** (POST), nunca editado depois. Isto é coerente com **D8/T18** (decisão de tornar a `OccurrenceViewSet` POST-only — hoje é `viewsets.ModelViewSet` sem `http_method_names`, `core/views.py:203`, e expõe PUT/PATCH/DELETE que o trigger recusa).

### A decisão já tomada pelo dono (2026-05-30)

O `plano interno de refactor` regista em §6 as decisões **D9, D10 e D11** e desenvolve-as em **T19** (§3). Este ADR formaliza-as; não as reabre.

- **D9 — Taxonomia = dados de referência.** Modelar a classificação em **3 tabelas de referência** fiéis aos 3 níveis da Tabela de Crimes Registados, semeadas da versão **2024** (DGPJ/SIEJ Modelo 262 + INE/CSE). A versão de 2008 (`tabela-crimes.pdf` na raiz do repo) fica como **referência histórica**, não como fonte de seed — está desactualizada (não cobre, p.ex., os crimes contra animais de companhia da Lei 69/2014).

- **D10 — Prioridade binária, fiel à lei.** A `priority` da `Occurrence` deixa de ser uma escala arbitrária P1-P4 e passa a ser **binária** (`prioritária`/`normal`), **derivada** de uma configuração versionada por biénio (`PoliticaCriminalPrioridade`) semeada da **Lei n.º 51/2023, de 28 de agosto** (Lei de Política Criminal do biénio 2023-2025; DR n.º 166/2023, Série I). O **eixo operativo é o Art. 5.º** (crimes de investigação prioritária — porque o ForensiQ é uma ferramenta de *investigação*, não de prevenção); o **Art. 4.º** (crimes de prevenção prioritária) guarda-se como **flag informativa**. Há **override manual** do agente (`priority_source`: `lei`/`manual`). Nova lei = nova versão de config, **zero código**.

- **D11 — `crime_type` obrigatório + alertas.** `Occurrence.crime_type` é FK obrigatória à taxonomia, **definida na criação** (coerente com a imutabilidade de D8/T18). Ao registar uma ocorrência cujo crime é prioritário, a consola dispara **alerta**: evento no feed de actividade (liga a T06) + badge no hero. O **mapeamento curado lei↔tabela** (frases da lei → códigos N3/N2) é trabalho bounded, a produzir num curadoria com revisão cruzada.

### Estado das fontes legais e estatísticas (verificado)

- A **Tabela de Crimes Registados** é aprovada pelo Conselho Superior de Estatística (CSE/INE) no âmbito do Sistema Estatístico Nacional; a sua gestão operacional cabe à DGPJ via SIEJ (Modelo 262 — "Mapa para Notação de Crimes"). Estrutura de **3 níveis**: Nível 1 — Categorias (6: `1` Contra as pessoas, `2` Contra o património, `3` Contra a identidade cultural e integridade pessoal, `4` Contra a vida em sociedade, `5` Contra o Estado, `6` Legislação avulsa); Nível 2 — Subcategorias; Nível 3 — Tipos (com código oficial). A **versão canónica actual é a de 2024**; existem versões anteriores (1998/2005/2008/2010/2012/2015).
- A **Lei n.º 51/2023** é a Lei de Política Criminal **em vigor** (biénio 2023-2025). A sucessora (2025-2027) foi aprovada **na generalidade em 2026-03-20** mas **não está promulgada** — modela-se como versão futura, pré-carregável quando publicada, sem código novo.

## Decision

1. **Modelar a taxonomia como 3 tabelas de referência** (dados de lookup, **não** prova), uma por nível da Tabela de Crimes Registados:
   - `CrimeCategoria` (Nível 1, 6 registos): `codigo` (1-6), `nome`.
   - `CrimeSubcategoria` (Nível 2): FK→`CrimeCategoria`, `codigo`, `nome`.
   - `CrimeTipo` (Nível 3): FK→`CrimeSubcategoria`, `codigo` (código oficial, p.ex. `1` homicídio, `53` burla informática, `57` extorsão), `descritivo`, mais flags derivadas (ver ponto 4).

   São **dados de referência**: editáveis/versionáveis no admin, **não** abrangidos pelos invariantes de imutabilidade da prova (não são `Evidence`/`ChainOfCustody`/`AuditLog`/`Occurrence`). Não levam triggers PG de imutabilidade.

2. **Semear a partir da Tabela de Crimes Registados 2024** (DGPJ/SIEJ Modelo 262 + INE/CSE) por um comando de seed dedicado e idempotente. A versão de 2008 (`tabela-crimes.pdf`) fica documentada como referência histórica; **não** é a fonte do seed. Cada `CrimeTipo` guarda o seu código oficial para que a estatística por categoria do ForensiQ alinhe com a do INE.

3. **`Occurrence.crime_type` FK→`CrimeTipo`, obrigatória, definida na criação.** Coerente com a imutabilidade da `Occurrence` (`0013_protect_occurrence`) e com D8/T18 (ViewSet POST-only): o `crime_type` é um campo de **criação**, nunca de edição. O selector na criação é **em cascata** (N1 → N2 → N3) para tornar a entrada de dados rápida e correcta.

4. **A prioridade é derivada de configuração versionada, não codificada.** Introduzir uma tabela `PoliticaCriminalPrioridade` que liga **uma versão de Lei de Política Criminal** a **um conjunto de `CrimeTipo`** marcados como prioritários:
   - Campos: `lei` (ex.: `'Lei 51/2023'`), `biennium` (ex.: `'2023-2025'`), `vigente_desde`, `vigente_ate` (nullable), `is_active` (bool — a versão actualmente em vigor), e a relação M2M para os `CrimeTipo` abrangidos.
   - Cada associação config↔tipo distingue o **eixo**: `INVESTIGACAO` (Art. 5.º — **operativo**) e `PREVENCAO` (Art. 4.º — **informativo**). A prioridade efectiva da `Occurrence` resolve-se pelo eixo `INVESTIGACAO` da versão activa.
   - "Nova lei = nova versão de config": publicar a Lei 2025-2027 é **criar uma nova `PoliticaCriminalPrioridade`** (e marcá-la activa), **sem alterar código**.

5. **`Occurrence.priority` é binária e derivada, com override manual auditável.**
   - `priority`: `TextChoices` com **dois** valores — `PRIORITARIA` / `NORMAL`. **Não** P1-P4.
   - `priority_source`: `TextChoices` — `LEI` (derivada da `PoliticaCriminalPrioridade` activa via `crime_type`) ou `MANUAL` (override explícito do agente).
   - Na criação, o sistema deriva `priority` a partir do `crime_type` e da config activa (eixo `INVESTIGACAO`), com `priority_source=LEI`. O agente pode **elevar** manualmente para `PRIORITARIA` (`priority_source=MANUAL`) — caso operacional legítimo (p.ex. contexto agravante não capturado pelo tipo). Como a `Occurrence` é imutável, isto fixa-se **na criação** (pré-gravação), não há edição posterior.

6. **Alertas de crime prioritário na consola.** Quando uma `Occurrence` é criada com `priority=PRIORITARIA`:
   - regista-se um evento no `AuditLog` que o **feed de actividade** (endpoint read-only de T06) exibe com destaque;
   - o **hero** mostra um **badge** de crime prioritário.
   O alerta é uma **leitura** do estado (feed + badge), não uma escrita adicional sobre a prova — não toca os invariantes de imutabilidade.

7. **Mapeamento curado lei↔tabela como artefacto de dados versionado.** As frases da lei (Art. 4.º e Art. 5.º) traduzem-se para códigos N3/N2 da Tabela 2024 num mapa curado e revisto (ex.: "homicídio" → tipo `1`; "violência doméstica" → tipos `194`/`195`/`196`; "burla cometida através de meio informático" → tipo `53`; "extorsão" → tipo `57`; "cibercriminalidade" → subcategoria da legislação avulsa). Este mapa é a fonte de verdade do seed da `PoliticaCriminalPrioridade` e produz-se num **curadoria com revisão cruzada** (a coerência semântica lei↔código é o ponto de falha mais provável).

8. **Implicação para a Fase 3 (`a especificação de art direction`).** A colorbar/legenda do hero e a coluna "Pri." passam de P1-P4 para **2 estados** (`prioritária`/`normal`). Actualizar a §Hero do `art direction` e o `geo-hero` em conformidade. (Trabalho de Fase 3 — apenas registado aqui.)

## Alternatives Considered

- **Manter a `description` em texto livre + uma `priority` P1-P4 manual** (o que o mockup V20 desenhava antes desta decisão). Rejeitado — P1-P4 é arbitrário, não tem ancoragem legal, depende do juízo individual do agente e não agrega com a estatística oficial. A binária `prioritária`/`normal` **derivada da lei** é defensável em sede de defesa académica e reproduzível.

- **Codificar a lista de crimes prioritários em Python** (constante/enum no código). Rejeitado — a Lei de Política Criminal muda **a cada biénio**. Hard-coding obrigaria a um deploy a cada lei nova e perderia o histórico de "que ocorrência foi prioritária segundo que lei". A `PoliticaCriminalPrioridade` versionada torna a transição de biénio uma operação de dados (seed), não de código.

- **Usar o eixo do Art. 4.º (prevenção) como operativo.** Rejeitado — o ForensiQ é uma ferramenta de **investigação** de prova já apreendida, não de prevenção/policiamento. O Art. 5.º (investigação prioritária) é o eixo semanticamente correcto. O Art. 4.º guarda-se como flag informativa porque tem valor analítico, mas não governa a `priority` operativa.

- **Modelar a taxonomia numa só tabela plana (lista de tipos com categoria como texto).** Rejeitado — perde a hierarquia oficial de 3 níveis, impede o selector em cascata e parte a agregação por categoria que o INE usa. As 3 tabelas espelham 1:1 a nomenclatura oficial.

- **Semear da Tabela de 2008** (`tabela-crimes.pdf`, a que está no repo). Rejeitado como fonte canónica — está desactualizada face à 2024 (faltam tipos introduzidos por legislação posterior). Mantém-se apenas como referência histórica citável.

- **Tornar `crime_type` opcional / editável depois.** Rejeitado — colidiria com a imutabilidade da `Occurrence` (0013) e com D8/T18 (POST-only). Um campo "editável depois" numa entidade que a BD recusa actualizar é uma contradição que dá 500 em produção e mutação silenciosa em SQLite de teste. `crime_type` é obrigatório e de criação.

## Consequences

### Positivas

- **A prioridade ganha semântica jurídica.** "Prioritária" passa a significar "crime de investigação prioritária segundo a Lei 51/2023, Art. 5.º" — uma afirmação verificável, não um juízo arbitrário. Bom material para a defesa.
- **Linguagem comum com a estatística oficial.** A classificação em 3 níveis com códigos da Tabela 2024 permite produzir números comparáveis com o INE/DGPJ e habilita estatística por categoria alinhada.
- **Entrada de dados mais rápida e correcta.** O selector em cascata N1→N2→N3 estrutura o que era prosa livre; reduz erro e ambiguidade.
- **Transição de biénio sem deploy.** Publicada uma nova lei, basta semear uma nova `PoliticaCriminalPrioridade` e marcá-la activa. O histórico de "que ocorrência foi prioritária segundo que lei" fica preservado por desenho.
- **Não toca os invariantes forenses.** As 3 tabelas + a config são **dados de referência**; não são prova, não levam triggers de imutabilidade, não tocam `Evidence`/`ChainOfCustody`/`AuditLog`. O `crime_type`/`priority`/`priority_source` na `Occurrence` são **aditivos** e de **criação** — coerentes com a imutabilidade já em vigor (0013).

### Negativas / Trade-offs

- **O mapeamento lei↔tabela é trabalho de curadoria sujeito a erro.** As frases da lei nem sempre têm correspondência 1:1 com um código N3 (umas mapeiam para vários tipos, outras para uma subcategoria inteira). É o ponto de falha mais provável — daí o processo de revisão cruzada. Um mapeamento errado classifica mal a prioridade de ocorrências reais.
- **A Tabela 2024 e a Lei 51/2023 desactualizam-se.** A 2024 será sucedida por novas versões; a Lei 51/2023 termina em 2025. A `PoliticaCriminalPrioridade` versionada mitiga a lei; a taxonomia exige um re-seed quando o CSE publicar nova tabela. Há que documentar o procedimento de actualização.
- **`crime_type` obrigatório aumenta o atrito do formulário de criação.** Quem regista a ocorrência tem de classificar o crime já na apreensão, quando a informação pode ser preliminar. Aceitável (a classificação pode ser refinada noutra ocorrência/processo a montante), mas é fricção real — registar como limitação.
- **Override manual abre uma janela de subjectividade.** `priority_source=MANUAL` permite elevar a prioridade fora da lei. É necessário, mas dilui a pureza do "derivado da lei". Mitigação: o `priority_source` torna a origem **explícita e auditável** — quem lê a ocorrência sabe se a prioridade veio da lei ou do agente.

### Impactos noutros documentos

- **`o plano interno de refactor`**: T19 e D9/D10/D11 passam de "decisão registada" a "formalizada em ADR-0014"; T03 referencia este ADR para a forma dos campos.
- **`a especificação de art direction`** (Fase 3): §Hero e `geo-hero` — colorbar/legenda de P1-P4 → 2 estados (`prioritária`/`normal`); coluna "Pri." da tabela idem.
- **`README.md`**: a secção de modelo de dados passa a descrever a taxonomia de crimes e a prioridade derivada da Política Criminal.
- **ADR-0010** (taxonomia de `Evidence`): este ADR é o seu par para a **classificação do crime** (a `Evidence` classifica o *quê* da prova; o `crime_type` classifica o *contexto* da ocorrência). Sem sobreposição.
- **ADR-0013** (GPS na custódia) e o **PASSO 0** do sequenciamento da Fase 2: T19 é track independente do GPS; arranca por obter a Tabela 2024 + este ADR.

## Implementação

### Modelos (dados de referência — `core/models.py`)

- `CrimeCategoria`: `codigo` (`PositiveSmallIntegerField`, unique, 1-6), `nome` (`CharField`). 6 registos fixos.
- `CrimeSubcategoria`: `categoria` (FK→`CrimeCategoria`, `PROTECT`), `codigo` (`PositiveSmallIntegerField`), `nome`. `unique_together = ('categoria', 'codigo')`.
- `CrimeTipo`: `subcategoria` (FK→`CrimeSubcategoria`, `PROTECT`), `codigo` (`PositiveIntegerField`, unique — o código oficial N3), `descritivo` (`CharField`), `is_active` (bool, para tipos retirados em versões futuras da tabela). `ordering = ['codigo']`.
- `PoliticaCriminalPrioridade`: `lei` (`CharField`, ex.: `'Lei 51/2023'`), `biennium` (`CharField`, ex.: `'2023-2025'`), `vigente_desde` (`DateField`), `vigente_ate` (`DateField`, null), `is_active` (bool). Relação aos tipos abrangidos via tabela intermédia explícita `PrioridadeCrimeTipo` com `crime_tipo` (FK→`CrimeTipo`) + `eixo` (`TextChoices`: `INVESTIGACAO`/`PREVENCAO`). Garantir, por constraint/validação, **uma só** versão `is_active=True`.

### Campos novos na `Occurrence` (aditivos, de criação)

- `crime_type` = `ForeignKey(CrimeTipo, on_delete=PROTECT, related_name='occurrences')` — **obrigatório** (não-nulo).
- `priority` = `CharField(choices=Priority.choices)` com `Priority = TextChoices(PRIORITARIA, NORMAL)`, default derivado na criação.
- `priority_source` = `CharField(choices=PrioritySource.choices)` com `PrioritySource = TextChoices(LEI, MANUAL)`, default `LEI`.
- **Derivação** em `Occurrence.save()`/`clean()` (na criação): se o `crime_type` está na config activa pelo eixo `INVESTIGACAO` → `PRIORITARIA`/`LEI`; senão `NORMAL`/`LEI`; o agente pode forçar `PRIORITARIA`/`MANUAL`. Como a `Occurrence` é imutável (0013), **toda** a lógica de prioridade corre **pré-gravação**.
- A migração é **puramente aditiva** (add fields + FK). Os triggers de linha de `0013_protect_occurrence` já cobrem automaticamente as colunas novas (são `FOR EACH ROW`, protegem a linha inteira) — **não** é preciso nova migração de imutabilidade.

### Migrations

- Cabeça actual da migration chain: `0017_alter_auditlog_options_auditlog_sequence`. O track GPS (ADR-0013) **reserva `0018`-`0019`** (rename `gps_lng` + GPS na custódia); para **evitar colisão de numeração** entre os tracks paralelos (T01/T02 e T19, plano interno de refactor §5), este ADR usa a faixa **`0020`-`0021`**.
- `0020_crime_taxonomy` (cria as 4 tabelas de referência) + `0021_occurrence_crime_priority` (add `crime_type`/`priority`/`priority_source` à `Occurrence`). Aditivas; sem `RunPython` de dados sobre prova; sem mexer em `0002`/`0008`/`0013`. (Se a ordem de merge dos tracks divergir, reconciliar a numeração no merge — mas a faixa fixa evita-o.)
- **Não** semear via `RunPython` na migração (mantém migrations puras de schema) — o seed dos dados de referência fica num management command (abaixo).

### Serializers / API

- `CrimeCategoriaSerializer`/`CrimeSubcategoriaSerializer`/`CrimeTipoSerializer` (read-only) + endpoints **read-only** para alimentar o selector em cascata. Não comprometem imutabilidade (GET-only).
- `OccurrenceSerializer` (`core/serializers.py:126-143`): acrescentar `crime_type` (writable, obrigatório na criação), e `priority`/`priority_source` como **read-only** (derivados pelo modelo), exceto o sinal de override manual passado no POST. Manter `priority`/`priority_source` fora de qualquer caminho de update (a `OccurrenceViewSet` é POST-only por D8/T18).
- **Pré-condição (D8/T18):** a decisão **D8** (`plano interno de refactor` §6, decisão do dono 2026-05-30) torna a `OccurrenceViewSet` POST-only; executa-se em **T18**, *antes* de T19 — adicionar `http_method_names = ['get','post','head','options']` à `OccurrenceViewSet` (`core/views.py:203`, hoje `ModelViewSet` sem restrição), senão a API continua a expor PUT/PATCH/DELETE que o trigger 0013 recusa (500 em produção, mutação silenciosa em SQLite de teste). O teste `PUT/PATCH/DELETE → 405` (abaixo) verifica esta pré-condição.

### Seed (management command idempotente)

- Novo comando `seed_crime_taxonomy` (separado do `seed_demo`, que é dados de demonstração): popula `CrimeCategoria`→`CrimeSubcategoria`→`CrimeTipo` a partir de um dataset estruturado derivado da **Tabela 2024** (Modelo 262), e cria a `PoliticaCriminalPrioridade` de `'Lei 51/2023'` com as associações `PrioridadeCrimeTipo` (eixos `INVESTIGACAO`/`PREVENCAO`) a partir do **mapa curado** lei↔tabela. Idempotente (`update_or_create` por código oficial).
- Pré-carregar a versão `2025-2027` como `is_active=False`, pronta a activar quando a lei for promulgada (sem código novo).

### Mapeamento lei↔tabela

- Artefacto de dados versionado (ex.: `core/data/mapa_politica_criminal.{json,py}`) com, por cada alínea do Art. 4.º e do Art. 5.º, a lista de códigos N3 (ou N2, quando a frase abrange uma subcategoria inteira) e o eixo. Produzido por **curadoria com revisão cruzada** — a verificação confirma (a) cobertura de todas as alíneas, (b) que cada código existe na Tabela 2024, (c) ausência de mapeamentos contraditórios.

### Testes

- Taxonomia: integridade hierárquica (cada `CrimeTipo` tem subcategoria e categoria válidas), unicidade de códigos, seed idempotente.
- Derivação de prioridade: crime do Art. 5.º → `PRIORITARIA`/`LEI`; crime fora da lista → `NORMAL`/`LEI`; override → `PRIORITARIA`/`MANUAL`.
- Versionamento: exactamente uma `PoliticaCriminalPrioridade` activa; trocar a versão activa muda a derivação de **novas** ocorrências sem tocar as antigas (imutabilidade — as ocorrências já criadas mantêm a `priority` gravada).
- `Occurrence` POST-only (D8/T18): `crime_type` obrigatório no POST; PUT/PATCH/DELETE → 405.
- Alertas: criar ocorrência prioritária regista evento no `AuditLog` que o feed (T06) exibe.

## Referências

- `o plano interno de refactor` — §3 (T03, T19), §6 (D8, D9, D10, D11), §7 (verificação da `Occurrence` imutável vs ViewSet mutável).
- ADR-0013 — GPS na `ChainOfCustody` (par estrutural deste ADR na Fase 2).
- ADR-0010 — Taxonomia de `Evidence` (classifica a prova; este ADR classifica o crime/contexto).
- `core/models.py:217-315` — `Occurrence` actual (sem `crime_type`/`priority`).
- `core/migrations/0013_protect_occurrence.py:33-41` — triggers de imutabilidade da `Occurrence` (PostgreSQL).
- `core/views.py:203` — `OccurrenceViewSet` (hoje `ModelViewSet` sem `http_method_names`; alvo de D8/T18).
- `core/serializers.py:126-143` — `OccurrenceSerializer` actual.
- Lei n.º 51/2023, de 28 de agosto — Lei de Política Criminal 2023-2025 (DR n.º 166/2023, Série I); Art. 4.º (crimes de prevenção prioritária) e Art. 5.º (crimes de investigação prioritária). Ficheiro de contexto no repo: `Lei n.º 51_2023, de 28 de Agosto.html`.
- Tabela de Crimes Registados — Conselho Superior de Estatística (CSE/INE) / DGPJ-SIEJ, Modelo 262 ("Mapa para Notação de Crimes"), estrutura de 3 níveis. Versão canónica: 2024. Referência histórica no repo: `tabela-crimes.pdf` (versão 2008, DR 2.ª série n.º 39, 25-02-2008). <https://estatisticas.justica.gov.pt/sites/siej/pt-pt/Documents/DM_Criminalidade_Registada.pdf>
- DGPJ — Estatísticas sobre crimes registados: <https://dgpj.justica.gov.pt/>
- Lei n.º 17/2006, de 23 de maio — Lei-Quadro da Política Criminal (habilita a Lei 51/2023).
