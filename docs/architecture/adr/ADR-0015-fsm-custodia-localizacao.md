# ADR-0015: FSM da cadeia de custódia ramificada (CPP Art. 178.º) + localização/custódio por transição

## Status

Accepted — 2026-05-30

Formaliza o tema **T20** do `docs/refactor/REFACTOR_MANIFEST.md` (Fase 2 do refactor) e as decisões Q1/Q2/Q3 do dono tomadas em 2026-05-30. **Depende de** e estende o ADR-0013 (campos GPS na `ChainOfCustody` + entrada versionada no hash). **Liga-se** ao ADR-0012 / T18 (intake = recepção/validação no laboratório).

## Data

2026-05-30

## Context

A `ChainOfCustody` é, hoje, um **ledger append-only com hash-chain SHA-256** cuja máquina de estados é **estritamente linear**. O validador vive no modelo (`clean()`), não nas views, e o conjunto de transições é declarado em `models.py:944-953`:

```python
VALID_TRANSITIONS = {
    '': [CustodyState.APREENDIDA],                                   # estado inicial
    CustodyState.APREENDIDA: [CustodyState.EM_TRANSPORTE],
    CustodyState.EM_TRANSPORTE: [CustodyState.RECEBIDA_LABORATORIO],
    CustodyState.RECEBIDA_LABORATORIO: [CustodyState.EM_PERICIA],
    CustodyState.EM_PERICIA: [CustodyState.CONCLUIDA],
    CustodyState.CONCLUIDA: [CustodyState.DEVOLVIDA, CustodyState.DESTRUIDA],
    CustodyState.DEVOLVIDA: [],                                      # terminal
    CustodyState.DESTRUIDA: [],                                      # terminal
}
```

São **7 estados** (`CustodyState`, `models.py:934-941`). O grafo é um corredor único: `APREENDIDA → EM_TRANSPORTE → RECEBIDA_LABORATORIO → EM_PERICIA → CONCLUIDA → {DEVOLVIDA | DESTRUIDA}`. O validador rejeita qualquer transição fora deste corredor (`clean()`, `models.py:1034-1050`).

Este corredor **não corresponde ao percurso legal real** de uma prova apreendida em Portugal. O Código de Processo Penal (DL 78/87, **Art. 178.º**) impõe ramificações que o modelo linear não consegue representar:

- A apreensão é feita pelo OPC; logo após, faz-se exame directo e avaliação com registo fotográfico.
- A apreensão tem de ser **validada pela autoridade judiciária no prazo máximo de 72 horas** (Art. 178.º/6). Se **não for validada** (ou se a apreensão for desnecessária), há **levantamento e restituição imediata** ao titular.
- Há despacho para perícia/exame; sem despacho, o bem fica **à guarda**.
- Os destinos legais possíveis incluem **restituição** ao proprietário ou a terceiro de boa-fé (Art. 178.º/7), **perda a favor do Estado** (Art. 109.º a 111.º do Código Penal) e **destruição/inutilização**.

O modelo linear actual só consegue representar o caminho «feliz» (apreensão → laboratório → perícia → conclusão → devolução/destruição). Não tem como exprimir a janela de validação das 72h, a restituição por não-validação, o encaminhamento para um segundo laboratório, nem a perda a favor do Estado. Em consequência, a prova que segue um ramo legal legítimo **não consegue ser registada** sem forçar estados que mentem sobre o que aconteceu.

Há, além disso, uma confusão de eixos no modelo actual: o `new_state` mistura **estado de processo** (onde está a prova *no processo judicial*) com **localização física** (onde está a prova *no espaço*). `RECEBIDA_LABORATORIO` é simultaneamente um estado de processo e uma afirmação de lugar. Não existem campos para **onde** a prova está nem para **quem** a custodia em cada transição. A `ChainOfCustody` não tem hoje qualquer campo de localização (confirmado em `models.py:919-1012` — só `evidence`, `previous_state`, `new_state`, `agent`, `timestamp`, `observations`, `record_hash`, `sequence`).

O hash-chain actual (`compute_record_hash`, `models.py:1085-1094`) cobre `previous_hash | seq | evidence_id | previous_state | new_state | agent_id | timestamp_iso | observations`. **Não inclui GPS nem localização** — essa entrada é tratada, de forma aditiva e versionada, pelo ADR-0013. Este ADR não toca a fórmula do hash; apenas garante que os campos novos de localização entram pela via já decidida no ADR-0013 (segmento opcional versionado).

Já existe infra-estrutura de geocodificação reutilizável: `ReverseGeocodeView` (`views.py:1003-1088`) é um **proxy server-side para o Nominatim** (OpenStreetMap), com `throttle_scope = 'reverse_geocode'` (10 req/min em produção — `settings.py:148`), motivado por RGPD: as coordenadas das ocorrências policiais **nunca saem do browser do agente para terceiros**. A CSP autoriza `nominatim.openstreetmap.org` em `connect-src` e `*.tile.openstreetmap.org` em `img-src` (`middleware.py:123-124`).

Confrontado com o desenho linear em 2026-05-30, o dono do projecto decidiu (Q1/Q2/Q3, registadas em REFACTOR_MANIFEST §3-T20 e §6):

- **Q1 — FSM ramificada fiel ao CPP** (~12 estados), aditiva sobre os 7 actuais.
- **Q2 — dois eixos**: separar o **estado** (processo) da **localização/custódio**, com campos próprios por registo do ledger.
- **Q3 — estabelecimentos via OSM/Nominatim**, sem tabela curada de instalações; reutilizar a infra de reverse-geocode, estendida a pesquisa de POIs próximos.

A restrição inquebrável que enquadra todo este ADR: **o ledger é append-only imutável**. As três camadas de imutabilidade (triggers PG das migrações `0002`/`0008`/`0013`, admin readonly, API POST-only) estão intactas e não podem regredir. **Nenhum registo antigo pode ser reescrito.** Logo, qualquer mudança aqui é **aditiva** — novos *choices* de estado, novo grafo de transições que **aceita os legados**, novos campos que entram pela migração aditiva do ADR-0013.

## Decision

1. **Adicionar 4 estados novos ao `CustodyState`** (TextChoices em `models.py:934`), preservando os 7 existentes exactamente como estão (mesmos valores de BD, mesmos rótulos):

   - `A_AGUARDAR_VALIDACAO` — "A aguardar validação (≤72h)" — janela do Art. 178.º/6.
   - `VALIDADA` — "Apreensão validada" — validação pela autoridade judiciária.
   - `ENCAMINHADA` — "Encaminhada (outro laboratório)" — transferência para outro laboratório, público ou privado.
   - `PERDIDA_FAVOR_ESTADO` — "Perdida a favor do Estado" — Art. 109.º-111.º CP.

   Mantêm-se `APREENDIDA`, `EM_TRANSPORTE`, `RECEBIDA_LABORATORIO`, `EM_PERICIA`, `CONCLUIDA`, `DEVOLVIDA` (terminal), `DESTRUIDA` (terminal). Total: **11 estados** (2 terminais).

2. **Substituir o `VALID_TRANSITIONS` linear por um grafo ramificado** que **aceita todas as transições legadas** (nenhum registo histórico fica inverificável ou irreproduzível). O validador continua **no modelo** (`clean()`), nunca nas views. Grafo proposto (ver §Implementação para o dicionário literal):

   ```
                          (sem estado anterior)
                                  │
                                  ▼
                            APREENDIDA
                          ┌──────┴───────────────┐
                          ▼                       ▼
                  A_AGUARDAR_VALIDACAO       EM_TRANSPORTE ──┐  (legado: apreensão→transporte directo)
                    ┌─────┴──────┐                           │
            (validada)      (não validada / 72h)             │
                  ▼              ▼                            │
              VALIDADA       DEVOLVIDA⛔ (restituição)        │
                  │                                          │
                  ▼                                          │
            EM_TRANSPORTE ◄──────────────────────────────────┘
                  │
                  ▼
          RECEBIDA_LABORATORIO
            ┌─────┴───────────────┐
            ▼                     ▼
        EM_PERICIA           ENCAMINHADA (outro lab) ──► EM_TRANSPORTE / EM_PERICIA
            │
            ▼
        CONCLUIDA
       ┌────┴───────────────┐
       ▼                    ▼
   DEVOLVIDA⛔        PERDIDA_FAVOR_ESTADO
   (restituição)            │
                            ▼
                       DESTRUIDA⛔
   ```

   Ramos legais cobertos: (a) **não-validada → restituição** (`A_AGUARDAR_VALIDACAO → DEVOLVIDA`); (b) **sem despacho → guarda → restituição** (modelado por `VALIDADA → DEVOLVIDA`, restituição sem perícia); (c) **perícia concluída → restituição** (`CONCLUIDA → DEVOLVIDA`) **ou perda a favor do Estado → destruição** (`CONCLUIDA → PERDIDA_FAVOR_ESTADO → DESTRUIDA`); (d) **encaminhamento** para segundo laboratório (`RECEBIDA_LABORATORIO → ENCAMINHADA`).

3. **Compatibilidade retroactiva total do validador.** Toda a transição que era válida no `VALID_TRANSITIONS` linear continua válida no grafo novo. Em concreto, mantêm-se: `'' → APREENDIDA`, `APREENDIDA → EM_TRANSPORTE`, `EM_TRANSPORTE → RECEBIDA_LABORATORIO`, `RECEBIDA_LABORATORIO → EM_PERICIA`, `EM_PERICIA → CONCLUIDA`, `CONCLUIDA → {DEVOLVIDA, DESTRUIDA}`. Acrescentam-se ramos; **não se remove nenhum**. Os registos legados, ao serem revalidados (ex.: ao recalcular a cadeia para auditoria), continuam a passar.

4. **Dois eixos — separar estado de localização/custódio.** Cada registo do ledger passa a transportar, além de `new_state`, os campos de **localização** e o **tipo de custódio**:

   - `gps_lat`, `gps_lng`, `gps_accuracy_m` — **campos do ADR-0013** (precisão máxima, `decimal_places=7`, `gps_accuracy_m` como metadado de precisão reportada pelo dispositivo). Convenção `gps_lng` (decisão D2). Reutilizam-se exactamente os campos que o ADR-0013 acrescenta à `ChainOfCustody`; este ADR não cria campos GPS novos.
   - `location_name` (`CharField`, texto) — nome legível do local da transição, preenchido a partir de POIs OSM (ver decisão 6). Diz *em que edifício/marco*.
   - `storage_location` (`CharField`, texto livre) — localização **interna** de armazenamento, para os estados de laboratório/esquadra (ex.: "Armário B-12, Sala 3"). Decisão **D5** do REFACTOR_MANIFEST: "o GPS dá o sítio, o armário dá a gaveta". Distinto do `location_name` (POI OSM): este diz *em que edifício*, o `storage_location` diz *em que gaveta*. Texto livre (o perito/agente escreve); entra no hash pelo segmento `|loc=` fixado no ADR-0013.
   - `custodian_type` (`TextChoices`) — quem custodia a prova nesta transição. Enum: `LOCAL_CRIME` (local do crime), `ESQUADRA`, `LAB_PUBLICO`, `LAB_PRIVADO`, `TRIBUNAL`, `DEPOSITARIO`, `PROPRIETARIO`.

   O **estado** diz *em que ponto do processo* a prova está; a **localização + custódio** dizem *onde está e quem a tem*. São ortogonais: a mesma `EM_TRANSPORTE` pode ter custódio `ESQUADRA` (saída) ou `LAB_PUBLICO` (chegada), e a `ENCAMINHADA` pode ter `LAB_PUBLICO` ou `LAB_PRIVADO`.

5. **Estados terminais colocam a prova em terminal.** `DEVOLVIDA` e `DESTRUIDA` continuam a ser estados de saída do grafo (sucessores `[]`). Após uma transição terminal, o validador recusa qualquer nova transição para essa evidência (o sucessor de um terminal é o conjunto vazio — comportamento já existente em `models.py:951-952`, preservado). `PERDIDA_FAVOR_ESTADO` **não** é terminal: é o passo legal que precede `DESTRUIDA` (a perda a favor do Estado pode anteceder destruição ou guarda em depósito do Estado).

6. **`location_name` vem de POIs OSM, sem tabela curada.** Reutiliza-se e estende-se `ReverseGeocodeView` (`views.py:1003`) com o mesmo `throttle_scope = 'reverse_geocode'` e o mesmo princípio RGPD (proxy server-side; coordenadas não saem do browser). A extensão acrescenta **pesquisa de POIs próximos** (esquadras, laboratórios, tribunais, marcos da cena do crime) via **Overpass API** (`overpass-api.de`), devolvendo uma lista de candidatos que o agente selecciona. **Não** há tabela curada de instalações: tanto a cena do crime (bombas de combustível, marcos, edifícios) como os nós oficiais (esquadras/labs/tribunais) vêm todos do OSM; o agente escolhe o POI mais adequado. Mantém-se **sempre** o par GPS + nome textual: o GPS é a fonte de verdade da posição, o `location_name` é o rótulo humano.

7. **Entrada da localização no hash — serialização fixada no ADR-0013.** Os campos `gps_lat/gps_lng/gps_accuracy_m` (segmento `|gps=`) e `location_name`/`custodian_type`/`storage_location` (segmento `|loc=`) entram no `compute_record_hash` **de forma versionada** — segmento anexado só quando o grupo é não-vazio, texto livre escapado, ordem não-comutável, coordenadas quantizadas. A serialização byte-a-byte (ordem, escaping, presença, quantização) é **fixada integralmente no ADR-0013**, dono único da fórmula; este ADR **define** os campos e a sua semântica, mas **não** redefine a sua serialização. Registos históricos (sem GPS, sem localização) recalculam exactamente o mesmo hash de hoje; o `previous_hash` continua a encadear inalterado.

8. **Toda a mudança é aditiva.** Novos *choices*, novo grafo que aceita os legados, novos campos pela migração aditiva do ADR-0013. **Nenhum registo do ledger é reescrito.** As três camadas de imutabilidade ficam intactas: os triggers de linha da migração `0002` (`trg_custody_no_update`/`trg_custody_no_delete`, `0002_add_immutability_triggers.py:73-81`) cobrem automaticamente as colunas novas porque disparam por linha (a `0008` é apenas documental e Evidence-only — `forensiq_evidence_immutable_fields()`, não contém triggers de custódia); o admin continua readonly; o `ChainOfCustodyViewSet` continua POST-only (`http_method_names = ['get','post','head','options']`, `views.py:657`).

## Alternatives Considered

- **Manter a FSM linear e modelar os ramos legais em `observations`** (texto livre). Rejeitado — a janela das 72h, a restituição por não-validação e a perda a favor do Estado são **estados de processo**, não anotações. Enterrá-los em texto livre impede consultas, alertas e a verificação de que a prova seguiu um percurso legalmente válido. Mente sobre o estado real da prova.

- **Permitir UPDATE dos registos para "corrigir" o estado** quando um ramo novo é necessário. Rejeitado de forma absoluta — viola o invariante append-only e as três camadas de imutabilidade. Reescrever um registo do ledger destrói a cadeia de custódia e a sua admissibilidade. A solução é **sempre** acrescentar um novo registo, nunca editar um antigo.

- **Substituir `VALID_TRANSITIONS` por um grafo que abandona transições legadas** (ex.: forçar `APREENDIDA → A_AGUARDAR_VALIDACAO` obrigatório, removendo `APREENDIDA → EM_TRANSPORTE` directo). Rejeitado — tornaria os registos históricos inválidos à revalidação e quebraria a reprodutibilidade da cadeia para auditoria. O grafo novo é estritamente um **superconjunto** do linear.

- **Tabela curada de instalações** (esquadras/labs/tribunais como dados de referência, à imagem da taxonomia de crimes do T19). Rejeitado pela decisão Q3 — o universo de locais (cena do crime incluída) é aberto e geográfico; uma tabela curada nunca cobriria as cenas de crime e duplicaria informação que o OSM já tem com qualidade. O OSM dá tanto os nós oficiais como os marcos da cena. Revisível se o feedback do orientador pedir uma lista controlada de laboratórios oficiais.

- **Capturar a localização num eixo único, fundido no estado** (manter `new_state` a carregar lugar, ex.: estados `EM_TRANSPORTE_PARA_LAB_X`). Rejeitado — explode a cardinalidade da FSM (estado × lugar) e mistura dois eixos ortogonais. A separação estado/localização (Q2) mantém a FSM pequena e legível e deixa o lugar variar livremente.

- **Fazer a localização entrar no hash de forma não-versionada** (anexar sempre o segmento GPS/localização à fórmula). Rejeitado — partiria o recálculo de **todos** os hashes históricos (registos antigos não têm GPS). A entrada versionada (segmento opcional, decisão D1 do ADR-0013) é a única coerente com o append-only.

## Consequences

### Positivas

- **A cadeia passa a contar a verdade legal.** Uma prova que é apreendida, não validada em 72h e restituída tem um percurso registável e auditável; antes, era inexprimível.
- **Dois eixos clarificam a leitura.** O estado responde "em que ponto do processo"; a localização/custódio responde "onde e com quem". O mini-mapa "Cadeia" da v2 ganha nós nomeados e a timeline ganha custódio por passo.
- **Invariantes preservados.** Mudança 100% aditiva: hash-chain inalterado, três camadas de imutabilidade intactas, validador no modelo, registos legados sempre válidos. Não há regressão forense.
- **Reaproveitamento da infra RGPD-safe.** O reverse-geocode e o seu throttle/CSP já existem; estendê-los a POIs custa pouco e mantém a garantia de que as coordenadas não saem do browser para terceiros.
- **Base para alertas.** Estados como `A_AGUARDAR_VALIDACAO` permitem alertas de prazo (72h a expirar), úteis na consola da v2 (liga ao feed do T06).

### Negativas / Trade-offs

- **Mais estados = mais ramos a testar.** O grafo ramificado tem mais arestas que o corredor linear; a suite de testes da FSM cresce (todos os ramos legais + confirmação de que os legados continuam válidos). É trabalho real, não cosmético.
- **Dependência forte do ADR-0013.** Este ADR não pode ir a produção antes de o ADR-0013 fixar a ordem dos campos GPS/localização no hash versionado. Acoplamento assumido e sequenciado (T01 antes de T20 no REFACTOR_MANIFEST §5).
- **Nova origem externa (Overpass).** A pesquisa de POIs introduz dependência do `overpass-api.de` (latência, rate-limits, disponibilidade). Mitigação: timeout curto à imagem dos 5s do Nominatim (`views.py:1019`), degradação graciosa (502 + entrada manual do `location_name`), e o mesmo throttle `reverse_geocode`.
- **CSP a actualizar.** Autorizar Overpass exige acrescentar `https://overpass-api.de` a `connect-src` em `middleware.py:123` (regra do projecto: alteração de allowlist CSP exige middleware + ADR juntos — este ADR satisfaz o requisito). Sem isto, em produção (CSP enforced) a pesquisa de POIs falha silenciosamente, tal como o tile CartoDB do T08.
- **`PERDIDA_FAVOR_ESTADO` não-terminal pode confundir.** Decisão deliberada (precede destruição/depósito), mas exige documentação clara para não se interpretar como saída do grafo.

### Impactos noutros documentos

- **`docs/architecture/adr/ADR-0013-gps-cadeia-custodia.md`**: fixa a serialização dos campos `gps_lat/gps_lng/gps_accuracy_m` (segmento `|gps=`) e `location_name`/`custodian_type`/`storage_location` (segmento `|loc=`) no `compute_record_hash`. Este ADR-0015 **consome** essa fórmula e define a semântica dos campos `|loc=`.
- **`docs/refactor/REFACTOR_MANIFEST.md`**: T20 passa de "decisão" a "ADR escrito"; referência cruzada a este ficheiro na linha do T20 (§3) e no sequenciamento (§5).
- **`docs/refactor/art-direction.md`** (Fase 3): o `transition_modal` ganha captura GPS + selecção de POI (OSM) + selector de `custodian_type`; o mini-mapa "Cadeia" mostra a jornada com nós nomeados. A legenda de estados da timeline passa de 7 para 11 rótulos.
- **`src/backend/core/middleware.py`**: `connect-src` a incluir `https://overpass-api.de` (par com a actualização CSP do T08).
- **Documentação de conformidade ISO/IEC 27037 / `docs/scope/`**: a FSM ramificada reforça a rastreabilidade do percurso legal da prova; revisitar a matriz de traceabilidade para refletir os novos estados.

## Implementação

Notas concretas para a execução do T20 (Fase 2), **sempre depois** de T01/ADR-0013 fechado.

### Estados (aditivo, `models.py:934`)

Acrescentar ao `CustodyState`, sem tocar os 7 existentes:

```python
A_AGUARDAR_VALIDACAO = 'A_AGUARDAR_VALIDACAO', 'A aguardar validação (≤72h)'
VALIDADA = 'VALIDADA', 'Apreensão validada'
ENCAMINHADA = 'ENCAMINHADA', 'Encaminhada (outro laboratório)'
PERDIDA_FAVOR_ESTADO = 'PERDIDA_FAVOR_ESTADO', 'Perdida a favor do Estado'
```

`previous_state`/`new_state` são `CharField(max_length=25)` (`models.py:970-981`) — confirmar que `A_AGUARDAR_VALIDACAO` (20 chars) e `PERDIDA_FAVOR_ESTADO` (20 chars) cabem. Cabem; **não alterar `max_length`** sem necessidade (alteração de coluna numa tabela protegida por triggers deve ser feita com cuidado e `DROP IF EXISTS` no padrão das migrações `0002`/`0013`).

### Grafo de transições (substituição de `VALID_TRANSITIONS`, `models.py:944`)

```python
VALID_TRANSITIONS = {
    '': [CustodyState.APREENDIDA],
    CustodyState.APREENDIDA: [
        CustodyState.A_AGUARDAR_VALIDACAO,
        CustodyState.EM_TRANSPORTE,            # legado preservado
    ],
    CustodyState.A_AGUARDAR_VALIDACAO: [
        CustodyState.VALIDADA,
        CustodyState.DEVOLVIDA,                # não validada → restituição
    ],
    CustodyState.VALIDADA: [
        CustodyState.EM_TRANSPORTE,
        CustodyState.DEVOLVIDA,                # sem despacho → guarda → restituição
    ],
    CustodyState.EM_TRANSPORTE: [CustodyState.RECEBIDA_LABORATORIO],   # legado
    CustodyState.RECEBIDA_LABORATORIO: [
        CustodyState.EM_PERICIA,               # legado
        CustodyState.ENCAMINHADA,              # outro laboratório
    ],
    CustodyState.ENCAMINHADA: [
        CustodyState.EM_TRANSPORTE,
        CustodyState.EM_PERICIA,
    ],
    CustodyState.EM_PERICIA: [CustodyState.CONCLUIDA],                 # legado
    CustodyState.CONCLUIDA: [
        CustodyState.DEVOLVIDA,                # legado
        CustodyState.DESTRUIDA,                # legado
        CustodyState.PERDIDA_FAVOR_ESTADO,     # perda a favor do Estado
    ],
    CustodyState.PERDIDA_FAVOR_ESTADO: [CustodyState.DESTRUIDA],
    CustodyState.DEVOLVIDA: [],                # terminal
    CustodyState.DESTRUIDA: [],                # terminal
}
```

Verificação obrigatória: para cada chave/valor do `VALID_TRANSITIONS` **antigo**, a aresta tem de continuar presente no novo (teste automático no §Testes). O `clean()` (`models.py:1034-1050`) **não muda** — continua a consultar `VALID_TRANSITIONS.get(self.previous_state, [])` e a rejeitar `new_state` fora da lista. Validador permanece no modelo.

### Campos novos

- `gps_lat`, `gps_lng`, `gps_accuracy_m` — **criados pela migração aditiva do ADR-0013** (não por este ADR). Convenção `gps_lng`, `decimal_places=7` (par com `Occurrence.gps_lat`/`gps_lon`, `models.py:243-258`), `null=True`.
- `location_name = models.CharField(max_length=255, blank=True, default='')` — nome do POI OSM (edifício/marco).
- `storage_location = models.CharField(max_length=120, blank=True, default='')` — localização interna de armazenamento (armário/sala), texto livre (D5); relevante sobretudo em estados de laboratório/esquadra.
- `custodian_type = models.CharField(max_length=20, choices=CustodianType.choices, blank=True, default='')`, com:

  ```python
  class CustodianType(models.TextChoices):
      LOCAL_CRIME = 'LOCAL_CRIME', 'Local do crime'
      ESQUADRA = 'ESQUADRA', 'Esquadra'
      LAB_PUBLICO = 'LAB_PUBLICO', 'Laboratório público'
      LAB_PRIVADO = 'LAB_PRIVADO', 'Laboratório privado'
      TRIBUNAL = 'TRIBUNAL', 'Tribunal'
      DEPOSITARIO = 'DEPOSITARIO', 'Depositário'
      PROPRIETARIO = 'PROPRIETARIO', 'Proprietário'
  ```

  `blank=True, default=''` para os registos legados (que não têm custódio) continuarem válidos. Em registos novos, recomendar (não obrigar a nível de BD) o preenchimento via validação de serializer.

### Migração (aditiva)

- `location_name` e `custodian_type` numa migração `AddField` simples (no-op para triggers — os `trg_custody_no_update`/`no_delete` de `0002` cobrem as colunas novas automaticamente, pois disparam por linha, não por coluna).
- **Não criar trigger novo**; os de `0002_add_immutability_triggers.py:73-81` já bastam.
- **Não** mexer em `0002`/`0008`/`0013` nem squashar migrações de imutabilidade.
- Os campos GPS vêm na migração do ADR-0013; este ADR depende dela na ordem de `dependencies`.

### Hash (serialização fixada no ADR-0013)

A `compute_record_hash` (`models.py:1052-1094`) ganha dois segmentos opcionais — `|gps=<lat>,<lng>,<acc>` e `|loc=<location_name>,<custodian_type>,<storage_location>` — cuja serialização exacta (ordem, escaping do texto livre via `_hash_escape`, regra de presença, quantização das coordenadas a 7 casas) está **fixada no ADR-0013**, dono único da fórmula. Este ADR **não** a reescreve: apenas garante que `location_name`, `custodian_type` e `storage_location` são os campos que entram no segmento `|loc=`. Registos legados (todos os campos nulos/vazios) produzem exactamente a `data` actual → mesmo hash. Precedente do projecto: o `Evidence.integrity_hash` já incorpora GPS (`models.py:626`); a `ChainOfCustody` segue o mesmo princípio, mas versionado por causa do histórico.

### Reverse-geocode estendido a POIs (`views.py:1003`)

- Acrescentar acção/endpoint de pesquisa de POIs próximos (ex.: `GET /api/nearby-pois/?lat=&lon=&radius=`), com `permission_classes = [IsAuthenticated, IsAgentOrExpert]`, `throttle_scope = 'reverse_geocode'` (reutilizar o scope), proxy server-side para Overpass (`https://overpass-api.de/api/interpreter`), timeout curto (≤5s, par com `_TIMEOUT_SECONDS`), `User-Agent` `ForensiQ/1.0 (forensiq.pt)`, e degradação graciosa (502 → entrada manual).
- Filtrar POIs por tags OSM relevantes (`amenity=police`, `amenity=courthouse`, edifícios/marcos para cena de crime).
- Devolver ao frontend só o necessário (nome, tipo, distância, lat/lon) — princípio de minimização já aplicado no `ReverseGeocodeView` (`views.py:1076-1088`).
- **CSP (coordenar com T08):** acrescentar `https://overpass-api.de` a `connect-src` (`middleware.py:123`). Esta alteração **tem de ser feita na mesma passagem/PR que o ADR de CSP do T08** (remover `cdnjs` morto + autorizar CartoDB em `img-src`), para o header final ser coerente e nenhum dos dois trabalhos reverter o outro. `connect-src` final esperado: `'self' https://nominatim.openstreetmap.org https://overpass-api.de`. Sem a autorização, a pesquisa de POIs degrada para entrada manual do `location_name` (502 → input livre).

### Serializer / API

- Estender `ChainOfCustodySerializer` (`serializers.py:384-415`) com `location_name`, `custodian_type`, `gps_lat`, `gps_lng`, `gps_accuracy_m` (estes três do ADR-0013) como **campos de escrita na criação** (não read-only — são input do agente, ao contrário de `previous_state`/`timestamp`/`record_hash` que são server-side). Validação de coerência GPS (lat e lng ambas presentes ou ambas ausentes) à imagem de `Occurrence.clean()` (`models.py:290-291`).
- `ChainOfCustodyViewSet` (`views.py:643-657`) e a acção `cascade` (`views.py:779`) **não mudam de classe base nem de `http_method_names`** — continuam POST-only.

### Testes (novo/estendido `core/tests_*`)

1. **Ramos legais novos** (um teste por aresta nova): `APREENDIDA → A_AGUARDAR_VALIDACAO`; `A_AGUARDAR_VALIDACAO → VALIDADA`; `A_AGUARDAR_VALIDACAO → DEVOLVIDA` (não validada → restituição); `VALIDADA → DEVOLVIDA` (guarda → restituição); `RECEBIDA_LABORATORIO → ENCAMINHADA`; `ENCAMINHADA → EM_PERICIA`; `CONCLUIDA → PERDIDA_FAVOR_ESTADO`; `PERDIDA_FAVOR_ESTADO → DESTRUIDA`.
2. **Compatibilidade legada** (teste guardião): assertar que **toda** aresta do `VALID_TRANSITIONS` linear original continua aceite pelo grafo novo (iterar o dicionário legado e confirmar inclusão). Evita regressão silenciosa do percurso histórico.
3. **Transições inválidas** continuam rejeitadas pelo `clean()` (ex.: `APREENDIDA → CONCLUIDA`, `DESTRUIDA → qualquer`).
4. **Terminais**: confirmar que `DEVOLVIDA`/`DESTRUIDA` recusam qualquer sucessor (sucessor `[]`).
5. **Determinismo do hash com localização preenchida** — escrever **ao mesmo tempo** que os campos (não depois), confirmando que (a) registos sem GPS/localização produzem o mesmo hash de hoje (reprodutibilidade do histórico) e (b) registos com localização produzem hash estável e recalculável. Cobre a invariante D1/ADR-0013.
6. **Imutabilidade** (ORM): `save()` em registo existente levanta `ValidationError` (`models.py:1118-1122`); `delete()` levanta `ValidationError` (`models.py:1180-1184`) — confirmar que os campos novos não abrem nenhuma via de UPDATE.
7. **API POST-only**: PUT/PATCH/DELETE em `/api/custody/<id>/` devolvem 405.
8. **Reverse-geocode/POIs**: validação de parâmetros (lat/lon obrigatórios e em gama), 502 em indisponibilidade do Overpass, e que o throttle `reverse_geocode` dispara.
9. **Trigger PG** (`skipUnless(vendor == 'postgresql')`, cursor bruto): UPDATE directo a `core_chainofcustody` com `location_name` é rejeitado pelo `trg_custody_no_update` — confirma que a 3.ª camada cobre as colunas novas (liga ao T16).

## Referências

- **ADR-0013** (`ADR-0013-gps-cadeia-custodia.md` — campos GPS na `ChainOfCustody` + serialização versionada de GPS e localização no hash; decisões D1/D2/D5). Este ADR **depende** dele para a fórmula do hash e os campos GPS/localização.
- **ADR-0012** (`docs/architecture/adr/ADR-0012-pdf-transport-guide.md`) — PDF guia de transporte; Vaga 2 (intake EXPERT-only) submete para `/api/custody/cascade/` → liga a T18 (recepção/validação no laboratório).
- **ADR-0010** — taxonomia de `Evidence` + estrutura da `ChainOfCustody`.
- `docs/refactor/REFACTOR_MANIFEST.md` — T20 (§3, detalhe), §5 (sequenciamento), §6 (decisões D1/D2/D5).
- `src/backend/core/models.py:919-1184` — `ChainOfCustody`: `CustodyState` (934-941), `VALID_TRANSITIONS` (944-953), `clean()` (1034-1050), `compute_record_hash` (1052-1094), `save()` append-only (1104-1178), `delete()` bloqueado (1180-1184).
- `src/backend/core/models.py:243-258` — `Occurrence.gps_lat/gps_lon` (`decimal_places=7`); `:290-291` — validação de coerência GPS; `:626` — GPS no `Evidence.integrity_hash` (precedente).
- `src/backend/core/views.py:643-657` — `ChainOfCustodyViewSet` POST-only; `:779-800` — acção `cascade`; `:1003-1088` — `ReverseGeocodeView` (proxy Nominatim, throttle `reverse_geocode`, RGPD).
- `src/backend/core/serializers.py:384-415` — `ChainOfCustodySerializer`.
- `src/backend/core/middleware.py:119-134` — CSP; `:123` `connect-src` (Nominatim), `:124` `img-src` (tiles OSM).
- `src/backend/core/migrations/0002_add_immutability_triggers.py:64-87` — `prevent_custody_modification()` + `trg_custody_no_update`/`trg_custody_no_delete`.
- `src/backend/core/migrations/0013_protect_occurrence.py` — padrão de trigger PG (no-op SQLite, `DROP IF EXISTS` no reverse).
- `src/backend/forensiq_project/settings.py:148` — throttle `reverse_geocode` (10/minute prod).
- **CPP — DL 78/87, Art. 178.º** (apreensão; validação ≤72h no n.º 6; restituição no n.º 7).
- **Código Penal, Art. 109.º a 111.º** — perda de instrumentos/produtos a favor do Estado.
- **ISO/IEC 27037** §5.4 — preservação da integridade e rastreabilidade da prova.
- OpenStreetMap / Nominatim — <https://nominatim.org/release-docs/latest/api/Reverse/>; Overpass API — <https://wiki.openstreetmap.org/wiki/Overpass_API>.
