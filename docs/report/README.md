# Relatórios

Esta pasta contém as versões PDF dos relatórios formais.

## Ficheiros esperados

| Ficheiro | Entrega | Data |
|---------|---------|------|
| `proposta.pdf` | Proposta inicial | (entregue) |
| `intercalar.pdf` | Relatório intercalar | 6 de maio |
| `final.pdf` | Relatório final (ainda por produzir) | 24 de junho |

## Notas

- Os relatórios são submetidos em PDF nesta pasta **e** pelo canal formal da UC.
- As fontes LaTeX estão em `src_latex/` e não são versionadas (ver `.gitignore`); apenas os PDFs compilados são guardados aqui.
- Compilam-se com `latexmk` — por exemplo `latexmk -pdf -cd src_latex/intercalar.tex` (intercalar) e `latexmk -pdf -output-directory=../docs/report proposta.tex` (proposta).
- O relatório final é o artefacto principal da defesa pública — o júri externo avalia o relatório, não apenas o código.
