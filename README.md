# ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders

> Digitalizar e padronizar a recolha, registo e cadeia de custódia de prova digital — do terreno ao laboratório.

**Estudante:** João Rodrigues · 2203474
**Orientador:** Professor Pedro Duarte Pestana
**UC:** 21184 — Projecto de Engenharia Informática · Universidade Aberta · 2025/26
**Repositório:** https://github.com/joao-pt/ForensiQ

---

## Estado actual

🔴 **Vermelho** — Fase 1 em curso. Proposta submetida, a aguardar aceitação do orientador.

---

## O que está implementado

- [x] Estrutura do repositório a partir do template do orientador
- [x] Proposta inicial redigida em LaTeX e compilada para PDF

---

## O que está pendente

- [ ] MoSCoW, C4 nível 1 e 2, modelo de dados ER — semana 3
- [ ] ADRs de arquitectura — semana 4
- [ ] Wireframes mobile-first — semana 5
- [ ] Autenticação JWT com perfis agente e perito — semana 5
- [ ] Registo de prova com fotografia e GPS — semana 6
- [ ] Cadeia de custódia com máquina de estados — semana 6
- [ ] Módulo de forense digital (ficha de dispositivo) — semana 9
- [ ] API REST com 10+ endpoints e Swagger UI — semana 9–10
- [ ] Exportação de relatório em PDF — semana 10
- [ ] Testes (pytest, Postman/Newman) — semana 11
- [ ] GitHub Actions CI — semana 11

---

## Como instalar e correr

A preencher na Fase 2.

---

## Decisões de arquitectura principais

| Decisão | Alternativa considerada | Razão da escolha |
|---------|------------------------|-----------------|
| Django + DRF | FastAPI | Estrutura convencional; autenticação built-in; ORM; mais fácil de defender |
| PostgreSQL | SQLite / MongoDB | Integridade referencial; append-only para logs de custódia |
| HTML/CSS/JS vanilla | React / Vue | Mobile-first sem overhead de framework; suficiente para MVP |
| SHA-256 nos metadados | Hash do ficheiro completo | Conforme ISO/IEC 27037; detecta alteração de qualquer campo do registo |

---

## Referências

- Casey, E. (2011). *Digital Evidence and Computer Crime* (3rd ed.). Academic Press.
- ACPO (2012). *Good Practice Guide for Digital Evidence*.
- ISO/IEC 27037:2012 — Guidelines for identification, collection, acquisition and preservation of digital evidence.
- NIST SP 800-86 (2006). *Guide to Integrating Forensic Techniques into Incident Response*.
- Pestana, P. D. (Projecto #38 — LEI 2025/26). *Plataforma Modular de Captura e Preservação de Evidência Digital para OSINT*. Universidade Aberta.

---

*Última actualização: 22 mar 2026 · Sem. 1–2*
