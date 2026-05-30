# Dados de referência — taxonomia de crimes e prioridade (ADR-0014)

Esta pasta contém **dados de referência** (lookup), não prova. Alimentam a
classificação do crime e a prioridade da `Occurrence` descritas no
[ADR-0014](../../../../docs/architecture/adr/ADR-0014-taxonomia-crimes-prioridade.md).
Não são `Evidence`/`ChainOfCustody`/`AuditLog`/`Occurrence`: são editáveis e
versionáveis no admin e **não** levam os triggers de imutabilidade.

O comando `seed_crime_taxonomy` (a criar no PASSO seguinte) semeia a base de
dados a partir destes ficheiros, de forma idempotente.

## Ficheiros

### `tabela_crimes_2024.json` — Tabela de Crimes Registados 1.7 (2024)

Nomenclatura oficial de crimes registados, em 3 níveis (N1 categorias → N2
subcategorias → N3 tipos), com os **códigos oficiais** para alinhar a
estatística do ForensiQ com a do INE/DGPJ.

- **Fonte:** Conselho Superior de Estatística (CSE/INE) / DGPJ-SIEJ, Modelo 262
  ("Mapa para Notação de Crimes") — **Tabela de Crimes Registados 1.7**, versão
  canónica de 2024.
- **Original:** <https://estatisticas.justica.gov.pt/sites/siej/pt-pt/Documents/Tabela_Crimes_Registados_2024.pdf>
  (o portal SIEJ não serve o PDF a pedidos directos; obtido via arquivo)
- **Arquivo:** <https://web.archive.org/web/20250401172838/https://estatisticas.justica.gov.pt/sites/siej/pt-pt/Documents/Tabela_Crimes_Registados_2024.pdf>
- **Dimensão:** 7 categorias N1, 50 subcategorias N2, 219 tipos N3.
- **Descritivos:** *verbatim* da fonte oficial — preservam a grafia do original
  (p.ex. `1` aparece como "Homicidio voluntário consumado", sem o acento, tal
  como na tabela).
- **Códigos N1 não contíguos:** `{1, 2, 3, 4, 5, 6, 10}`. A categoria `10`
  (crimes contra animais de companhia) foi aditada depois das seis originais.
- **Extracção e verificação:** descritivos a partir da camada de texto do PDF;
  o conjunto de códigos N3 foi cruzado contra uma extracção independente
  (`pypdf`) — **0 divergências** nos 219 códigos.

### `mapa_politica_criminal.json` — Lei 51/2023 → Tabela 1.7

Mapa curado que liga as frases da **Lei de Política Criminal n.º 51/2023, de 28
de agosto** (biénio 2023-2025) aos códigos da Tabela 1.7, por eixo:

- **`INVESTIGACAO`** (Art. 5.º) — eixo **operativo**: governa a `priority` da
  `Occurrence` (`PRIORITARIA`/`NORMAL`).
- **`PREVENCAO`** (Art. 4.º) — eixo **informativo**: valor analítico, não
  governa a prioridade operativa.

Cada associação guarda o(s) tipo(s) N3 e as alíneas-fonte. Produzido por um
workflow de mapeamento com **verificação adversarial** (duas lentes de
mapeamento por alínea → reconciliador céptico → crítico de cobertura), com
validação determinística de que **todos** os códigos existem na Tabela 1.7.
Alíneas puramente contextuais (criminalidade violenta/organizada, ambiente
escolar/saúde, vítimas vulneráveis, violência de género) **não** têm tipo
próprio na tabela e não são mapeadas — são agravantes de contexto, não tipos.

## Procedimento de actualização (re-seed)

- **Nova versão da Tabela de Crimes Registados** (o CSE publica versões novas):
  substituir `tabela_crimes_2024.json` pela nova versão e re-correr
  `seed_crime_taxonomy`. Os `CrimeTipo` retirados marcam-se `is_active=False`
  (não se apagam — preservam a leitura histórica das ocorrências já criadas).
- **Nova Lei de Política Criminal** (p.ex. biénio 2025-2027): criar uma nova
  `PoliticaCriminalPrioridade` com o novo mapa e marcá-la activa — **operação de
  dados, sem código novo** (ver ADR-0014). A Lei 2025-2027 pré-carrega-se
  inactiva, pronta a activar quando for promulgada.
