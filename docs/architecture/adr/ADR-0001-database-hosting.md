# ADR-0001 — Base de Dados e Alojamento: PostgreSQL + Neon

**Data:** 2026-03-23
**Estado:** Aceite
**Decisores:** João Rodrigues

---

## Contexto

O ForensiQ é uma plataforma web de gestão de prova digital para first responders da PSP, construída com Django + Django REST Framework. A aplicação requer:

- **Integridade da cadeia de custódia** — toda a alteração ou eliminação de registos de prova deve ser auditável e imutável, com conformidade à norma ISO/IEC 27037.
- **Hashing criptográfico** — os ficheiros de prova são identificados por digest SHA-256, calculado e verificado ao nível da base de dados.
- **Controlo de acesso granular** — perfis distintos (administrador, investigador, first responder, perito) com permissões diferenciadas a nível de linha.
- **Credibilidade forense e legal** — a tecnologia escolhida deve ser reconhecida em contexto judicial e académico.
- **Custo controlado** — o projecto é académico, com orçamento próximo de zero durante o desenvolvimento, mas com necessidade de ambiente funcional e público para a defesa pública (julho de 2026).

A escolha da base de dados e do fornecedor de alojamento são decisões interligadas: o motor de base de dados determina as funcionalidades disponíveis, e o fornecedor determina a sustentabilidade operacional durante e após o período de desenvolvimento.

---

## Decisão

**Decidimos utilizar PostgreSQL como motor de base de dados, alojado na plataforma Neon (neon.tech).**

Durante o desenvolvimento, será utilizado o plano gratuito do Neon (*Free Tier*). Antes da defesa pública (antecipadamente ao período 6–10 de julho de 2026), o projecto será migrado para o plano *Neon Launch* (5 USD/mês), de forma a garantir disponibilidade e desempenho adequados para a demonstração.

---

## Alternativas consideradas

| Alternativa | Razão de rejeição |
|---|---|
| **Supabase** | O plano gratuito pausa a base de dados ao fim de 7 dias de inactividade. O plano pago começa nos 25 USD/mês — desproporcionado para um projecto académico. |
| **Render (PostgreSQL managed)** | O plano gratuito expira ao fim de 30 dias, obrigando a recriar a instância repetidamente durante o desenvolvimento. |
| **Aiven** | Opção tecnicamente válida, com suporte completo a PostgreSQL. Rejeitada por apresentar menor documentação de integração com Django e plano gratuito mais restritivo. Pode ser reavaliada em contexto de produção futura. |
| **ElephantSQL** | Encerrado em janeiro de 2025. Não disponível. |
| **Railway** | Não oferece tier permanente sem custos; requer cartão de crédito e cobra após período de créditos iniciais. |
| **SQLite** | Adequado apenas para desenvolvimento local. Não suporta `BEFORE UPDATE/DELETE` triggers, `pgcrypto`, nem acesso concorrente multi-utilizador. Incompatível com os requisitos forenses do projecto. |

---

## Consequências

**Positivas:**

- Os triggers `BEFORE UPDATE` e `BEFORE DELETE` do PostgreSQL permitem implementar imutabilidade da cadeia de custódia directamente na base de dados, independentemente da camada aplicacional — conformidade com ISO/IEC 27037.
- A extensão `pgcrypto` suporta o cálculo e verificação de digests SHA-256 ao nível da base de dados, reforçando a integridade da prova mesmo em caso de falha da aplicação.
- O RBAC nativo do PostgreSQL complementa o sistema de permissões do Django, permitindo defesa em profundidade.
- O modelo ACID completo garante consistência transaccional em operações críticas (registo de prova, transferência de custódia).
- O Neon oferece dados que nunca expiram no plano gratuito; o auto-suspend é transparente para o utilizador (retoma em milissegundos).
- O plano *Neon Launch* (5 USD/mês) é suficiente para a demo pública e está dentro do orçamento do projecto.
- PostgreSQL é amplamente reconhecido em contextos forenses, judiciais e académicos, reforçando a credibilidade do projecto na defesa pública.

**Negativas / trade-offs:**

- O auto-suspend do Neon no plano gratuito pode introduzir uma latência de arranque (*cold start*) na primeira ligação após período de inactividade. Este comportamento é aceitável em contexto de desenvolvimento; será eliminado com a migração para o plano *Launch* antes da defesa.
- A dependência de um fornecedor externo (Neon) introduz risco de disponibilidade. Mitigação: os backups locais e o facto de o projecto ser académico tornam este risco aceitável.
- A configuração de `pgcrypto` e dos triggers de custódia requer atenção na gestão de migrações Django (`RunSQL` em vez de migrações automáticas para esses elementos).

---

*Para criar um novo ADR: copiar `ADR-000-template.md`, incrementar o número, preencher e actualizar o estado.*
