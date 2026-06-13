# Glossário e guia de estilo terminológico — ForensiQ

> **Fonte única de terminologia do projecto (13 jun 2026).** Este documento define,
> para cada termo técnico, jurídico ou estrangeiro, a forma a usar de modo consistente
> em **todos os documentos** (relatório final, README, ADRs, changelog, scope) e uma
> explicação em português claro — pensada como **material de preparação para a defesa**.

## Princípio orientador

O critério não é "está em inglês ou em português?", mas **"consigo explicar este termo
numa frase, em voz alta, perante o júri?"**. Um termo que o autor não saiba explicar é
um termo a aprender ou a substituir. A **incoerência** (o mesmo conceito escrito de
formas diferentes) é o que mais denuncia fragilidade — por isso esta tabela manda.

## Política (híbrida)

1. **Manter em inglês, em *itálico*, com glosa na 1.ª ocorrência** — termos universais de
   informática cuja tradução soaria amadora ou ambígua.
2. **Traduzir (ou glosar com o termo PT à frente)** — quando existe um termo português
   limpo e mais claro.
3. **Sempre em português** — termos de domínio e jurídicos.

Regra de glosa: na **primeira** ocorrência de um termo do nível 1, escrever a forma
longa com a explicação entre parêntesis; depois, usar a forma curta. Exemplo:
*"um* ledger *(registo cronológico só-de-acréscimo, à semelhança de um livro-razão)"* →
a seguir, apenas *ledger*.

---

## Nível 1 — Manter em inglês (itálico + glosa na 1.ª ocorrência)

| Termo | Forma a usar | Explicação em PT (defesa) |
|---|---|---|
| **hash** | *hash* | Resumo criptográfico de tamanho fixo de um conjunto de dados; aqui SHA-256. Qualquer alteração ao input muda o *hash* — é o que torna a adulteração detectável. |
| **ledger** | *ledger* (de eventos) | Registo cronológico **só-de-acréscimo** onde cada entrada referencia a anterior, à semelhança de um livro-razão contabilístico. No ForensiQ, o histórico de custódia de cada item. **Não** é sinónimo de "cadeia de custódia" (conceito jurídico): é o mecanismo que a implementa. |
| **append-only** | *append-only* (só-de-acréscimo) | Estrutura onde só se inserem registos novos — nunca se altera (`UPDATE`) nem se apaga (`DELETE`). Garante imutabilidade. |
| **hash-chain / encadeado** | *hash* encadeado | Cada evento inclui no seu *hash* o *hash* do evento anterior; alterar um evento quebra todos os seguintes (inspirado em *blockchain*, sem prova-de-trabalho). |
| **trigger** | *trigger* (gatilho) | Função na base de dados que dispara automaticamente antes de `UPDATE`/`DELETE`; última camada de imutabilidade, atua mesmo perante SQL fora da aplicação. |
| **backend / frontend** | *backend* / *frontend* | Lado do servidor (Django/API) vs. lado do cliente (o que corre no *browser*). |
| **deploy / deployment** | *deploy* | Colocar a aplicação em funcionamento num servidor (aqui, Fly.io). |
| **dashboard** | *dashboard* (painel) | Ecrã-resumo com métricas e acções rápidas. Usar "painel" no corpo, *dashboard* só quando se refere ao componente. |
| **throttle / throttling** | limitação de débito (*throttle*) | Limite ao número de pedidos por intervalo (ex.: 5/min no login) para travar abuso/força bruta. |
| **lookup** | consulta/enriquecimento (*lookup*) | Consulta a um serviço externo para enriquecer um registo (ex.: metadados a partir do IMEI). |
| **hardening** | endurecimento (*hardening*) | Conjunto de medidas que reduzem a superfície de ataque (cabeçalhos, CSP, *throttle*...). |
| **throughput** | débito (*throughput*) | Volume de itens processados por unidade de tempo. |
| **dwell** | tempo de permanência (*dwell*) | Quanto tempo um item fica parado num estado/custódio. |
| **seed** | *seed* (dados de demonstração) | Comando que popula a base de dados com dados sintéticos para demonstração. |
| **timestamp** | *timestamp* (carimbo temporal) | Marca de data/hora; no ForensiQ, gerada pelo servidor no momento do evento. |

## Nível 2 — Traduzir (termo PT preferido)

| Inglês | Usar em PT | Nota |
|---|---|---|
| wizard | **assistente** / formulário guiado | Não usar "wizard" no relatório. |
| drawer | **painel lateral** | O painel lateral foi **removido** na Sem. 14 (as linhas da grelha navegam direto) — não descrever como funcionalidade atual. |
| state machine | **máquina de estados** | Modelo **anterior** ao *ledger*; referir só em contexto histórico (foi substituído — ADR-0015). |
| grid | **grelha** | "modo tabela densa" / "gerador único de grelha". |
| badge | **etiqueta** / *badge* | Aceitável *badge* em itálico quando se refere ao elemento de UI. |
| feed | **feed** / fluxo | "feed de auditoria"; aceitável em itálico. |

## Nível 3 — Sempre em português (domínio e jurídico)

| Termo | Significado curto (defesa) |
|---|---|
| **cadeia de custódia** | Registo de quem manuseou a prova, quando e em que condições — garante a sua admissibilidade em tribunal. |
| **apreensão** | Acto de recolha da prova (CPP art. 178.º); génese do *ledger*. |
| **validação da apreensão** | Confirmação pela autoridade judiciária (CPP art. 178.º/5-6), em prazo (72h por defeito). |
| **despacho de perícia** | Ordem da autoridade para a perícia (CPP art. 154.º); exige apreensão validada. |
| **perícia** | Exame técnico-forense da prova (início/conclusão). |
| **restituição** | Devolução da prova ao titular (CPP art. 186.º); evento terminal. |
| **acto certificado** | Acto jurídico (validação, despacho) cuja autoridade fica selada no *hash* (hv4). |
| **estado legal derivado** | Estado da prova **calculado** da sequência de eventos, não guardado como campo. |
| **génese** | Primeiro evento do *ledger* (apreensão de objeto/dados ou derivação de sub-componente). |
| **need-to-know** | Princípio de acesso: cada utilizador vê apenas o que a sua função/instituição justifica. |

---

## Acrónimos
Mantêm-se os definidos na "Lista de Acrónimos" do relatório final (ADR, API, CPP, DRF,
JWT, MP, NUIPC, OPC, RBAC, RGPD, SHA, etc.). Cada acrónimo é expandido na 1.ª ocorrência.

## Notas de aplicação
- O **relatório final** e o **README** seguem este guia integralmente.
- Os **ADRs** e o **changelog** são registos históricos: mantêm a terminologia da data em
  que foram escritos; não são reescritos retroactivamente, mas qualquer termo novo segue
  este guia.
- A **proposta** e o **relatório intercalar** são entregas aprovadas e **não** se alteram.
