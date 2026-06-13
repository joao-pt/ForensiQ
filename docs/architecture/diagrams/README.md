# Diagramas — ForensiQ

Fontes em Mermaid (`.mmd`) e/ou Graphviz (`.dot`) e renders correspondentes (`.png`).
Os C4 e os ER divididos do **relatório final** (`relatorio_final.tex`) foram, a 13 jun 2026,
renderizados via Graphviz (`.dot`) por indisponibilidade offline do `mermaid-cli`; os `.mmd`
mantêm-se como fonte alternativa com o mesmo conteúdo.

## Lista

| Ficheiro | Diagrama | Usado em |
|---|---|---|
| `c4-context.mmd` / `.dot` | C4 Nível 1 — Contexto (6 perfis + sistemas externos) | `relatorio_final.tex` Fig. 1 (rodado) |
| `c4-container.mmd` / `.dot` | C4 Nível 2 — Containers (Django, política, BD, deploy) | `relatorio_final.tex` Fig. 2 (rodado) |
| `c4-container-hibrido.mmd` / `.png` | Variante híbrida do C4 de containers | (apoio) |
| `er-forensiq.mmd` / `.png` | Modelo Entidade-Relação integral (alta resolução) | referência integral |
| `er-nucleo.dot` / `.png` | ER — núcleo de prova e custódia (ledger) | `relatorio_final.tex` Fig. 3 |
| `er-acesso.dot` / `.png` | ER — acesso (RBAC), instituições e transporte | `relatorio_final.tex` Fig. 4 |
| `er-crimes.dot` / `.png` | ER — taxonomia de crimes e prioridade | `relatorio_final.tex` Fig. 5 |
| `state-machine-custody.mmd` | OBSOLETO (ADR-0015) — a custódia é um ledger de eventos append-only, não uma máquina de estados; o estado legal é derivado por `derive_legal_state()` (`core/policy/event_states.py`). Mantido apenas como artefacto histórico do intercalar. | (histórico) |
| `sequence-evidence-creation.mmd` | Sequência: criação de uma evidência no terreno | (apoio) |
| `hash-chain-flow.mmd` / `.png` | Encadeamento de hashes do ledger (`record_hash`) | `relatorio_final.tex` § hash-chain |
| `immutability-3-layers.mmd` / `.png` | Imutabilidade em 3 camadas (ORM / DRF / triggers PostgreSQL) | `relatorio_final.tex` § imutabilidade |
| `*.pre-refactor.png` | Versões pré-refactor dos C4 (registo histórico) | (histórico) |

## Renderizar

```bash
# Pré-requisito: Node.js >= 18
cd docs/architecture/diagrams

# render individual
npx -p @mermaid-js/mermaid-cli mmdc -i c4-context.mmd -o c4-context.png -b transparent -w 1600

# render todos (mermaid)
for f in *.mmd; do
    npx -p @mermaid-js/mermaid-cli mmdc -i "$f" -o "${f%.mmd}.png" -b transparent -w 1600
done

# Graphviz (fontes .dot — C4 e ER do relatório final)
for f in *.dot; do dot -Tpng -Gdpi=150 "$f" -o "${f%.dot}.png"; done
```

## Convenções

- **Mermaid syntax** garante reprodutibilidade e versionamento — qualquer
  pessoa pode editar `.mmd` e ver o diff (ao contrário de PNG/SVG opacos).
- **PNG + transparente** evita conflito com tema dark/light no LaTeX.
- **1600 px** de largura assegura nitidez na impressão A4.
- **Sem emojis** no Mermaid (incompatibilidade com alguns renderers).

Sempre que o modelo de dados ou a arquitectura mudem, actualizar `.mmd`,
re-renderizar o PNG e copiar para `src_latex/figures/`.
