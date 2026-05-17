# Política de Segurança

O ForensiQ trata dados sensíveis de investigações criminais (prova digital, GPS, NUIPCs, IMEIs). Levamos a sério qualquer vulnerabilidade ou falha de configuração.

## Versões suportadas

Apenas o ramo `main` (deployado em <https://forensiq.pt>) recebe correcções de segurança. Não há releases formais durante a fase académica do projecto (UC 21184 da UAb, 2025/26).

| Versão | Suporte |
|---|---|
| `main` (HEAD) | ✅ |
| Outras branches | ❌ |

## Como reportar uma vulnerabilidade

**Não abras issue público.** Issues no GitHub são indexados e podem expor a vulnerabilidade antes da correcção estar disponível.

Em vez disso:

1. **Preferencial — GitHub Security Advisory privado:** abre um advisory privado em <https://github.com/joao-pt/ForensiQ/security/advisories/new>. O GitHub notifica o maintainer e mantém o conteúdo privado até divulgação coordenada.
2. **Alternativa — Email:** <rodriguesrede@gmail.com>. Usa o assunto `[ForensiQ Security] <título curto>`.

### O que incluir no relatório

- Versão/commit hash afectado (ex.: `git rev-parse HEAD`)
- Descrição do impacto (confidencialidade / integridade / disponibilidade)
- Passos de reprodução mínimos
- Prova de conceito (idealmente sem expor dados pessoais reais)
- Recomendação de mitigação se já tiveres ideia

## Resposta esperada

- **Acknowledge:** dentro de 72 horas úteis
- **Triagem inicial:** 7 dias
- **Patch / mitigação:** depende da severidade — críticas em &lt;30 dias, altas em &lt;60 dias, médias/baixas planeadas para o próximo ciclo
- **Divulgação coordenada:** discutida caso a caso; por defeito divulgação 30 dias após patch ou imediatamente se já houver exploração pública

## Âmbito

**Dentro do âmbito:**

- O código do repositório `joao-pt/ForensiQ`
- A instância de demonstração <https://forensiq.pt> (apenas testes não-destrutivos, sem DoS, sem fuzz pesado, sem dados reais)
- Configuração de deployment em Fly.io e Neon.tech

**Fora do âmbito:**

- Dependências terceiras (reportar directamente ao upstream)
- Falhas que requeiram acesso físico ao dispositivo do utilizador
- Engenharia social
- Testes que afectem a disponibilidade do serviço

## Hall of Fame

Pesquisadores que reportem vulnerabilidades válidas serão creditados aqui (com autorização). Sendo um projecto académico sem bug bounty, o reconhecimento é informal mas público.

_(Vazio.)_

## Auditorias internas

O código foi auditado internamente em 11 e 16 de Abril de 2026 (`docs/code-review-2026-04-11.md`, `docs/AUDIT_2026-04-16.md`). Os achados estão tapados ou enquadrados como trabalho futuro com justificação.
