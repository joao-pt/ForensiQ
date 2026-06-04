# ADR-0013: GPS na cadeia de custódia, convenção `gps_lng` e fórmula única do hash encadeado

## Status

Accepted — 2026-05-30. Este ADR é o **dono único** da fórmula do `record_hash` da `ChainOfCustody` e dos campos GPS do ledger. Fixa, num só sítio, a serialização determinística de todos os campos que entram no hash encadeado SHA-256, a convenção de longitude `gps_lng` em todo o schema, e os três campos GPS do ledger com precisão máxima.

O ADR-0015 **define** a semântica dos campos `event_type`, `custodian_type`, `location_name` e `storage_location` (enums, fonte OSM, guardas mínimas do ledger de eventos); a **serialização desses campos no hash é fixada aqui**, porque a fórmula tem de viver num único documento para não haver duas fontes de verdade sobre o que entra no SHA-256.

## Data

2026-05-30

## Context

A `ChainOfCustody` é um **ledger append-only com hash-chain SHA-256** (ADR-0010). Cada registo encadeia com o anterior via `compute_record_hash` (`core/models.py:1052-1094`). A imutabilidade está garantida em três camadas — triggers PostgreSQL (`prevent_custody_modification`, `core/migrations/0002_add_immutability_triggers.py:63-82`), admin read-only, e API POST-only — e o `save()` recusa qualquer escrita com `pk` já atribuído (`core/models.py:1118-1122`). O cálculo do hash corre dentro de `transaction.atomic()` com `select_for_update()`, e o `previous_hash` é passado explicitamente para a função se manter pura (`core/models.py:1162-1169`).

O frontend v2 precisa de uma **trajetória geo-referenciada da prova**: um mini-mapa "Cadeia" com a polyline da jornada, pins por evento, tooltip com a precisão `±N m`, e uma timeline com localização. Hoje não há fonte de dados para isto — a `ChainOfCustody` não tem nenhum campo de coordenadas: o modelo (`core/models.py:919-1012`) vai de `code` a `sequence` sem GPS. Esta é a lacuna estrutural que este ADR fecha.

Em paralelo, há uma incoerência de nomenclatura no schema. `Occurrence` (`core/models.py:251-258`) e `Evidence` (`core/models.py:454-461`) usam `gps_lon`; os serializers expõem `gps_lon` (`core/serializers.py:139,247`); os filtros tocam `gps_lat` (`core/filters.py:27-31,61-63`); o PDF lê `evidence.gps_lon`/`occ.gps_lon` (`core/pdf_export.py:516,691,808`). A spec de frontend e o JS de mapas esperam `gps_lng`. Esta divergência `gps_lon` (backend) vs `gps_lng` (spec/JS) é a raiz de uma classe inteira de bugs de contrato no hero geo. Criar campos GPS novos no ledger obriga a escolher uma convenção; manter `gps_lon` perpetuaria a divergência.

Há ainda a questão da granularidade. Numa primeira leitura, registar GPS em cada evento parece vigilância do agente, o que sugeriria arredondar coordenadas por minimização RGPD. O enquadramento correto é outro: **o GPS regista onde está a evidência em cada evento — na apreensão, no transporte, no armazenamento do laboratório — não a posição do agente.** A coordenada é necessidade estrita para a prova (ISO/IEC 27037 §5.4). A inferência da posição do agente é incidental e acontece em qualquer registo de campo. Por isso quer-se a posição com a **precisão máxima possível**, e o agente tem de poder ajustar manualmente a marcação antes de gravar, porque o GPS faz *drift* em ambiente urbano e interior. Isto muda a base legal RGPD: a minimização satisfaz-se pela **limitação de finalidade** (a coordenada serve a localização da prova, não o rastreio do agente), não por *coarsening* — arredondar destruiria valor probatório sem servir a finalidade declarada.

Por fim, o hash. Como cada registo do ledger fica imutável ao gravar (triggers + `save()` recusa `pk is not None`), a fórmula tem de ser **determinística e auto-suficiente**: um perito independente, relendo o registo da BD, recalcula o `record_hash` a partir dos campos e do `previous_hash`, e confirma a integridade da cadeia. Isto impõe três exigências sobre a serialização — ordem fixa dos campos, tratamento determinístico de campos em falta, e neutralização do separador em campos de texto livre — que este ADR fixa de forma única.

## Decision

1. **Fixo a fórmula completa e única do `record_hash` neste ADR.** Todos os campos do registo entram **sempre** na string de dados, na ordem fixa abaixo; o hash é `SHA-256(data)` e o `previous_hash` encadeia inalterado. Não há ramos condicionais, não há segmentos omitidos, não há versionamento da fórmula. A ordem dos campos é parte do contrato forense.

   ```
   data = previous_hash | seq=N | evidence_id | event_type | custodian_type
        | agent_id | timestamp_iso | gps_lat | gps_lng | gps_acc
        | esc(location_name) | esc(storage_location) | observations
   ```

   > **Emenda (ADR-0016 §6 · migração `0023`).** A fórmula foi posteriormente **estendida** com quatro campos de selo por-evento — `sealed`, `seal_condition_on_receipt`, `new_seal_number`, `relinquished_by` — acrescentados *após* `observations`. A fórmula em produção tem hoje **17 segmentos**; a *docstring* de `compute_record_hash` (`core/models.py`) é a fonte viva e descreve-os na íntegra. O bloco acima preserva a decisão original (13 segmentos) tal como foi tomada; a extensão respeitou a regra de ordem fixa, anexando os campos novos no fim.

2. **Campo em falta serializa como string vazia, determinismicamente.** Um campo `null` (GPS não capturado, `storage_location` por preencher) entra na string como `''` entre separadores. Isto é tratamento de **dados em falta**, não de qualquer formato anterior: o desenho é novo e limpo, não há registos a preservar. A posição do campo na string é sempre a mesma, esteja preenchido ou vazio.

3. **Campos de texto livre são escapados antes de entrar no hash.** `location_name` (nome de POI vindo do OSM/Nominatim) e `storage_location` (texto livre: armário/sala interno) podem conter `|` ou `,`, que são os separadores da string. Passam por `_hash_escape` (`\` → `\\`, `|` → `\|`, `,` → `\,`), garantindo que o conteúdo nunca colide com a estrutura da string. `event_type` e `custodian_type` são enums de valores controlados (sem separadores), logo não precisam de escaping.

4. **Coordenadas quantizadas a 7 casas decimais no `clean()`, antes do hash.** `gps_lat` e `gps_lng` são `quantize(Decimal('0.0000001'))` em `clean()`, antes de `compute_record_hash` correr em `save()`. Sem isto, um input com nº de casas diferente de 7 (ex.: `'38.72234'`) seria hasheado em memória com a representação do input, mas relido da BD com 7 casas — o perito recalcularia um hash divergente. A quantização garante `valor em memória == valor na BD == valor recalculado`.

5. **Três campos GPS novos na `ChainOfCustody`, com precisão máxima:**
   - `gps_lat` — `DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)`, validadores `Min(-90)/Max(90)` — idêntico ao de `Occurrence`/`Evidence`.
   - `gps_lng` — `DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)`, validadores `Min(-180)/Max(180)`.
   - `gps_accuracy_m` — `PositiveIntegerField(null=True, blank=True)`: **metadado** do raio de incerteza em metros reportado pelo dispositivo. Documenta a precisão *real* do sensor — não é mecanismo de arredondamento.

   A coordenada é gravada com a precisão máxima disponível; não há tabela de arredondamento por papel. A minimização RGPD satisfaz-se pela limitação de finalidade (localização da prova).

6. **Convenção `gps_lng` em todo o schema.** A `ChainOfCustody` nasce já com `gps_lng`. Em paralelo, renomeio `Occurrence.gps_lon` e `Evidence.gps_lon` para `gps_lng` via `RenameField`, com actualização de `core/serializers.py:139,247`, `core/filters.py`, `core/pdf_export.py` e do JS de mapas. **O rename não altera o `integrity_hash` da `Evidence`**: `compute_integrity_hash` usa o *valor* do campo (`core/models.py:626` — `f'{self.gps_lat}|{self.gps_lon}|'`), não o nome Python; o byte-stream que entra no SHA-256 é idêntico antes e depois do rename.

7. **Ajuste manual da posição é permitido, mas sempre pré-hash.** O agente pode corrigir a marcação (drift de GPS) antes de submeter o evento. Como o registo se torna imutável ao gravar (`save()` calcula o hash dentro da `transaction.atomic()`, `core/models.py:1162-1169`), qualquer ajuste acontece necessariamente *antes* do cálculo do hash e do INSERT. Não há — nem pode haver — edição pós-gravação: os triggers de linha recusam-na (ponto 8) e o `save()` recusa `pk is not None`. O ajuste é, por construção, server-side e pré-hash.

8. **Os campos GPS novos ficam cobertos pelos triggers de imutabilidade existentes, sem migration de trigger.** `trg_custody_no_update` (`core/migrations/0002_add_immutability_triggers.py:73-77`) é `BEFORE UPDATE ... FOR EACH ROW` — bloqueia a linha inteira, incluindo colunas adicionadas depois. Nenhuma migration de trigger é necessária para os campos novos. (A migration `0008_extend_immutability` é Evidence-only/documental e **não** tem triggers de custódia; os triggers de custódia vivem na `0002`. A `0013` protege `Occurrence`, não `ChainOfCustody`.)

## Alternatives Considered

- **GPS fora do hash** — campos GPS na tabela, protegidos só pelo trigger de linha, mas ausentes da fórmula do `record_hash`. Rejeitado: deixaria a localização da prova fora da cadeia de integridade verificável. Um perito que recalcule a cadeia não confirmaria que o GPS gravado é o GPS original. O valor probatório do GPS depende de ele estar *dentro* do encadeamento, como defesa em profundidade para lá do trigger.

- **Manter `gps_lon`** (e criar a `ChainOfCustody` com `gps_lon` por coerência interna). Rejeitado: a divergência `gps_lon` (backend) vs `gps_lng` (spec/JS) é a raiz do bug do hero geo. Convergir tudo para `gps_lng` elimina a classe inteira de bugs de contrato; o rename é seguro porque o `integrity_hash` usa o valor, não o nome.

- **Arredondamento por papel** (truncar coordenadas por nível de acesso, à la *geo-coarsening* de privacidade). Rejeitado: o GPS marca a **localização da evidência**, não vigia o agente; arredondar destruiria precisão probatória para mitigar um risco (rastreio do agente) que é incidental e já coberto pela limitação de finalidade RGPD. O `gps_accuracy_m` regista a incerteza *real* do sensor — informação honesta —, não uma incerteza fabricada por política.

- **Eliminar o ajuste manual** (gravar sempre a leitura crua do GPS). Rejeitado: o drift de GPS em ambiente urbano/interior é real; obrigar a gravar uma leitura errada degradaria a prova. O ajuste pré-hash dá ao agente a correcção sem abrir qualquer janela de mutação pós-gravação — o registo só fica imutável depois do ajuste, ao gravar.

- **Não escapar os campos de texto livre** (confiar em que `location_name`/`storage_location` não contêm separadores). Rejeitado: nomes de POI do OSM contêm vírgulas com frequência (ex.: `"Bomba BP, Av. da Liberdade"`) e texto livre de armazenamento pode conter qualquer caractere. Sem escaping, duas localizações distintas poderiam colidir na mesma string de dados, partindo a injetividade do hash. O `_hash_escape` é determinístico e reversível, e torna a colisão de separador impossível.

- **Campo `hash_version` materializado na linha** para descrever a geração da fórmula. Rejeitado: não há gerações. A aplicação é construída de raiz, a fórmula é única, e todos os campos entram sempre. Um `hash_version` seria uma coluna a documentar uma variabilidade que não existe.

## Consequences

### Positivas

- **Desbloqueia o mini-mapa "Cadeia" e a timeline geo da v2.** A jornada da prova passa a ter fonte de dados real: pins por evento, polyline, tooltip `±N m` a partir de `gps_accuracy_m`.
- **Fórmula única, num só sítio.** A serialização de todos os campos do hash vive neste ADR. O ADR-0015 define a *semântica* de `event_type`/`custodian_type`/`location_name`/`storage_location`, mas não redefine como entram no SHA-256 — não há duas fontes de verdade.
- **Cadeia 100% verificável por perito independente.** Ordem fixa, campos em falta como vazio determinístico, texto livre escapado, coordenadas quantizadas — o recálculo a partir do registo relido bate sempre certo com o `record_hash` gravado.
- **Convenção única `gps_lng`** elimina a raiz do bug do hero geo e harmoniza schema, serializers, PDF e JS.
- **Base legal RGPD limpa e defensável.** A minimização por limitação de finalidade é argumentável na defesa: o GPS serve a prova, não o agente; documentado e rastreável.
- **Imutabilidade preservada sem trabalho extra.** Os triggers `BEFORE UPDATE FOR EACH ROW` cobrem as colunas novas automaticamente — defesa em profundidade intacta, sem migration de trigger.

### Negativas / Trade-offs

- **A fórmula é um contrato irreversível.** Uma vez em produção com registos gravados, a ordem dos campos, a regra de campo-vazio e o escaping não podem mudar sem partir esses hashes. É por isso que fixo a fórmula completa neste ADR, antes de qualquer código tocar `compute_record_hash`. Mitigação: testes de determinismo e de escaping escritos ao mesmo tempo que o código, incluindo um vector de regressão que congela a string de dados.
- **Rename `gps_lon`→`gps_lng` toca muitos ficheiros** (serializers, filters, PDF, JS). Mitigação: migration de rename mecânica (`RenameField`), e o invariante de que o `integrity_hash` não muda dá confiança de que a prova não é afectada. Nenhum índice ou constraint depende do nome antigo — os índices de `Evidence`/`Occurrence` são sobre outras colunas.
- **Inferência incidental da posição do agente.** Gravar GPS de precisão máxima permite, em teoria, reconstruir trajetos do agente. Aceite e documentado como incidental à finalidade probatória; não há decisão de *coarsening*. Registar como limitação assumida no relatório, secção RGPD.

### Impactos noutros documentos

- **`docs/architecture/adr/ADR-0015-*.md`** (ledger de eventos): define a semântica de `event_type`, `custodian_type`, `location_name`, `storage_location` (enums, fonte OSM, guardas mínimas no `clean()` e estado legal derivado do log). A **serialização desses campos no hash é a fixada aqui** — o ADR-0015 referencia esta fórmula; não a redefine.
- **`docs/scope/iso27037-traceability.tex`** / matriz documental de imutabilidade: acrescentar `gps_lat`, `gps_lng`, `gps_accuracy_m` da `ChainOfCustody` à lista de campos cobertos por `trg_custody_no_update`.
- **`core/pdf_export.py`**: o `_fmt_gps` (`core/pdf_export.py:338-349`) já corrige o hemisfério (N/S, E/W); o bug pré-existente de imprimir sempre `°N/°E` — Portugal continental é longitude W — foi sanado em conjunto com o rename para `gps_lng`.
- **`README.md`** / spec de frontend (`a especificação de art direction`): convenção de longitude passa a `gps_lng` em todas as referências.

## Implementação

> **Nota sobre as âncoras de linha.** Os números de linha desta secção (e das Referências) refletem o estado do `models.py` à data da decisão, pré-implementação. Concluída a Fase 2 — com a taxonomia (`0019`), o ledger (`0021`) e o modelo v2 (`0023`) já gravados —, o ficheiro cresceu: `compute_record_hash` está hoje em `core/models.py:1801`, `ChainOfCustody.save()` em `:1873`, `Evidence.compute_integrity_hash` em `:1100` (o GPS entra em `:1123`), e os três campos GPS da `ChainOfCustody` em `:1550-1574` (`gps_lat` `:1550`, `gps_lng` `:1558`, `gps_accuracy_m` `:1566`). Mantenho as âncoras originais no corpo como registo da decisão; é só a esta nota que se deve recorrer para localizar o código atual.

### Campos novos (`ChainOfCustody`, `core/models.py`)

```python
gps_lat = models.DecimalField(
    max_digits=10, decimal_places=7, null=True, blank=True,
    validators=[MinValueValidator(-90), MaxValueValidator(90)],
    verbose_name='Latitude GPS (evento)',
)
gps_lng = models.DecimalField(
    max_digits=10, decimal_places=7, null=True, blank=True,
    validators=[MinValueValidator(-180), MaxValueValidator(180)],
    verbose_name='Longitude GPS (evento)',
)
gps_accuracy_m = models.PositiveIntegerField(
    null=True, blank=True,
    verbose_name='Precisão GPS reportada (m)',
    help_text='Raio de incerteza em metros reportado pelo dispositivo. '
              'Metadado de precisão — não altera a coordenada gravada.',
)
```

### Fórmula única do hash (`compute_record_hash`, `core/models.py:1085-1094`)

Todos os campos entram sempre. Campo `null` serializa como string vazia (`_str` abaixo). Texto livre escapado. Coordenadas já quantizadas a 7 casas pelo `clean()`. A ordem dos campos é fixa e parte do contrato.

```python
def _str(value):
    """Serializa um campo do hash: None → '' (dado em falta), determinístico."""
    return '' if value is None else str(value)


data = (
    f'{previous_hash}|'
    f'seq={self.sequence}|'
    f'{self.evidence_id}|'
    f'{self.event_type}|'
    f'{self.custodian_type}|'
    f'{self.agent_id}|'
    f'{self.timestamp.isoformat()}|'
    f'{_str(self.gps_lat)}|'
    f'{_str(self.gps_lng)}|'
    f'{_str(self.gps_accuracy_m)}|'
    f'{_hash_escape(self.location_name)}|'
    f'{_hash_escape(self.storage_location)}|'
    f'{self.observations}'
)
return hashlib.sha256(data.encode('utf-8')).hexdigest()
```

Helper de escaping (módulo `core/models.py`), determinístico e reversível:

```python
def _hash_escape(value):
    """Escapa separadores do hash em campos de texto livre.
    Ordem fixa: backslash primeiro, depois os separadores."""
    return (value or '').replace('\\', '\\\\').replace('|', '\\|').replace(',', '\\,')
```

**Regras de serialização fixadas (irreversíveis — contrato forense):**
- **Ordem dos campos** conforme a fórmula acima, não-comutável. `previous_hash`, `seq`, `evidence_id`, `event_type`, `custodian_type`, `agent_id`, `timestamp_iso`, `gps_lat`, `gps_lng`, `gps_accuracy_m`, `location_name`, `storage_location`, `observations`.
- **Campo em falta** → string vazia entre separadores (dado ausente, posição preservada).
- **`location_name` e `storage_location`** passam por `_hash_escape` (texto livre); `event_type` e `custodian_type` são `TextChoices` com `default=''` (nunca `None`), logo entram **crus** na string — sem `_str` e sem `_hash_escape` — por serem valores de enum controlados, sem separadores.
- **Coordenadas** `gps_lat`/`gps_lng` quantizadas a 7 casas no `clean()` antes do hash, para `valor em memória == valor na BD == valor recalculado`.

Actualizar a docstring de `compute_record_hash` (`core/models.py:1062-1063`) para descrever a fórmula única, o tratamento de campo-vazio, o escaping e a quantização.

### Quantização no `clean()`

```python
def clean(self):
    super().clean()
    # ... guardas mínimas do ledger de eventos (ADR-0015) ...
    # Quantização GPS (ADR-0013): garante o determinismo do hash —
    # valor em memória == valor na BD == valor recalculado pelo perito.
    q = Decimal('0.0000001')  # 7 casas
    if self.gps_lat is not None:
        self.gps_lat = self.gps_lat.quantize(q)
    if self.gps_lng is not None:
        self.gps_lng = self.gps_lng.quantize(q)
```

O `clean()` corre via `full_clean()` já invocado em `save()` (`core/models.py:1162`); a quantização corre no mesmo `full_clean()`, antes de `compute_record_hash`. Os validadores de campo `Min/Max` correm no mesmo passo.

### Migrations

À data da decisão a cabeça da chain era `0017_alter_auditlog_options_auditlog_sequence`. A implementação acabou repartida por duas frentes:

1. **`0018_rename_gps_lon_gps_lng`** — `migrations.RenameField` em `Occurrence` (`gps_lon`→`gps_lng`) e em `Evidence` (`gps_lon`→`gps_lng`). Operação de metadados de schema; não toca dados nem hashes. O `integrity_hash` da `Evidence` é invariante ao rename (usa o valor, `core/models.py:626`).
2. **`0021_chainofcustody_ledger`** — os três campos GPS da `ChainOfCustody` (`gps_lat`, `gps_lng`, `gps_accuracy_m`) entram aqui, junto da reforma do ledger, não numa migração GPS isolada. Sem trigger novo: `trg_custody_no_update` (`BEFORE UPDATE FOR EACH ROW`, `core/migrations/0002_add_immutability_triggers.py:73-77`) já cobre as colunas adicionadas.

A `0019` ficou para a taxonomia (`0019_taxonomia_crimes_prioridade`); a cabeça da chain é hoje `0023_modelo_v2_genese_aquisicao_selagem`.

### Serializer / write-path

- Acrescentar `gps_lat`, `gps_lng`, `gps_accuracy_m` ao `ChainOfCustodySerializer` (campos de escrita-na-criação; o ledger é POST-only).
- O write no `perform_create` da `ChainOfCustodyViewSet` aceita os valores ajustados (pré-hash). O ajuste manual do agente chega como input normal do POST; o `save()` calcula o hash já com os valores finais (`core/models.py:1162-1169`). Nenhuma mutação pós-gravação é possível (triggers + `save()` recusa `pk is not None`, `core/models.py:1118-1122`).
- Actualizar os call-sites do rename: `core/models.py:626` (`compute_integrity_hash` — editar `self.gps_lon`→`self.gps_lng`; o byte-stream fica idêntico e o `integrity_hash` invariante, mas o nome do atributo Python tem de mudar senão levanta `AttributeError` pós-`RenameField`), `core/serializers.py:139,247`, `core/filters.py:27-31,61-63`, `core/pdf_export.py:516,691,808` e o `_fmt_gps` (`core/pdf_export.py:338-341`), além do JS de mapas (`config.js`, `dashboard_geo_hero.js`, páginas).

### Testes (escritos ao mesmo tempo que o código)

Acrescentar a `core/tests.py` (junto de `test_hash_is_deterministic`, `core/tests.py:107`, e `test_hash_chain_integrity`, `core/tests.py:269`):

1. **`test_hash_determinismo_com_gps`** — registo com `gps_lat`/`gps_lng`/`gps_accuracy_m` preenchidos: `compute_record_hash()` chamado duas vezes dá o mesmo valor; congelar a string de dados esperada como vector de regressão.
2. **`test_hash_difere_com_e_sem_gps`** — o mesmo registo com e sem GPS produz hashes distintos (o GPS está dentro do encadeamento).
3. **`test_hash_gps_parcial`** — só `gps_accuracy_m` preenchido (lat/lng nulos): os campos lat/lng entram vazios e o hash difere do registo totalmente sem GPS.
4. **`test_gps_ordem_lat_lng_nao_comutavel`** — trocar lat↔lng produz hash diferente (a ordem é parte do contrato).
5. **`test_gps_quantizacao_determinismo`** — gravar via API um evento com `gps_lat='38.72234'` (5 casas); reler o registo da BD e confirmar que `compute_record_hash` recalculado a partir do valor relido bate certo com o `record_hash` gravado (prova que a quantização a 7 casas elimina a divergência memória↔BD).
6. **`test_hash_escaping_texto_livre`** — `location_name` contendo `,` e `|` (ex.: `"Bomba BP, Av. da Liberdade | Lisboa"`) produz um hash distinto de uma `location_name` sem esses caracteres que, sem escaping, colidiria; confirma que `_hash_escape` evita a colisão de separador. Cobrir também `storage_location` com vírgula (ex.: `"Armário B-12, Sala 3"`).
7. **`test_gps_campos_imutaveis`** — ao nível ORM, tentar re-gravar um registo com GPS alterado levanta `ValidationError` (`pk is not None`, `core/models.py:1118-1122`); e, com `skipUnless(connection.vendor == 'postgresql')`, um teste de `UPDATE` directo que confirma o `trg_custody_no_update` a bloquear a coluna nova.
8. **`test_rename_integrity_hash_invariante`** (na suite da `Evidence`) — gravar uma evidência com GPS e confirmar que o `integrity_hash` é idêntico ao calculado pela fórmula com o valor (o rename de campo não muda o byte-stream, `core/models.py:626`).

### Base legal (a registar no relatório)

O tratamento de coordenadas GPS de precisão máxima no ledger de custódia funda-se na **necessidade probatória** — registo da localização da evidência em cada evento (ISO/IEC 27037 §5.4) — e respeita a **minimização por limitação de finalidade** (RGPD Art. 5.º/1/b-c): a finalidade declarada é localizar a *prova*, não vigiar o agente. Não se aplica *coarsening* de coordenadas porque reduziria valor probatório sem servir a finalidade. O `gps_accuracy_m` documenta a incerteza real do sensor (transparência), não uma incerteza imposta por política. A inferência incidental da posição do agente é assumida e documentada como limitação.

A cadeia de custódia, em Portugal, não tem regime legal próprio: é exigida pela doutrina e jurisprudência (Ac. Tribunal da Relação de Évora, 19-11-2024) como documentação do percurso da prova — rastreabilidade, integridade e autenticidade. O hash encadeado e o GPS por evento são os instrumentos técnicos que materializam essa documentação.

## Referências

- ADR-0009 — JWT em cookies HttpOnly; modelo de autorização base.
- ADR-0010 — Taxonomia digital-first; estrutura de `Evidence` + `ChainOfCustody` hash-chained, append-only.
- ADR-0012 — PDF como guia de transporte (cruza com o `_fmt_gps` do PDF).
- ADR-0015 — Ledger de eventos da custódia: define `event_type`, `custodian_type`, `location_name`, `storage_location` e o estado legal derivado do log; herda a fórmula de hash deste ADR.
- `core/models.py:1052-1094` — `compute_record_hash` (fórmula a substituir pela única).
- `core/models.py:1104-1184` — `ChainOfCustody.save()`/`delete()` (append-only, hash pré-INSERT, `pk is not None`).
- `core/models.py:603-633` — `Evidence.compute_integrity_hash` (invariante ao rename; usa valor, não nome — `:626`).
- `core/models.py:251-258` / `:454-461` — campos `gps_lat`/`gps_lon` de `Occurrence`/`Evidence` a renomear.
- `core/migrations/0002_add_immutability_triggers.py:63-88` — `trg_custody_no_update`/`no_delete` (cobre colunas novas).
- `core/migrations/0013_protect_occurrence.py` — triggers de `Occurrence` (padrão de imutabilidade PG; não toca custódia).
- `core/serializers.py:139,247` · `core/filters.py:27-31,61-63` · `core/pdf_export.py:338-341,516,691,808` — call-sites do rename `gps_lon`→`gps_lng`.
- `core/tests.py:107,269` — testes de determinismo e hash-chain existentes a estender.
- CPP (DL 78/87) Art. 154.º, 158.º, 178.º — perícia, nova perícia, apreensão e validação ≤72h.
- Código Penal Art. 109.º-111.º — perda de instrumentos/produtos a favor do Estado.
- Ac. Tribunal da Relação de Évora, 19-11-2024 — cadeia de custódia como documentação do percurso da prova.
- ISO/IEC 27037 §5.4 — preservação da integridade de metadados contextuais da prova.
- RGPD Art. 5.º/1/b-c — limitação de finalidade e minimização.
