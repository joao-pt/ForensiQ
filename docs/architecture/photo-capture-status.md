# Captura de fotografia — estado actual e backlog

## Implementado (Fase 2)

`src/frontend/templates/evidences_new.html` — campo Fotografia no formulário
único de registo (server-rendered, HTMX, POST `/evidences/new/`)

- **Câmara nativa em mobile** via `<input type="file" accept="image/*" capture="environment">`
  — abre directamente a câmara traseira (mais útil para fotografar evidências
  pousadas em superfície)
- **Upload de ficheiro** alternativo para desktop ou re-uso de fotos pré-existentes
- **Fotografia opcional** — o input não tem `required` (existem evidências sem
  representação visual útil, ex.: contas cloud, chaves de licença)
- O wizard multi-passo, a pré-visualização `FileReader` e os botões
  Remover/Saltar foram removidos na reconstrução do frontend (branch
  `refactor/frontend-rebuild`)
- **Tamanho máximo 25 MB**, validado no backend em `validate_image_max_size`
  (`core/models.py:209`), que também confirma o formato real via `Pillow.verify()`
  (whitelist JPEG/PNG/WEBP, anti-polyglot)
- **Remove EXIF/IPTC/XMP** no `Evidence.save()` via helper `_strip_exif()`
  em `core/models.py` (auditoria 2026-05-18 §2 S9). Postura revista em
  2026-05-27: o trade-off "metadata = prova" foi substituído por
  "metadata = PII a proteger" — EXIF de telemóveis inclui GPS exacto
  da captura, modelo de câmara e timestamps originais, que podem
  identificar o portador do equipamento ou revelar dados sensíveis da
  cena a quem receba o PDF/ficheiro. A informação forense relevante
  (GPS, timestamp da apreensão, agente) é registada **independentemente**
  no modelo `Evidence` e no `ChainOfCustody`. Formato e dados de pixel
  preservados (JPEG/PNG/WEBP).

`core/frontend_views.py` — vista `evidences_new_view` (POST `/evidences/new/`)
- Recebe multipart/form-data com `photo` (`request.FILES.get("photo")`,
  `core/frontend_views.py:814-815`), reusa o `EvidenceSerializer` e guarda via
  `Evidence.photo` (`upload_to=evidence_photo_path`, `core/models.py:934`). A API
  DRF `/api/evidences/` mantém-se para consulta, PDF e lookups.
- Guarda em `MEDIA_ROOT/evidencias/<codigo_da_ocorrencia>/<uuid8>_<ficheiro>`
  (`core/models.py:934` `evidence_photo_path`). Sem segmento `<volume>`, sem
  `YYYY/MM`; a pasta chama-se `evidencias` (com a).
- O hash SHA-256 da evidência **inclui os bytes da fotografia** (S6 da
  auditoria 2026-04-16) — qualquer alteração ao ficheiro detecta-se na
  verificação. Os bytes hasheados são os bytes **pós-strip** (`Evidence.save`
  faz `_strip_exif()` antes do `compute_integrity_hash()`), tornando o
  `integrity_hash` **invariante a EXIF** — defesa em profundidade contra
  manipulações externas que removam metadados.

## Por implementar (Fase 3 ou pós-projecto)

### Réguas / grids de orientação

Overlay sobre o `<video>`/preview ajuda o agente a:
- alinhar o item com a horizontal
- enquadrar segundo a regra dos terços
- preservar margens (cantos do item visíveis)
- incluir uma referência de escala (régua virtual em cm/mm)

Implementação proposta (modular, reutilizável):
- Componente `<photo-capture data-guide="smartphone|laptop|storage|generic">`
- Cada guide é um SVG overlay parametrizado (proporções tipo do item)
- Switch dinâmico baseado no `Evidence.type` já preenchido no wizard
- Configurável por força policial (override por organização — não é
  preciso fazer 18 guides; um por categoria já cobre 80% dos casos)

### Captura múltipla

Algumas evidências precisam de **várias fotografias**:
- Smartphone: frente, verso, IMEI sticker
- Laptop: ângulo geral, etiquetas, portas
- Documentos: cada página

Hoje só uma foto por `Evidence` (apesar de o wizard permitir criar
sub-componentes, o que parcialmente resolve este caso). Modelo sugerido:
modelo `EvidencePhoto(evidence, file, order, kind)`.

### Validação de qualidade

- Detecção de blur (variance of Laplacian) antes do upload
- Detecção de subexposição/sobre-exposição
- Aviso se foto for muito pequena (< 1024 px lado mais curto)

Tudo client-side, sem dependências de IA externa.

### OCR opcional para etiquetas

`Evidence.serial_number`, `IMEI`, número de chassis (VIN) podem
ser extraídos da fotografia com Tesseract.js — não substitui o
campo manual mas oferece-o como sugestão. **Privacy first**: tudo
on-device (Tesseract WASM), nada enviado para serviços externos.

## Decisão actual

Mantém-se o componente simples até **6 mai 2026** (Fase 2). As
melhorias acima são listadas no backlog do Relatório Intercalar e
priorizadas para a Fase 3 (24 jun 2026) ou para a defesa pública.

A escolha de **não imprimir etiquetas físicas** é deliberada: as
forças policiais portuguesas raramente têm impressoras térmicas em
campo, e a fotografia + hash SHA-256 + metadata GPS substituem o
papel sem perder rastreabilidade. Esta justificação deve constar
no relatório.
