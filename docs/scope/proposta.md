# Proposta de Projecto

**ForensiQ — Plataforma Modular de Gestão de Prova Digital para *First Responders***

| Campo | Valor |
|---|---|
| Estudante | João M. M. Rodrigues · 2203474 |
| Orientador | Prof. Pedro Duarte Pestana |
| UC | 21184 — Projecto de Engenharia Informática · UAb · 2025/26 |
| Data | 22 de março de 2026 |
| Versão | 1.0 (Markdown) — fonte autoritativa: [`proposta.tex`](./proposta.tex) → [PDF](../report/proposta.pdf) |

---

## 1. Sinopse

Os agentes que chegam primeiro a uma cena de crime — os *first responders* — recorrem actualmente a métodos manuais (papel, fotografias avulsas, anotações) para registar e preservar a prova digital. Esta ausência de padronização traduz-se em vulnerabilidades processuais reais: cadeia de custódia inconsistente, prova sem localização verificável e procedimentos que variam de agente para agente. O problema é identificado da experiência directa do estudante como perito digital forense na PSP.

O ForensiQ é uma aplicação web *mobile-first* que digitaliza e padroniza este processo, do momento da apreensão no terreno até à chegada ao laboratório e remessa das conclusões da perícia. Distingue-se dos sistemas existentes (SAFE, Axon Evidence) por ser desenhado para o agente sem formação técnica avançada, por seguir os procedimentos da PSP, e por garantir integridade dos registos via *hash* SHA-256 conforme a ISO/IEC 27037. Diferencia-se do Projecto #38 (OSINT) por não adquirir prova — apenas a gerir e controlar após apreensão.

O resultado esperado é um protótipo funcional demonstrável num *smartphone* no terreno, com API REST documentada, módulo de forense digital completo e cadeia de custódia com *log* imutável verificável. O sucesso é medido pelos critérios de aceitação definidos para cada funcionalidade do MVP.

---

## 2. MVP — definição e critérios de aceitação

### F1 — Autenticação com perfis (agente e perito)

> Dado *email* e *password* válidos de agente, o sistema autentica e devolve *token* JWT em menos de 2 segundos; dado *email* inválido, devolve erro 401 sem expor informação interna. Perfis agente e perito têm permissões distintas verificáveis.

### F2 — Registo de prova com fotografia e metadados GPS

> Um agente autenticado cria um registo de prova com fotografia, tipo, descrição e localização GPS capturada automaticamente pelo *browser*. O registo recebe identificador único, *timestamp* do servidor e *hash* SHA-256 dos metadados. Verificável em menos de 30 segundos num telemóvel.

### F3 — Cadeia de custódia com máquina de estados e *log* imutável

> A prova percorre estados em ordem fixa sem possibilidade de retrocesso: APREENDIDA → EM_TRANSPORTE → RECEBIDA_LABORATORIO → EM_PERICIA → CONCLUIDA → DEVOLVIDA / DESTRUIDA. Cada transição regista agente responsável, *timestamp* e *hash* do registo nesse momento. Nenhuma transição pode ser saltada. O *log* é *append-only* — sem `UPDATE` nem `DELETE` na tabela de custódia. Qualquer tentativa de alteração directa na base de dados é detectável via *hash*.

### F4 — Módulo de forense digital (ficha de dispositivo)

> Perito preenche ficha completa de dispositivo digital (tipo, marca, modelo, estado, número de série) associada a uma prova existente.

### F5 — API REST documentada

> Mínimo 10 *endpoints* funcionais documentados e testáveis via Swagger UI (`drf-spectacular`).

### F6 — Exportação de relatório de ocorrência em PDF

> Relatório gerado automaticamente com todos os registos de prova e histórico de custódia da ocorrência.

---

## 3. Stack tecnológica

| Componente | Tecnologia | Justificação |
|---|---|---|
| *Backend* | Django + Django REST Framework | Estrutura convencional e previsível; autenticação *built-in*; ORM transparente |
| *Frontend* | HTML + CSS + JavaScript *vanilla* | *Mobile-first* sem *overhead* de *framework*; suficiente para MVP |
| Base de dados | PostgreSQL | Integridade referencial crítica para cadeia de custódia; *triggers* para *append-only* |
| Autenticação | JWT + RBAC | Dois perfis: agente (*first responder*) e perito forense digital |
| API docs | drf-spectacular → Swagger UI | Documentação automática da API REST |
| Geolocalização | *Browser* Geolocation API + Leaflet.js | Sem dependência de API externa paga; funciona no telemóvel |
| Integridade | SHA-256 (`hashlib`) | *Hash* dos metadados do registo no momento de criação |
| CI/CD | GitHub Actions | *Pipeline* de testes automáticos a cada *push* |

---

## 4. Esboço de arquitectura — C4 Nível 1

**Sistema:** ForensiQ

**Utilizadores:**

- **Agente** (*first responder*) — regista provas no terreno, inicia cadeia de custódia, captura fotografias e localização GPS.
- **Perito forense digital** — recebe provas no laboratório, preenche fichas de dispositivo, avança estados da custódia, exporta relatórios.

**Sistemas externos:**

- *Browser* Geolocation API — fornece coordenadas GPS do dispositivo do agente no terreno.
- Servidor de *email* (futuro) — notificações de transição de custódia.

Diagramas em [`docs/architecture/c4-context.png`](../architecture/c4-context.png) e [`docs/architecture/c4-containers.png`](../architecture/c4-containers.png).

---

## 5. Calendário individual detalhado

| Semanas | Datas | Conteúdo planeado | Marco |
|---|---|---|---|
| Sem. 1–2 | 17–28 mar | Proposta completa. Configuração do repositório. Sinopse, MVP e calendário ao orientador. | **Proposta (25 mar)** |
| Sem. 3–4 | 31 mar–11 abr | MoSCoW final, diagramas C4, modelo de dados ER, ADRs obrigatórios. | |
| Sem. 5–6 | 14–25 abr | Wireframes *mobile-first*. Início implementação: modelos Django, autenticação JWT, registo de prova. | |
| Sem. 7 | 28 abr–2 mai | Demo interna ao orientador. Cadeia de custódia funcional. | **Demo interna** |
| Sem. 8 | 5–6 mai | Relatório intercalar. | **Intercalar (6 mai)** |
| Sem. 9–10 | 7–16 mai | Módulo forense digital. API REST completa (10+ *endpoints*). Swagger UI. | |
| Sem. 11–12 | 19–30 mai | Exportação PDF. Testes integração. GitHub Actions CI. | |
| Sem. 13 | 2–6 jun | Polimento UI. Revisão relatório final (Cap. 4 e 5). | |
| Sem. 14 | 9–13 jun | Revisão final do relatório. Correcções. | |
| Sem. 15 | 16–20 jun | Preparação da defesa oral. Ensaio com simulação de perguntas. | **Prep. defesa** |
| Sem. 16 | 24 jun | Submissão do relatório final. | **Final (24 jun)** |
