# ADR-0013: GPS na cadeia de custódia (hash versionado, convenção `gps_lng` e precisão máxima sem arredondamento)

## Status

Accepted — 2026-05-30. Formaliza as decisões **D1**, **D2** e **D5** do `docs/refactor/REFACTOR_MANIFEST.md` (§6) e é o **contrato forense** que governa os temas **T01** (GPS na custódia + hash versionado) e **T02** (normalização `gps_lng`). É **pré-requisito do ADR-0015** (FSM ramificada da custódia, T20): os campos GPS vivem *aqui*; a localização textual (`location_name`) e o tipo de custódio (`custodian_type`) são detalhados nesse ADR mas assentam na fórmula de hash fixada neste.

Supersede parcialmente a nota de implementação de `core/models.py:1062-1063` (docstring da fórmula do hash), que passa a descrever o **segmento GPS condicional** introduzido aqui.

## Data

2026-05-30

## Context

A `ChainOfCustody` é um **ledger append-only com hash-chain SHA-256** (ADR-0010). Cada registo encadeia com o anterior via `compute_record_hash` (`core/models.py:1052-1094`), e a fórmula actual, verificada directamente no código (`core/models.py:1085-1093`), é:

```python
data = (
    f'{previous_hash}|'
    f'seq={self.sequence}|'
    f'{self.evidence_id}|'
    f'{self.previous_state}|{self.new_state}|'
    f'{self.agent_id}|'
    f'{self.timestamp.isoformat()}|'
    f'{self.observations}'
)
return hashlib.sha256(data.encode('utf-8')).hexdigest()
```

Ou seja: `SHA-256(previous_hash | seq=N | evidence_id | previous_state | new_state | agent_id | timestamp_iso | observations)`. **O GPS não entra no hash hoje** — e a `ChainOfCustody` nem sequer tem campos GPS (confirmado: o modelo, `core/models.py:919-1012`, vai de `code` a `sequence` sem nenhum campo de coordenadas).

A v2 do frontend (mockup V20) pressupõe um mini-mapa "Cadeia" — polyline com a jornada da prova, pins por estado, tooltip com a precisão `±N m` — e uma timeline geo-referenciada. **Nenhum destes elementos tem fonte de dados**: o backend não regista *onde* esteve a prova em cada transição. Esta é a lacuna estrutural #1 do inventário (REFACTOR_MANIFEST §2.9, §4.1).

Acrescentar GPS a um ledger imutável e encadeado tem duas armadilhas forenses que este ADR existe para desarmar:

1. **Partir o recálculo histórico.** Se o GPS entrar incondicionalmente na fórmula, *todos* os registos já gravados (que têm GPS ausente) deixam de recalcular para o mesmo `record_hash` — a cadeia histórica fica inverificável por um perito independente. A imutabilidade ao nível dos triggers (`prevent_custody_modification`, `core/migrations/0002_add_immutability_triggers.py:63-82`) impede corrigir os registos *a posteriori*; logo a fórmula nova **tem de** recalcular byte-a-byte idêntico para os registos antigos.

2. **Regressão silenciosa.** As factories de teste gravam GPS ausente por defeito; um teste de determinismo que não preencha GPS continua verde mesmo que o segmento GPS esteja mal serializado. O determinismo do ramo *com* GPS tem de ser testado explicitamente, escrito **ao mesmo tempo** que o código (REFACTOR_MANIFEST §5, PASSO 2).

Há ainda uma incoerência de nomenclatura herdada: `Occurrence` (`core/models.py:251-258`) e `Evidence` (`core/models.py:454-461`) usam `gps_lon`; os serializers expõem `gps_lon` (`core/serializers.py:139`, `:247`); os filtros tocam `gps_lat` (`core/filters.py:27-31`, `:61-63`); o PDF lê `evidence.gps_lon`/`occ.gps_lon` (`core/pdf_export.py:516`, `:691`, `:808`). A spec/mockup e o JS de mapas esperam `gps_lng`. Criar campos GPS novos na `ChainOfCustody` obriga a escolher uma convenção — e mantê-la divergente seria perpetuar a raiz do bug do hero geo (REFACTOR_MANIFEST §7.5).

Por fim, a granularidade. Numa primeira leitura, registar GPS em cada transição parece **vigilância do agente** (RGPD: minimização de dados → arredondar coordenadas). O dono reenquadrou a finalidade em 2026-05-30:

> "O GPS na custódia regista **onde está a evidência** em cada transição — na apreensão, no transporte, no armazenamento do laboratório —, **não** é vigiar a posição do agente. É necessidade estrita para a prova. A inferência da posição do agente é incidental e aceitável, acontece em qualquer registo de campo. Quero a posição com a precisão máxima possível, e o agente deve poder ajustar manualmente a marcação antes de gravar, porque o GPS faz drift."

Esta clarificação muda a base legal RGPD: a minimização satisfaz-se pela **limitação de finalidade** (a coordenada serve a localização da prova, não o rastreio do agente), **não** por arredondamento — o *coarsening* destruiria valor probatório sem reduzir a finalidade declarada.

## Decision

1. **O GPS entra no `compute_record_hash` de forma ADITIVA/VERSIONADA (D1).** Anexa-se um **segmento GPS condicional** à string de dados, presente **apenas quando pelo menos um campo GPS é não-nulo**. Para registos com GPS totalmente ausente (todos os históricos e qualquer transição futura sem captura), a string de dados é **byte-a-byte idêntica** à fórmula actual → o `record_hash` recalcula igual → a cadeia histórica permanece verificável. **Esta é a decisão forense irreversível** depois de em produção.

2. **A fórmula completa do hash é fixada AQUI, num só sítio** (ver *Implementação*) — incluindo o segmento de localização cujos campos são definidos no ADR-0015. Isto elimina qualquer deferral: a serialização de `location_name`/`custodian_type`/`storage_location` no hash **não** fica adiada para o ADR-0015. Ordem global dos segmentos: `...|observations` → `[|gps=<lat>,<lng>,<acc>]` → `[|loc=<location_name>,<custodian_type>,<storage_location>]`. Cada segmento omitido por inteiro quando o seu grupo é vazio; ordens internas não-comutáveis; texto livre escapado; coordenadas quantizadas a 7 casas antes do hash. Tudo parte do contrato irreversível.

3. **Convenção de longitude normalizada para `gps_lng` em todo o schema (D2).** A `ChainOfCustody` nasce já com `gps_lng`. Em paralelo, `Occurrence.gps_lon` e `Evidence.gps_lon` são **renomeados** para `gps_lng` via migration de rename, com actualização de `core/serializers.py:139,247`, `core/filters.py`, `core/pdf_export.py` (`_fmt_gps` e os três call-sites) e do JS de mapas (`config.js`, `dashboard_geo_hero.js`, pages). O rename **não altera o `integrity_hash` da `Evidence`**: `compute_integrity_hash` usa o *valor* do campo (`core/models.py:626` — `f'{self.gps_lat}|{self.gps_lon}|'`), não o nome Python; o byte-stream que entra no SHA-256 é idêntico antes e depois.

4. **Três campos novos na `ChainOfCustody`, com precisão máxima e sem arredondamento por papel (D5):**
   - `gps_lat` — `DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)`, validadores `Min(-90)/Max(90)` — idêntico a `Occurrence`/`Evidence`.
   - `gps_lng` — `DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)`, validadores `Min(-180)/Max(180)`.
   - `gps_accuracy_m` — `PositiveIntegerField(null=True, blank=True)`, **metadado** de precisão reportada pelo dispositivo (raio em metros), **não** mecanismo de arredondamento.

   **Sem tabela de arredondamento por papel.** A coordenada é gravada com a precisão máxima disponível. A minimização RGPD satisfaz-se pela **limitação de finalidade** (localização da prova), documentada na *Implementação* (base legal).

5. **Ajuste manual da posição é permitido, mas SEMPRE pré-hash.** O agente pode corrigir a marcação (drift de GPS) antes de submeter a transição. Como o registo se torna imutável **ao gravar** (`save()` calcula o hash dentro da `transaction.atomic()`, `core/models.py:1162-1169`), qualquer ajuste acontece necessariamente **antes** do cálculo do hash e do INSERT. Não há — nem pode haver — edição pós-gravação: os triggers de linha recusam-na (ponto 6). O ajuste é, por construção, server-side e pré-hash.

6. **Os campos novos ficam cobertos automaticamente pelos triggers de imutabilidade.** `trg_custody_no_update` (`core/migrations/0002_add_immutability_triggers.py:73-77`) é `BEFORE UPDATE ... FOR EACH ROW` — bloqueia a linha inteira, incluindo colunas adicionadas depois. **Nenhuma migration de trigger é necessária** para os campos novos. A matriz documental de imutabilidade (relatório final / `docs/scope/iso27037-traceability.tex`) **deve listar** `gps_lat`, `gps_lng`, `gps_accuracy_m` como campos cobertos pelo trigger de `ChainOfCustody`.

7. **O validador da FSM continua no modelo, não nas views.** Este ADR não toca em `VALID_TRANSITIONS` (`core/models.py:943-953`) nem em `clean()` (`core/models.py:1034-1050`) — a FSM ramificada é trabalho do ADR-0015/T20. O GPS é ortogonal ao estado: entra no hash, não na máquina de estados.

## Alternatives Considered

- **(D1-a) GPS fora do hash** — campos GPS na tabela, protegidos só pelo trigger de linha, mas ausentes da fórmula do `record_hash`. Rejeitado: deixaria a localização da prova fora da cadeia de integridade verificável. Um perito que recalcule a cadeia não confirmaria que o GPS gravado é o GPS original; bastaria um `UPDATE` directo (que o trigger *deveria* travar, mas a defesa-em-profundidade exige que o próprio hash também o cubra). O valor probatório do GPS depende de ele estar *dentro* do encadeamento.

- **(D1-b) GPS sempre no hash, incondicional** — anexar `|gps=...,...,...` a todos os registos, com `None` serializado como string vazia para os antigos. Rejeitado: **partiria o recálculo histórico**. Mesmo serializando os nulos, a string deixaria de ser byte-idêntica (o separador `|gps=,,` não existe nos hashes já gravados). A cadeia histórica ficaria inverificável — violação directa do invariante append-only. A condicionalidade (D1-c) é o que preserva a verificabilidade do passado.

- **(D1-c, escolhida) versão por presença vs. campo `hash_version` explícito** — considerou-se um `hash_version` inteiro materializado na linha. Rejeitado a favor da **condicionalidade por presença** (segmento omitido quando o grupo de campos é vazio): é mais simples, não acrescenta coluna, e o "versionamento" fica implícito e determinístico (a presença de cada segmento *é* a versão). Isto escala para as 3 gerações que já existem — legado / `+gps` / `+gps+loc` (este último com os campos do ADR-0015): a presença combinada dos segmentos `gps` e `loc` descreve a geração sem ambiguidade, sem precisar de coluna de versão. O princípio aditivo mantém-se em ambos os segmentos.

- **(D2) manter `gps_lon`** (já em produção) e criar a `ChainOfCustody` com `gps_lon` para coerência interna. Rejeitado: a divergência `gps_lon` (backend) vs `gps_lng` (spec/JS) é a raiz do bug do hero geo (REFACTOR_MANIFEST §7.5). Convergir tudo para `gps_lng` elimina a classe inteira de bugs de contrato; o rename é seguro porque o `integrity_hash` usa o valor, não o nome.

- **(D5) arredondamento por papel** (truncar coordenadas por nível de acesso, à la *geo-coarsening* de privacidade). Rejeitado após o reenquadramento de finalidade: o GPS marca a **localização da evidência**, não vigia o agente; arredondar destruiria precisão probatória para mitigar um risco (rastreio do agente) que é incidental e já coberto pela limitação de finalidade RGPD. O `gps_accuracy_m` regista a incerteza *real* do sensor — informação honesta —, não uma incerteza fabricada por política.

- **Eliminar o ajuste manual** (gravar sempre a leitura crua do GPS). Rejeitado: o drift de GPS em ambiente urbano/interior é real; obrigar a gravar uma leitura errada degradaria a prova. O ajuste pré-hash dá ao agente a correcção sem abrir qualquer janela de mutação pós-gravação (o registo só fica imutável *depois* do ajuste, ao gravar).

## Consequences

### Positivas

- **Desbloqueia o mini-mapa "Cadeia" e a timeline geo da v2** (T01). A jornada da prova passa a ter fonte de dados real: pins por estado, polyline, tooltip `±N m` a partir de `gps_accuracy_m`.
- **Cadeia histórica permanece 100% verificável.** A condicionalidade do segmento garante que todos os registos pré-existentes recalculam o mesmo `record_hash`. Zero migrações de dados sobre o ledger (que aliás seriam impossíveis sob os triggers).
- **Convenção única `gps_lng`** elimina a raiz do bug do hero geo e harmoniza schema/serializers/PDF/JS.
- **Base legal RGPD limpa e defensável.** A minimização por limitação de finalidade é argumentável na defesa: o GPS serve a prova, não o agente; documentado e rastreável.
- **Imutabilidade preservada sem trabalho extra.** Os triggers `BEFORE UPDATE FOR EACH ROW` cobrem as colunas novas automaticamente — defesa-em-profundidade intacta.

### Negativas / Trade-offs

- **A fórmula do hash passa a ter dois ramos.** Acresce complexidade de teste: o determinismo tem de ser provado *com* e *sem* GPS, e o ramo sem-GPS tem de ser provado **byte-idêntico** ao histórico. Mitigação: teste escrito ao mesmo tempo que o código (ver *Implementação*), incluindo um vector de regressão que congela a string de dados de um registo sem GPS.
- **Irreversibilidade.** Uma vez em produção com registos GPS gravados, a ordem/serialização do segmento não pode mudar sem partir esses hashes. É por isso que este ADR fixa a ordem `lat,lng,acc` e a regra de serialização *antes* de qualquer código tocar a fórmula (REFACTOR_MANIFEST §5, PASSO 0/PASSO 2).
- **Rename `gps_lon`→`gps_lng` toca muitos ficheiros** (serializers, filters, PDF, JS). Mitigação: migration de rename mecânica (`RenameField`), e o invariante de que o `integrity_hash` não muda dá confiança de que a prova não é afectada. Confirmar que nenhum índice/constraint depende do nome antigo (não dependem — os índices da `Evidence`/`Occurrence` são sobre outras colunas).
- **Inferência incidental da posição do agente.** Gravar GPS de precisão máxima permite, em teoria, reconstruir trajectos do agente. Aceite e documentado como incidental à finalidade probatória; não há decisão de coarsening. Registar como limitação assumida no relatório (secção RGPD).

### Impactos noutros documentos

- **`docs/architecture/adr/ADR-0015-*.md`** (FSM ramificada): **define** os campos `location_name`, `custodian_type`, `storage_location` (semântica, fonte OSM, enum), mas a sua **serialização no hash é fixada neste ADR** (segmento `|loc=`). O ADR-0015 referencia esta fórmula; não a redefine. Assim a fórmula do `record_hash` vive num único sítio.
- **`docs/scope/iso27037-traceability.tex`** / matriz documental de imutabilidade: acrescentar `gps_lat`, `gps_lng`, `gps_accuracy_m` da `ChainOfCustody` à lista de campos cobertos por `trg_custody_no_update`.
- **`docs/refactor/REFACTOR_MANIFEST.md`**: T01 e T02 passam de "decidido" a "especificado" — este ADR é o contrato que o PASSO 2 implementa.
- **`core/pdf_export.py`**: o `_fmt_gps` (`core/pdf_export.py:338-341`) tem um **bug de hemisfério pré-existente** (imprime sempre `°N, °E`; Portugal é longitude W). Corrigir o sinal **antes** de o GPS da custódia aparecer no PDF (finding `pdf-fmt-gps-hemisferio-errado`, T14). Fora do âmbito de aceitação deste ADR, mas a renomeação do call-site para `gps_lng` cruza com ele.
- **`README.md`** / spec de frontend (`docs/refactor/art-direction.md`): convenção de longitude passa a `gps_lng` em todas as referências.

## Implementação

### Campos novos (`ChainOfCustody`, `core/models.py`)

```python
gps_lat = models.DecimalField(
    max_digits=10, decimal_places=7, null=True, blank=True,
    validators=[MinValueValidator(-90), MaxValueValidator(90)],
    verbose_name='Latitude GPS (transição)',
)
gps_lng = models.DecimalField(
    max_digits=10, decimal_places=7, null=True, blank=True,
    validators=[MinValueValidator(-180), MaxValueValidator(180)],
    verbose_name='Longitude GPS (transição)',
)
gps_accuracy_m = models.PositiveIntegerField(
    null=True, blank=True,
    verbose_name='Precisão GPS reportada (m)',
    help_text='Raio de incerteza em metros reportado pelo dispositivo. '
              'Metadado de precisão — não altera a coordenada gravada.',
)
```

### Nova fórmula do hash (`compute_record_hash`, `core/models.py:1085-1094`)

O segmento GPS é **anexado só quando há GPS**. A regra de presença: `gps_lat is not None or gps_lng is not None or gps_accuracy_m is not None`.

```python
data = (
    f'{previous_hash}|'
    f'seq={self.sequence}|'
    f'{self.evidence_id}|'
    f'{self.previous_state}|{self.new_state}|'
    f'{self.agent_id}|'
    f'{self.timestamp.isoformat()}|'
    f'{self.observations}'
)
# Segmento GPS — ADITIVO/VERSIONADO (D1): só quando algum campo GPS é
# não-nulo. Registos históricos (GPS=None) recalculam byte-a-byte
# idêntico à fórmula anterior → cadeia verificável. As coordenadas são
# QUANTIZADAS a 7 casas no clean() ANTES de chegar aqui (ver regra de
# quantização), para o valor em memória == valor na BD == valor que o
# perito recalcula a partir do registo relido.
if self.gps_lat is not None or self.gps_lng is not None or self.gps_accuracy_m is not None:
    data += (
        f'|gps='
        f'{"" if self.gps_lat is None else self.gps_lat},'
        f'{"" if self.gps_lng is None else self.gps_lng},'
        f'{"" if self.gps_accuracy_m is None else self.gps_accuracy_m}'
    )
# Segmento de LOCALIZAÇÃO — campos definidos operacionalmente no
# ADR-0015 (location_name, custodian_type, storage_location). A sua
# serialização no hash é fixada AQUI para a fórmula viver num só sítio
# (resolve o deferral circular). Mesma regra aditiva: presente só quando
# algum é não-vazio → registos GPS-only (ADR-0013) e legados recalculam
# idêntico. Os campos de texto livre são ESCAPADOS (free text OSM/manual
# pode conter "|" ou "," — evita colisão de separador).
if self.location_name or self.custodian_type or self.storage_location:
    data += (
        f'|loc='
        f'{_hash_escape(self.location_name)},'
        f'{self.custodian_type},'
        f'{_hash_escape(self.storage_location)}'
    )
return hashlib.sha256(data.encode('utf-8')).hexdigest()
```

Helper de escaping (módulo `core/models.py`), determinístico e reversível:

```python
def _hash_escape(value: str) -> str:
    """Escapa separadores do hash em campos de texto livre.
    Ordem fixa: backslash primeiro, depois os separadores."""
    return (value or '').replace('\\', '\\\\').replace('|', '\\|').replace(',', '\\,')
```

**Regras de serialização fixadas (IRREVERSÍVEIS — contrato forense):**
- **Ordem global dos segmentos:** `...|observations` → `[|gps=...]` → `[|loc=...]`. Cada segmento opcional, presente só quando o seu grupo de campos é não-vazio. Esta ordem é parte do contrato (gps antes de loc).
- **Segmento GPS** `|gps=<lat>,<lng>,<acc>`: ordem `lat`, `lng`, `acc` (não-comutável). Componente nulo → string vazia entre vírgulas (`|gps=38.7223400,-9.1393660,`). Omitido por inteiro quando os três são nulos.
- **Segmento de localização** `|loc=<location_name>,<custodian_type>,<storage_location>`: ordem `location_name`, `custodian_type`, `storage_location` (não-comutável). `location_name` e `storage_location` passam por `_hash_escape` (texto livre); `custodian_type` é enum (sem escaping). Componente nulo/vazio → string vazia. Omitido por inteiro quando os três são vazios.
- **Quantização (resolve a regressão de determinismo):** `gps_lat`/`gps_lng` são quantizados para EXACTAMENTE 7 casas no `clean()` — `value.quantize(Decimal('0.0000001'))` — **antes** do cálculo do hash. Sem isto, um input com nº de casas ≠ 7 (ex.: `'38.72234'`) seria hasheado em memória com a representação do input, mas relido da BD com 7 casas → o perito recalcularia hash diferente. A quantização garante `valor em memória == valor na BD == valor recalculado`.
- **Versionamento por presença, não por coluna:** há agora 3 gerações da fórmula (legado / `+gps` / `+gps+loc`). A *presença* de cada segmento descreve a geração de forma determinística e auto-explicativa — **não** se materializa um campo `hash_version` (mantém-se aditivo e sem coluna extra; a regra de presença é a versão).

**Faseamento da implementação.** A fórmula completa é *especificada* aqui — fonte única, decisão irreversível tomada já — mas é *implementada* em duas aterragens, alinhadas com o sequenciamento (T01 antes de T20, REFACTOR_MANIFEST §5):
- O segmento `|gps=` entra com **T01** (este ADR), quando se acrescentam `gps_lat/gps_lng/gps_accuracy_m`.
- O segmento `|loc=` entra com **T20** (ADR-0015), quando se acrescentam `location_name/custodian_type/storage_location`. Até lá, `compute_record_hash` implementa **só** o segmento `|gps=`; o código do `|loc=` é acrescentado pelo T20 **exactamente** como fixado aqui (mesmo separador, ordem, escaping, regra de presença).

Em qualquer das aterragens, registos sem os campos do segmento recalculam idêntico (regra de presença) — a cadeia histórica nunca quebra entre fases.

Actualizar a docstring de `compute_record_hash` (`core/models.py:1062-1063`) para descrever os dois segmentos condicionais e a quantização.

### Migrations

Cabeça actual da migration chain: `0017_alter_auditlog_options_auditlog_sequence`. Duas migrations novas (separadas para clareza de revisão):

1. **`0018_rename_gps_lon_to_gps_lng`** — `migrations.RenameField` em `Occurrence` (`gps_lon`→`gps_lng`) e em `Evidence` (`gps_lon`→`gps_lng`). Operação de metadados de schema; **não toca dados** nem hashes. Confirma-se que o `integrity_hash` da `Evidence` é invariante ao rename (usa o valor, `core/models.py:626`).
2. **`0019_chainofcustody_gps`** — `AddField` dos três campos (`gps_lat`, `gps_lng`, `gps_accuracy_m`) à `ChainOfCustody`. **Sem trigger novo**: `trg_custody_no_update` (`BEFORE UPDATE FOR EACH ROW`, `core/migrations/0002_add_immutability_triggers.py:73-77`) já cobre as colunas adicionadas. Documentar isto no docstring da migration.

### Serializer / write-path

- Acrescentar `gps_lat`, `gps_lng`, `gps_accuracy_m` ao `ChainOfCustodySerializer` (campos de **escrita-na-criação**; o ledger é POST-only).
- O write no `perform_create` da `ChainOfCustodyViewSet` aceita os valores ajustados (pré-hash). O ajuste manual do agente chega como input normal do POST; o `save()` calcula o hash já com os valores finais (`core/models.py:1162-1169`). Nenhuma mutação pós-gravação é possível (triggers + `save()` recusa `pk is not None`, `core/models.py:1118-1122`).

### Quantização e validador

A FSM (`VALID_TRANSITIONS`, `core/models.py:943-953`) e a lógica de transição do `clean()` (`core/models.py:1034-1050`) não mudam neste ADR (são trabalho do ADR-0015). Mas o `clean()` ganha um passo de **quantização** das coordenadas a 7 casas, antes de o hash ser calculado em `save()`:

```python
def clean(self):
    super().clean()
    # ... validação de transição existente (inalterada) ...
    # Quantização GPS (ADR-0013): garante o determinismo do hash —
    # valor em memória == valor na BD == valor recalculado pelo perito.
    q = Decimal('0.0000001')  # 7 casas
    if self.gps_lat is not None:
        self.gps_lat = self.gps_lat.quantize(q)
    if self.gps_lng is not None:
        self.gps_lng = self.gps_lng.quantize(q)
```

Os validadores de campo `Min/Max` correm via `full_clean()` já invocado em `save()` (`core/models.py:1162`); a quantização corre no mesmo `full_clean()`, **antes** de `compute_record_hash`. Sem este passo, um input com casas ≠ 7 seria hasheado em memória com a representação do input mas relido da BD com 7 casas → recálculo divergente.

### Testes (escritos **ao mesmo tempo** que o código — REFACTOR_MANIFEST §5 PASSO 2)

Acrescentar a `core/tests.py` (junto de `test_hash_is_deterministic`, `core/tests.py:107-119`, e `test_hash_chain_integrity`, `core/tests.py:269-291`):

1. **`test_hash_determinismo_sem_gps_identico_ao_legado`** — registo com GPS=None recalcula o **mesmo** `record_hash` que a fórmula anterior. Congelar a string de dados esperada como vector de regressão (prova byte-identidade com o histórico). **Este é o teste que protege o invariante irreversível.**
2. **`test_hash_determinismo_com_gps`** — registo com `gps_lat`/`gps_lng`/`gps_accuracy_m` preenchidos: `compute_record_hash()` chamado duas vezes dá o mesmo valor; e difere do mesmo registo sem GPS.
3. **`test_hash_gps_parcial`** — só `gps_accuracy_m` preenchido (lat/lng nulos): o segmento aparece com lat/lng vazios (`|gps=,,N`) e o hash difere do registo totalmente sem GPS.
4. **`test_gps_ordem_lat_lng_nao_comutavel`** — trocar lat↔lng produz hash diferente (a ordem é parte do contrato).
5. **`test_gps_campos_imutaveis`** — ao nível ORM, tentar re-gravar um registo com GPS alterado levanta `ValidationError` (`pk is not None`, `core/models.py:1118-1122`); e marcar com `skipUnless(connection.vendor == 'postgresql')` um teste de `UPDATE` directo que confirma o `trg_custody_no_update` a bloquear a coluna nova (integra com o `trigger-layer-untested` de T16).
6. **`test_rename_integrity_hash_invariante`** (em `core/tests.py` da `Evidence`) — gravar uma evidência com GPS e confirmar que o `integrity_hash` é idêntico ao calculado pela fórmula com o valor (o rename de campo não muda o byte-stream, `core/models.py:626`).
7. **`test_gps_quantizacao_determinismo`** — gravar via API uma transição com `gps_lat='38.72234'` (5 casas); reler o registo da BD e confirmar que `compute_record_hash` recalculado a partir do valor relido bate certo com o `record_hash` gravado (prova que a quantização a 7 casas elimina a divergência memória↔BD).
8. **`test_loc_segment_escaping`** — `location_name` contendo `,` e `|` (ex.: `"Bomba BP, Av. da Liberdade | Lisboa"`) produz um hash distinto de uma `location_name` sem esses caracteres que, sem escaping, colidiria; confirma que `_hash_escape` evita a colisão de separador.

### Base legal RGPD (a registar no relatório)

O tratamento de coordenadas GPS de precisão máxima na cadeia de custódia funda-se na **necessidade probatória** (registo da localização da evidência em cada transição, ISO/IEC 27037 §5.4) e respeita a **minimização por limitação de finalidade** (RGPD Art. 5.º/1/b-c): a finalidade declarada é localizar a *prova*, não vigiar o agente. Não se aplica *coarsening* de coordenadas porque reduziria valor probatório sem servir a finalidade. A `gps_accuracy_m` documenta a incerteza real do sensor (transparência), não uma incerteza imposta por política. A inferência incidental da posição do agente é assumida e documentada como limitação.

## Referências

- ADR-0009 — JWT em cookies HttpOnly; modelo de autorização base.
- ADR-0010 — Taxonomia digital-first; estrutura de `Evidence` + `ChainOfCustody` hash-chained.
- ADR-0012 — PDF como guia de transporte (cruza com o `_fmt_gps` do PDF).
- ADR-0015 *(a redigir)* — FSM ramificada da custódia (CPP Art. 178.º) + `location_name`/`custodian_type`; herda a fórmula de hash deste ADR.
- `docs/refactor/REFACTOR_MANIFEST.md` — §6 (D1, D2, D5), temas T01/T02/T20, §5 (sequenciamento), §7 (verificações).
- `core/models.py:1052-1094` — `compute_record_hash` (fórmula a estender).
- `core/models.py:1104-1184` — `ChainOfCustody.save()`/`delete()` (append-only, hash pré-INSERT).
- `core/models.py:603-633` — `Evidence.compute_integrity_hash` (invariante ao rename; usa valor, não nome).
- `core/models.py:243-258` / `:446-461` — campos `gps_lat`/`gps_lon` de `Occurrence`/`Evidence` a renomear.
- `core/migrations/0002_add_immutability_triggers.py:63-88` — `trg_custody_no_update`/`no_delete` (cobre colunas novas).
- `core/migrations/0013_protect_occurrence.py` — triggers de `Occurrence` (padrão de imutabilidade PG).
- `core/serializers.py:139,247` · `core/filters.py:27-31,61-63` · `core/pdf_export.py:338-341,516,691,808` — call-sites do rename `gps_lon`→`gps_lng`.
- `core/tests.py:107-119,269-291` — testes de determinismo e hash-chain existentes a estender.
- Decisão do dono, 2026-05-30 (sessão de planeamento da Fase 2) — captura da finalidade do GPS e do ajuste manual pré-hash.
- ISO/IEC 27037 §5.4 — preservação da integridade de metadados contextuais da prova.
- RGPD Art. 5.º/1/b-c — limitação de finalidade e minimização.
