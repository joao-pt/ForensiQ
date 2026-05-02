# Captura de fotografia — estado actual e backlog

## Implementado (Fase 2)

`src/frontend/templates/evidences_new.html` — passo 5 do wizard

- **Câmara nativa em mobile** via `<input type="file" accept="image/*" capture="environment">`
  — abre directamente a câmara traseira (mais útil para fotografar evidências
  pousadas em superfície)
- **Upload de ficheiro** alternativo para desktop ou re-uso de fotos pré-existentes
- **Pré-visualização** com `FileReader` (sem upload prematuro ao servidor)
- **Botão Remover** que reinicia o estado
- **Saltar passo** — fotografia é opcional (existem evidências sem
  representação visual útil, ex.: contas cloud, chaves de licença)
- **Tamanho máximo 10 MB** (validado no backend; 25 MB hard limit no
  Django para impedir DoS)
- **Preserva EXIF** intencional (a metadata da câmara é evidência forense)

`backend/core/views.py` — endpoint `/api/evidences/`
- Recebe multipart/form-data com `photo`
- Guarda em `MEDIA_ROOT/<volume>/evidences/YYYY/MM/`
- O hash SHA-256 da evidência **inclui os bytes da fotografia** (S6 da
  auditoria 2026-04-16) — qualquer alteração ao ficheiro detecta-se na
  verificação.

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
