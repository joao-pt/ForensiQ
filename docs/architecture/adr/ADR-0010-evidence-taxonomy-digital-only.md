# ADR-0010: Taxonomia de Evidência Focada em Prova Digital

## Status

Accepted — **supersede parcialmente ADR-0002 §4** ("Modelos core: User, Occurrence, Evidence, DigitalDevice, ChainOfCustody"). Os modelos permanecem; o enum `Evidence.EvidenceType` é substituído pela taxonomia abaixo.

## Data

2026-04-19

## Context

A versão inicial de `Evidence.EvidenceType` (ADR-0002) definia cinco categorias genéricas herdadas da terminologia policial analógica:

| Legacy code       | Uso real observado (Wave 2a pilot) |
| ----------------- | ---------------------------------- |
| `DIGITAL_DEVICE`  | Telemóveis, computadores, discos, tudo — demasiado amplo |
| `DOCUMENT`        | 0 ocorrências na amostra piloto — a PSP digitalizou o fluxo em 2024 |
| `PHOTO`           | Confundido com a fotografia anexada a qualquer evidência (`photo` ImageField) |
| `VEHICLE`         | OK — mas faltam os sub-componentes electrónicos |
| `OTHER`           | 40% das entradas, maioria eram dispositivos IoT / wearables |

Três problemas derivam desta taxonomia:

1. **Ambiguidade na peritagem.** Um perito recebendo "DIGITAL_DEVICE: iPhone 13 Pro + SIM + microSD" não consegue, sem ler a descrição livre, distinguir dispositivo principal de sub-componentes. Perde-se hierarquia e automação (triagem, aquisições, relatórios).
2. **Campos específicos disfarçados.** IMEI, IMSI, ICCID, VIN, MAC não têm sítio natural — acabam misturados no `description` em texto livre, inviabilizando queries e lookups externos (ADR-0008).
3. **Pressão do ecossistema.** A doutrina ISO/IEC 27037 + ENFSI 2024 orienta para taxonomias digital-first (dispositivos, suportes, ficheiros, tokens de identidade), alinhadas com os fluxos das plataformas comerciais (Cellebrite, Magnet, MSAB).

Simultaneamente, um novo requisito entrou no Wave 2: **registos hierárquicos** — um telemóvel apreendido pode conter um SIM e um microSD que são em si evidências com número de série próprio, mas que dependem do telemóvel-pai para contextualização. A taxonomia tem de acomodar raízes e sub-componentes sem perder rastreabilidade.

## Decision

1. **Remover** `DIGITAL_DEVICE`, `DOCUMENT`, `PHOTO`, `OTHER` da enum `Evidence.EvidenceType`. Manter `VEHICLE`.
2. **Adicionar 18 códigos digital-first**, organizados em dois grupos lógicos (raízes autónomas vs sub-componentes típicos):

### Dispositivos autónomos (tipicamente raiz da árvore)
| Código | Descrição |
| ------ | --------- |
| `MOBILE_DEVICE`   | Telemóvel / Smartphone / Tablet |
| `COMPUTER`        | PC / portátil / servidor |
| `STORAGE_MEDIA`   | Suporte de armazenamento externo (pen USB, disco externo) |
| `GAMING_CONSOLE`  | Consola de jogos |
| `GPS_TRACKER`     | Rastreador GPS |
| `SMART_TAG`       | Localizador Bluetooth (AirTag, SmartTag, Tile) |
| `CCTV_DEVICE`     | CCTV / DVR / NVR |
| `VEHICLE`         | Veículo (container para componentes) |
| `DRONE`           | Drone / UAV |
| `IOT_DEVICE`      | Dispositivo IoT genérico |
| `NETWORK_DEVICE`  | Router, switch, AP |
| `DIGITAL_FILE`    | Ficheiro digital capturado isoladamente |
| `RFID_NFC_CARD`   | Cartão RFID / NFC |
| `OTHER_DIGITAL`   | Fallback explícito para dispositivos digitais não cobertos |

### Sub-componentes típicos (tipicamente folhas da árvore)
| Código | Descrição |
| ------ | --------- |
| `SIM_CARD`          | Cartão SIM |
| `MEMORY_CARD`       | Cartão de memória (SD / microSD / CF) |
| `INTERNAL_DRIVE`    | Disco interno (HDD / SSD / NVMe) |
| `VEHICLE_COMPONENT` | Componente electrónico de veículo (ECU, dashcam, telemetry) |

3. **Hierarquia explícita:** Adicionar `parent_evidence: ForeignKey('self', null=True)` com `MAX_TREE_DEPTH = 3` — permite "telemóvel → SIM → (chip é folha)" mas impede árvores patológicas. Validação em `Evidence.clean()` via walk recursivo anti-ciclos.
4. **Campos específicos via JSON:** Novo `type_specific_data: JSONField(default=dict)` recebe `imei`, `imsi`, `iccid`, `mac`, `vin`, `serial_bios`, etc. conforme o tipo. Serializer e `Model.clean()` aplicam validadores dedicados (`validate_imei`, `validate_imsi`, `validate_vin`) em defense-in-depth.
5. **Mapa de migração (forward-only):**
   | Legacy | Substituto | Notas |
   | ------ | ---------- | ----- |
   | `DIGITAL_DEVICE` | `MOBILE_DEVICE` ou `COMPUTER` | A peritagem escolhe por contexto |
   | `DOCUMENT`       | `OTHER_DIGITAL` | Fallback — papel deixou de existir |
   | `PHOTO`          | `DIGITAL_FILE` | Captura fotográfica como ficheiro digital |
   | `VEHICLE`        | `VEHICLE` | Inalterado |
   | `OTHER`          | `OTHER_DIGITAL` | Semântica digital explícita |
6. **Testes e factories alinhadas.** `core/tests_factories.py` expõe `EvidenceMobileFactory`, `EvidenceVehicleFactory`, `EvidenceSimCardFactory`; os testes unitários (`core/tests.py`, `core/tests_api.py`, `core/tests_pdf.py`, `core/tests_frontend.py`) usam sempre os novos códigos.

## Alternatives Considered

- **Manter `OTHER` sem qualificador digital.** Rejeitado — perde-se a demarcação deliberada face ao mundo analógico, reabrindo a porta a confusões com "documento em papel".
- **Uma única categoria `DIGITAL_DEVICE` + subtipo em `type_specific_data`.** Mais flexível mas torna queries/filtragem penosas (todos os relatórios teriam de ler JSON para distinguir telemóvel de computador). Rejeitado.
- **Importar taxonomia do Cellebrite UFED.** Demasiado operacional e sob marca comercial — o mapeamento faz-se externamente na interoperabilidade, não no modelo canónico.
- **Camada separada `EvidenceCategory` (modelo dedicado).** Over-engineering para 18 valores relativamente estáveis — uma `TextChoices` é suficiente e consta no código.

## Consequences

### Positivas
- **Triagem automatizável** — por tipo, a UI / backend aplica fluxos específicos (ex.: `MOBILE_DEVICE` → pedir IMEI; `VEHICLE` → pedir VIN).
- **Lookups externos viáveis** — IMEI e VIN ganham sítio formal, ligando ao cache BD descrito em ADR-0008.
- **Hierarquia explícita** — a cadeia de custódia de um telemóvel arrasta naturalmente os seus sub-componentes.
- **Alinhamento doutrinal** — compatível com ISO/IEC 27037 e com formatos de exchange usados em peritagem digital.

### Negativas / Trade-offs
- **Quebra retrocompatibilidade.** Qualquer fixture, teste ou import legado com `DIGITAL_DEVICE`, `DOCUMENT`, `PHOTO`, `OTHER` falha. Custo absorvido nesta wave (E1 do plano de trabalho); migration `core.0006_evidence_taxonomy_hierarchy` traduz dados existentes pelo mapa acima.
- **18 códigos podem parecer muitos.** A categorização guia a qualidade do registo — prática forense recomenda agrupar em `optgroup` no `<select>` do wizard (ADR-0004 refresh da Wave 2b).
- **Fallback `OTHER_DIGITAL` continua a ser um escape.** Comparado com `OTHER`, obriga ao menos a reconhecer a natureza digital da peça; mantém-se como válvula de segurança.

### Impactos em outros documentos
- **ADR-0002 §4** é superseded na parte do enum (modelos e relações continuam).
- **ADR-0008 (lookups externos)** passa a depender directamente dos códigos aqui definidos.
- **ADR-0004 (frontend)** — o wizard de nova evidência (`templates/evidences_new.html`) agrupa os códigos em `optgroup`s reflectindo os dois grandes grupos.
- **Documentação de peritagem** — os relatórios PDF (`core/pdf_export.py`) usam as descrições PT-PT da enum.

## Referências
- ISO/IEC 27037:2012 — *Guidelines for identification, collection, acquisition and preservation of digital evidence*.
- ENFSI 2024 — *Best Practice Manual for the Forensic Examination of Digital Technology*.
- SWGDE — *SWGDE Model Standard Operating Procedures for Computer Forensics* (2023 revision).
- Cellebrite UFED — taxonomy reference (inspiração; não adoptada 1:1).
