# ADR-0015: ChainOfCustody como ledger de eventos (CPP Art. 154.º/158.º/178.º) — event_type, custódio e localização por registo

## Status

Accepted — 2026-05-30

Formaliza o tema **T20** do `o plano interno de refactor` (Fase 2 do refactor). **Depende do** ADR-0013 (campos GPS na `ChainOfCustody` e fórmula única do `record_hash`, que inclui já os campos definidos aqui). **Liga-se** ao ADR-0012 / T18 (intake = recepção/validação no laboratório) e ao tema de CSP T08 (autorização de origens externas no `connect-src`).

Substitui o desenho de máquina-de-estados linear que descrevia a `ChainOfCustody` (`CustodyState` + `VALID_TRANSITIONS`). A descrição antiga do T20 no `plano interno de refactor` (grafo ramificado, `VALID_TRANSITIONS` alargado, +4 estados) fica **substituída** por este modelo de ledger de eventos.

> **Nota de superveniência.** Os nomes dos eventos descritos neste ADR foram depois refinados, sem alterar a semântica de ledger aqui fixada. O ADR-0016 desdobrou a génese por proveniência — `APREENSAO` passou a `APREENSAO_OBJETO`/`APREENSAO_DADOS` e acrescentou-se `DERIVACAO_ITEM`; `VALIDACAO` passou a `VALIDACAO_APREENSAO`. O ADR-0017 separou a transferência de custódia nos dois lados do movimento — `TRANSFERENCIA` (push, entrega) e `ASSUNCAO_CUSTODIA` (pull, recepção). O código actual reflecte estes nomes (`EventType`, `src/backend/core/models.py:1315-1343`), com as guardas a operar sobre conjuntos de eventos de génese (`GENESIS_EVENTS`, `SEIZURE_GENESIS_EVENTS`) em vez da guarda literal `APREENSAO`. A guarda `INICIO_PERICIA` ⇐ `DESPACHO_PERICIA` mantém-se. Tudo o resto deste ADR permanece válido.

## Data

2026-05-30

## Context

Construo a `ChainOfCustody` como o registo documentado da trajetória de cada prova: quem a deteve, onde, quando, e que acto processual ocorreu em cada passo. A versão de partida do modelo (`core/models.py:919-1184`) desenha-a como uma **máquina de estados estritamente linear**. O conjunto de transições é um corredor único, declarado em `core/models.py:944-953`:

```python
VALID_TRANSITIONS = {
    '': [CustodyState.APREENDIDA],
    CustodyState.APREENDIDA: [CustodyState.EM_TRANSPORTE],
    CustodyState.EM_TRANSPORTE: [CustodyState.RECEBIDA_LABORATORIO],
    CustodyState.RECEBIDA_LABORATORIO: [CustodyState.EM_PERICIA],
    CustodyState.EM_PERICIA: [CustodyState.CONCLUIDA],
    CustodyState.CONCLUIDA: [CustodyState.DEVOLVIDA, CustodyState.DESTRUIDA],
    CustodyState.DEVOLVIDA: [],
    CustodyState.DESTRUIDA: [],
}
```

São 7 estados (`CustodyState`, `core/models.py:934-941`) num corredor `APREENDIDA → EM_TRANSPORTE → RECEBIDA_LABORATORIO → EM_PERICIA → CONCLUIDA → {DEVOLVIDA | DESTRUIDA}`. O validador vive no modelo (`clean()`, `core/models.py:1034-1050`) e rejeita qualquer transição fora deste corredor.

Este desenho parte de uma premissa errada: a de que uma cadeia de custódia *prescreve* uma sequência válida de estados. Não prescreve. A cadeia de custódia, na ordem jurídica portuguesa, **não tem regime legal próprio**; é exigida pela doutrina e pela jurisprudência (Ac. do Tribunal da Relação de Évora, 19-11-2024) como **documentação do percurso da prova** — rastreabilidade, integridade e autenticidade. O que importa é provar *o que aconteceu à prova e em que mãos esteve*, não fazer o percurso caber num grafo de estados fechado. O percurso real é aberto, repetível e ramificado, e o Código de Processo Penal (DL 78/87) confirma-o:

- **Art. 178.º** — a apreensão é feita pelo OPC; tem de ser **validada pela autoridade judiciária no prazo máximo de 72 horas** (n.º 6); o destino legal inclui a **restituição** ao titular ou a terceiro de boa-fé. Sem validação tempestiva, há levantamento e restituição.
- **Art. 154.º** — a perícia é **ordenada por despacho** da autoridade judiciária, com objeto, quesitos e laboratório indicados. Não há perícia sem despacho prévio.
- **Art. 158.º** — admite-se, **em qualquer altura**, esclarecimentos e **nova perícia**, a cargo de outro laboratório ou perito. Isto significa, em concreto: múltiplas perícias sobre o mesmo objeto, encaminhamentos sucessivos entre laboratórios (público e privado), e retornos ao OPC entre fases — tudo legalmente normal.
- **Código Penal, Art. 109.º-111.º** — a prova pode ser declarada **perdida a favor do Estado** (instrumentos/produtos do crime), antecedendo destruição ou depósito.

A perícia informática, em particular, corre na UPTI / Laboratório de Polícia Científica da Polícia Judiciária (DL 137/2019, Art. 40.º/43.º), o que torna os encaminhamentos entre OPC apreensor e laboratório pericial o caso comum, não a excepção.

O corredor linear não consegue exprimir nada disto. Uma prova apreendida, não validada nas 72h e restituída não tem registo possível. Uma segunda perícia (Art. 158.º) não tem como ser representada — o estado `CONCLUIDA` é terminal-quase. Um encaminhamento para um laboratório privado, ou o regresso ao OPC entre fases, obriga a forçar estados que mentem sobre o percurso real. Pior: o `new_state` linear funde dois eixos ortogonais — *em que ponto do processo está a prova* e *quem a detém / onde está* — num só campo (`RECEBIDA_LABORATORIO` é, ao mesmo tempo, acto processual e afirmação de lugar). E não existe nenhum campo de localização na `ChainOfCustody` (confirmado em `core/models.py:955-1012`: o modelo vai de `code` a `sequence`, sem qualquer coordenada ou nome de local).

Há infra-estrutura reaproveitável para a localização. A `ReverseGeocodeView` (`core/views.py:1003-1088`) é um **proxy server-side para o Nominatim** (OpenStreetMap), com `throttle_scope = 'reverse_geocode'` (10 req/min em produção — `settings.py:148`), motivado por minimização RGPD: as coordenadas das ocorrências policiais nunca saem do browser do agente para terceiros. A CSP autoriza `https://nominatim.openstreetmap.org` em `connect-src` e `https://*.tile.openstreetmap.org` em `img-src` (`core/middleware.py:123-124`).

A restrição inquebrável que enquadra tudo: o ledger é **append-only imutável**. As três camadas de imutabilidade — triggers PostgreSQL das migrações `0002`/`0008`/`0013`, admin readonly, API POST-only — estão intactas e não regridem. Nenhum registo do ledger é alguma vez reescrito: corrige-se acrescentando um novo evento, nunca editando um antigo.

## Decision

Abandono a máquina de estados. A `ChainOfCustody` passa a ser um **ledger de eventos**: cada registo documenta **um evento** da trajetória da prova, e o estado legal é **derivado** da leitura do log, não gravado como campo rígido.

1. **Removo `CustodyState` e `VALID_TRANSITIONS`** (`core/models.py:934-953`) e os campos `previous_state`/`new_state` (`core/models.py:970-981`). Não há grafo de transições, não há `previous_state → new_state`. O contrato deixa de ser "que estado posso atingir a partir do estado actual" e passa a ser "que evento aconteceu à prova".

2. **Introduzo `event_type`** (`TextChoices`), o acto registado em cada evento:

   - `APREENSAO` — apreensão pelo OPC (Art. 178.º).
   - `VALIDACAO` — validação da apreensão pela autoridade judiciária (Art. 178.º/6).
   - `DESPACHO_PERICIA` — despacho que ordena perícia/exame (Art. 154.º).
   - `TRANSFERENCIA` — entrega/encaminhamento da prova a outro custódio (lab público, lab privado, regresso ao OPC, entrega ao tribunal).
   - `INICIO_PERICIA` — início de uma perícia (Art. 154.º; nova perícia, Art. 158.º).
   - `CONCLUSAO_PERICIA` — conclusão de uma perícia.
   - `RESTITUICAO` — restituição ao proprietário/terceiro (Art. 178.º). **Terminal.**
   - `PERDA_FAVOR_ESTADO` — declaração de perda a favor do Estado (Art. 109.º-111.º CP).
   - `DESTRUICAO` — destruição/inutilização. **Terminal.**

3. **Introduzo `custodian_type`** (`TextChoices`) — quem detém a prova **após** este evento:

   - `LOCAL_CRIME` (local do crime) · `OPC` (órgão de polícia criminal) · `LAB_PUBLICO` · `LAB_PRIVADO` · `TRIBUNAL` · `DEPOSITARIO` · `PROPRIETARIO`.

   O `event_type` diz *o que aconteceu*; o `custodian_type` diz *em mãos de quem a prova ficou*. São eixos ortogonais: uma `TRANSFERENCIA` pode entregar a `LAB_PUBLICO`, a `LAB_PRIVADO`, devolver ao `OPC` que apreendeu, ou entregar ao `TRIBUNAL`.

4. **Introduzo os campos de localização** por registo do ledger:

   - `gps_lat`, `gps_lng`, `gps_accuracy_m` — **campos do ADR-0013** (`DecimalField`, `decimal_places=7`; `gps_accuracy_m` como `PositiveIntegerField`, metadado de precisão reportada pelo dispositivo). Não os crio aqui; consumo-os tal como o ADR-0013 os define na `ChainOfCustody`.
   - `location_name` (`CharField`) — nome legível do POI vindo do OSM/Nominatim (esquadra, laboratório, tribunal, marco da cena do crime). Diz *em que edifício/marco*.
   - `storage_location` (`CharField`, texto livre) — localização **interna** de armazenamento (armário/sala), ex.: "Armário B-12, Sala 3". O GPS dá o sítio, o armário dá a gaveta. Distinto do `location_name`: este diz *em que edifício*, o `storage_location` diz *em que gaveta*.

5. **O validador é um conjunto de GUARDAS MÍNIMAS, no modelo (`clean()`)** — não um grafo. Substituo o `clean()` de transição por estas guardas:

   - O **1.º evento** de cada evidência (sequência 1) tem de ser `APREENSAO`.
   - `VALIDACAO` exige uma `APREENSAO` prévia, só pode ocorrer **uma vez**, e tem prazo **≤72h** sobre a apreensão (Art. 178.º/6). O incumprimento do prazo é **assinalado/registado** (a apreensão por validar fora de prazo é facto juridicamente relevante, não um erro a esconder).
   - `INICIO_PERICIA` exige um `DESPACHO_PERICIA` anterior (Art. 154.º; nova perícia, Art. 158.º).
   - `RESTITUICAO` e `DESTRUICAO` são **terminais**: nenhum evento é aceite depois de um deles.
   - Tudo o resto é **ordem livre e repetível**: `TRANSFERENCIA` para qualquer custódio, `INICIO_PERICIA`/`CONCLUSAO_PERICIA` repetidos (múltiplas perícias, Art. 158.º), `DESPACHO_PERICIA` adicional, em qualquer ordem coerente com as guardas acima.

   O validador continua **no modelo**, nunca nas views. As views (`ChainOfCustodyViewSet`) permanecem POST-only.

6. **O estado legal é DERIVADO do log, não gravado.** A fonte de verdade é a sequência de eventos. Calculo um estado legal de leitura — `à_guarda_OPC` / `validada` / `em_perícia` / `perícia_concluída` / `encaminhada` / `restituída` (terminal) / `perdida_a_favor_do_Estado` / `destruída` (terminal) — a partir do último evento relevante e do conjunto de eventos anteriores. Este estado derivado serve filtros, colorbar e timeline; **não** é uma coluna que se possa contradizer com o log.

7. **A fórmula do `record_hash` é a do ADR-0013, dono único da fórmula.** Não a redefino aqui. A fórmula já contempla todos os campos deste modelo. O hash encadeia, por registo:

   ```
   data = previous_hash | seq=N | evidence_id | event_type | custodian_type
        | agent_id | timestamp_iso | gps_lat | gps_lng | gps_acc
        | esc(location_name) | esc(storage_location) | observations
   ```

   Todos os campos **sempre** incluídos; campo nulo serializa como **string vazia** (determinístico, por dados em falta). O texto livre (`location_name`, `storage_location`) é **escapado** via `_hash_escape` (`\` → `\\`, `|` → `\|`, `,` → `\,`) para impedir colisão de separador. As coordenadas são **quantizadas a 7 casas** no `clean()` antes do hash, garantindo que o valor em memória é igual ao valor na BD e ao valor recalculado pelo perito. A ordem dos campos é fixa, parte do contrato. O `previous_hash` encadeia inalterado.

8. **A localização vem de POIs OSM, sem tabela curada.** Reutilizo e estendo a `ReverseGeocodeView` (`core/views.py:1003`) com o mesmo `throttle_scope = 'reverse_geocode'` e o mesmo princípio RGPD (proxy server-side; coordenadas não saem do browser). Acrescento **pesquisa de POIs próximos** via **Overpass API** (`https://overpass-api.de`), devolvendo candidatos (esquadras, laboratórios, tribunais, marcos) que o agente selecciona. Não há tabela curada de instalações: tanto a cena do crime como os nós oficiais vêm do OSM. Mantém-se sempre o par GPS + nome textual: o GPS é a posição autoritativa, o `location_name` é o rótulo humano. Há **degradação graciosa** — em indisponibilidade do Overpass (502), o agente preenche o `location_name` manualmente.

9. **Toda a mudança preserva as três camadas de imutabilidade.** Os triggers de linha da migração `0002` (`trg_custody_no_update`/`trg_custody_no_delete`, `core/migrations/0002_add_immutability_triggers.py:73-81`) disparam `FOR EACH ROW` e cobrem automaticamente as colunas novas (`event_type`, `custodian_type`, `location_name`, `storage_location`) — bloqueiam a linha inteira, independentemente de que colunas existam. Não crio trigger novo. O admin continua readonly; o `ChainOfCustodyViewSet` continua POST-only (`http_method_names = ['get', 'post', 'head', 'options']`, `core/views.py:657`).

## Alternatives Considered

- **Manter a máquina de estados linear e modelar os ramos legais em `observations`** (texto livre). Rejeito — a validação das 72h, a restituição por não-validação, as múltiplas perícias e os encaminhamentos são **factos processuais estruturados**, não anotações. Enterrá-los em texto livre impede consultas, alertas de prazo e a derivação do estado legal, e descreve mal o percurso da prova.

- **Manter um grafo de transições rígido (FSM ramificada / `VALID_TRANSITIONS` alargado / +4 estados)**, como o T20 propunha inicialmente. Rejeito — confunde *documentar o percurso* com *prescrever uma sequência*. A base legal (Art. 158.º) torna o percurso aberto e repetível: nova perícia em qualquer altura, encaminhamentos sucessivos, regressos ao OPC. Qualquer grafo fechado ou ficaria incompleto (faltariam arestas legítimas) ou seria tão permissivo que deixaria de ser um grafo. O modelo de eventos com guardas mínimas exprime exactamente as restrições legais reais (apreensão primeiro, validação ≤72h uma vez, perícia exige despacho, terminais fecham) e nada mais.

- **Fundir localização e custódio dentro do estado** (estados do tipo `EM_TRANSPORTE_PARA_LAB`). Rejeito — explode a cardinalidade (acto × custódio × lugar) e mistura eixos ortogonais. Separar `event_type`, `custodian_type` e localização mantém o modelo pequeno e deixa o lugar variar livremente.

- **Permitir `UPDATE` dos registos para "corrigir" um evento.** Rejeito de forma absoluta — viola o invariante append-only e as três camadas de imutabilidade. Reescrever um registo do ledger destrói a cadeia de custódia e a sua admissibilidade. A correcção é **sempre** um novo evento, nunca a edição de um antigo.

- **Gravar o estado legal como coluna materializada.** Rejeito — abriria a porta a um estado gravado que contradiz o log (a coluna e a sequência de eventos divergirem). A única fonte de verdade é o log; o estado é derivado em leitura.

- **Tabela curada de instalações** (esquadras/labs/tribunais como dados de referência). Rejeito — o universo de locais (cena do crime incluída) é aberto e geográfico; uma tabela curada nunca cobriria as cenas de crime e duplicaria informação que o OSM já tem. Revisível se o orientador pedir uma lista controlada de laboratórios oficiais.

## Consequences

### Positivas

- **O ledger conta a verdade do percurso.** Apreensão não validada e restituída, segunda perícia, encaminhamento para laboratório privado, regresso ao OPC — tudo tem registo fiel e auditável. Antes, eram inexprimíveis.
- **Dois eixos claros.** O `event_type` responde "o que aconteceu"; o `custodian_type` + localização respondem "em mãos de quem e onde". A timeline ganha custódio por passo e o mini-mapa "Cadeia" ganha nós nomeados.
- **Estado legal derivado é sempre coerente.** Não há coluna a contradizer o log; o estado de leitura é uma função pura da sequência de eventos.
- **Invariantes forenses preservados.** Hash-chain SHA-256 intacto (fórmula no ADR-0013), três camadas de imutabilidade intactas, validador no modelo, append-only por princípio. Nenhuma regressão forense.
- **Reaproveitamento da infra RGPD-safe.** O reverse-geocode, o seu throttle e a CSP já existem; estendê-los a POIs custa pouco e mantém a garantia de que as coordenadas não saem do browser para terceiros.
- **Base para alertas de prazo.** A guarda das 72h sobre a `VALIDACAO` permite assinalar apreensões a aproximar-se do limite — útil na consola da v2 (liga ao feed do T06).

### Negativas / Trade-offs

- **As guardas substituem o grafo, mas exigem leitura do log.** Validar `VALIDACAO requer APREENSAO prévia`, `INICIO_PERICIA requer DESPACHO_PERICIA anterior` e a regra dos terminais obriga o `clean()` a consultar os eventos anteriores da evidência. É feito dentro do `select_for_update` já existente em `save()` (`core/models.py:1124-1169`), serializando escritores concorrentes na mesma evidência — sem nova janela de corrida.
- **Estado legal derivado tem de ser testado.** A função de derivação é lógica nova e precisa de cobertura (cada estado de leitura a partir de sequências representativas). É trabalho real, não cosmético.
- **Dependência forte do ADR-0013.** A fórmula do hash — com `event_type`/`custodian_type`/`location_name`/`storage_location` — vive no ADR-0013. Este ADR consome-a; acoplamento assumido e sequenciado (T01 antes de T20, plano interno de refactor §5).
- **Nova origem externa (Overpass).** A pesquisa de POIs introduz dependência de `overpass-api.de` (latência, rate-limits, disponibilidade). Mitigação: timeout curto à imagem dos 5s do Nominatim (`core/views.py:1019`), degradação graciosa (502 + entrada manual do `location_name`), e o mesmo throttle `reverse_geocode`.
- **CSP sem alteração.** A pesquisa de POIs é um proxy server-side (`NearbyPOIsView`): o browser chama o endpoint próprio do ForensiQ, já coberto por `connect-src 'self'`, e é o servidor — não o browser — que contacta o Overpass. A CSP **não** precisa de listar `https://overpass-api.de`; o `connect-src` mantém-se `'self' https://nominatim.openstreetmap.org` (`core/middleware.py:150`). Mantém-se a garantia RGPD: as coordenadas não saem do browser para terceiros.

### Impactos noutros documentos

- **`docs/architecture/adr/ADR-0013-gps-cadeia-custodia.md`**: dono único da fórmula do `record_hash`. A fórmula passa a referir `event_type`/`custodian_type` (em vez de `previous_state`/`new_state`) e inclui o segmento de localização (`location_name`, `storage_location`). Este ADR-0015 **consome** essa fórmula e define a semântica dos campos; não a redefine.
- **`o plano interno de refactor`**: T20 passa de "decisão (FSM ramificada)" a "ADR escrito (ledger de eventos)"; a descrição antiga do T20 (grafo / `VALID_TRANSITIONS` / +4 estados) fica substituída. Referência cruzada a este ficheiro em §3 e §5.
- **`a especificação de art direction`** (Fase 3): o `transition_modal` ganha selector de `event_type`, selector de `custodian_type`, captura GPS e selecção de POI (OSM). O mini-mapa "Cadeia" mostra a trajetória com nós nomeados; a timeline mostra evento + custódio + local por passo. A legenda passa a usar o estado legal derivado.
- **`src/backend/core/middleware.py`**: sem alteração. Como a pesquisa de POIs é proxy server-side (`NearbyPOIsView`), o `connect-src` mantém-se `'self' https://nominatim.openstreetmap.org` — o browser nunca contacta o Overpass directamente.
- **Documentação de conformidade ISO/IEC 27037 / `docs/scope/`**: o ledger de eventos reforça a rastreabilidade do percurso legal da prova; revisitar a matriz de traceabilidade para reflectir `event_type`/`custodian_type`/localização como campos cobertos pelos triggers de imutabilidade.

## Implementação

Notas concretas para a execução do T20 (Fase 2), **depois** de T01/ADR-0013 fechado (os campos GPS e a fórmula do hash assentam aí).

### Enums (`core/models.py`)

```python
class EventType(models.TextChoices):
    APREENSAO = 'APREENSAO', 'Apreensão'
    VALIDACAO = 'VALIDACAO', 'Validação da apreensão'
    DESPACHO_PERICIA = 'DESPACHO_PERICIA', 'Despacho para perícia'
    TRANSFERENCIA = 'TRANSFERENCIA', 'Transferência de custódia'
    INICIO_PERICIA = 'INICIO_PERICIA', 'Início de perícia'
    CONCLUSAO_PERICIA = 'CONCLUSAO_PERICIA', 'Conclusão de perícia'
    RESTITUICAO = 'RESTITUICAO', 'Restituição'              # terminal
    PERDA_FAVOR_ESTADO = 'PERDA_FAVOR_ESTADO', 'Perda a favor do Estado'
    DESTRUICAO = 'DESTRUICAO', 'Destruição'                 # terminal

class CustodianType(models.TextChoices):
    LOCAL_CRIME = 'LOCAL_CRIME', 'Local do crime'
    OPC = 'OPC', 'Órgão de polícia criminal'
    LAB_PUBLICO = 'LAB_PUBLICO', 'Laboratório público'
    LAB_PRIVADO = 'LAB_PRIVADO', 'Laboratório privado'
    TRIBUNAL = 'TRIBUNAL', 'Tribunal'
    DEPOSITARIO = 'DEPOSITARIO', 'Depositário'
    PROPRIETARIO = 'PROPRIETARIO', 'Proprietário'

TERMINAL_EVENTS = {EventType.RESTITUICAO, EventType.DESTRUICAO}
VALIDATION_DEADLINE = timedelta(hours=72)  # CPP Art. 178.º/6
```

### Campos (substituição limpa)

Saem `previous_state`/`new_state` (`core/models.py:970-981`). Entram:

```python
event_type = models.CharField(
    max_length=20, choices=EventType.choices,
    verbose_name='Tipo de evento',
)
custodian_type = models.CharField(
    max_length=20, choices=CustodianType.choices,
    blank=True, default='',
    verbose_name='Custódio após o evento',
)
location_name = models.CharField(
    max_length=255, blank=True, default='',
    verbose_name='Local (POI OSM)',
)
storage_location = models.CharField(
    max_length=120, blank=True, default='',
    verbose_name='Localização interna de armazenamento',
)
```

`gps_lat`/`gps_lng`/`gps_accuracy_m` entram pela migração do ADR-0013 (não aqui). `blank=True, default=''` em `custodian_type`/`location_name`/`storage_location` cobre eventos sem esse dado disponível (ex.: um `DESPACHO_PERICIA` administrativo sem deslocação física) — serializados como vazio por dados em falta, e como tal entram no hash (string vazia).

### Validador (guardas mínimas, `clean()` — substitui a validação de transição)

O `clean()` deixa de consultar `VALID_TRANSITIONS`. Passa a aplicar as guardas, lendo os eventos anteriores da mesma evidência (dentro do `select_for_update` de `save()`):

```python
def clean(self):
    super().clean()
    prior = list(
        ChainOfCustody.objects.filter(evidence=self.evidence)
        .order_by('sequence')
    )
    prior_types = [r.event_type for r in prior]

    # 1.º evento tem de ser APREENSAO
    if not prior and self.event_type != EventType.APREENSAO:
        raise ValidationError({'event_type':
            'O primeiro evento de uma evidência tem de ser APREENSAO.'})
    if prior and self.event_type == EventType.APREENSAO:
        raise ValidationError({'event_type':
            'APREENSAO só pode ser o primeiro evento.'})

    # Terminais fecham o ledger
    if prior_types and prior_types[-1] in TERMINAL_EVENTS:
        raise ValidationError({'event_type':
            'A evidência tem um evento terminal (restituição/destruição); '
            'não são aceites mais eventos.'})

    # VALIDACAO: exige APREENSAO, só uma vez, prazo ≤72h
    if self.event_type == EventType.VALIDACAO:
        if EventType.APREENSAO not in prior_types:
            raise ValidationError({'event_type':
                'VALIDACAO requer uma APREENSAO prévia.'})
        if EventType.VALIDACAO in prior_types:
            raise ValidationError({'event_type':
                'A apreensão só pode ser validada uma vez.'})
        apreensao = next(r for r in prior if r.event_type == EventType.APREENSAO)
        self.validation_overdue = (
            self.timestamp - apreensao.timestamp > VALIDATION_DEADLINE
        )  # assinalado, não bloqueante (facto juridicamente relevante)

    # INICIO_PERICIA: exige DESPACHO_PERICIA anterior
    if self.event_type == EventType.INICIO_PERICIA:
        if EventType.DESPACHO_PERICIA not in prior_types:
            raise ValidationError({'event_type':
                'INICIO_PERICIA requer um DESPACHO_PERICIA anterior '
                '(CPP Art. 154.º).'})

    # Quantização GPS a 7 casas (ADR-0013), antes do hash
    q = Decimal('0.0000001')
    if self.gps_lat is not None:
        self.gps_lat = self.gps_lat.quantize(q)
    if self.gps_lng is not None:
        self.gps_lng = self.gps_lng.quantize(q)
```

`TRANSFERENCIA`, `DESPACHO_PERICIA`, `INICIO_PERICIA`/`CONCLUSAO_PERICIA` repetidos e `PERDA_FAVOR_ESTADO` não têm guarda de ordem para além das acima — ordem livre e repetível. O incumprimento das 72h é assinalado (`validation_overdue`/observação), nunca rejeitado.

### Estado legal derivado (leitura, não coluna)

Função pura sobre a sequência de eventos, p.ex. `Evidence.custody_state()` ou um helper de serializer:

- último evento `DESTRUICAO` → `destruída` (terminal); `RESTITUICAO` → `restituída` (terminal).
- existe `PERDA_FAVOR_ESTADO` (sem terminal posterior) → `perdida_a_favor_do_Estado`.
- último `INICIO_PERICIA` sem `CONCLUSAO_PERICIA` correspondente → `em_perícia`; com conclusão → `perícia_concluída`.
- último evento `TRANSFERENCIA` para `LAB_*` → `encaminhada`.
- existe `VALIDACAO` → `validada`; caso contrário, após `APREENSAO` → `à_guarda_OPC`.

Usado por filtros (substitui `?new_state=` por `?event_type=` e um filtro derivado de estado), colorbar e timeline.

### Migração (schema limpo, sem reescrever registos)

- Uma migração que **remove** `previous_state`/`new_state` e **acrescenta** `event_type`, `custodian_type`, `location_name`, `storage_location`. Como é greenfield, a substituição de colunas é directa; não há dados a preservar e nenhum registo do ledger é reescrito (append-only mantém-se por princípio).
- **Call-sites no próprio modelo a reescrever** (referenciam os campos removidos): `core/models.py:1029-1032` (`__str__` — passa a usar `event_type`/`custodian_type` em vez de `get_previous_state_display()`/`get_new_state_display()`); `core/models.py:1149` (remover `self.previous_state = last_record.new_state` no `save()` — já não há estado a propagar; `sequence` continua a ser atribuído server-side); `core/models.py:923-931` (docstring do modelo — deixa de descrever a "máquina de estados", passa a "ledger de eventos"). `CustodyState` e `VALID_TRANSITIONS` (`core/models.py:934-953`) são removidos.
- **Filtros** (`core/filters.py:67-79`): o `CustodyFilter` define hoje `new_state = MultipleChoiceFilter(field_name='new_state', choices=ChainOfCustody.CustodyState.choices)` e regista-o em `Meta.fields`; ao remover `CustodyState`/`new_state`, o módulo de filtros parte no import (`AttributeError`) e o `filterset_class=CustodyFilter` (`core/views.py:659`) deixa de carregar. Substituir por `event_type = MultipleChoiceFilter(choices=EventType.choices)` + um filtro de **método** para o estado legal derivado (não uma FK a coluna inexistente).
- Os campos GPS chegam pela migração do ADR-0013; este ADR depende dela na ordem de `dependencies`.
- **Sem trigger novo.** `trg_custody_no_update`/`trg_custody_no_delete` (`core/migrations/0002_add_immutability_triggers.py:73-81`) disparam `FOR EACH ROW` e cobrem as colunas novas. Não mexer em `0002`/`0008`/`0013` nem squashar migrações de imutabilidade.

### Hash (fórmula no ADR-0013)

Não redefino a fórmula. O `compute_record_hash` (`core/models.py:1052-1094`) passa a serializar `event_type`/`custodian_type` (em vez de `previous_state`/`new_state`) e os campos de localização/GPS, com texto livre escapado por `_hash_escape` e coordenadas quantizadas a 7 casas — tudo fixado no ADR-0013, dono único. Campos nulos serializam como string vazia. Actualizar a docstring da fórmula (`core/models.py:1062-1063`) em consonância.

### Reverse-geocode estendido a POIs (`core/views.py:1003`)

- Acrescentar acção/endpoint de pesquisa de POIs próximos (ex.: `GET /api/nearby-pois/?lat=&lon=&radius=`), com `permission_classes = [IsAuthenticated, IsAgentOrExpert]`, `throttle_scope = 'reverse_geocode'` (reutilizar o scope), proxy server-side para Overpass (`https://overpass-api.de/api/interpreter`), timeout ≤5s (par com `_TIMEOUT_SECONDS`, `core/views.py:1019`), `User-Agent` `ForensiQ/1.0 (forensiq.pt)`, degradação graciosa (502 → entrada manual).
- Filtrar POIs por tags OSM relevantes (`amenity=police`, `amenity=courthouse`, edifícios/marcos para cena de crime).
- Devolver ao frontend só o necessário (nome, tipo, distância, lat/lon) — minimização, à imagem do `ReverseGeocodeView` (`core/views.py:1074-1088`).
- **CSP:** sem alteração. O Overpass é contactado pelo servidor (proxy server-side, `NearbyPOIsView`); o browser só fala com o endpoint próprio, coberto por `connect-src 'self'`. O `connect-src` mantém-se `'self' https://nominatim.openstreetmap.org` (`core/middleware.py:150`) — **não** se acrescenta `https://overpass-api.de`.

### Serializer / API

- Estender `ChainOfCustodySerializer` (`core/serializers.py:384-415`): substituir `previous_state`/`new_state` por `event_type` (input do agente) + `custodian_type`, `location_name`, `storage_location`, `gps_lat`, `gps_lng`, `gps_accuracy_m` (estes três do ADR-0013) como **campos de escrita na criação**. Expor o estado legal **derivado** como campo `read_only`. Validação de coerência GPS (lat e lng ambas presentes ou ambas ausentes), à imagem de `Occurrence.clean()`. `sequence` e `timestamp` permanecem determinados pelo servidor (`read_only`, à imagem do serializer actual, `core/serializers.py:412-415`); o input do agente limita-se a `event_type`, `custodian_type`, `location_name`, `storage_location` e GPS.
- `ChainOfCustodyViewSet` (`core/views.py:643-657`) e a acção `cascade` (`core/views.py:779`) **não mudam de classe base nem de `http_method_names`** — continuam POST-only. O `cascade` passa a aceitar `event_type` (ex.: emitir `TRANSFERENCIA` para `RECEBIDA` em batch no intake do ADR-0012, agora modelado como `event_type=TRANSFERENCIA`, `custodian_type=LAB_PUBLICO`).
- Actualizar o export CSV (`core/views.py:735-766`): cabeçalho deixa de ter "Estado anterior"/"Novo estado" e passa a "Tipo de evento"/"Custódio"/"Local"/"Estado legal (derivado)".

### Testes (escritos ao mesmo tempo que o código)

1. **Guarda do 1.º evento**: criar evidência cujo primeiro registo é `VALIDACAO` (ou qualquer ≠ `APREENSAO`) levanta `ValidationError`; `APREENSAO` num evento não-primeiro também.
2. **Guarda da validação**: `VALIDACAO` sem `APREENSAO` prévia falha; segunda `VALIDACAO` falha; `VALIDACAO` >72h após apreensão é **aceite mas assinalada** (`validation_overdue`/observação).
3. **Guarda da perícia**: `INICIO_PERICIA` sem `DESPACHO_PERICIA` anterior falha; com despacho passa.
4. **Terminais fecham**: após `RESTITUICAO` ou `DESTRUICAO`, qualquer novo evento é rejeitado.
5. **Ordem livre aceite**: `TRANSFERENCIA` para vários custódios em qualquer ordem; `INICIO_PERICIA`/`CONCLUSAO_PERICIA` repetidos (múltiplas perícias, Art. 158.º); encaminhamento `OPC → LAB_PUBLICO → LAB_PRIVADO → OPC` — tudo passa.
6. **Estado legal derivado**: para sequências representativas, a função devolve `à_guarda_OPC`/`validada`/`em_perícia`/`perícia_concluída`/`encaminhada`/`restituída`/`perdida_a_favor_do_Estado`/`destruída`.
7. **Determinismo do hash**: registo com `event_type`/`custodian_type`/localização produz hash estável e recalculável; `location_name` com `,`/`|` (ex.: `"Bomba BP, Av. da Liberdade | Lisboa"`) é escapado e não colide; coordenadas com nº de casas ≠ 7 recalculam igual após relido da BD (quantização).
8. **Imutabilidade** (ORM): `save()` em registo existente levanta `ValidationError` (`core/models.py:1118-1122`); `delete()` levanta `ValidationError` (`core/models.py:1180-1184`).
9. **API POST-only**: PUT/PATCH/DELETE em `/api/custody/<id>/` devolvem 405.
10. **Reverse-geocode/POIs**: validação de parâmetros (lat/lon obrigatórios e em gama), 502 em indisponibilidade do Overpass, e que o throttle `reverse_geocode` dispara.
11. **Trigger PG** (`skipUnless(connection.vendor == 'postgresql')`, cursor bruto): `UPDATE` directo a `core_chainofcustody` numa coluna nova (`event_type`/`location_name`) é rejeitado pelo `trg_custody_no_update` — confirma que a 3.ª camada cobre as colunas novas (liga ao T16).

## Referências

- **ADR-0013** (`ADR-0013-gps-cadeia-custodia.md`) — campos GPS na `ChainOfCustody` e fórmula única do `record_hash` (inclui `event_type`/`custodian_type`/`location_name`/`storage_location`, escaping `_hash_escape`, quantização a 7 casas). Dono da fórmula; este ADR consome-a.
- **ADR-0012** (`ADR-0012-pdf-transport-guide.md`) — PDF guia de transporte; o intake EXPERT-only submete para `/api/custody/cascade/`, agora modelado como evento `TRANSFERENCIA` → `LAB_PUBLICO` (T18).
- **ADR-0010** — taxonomia de `Evidence` e estrutura da `ChainOfCustody` hash-chained.
- `o plano interno de refactor` — T20 (§3), §5 (sequenciamento T01 antes de T20).
- `src/backend/core/models.py:919-1184` — `ChainOfCustody`: campos (955-1012), `clean()` a substituir (1034-1050), `compute_record_hash` (1052-1094), `save()` append-only com `select_for_update` (1104-1178), `delete()` bloqueado (1180-1184).
- `src/backend/core/models.py:243-258` — `Occurrence.gps_lat`/`gps_lon` (`decimal_places=7`), precedente de campos GPS.
- `src/backend/core/views.py:643-657` — `ChainOfCustodyViewSet` POST-only; `:706-766` — export CSV; `:779-800` — acção `cascade`; `:1003-1088` — `ReverseGeocodeView` (proxy Nominatim, throttle `reverse_geocode`, RGPD).
- `src/backend/core/serializers.py:384-415` — `ChainOfCustodySerializer`.
- `src/backend/core/middleware.py:119-134` — CSP; `:123` `connect-src` (Nominatim), `:124` `img-src` (tiles OSM).
- `src/backend/core/migrations/0002_add_immutability_triggers.py:63-88` — `prevent_custody_modification()` + `trg_custody_no_update`/`trg_custody_no_delete` (`FOR EACH ROW`, cobre colunas novas).
- `src/backend/core/migrations/0013_protect_occurrence.py` — padrão de trigger PG (no-op SQLite, `DROP IF EXISTS` no reverse).
- `src/backend/forensiq_project/settings.py:148` — throttle `reverse_geocode` (10/minute prod; `:176` 10000/minute em TESTING).
- **CPP — DL 78/87**: Art. 154.º (perícia ordenada por despacho), Art. 158.º (esclarecimentos e nova perícia em qualquer altura, a cargo de outro laboratório), Art. 178.º (apreensão; validação ≤72h no n.º 6; restituição).
- **Código Penal, Art. 109.º-111.º** — perda de instrumentos/produtos a favor do Estado.
- **DL 137/2019, Art. 40.º/43.º** — UPTI / Laboratório de Polícia Científica da PJ (perícia informática).
- **Jurisprudência** — Ac. do Tribunal da Relação de Évora, 19-11-2024 (cadeia de custódia como documentação do percurso da prova: rastreabilidade, integridade, autenticidade).
- **ISO/IEC 27037** §5.4 — preservação da integridade e rastreabilidade da prova.
- OpenStreetMap / Nominatim — <https://nominatim.org/release-docs/latest/api/Reverse/>; Overpass API — <https://wiki.openstreetmap.org/wiki/Overpass_API>.
