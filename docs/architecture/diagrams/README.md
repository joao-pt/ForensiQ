# Diagramas — ForensiQ

Fontes Mermaid (`.mmd`) e renders correspondentes (`.png` / `.svg`).
Os PNGs em `src_latex/figures/` são utilizados pelo `intercalar.tex`.

## Lista

| Ficheiro | Diagrama | Usado em |
|---|---|---|
| `c4-context.mmd` | C4 Nível 1 — Contexto (actores + sistemas externos) | `intercalar.tex` Fig. 1 |
| `c4-container.mmd` | C4 Nível 2 — Containers (Django, BD, deploy) | `intercalar.tex` Fig. 2 |
| `er-forensiq.mmd` | Modelo Entidade-Relação (User, Occurrence, Evidence, ChainOfCustody, DigitalDevice, AuditLog) | `intercalar.tex` Fig. 3 |
| `state-machine-custody.mmd` | Máquina de estados da cadeia de custódia | `intercalar.tex` Fig. 4 |
| `sequence-evidence-creation.mmd` | Sequência: criação de uma evidência por agente no terreno | `intercalar.tex` Fig. 5 |

## Renderizar

```bash
# Pré-requisito: Node.js >= 18
cd docs/architecture/diagrams

# render individual
npx -p @mermaid-js/mermaid-cli mmdc -i c4-context.mmd -o c4-context.png -b transparent -w 1600

# render todos
for f in *.mmd; do
    npx -p @mermaid-js/mermaid-cli mmdc -i "$f" -o "${f%.mmd}.png" -b transparent -w 1600
done
```

## Convenções

- **Mermaid syntax** garante reprodutibilidade e versionamento — qualquer
  pessoa pode editar `.mmd` e ver o diff (ao contrário de PNG/SVG opacos).
- **PNG + transparente** evita conflito com tema dark/light no LaTeX.
- **1600 px** de largura assegura nitidez na impressão A4.
- **Sem emojis** no Mermaid (incompatibilidade com alguns renderers).

Sempre que o modelo de dados ou a arquitectura mudem, actualizar `.mmd`,
re-renderizar o PNG e copiar para `src_latex/figures/`.
