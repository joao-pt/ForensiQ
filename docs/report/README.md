# Relatórios

Esta pasta contém as versões PDF dos relatórios formais.

## Ficheiros esperados

| Ficheiro | Entrega | Data |
|---------|---------|------|
| `proposta.pdf` | Proposta inicial | (entregue, aprovada) |
| `intercalar.pdf` | Relatório intercalar | 6 de maio (entregue, aprovado) |
| `final.pdf` | Relatório final (34 págs.) | 24 de junho |

## Notas

- Os relatórios são submetidos em PDF nesta pasta **e** pelo canal formal da UC.
- A **proposta** e o **relatório intercalar** são entregas aprovadas e **não são alteradas** (nem as suas referências). O relatório final é um documento novo que **revê** os Cap. 1–2, **completa** o Cap. 3 e **acrescenta** os Cap. 4–5, reflectindo o sistema tal como foi construído.
- As fontes LaTeX estão arquivadas em `_arquivo_latex/src_latex/` (fora do versionamento do código). O relatório final é `relatorio_final.tex` + `capitulos/*-final.tex` + `capitulos/cap4-testes.tex` + `capitulos/cap5-conclusoes.tex`.
- Compila-se com `latexmk -pdf relatorio_final.tex` (a partir de `_arquivo_latex/src_latex/`). Os diagramas C4 do relatório final foram regenerados a 13 jun (ver `docs/architecture/diagrams/c4-*.dot`/`.mmd`).
- O relatório final é o artefacto principal da defesa pública — o júri externo avalia o relatório, não apenas o código.
