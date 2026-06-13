# Levantamento de Requisitos (MoSCoW)

**ForensiQ — Plataforma Modular de Gestão de Prova Digital para *First Responders***

| Campo | Valor |
|---|---|
| Versão | 1.0 · 22 mar 2026 (Markdown) — fonte autoritativa neste repositório; fonte LaTeX arquivada fora do repositório |
| Referência | [productplan.com/glossary/moscow-prioritization](https://www.productplan.com/glossary/moscow-prioritization/) |

---

## 1. Método MoSCoW

| Categoria | Significado |
|---|---|
| **Must have** | Obrigatório. Sem isto o projecto não é entregável. |
| **Should have** | Importante mas não crítico. Incluir se o tempo permitir. |
| **Could have** | Desejável. Só se tudo o resto estiver concluído. |
| **Won't have** | Explicitamente fora do âmbito desta versão. |

---

## 2. Requisitos funcionais

### Must have

- **RF01** — Autenticação JWT com perfis agente e perito forense digital
- **RF02** — Criação e gestão de ocorrências com georreferenciação automática
- **RF03** — Registo de prova com fotografia, metadados GPS, *timestamp* e *hash* SHA-256
- **RF04** — Módulo de forense digital: ficha completa de dispositivo digital (tipo, marca, modelo, estado, número de série)
- **RF05** — Cadeia de custódia com máquina de estados e *log append-only* imutável
- **RF06** — Exportação de relatório de ocorrência em PDF
- **RF07** — API REST com mínimo 10 *endpoints* documentados via Swagger UI

### Should have

- **RF08** — *Dashboard* de estado das provas por ocorrência
- **RF09** — Pesquisa e filtragem de ocorrências e provas

### Could have

- **RF10** — Perfis adicionais: coordenador e magistrado
- **RF11** — Verificação de IMEI via API externa
- **RF12** — *Dashboard* analítico por agente e por processo
- **RF13** — Criação e associação de despachos judiciais às provas

### Won't have (nesta versão)

- **RF14** — Integração com sistemas internos da PSP (requer autorizações não disponíveis)
- **RF15** — Dados reais de processos judiciais (questões legais e de confidencialidade)
- **RF16** — Módulos de Química, Biologia ou Física Forense (estrutura documentada, não implementada)
- **RF17** — Aplicação móvel nativa iOS/Android (interface web *mobile-first* é suficiente para MVP)

---

## 3. Requisitos não-funcionais

### Must have

- **RNF01 — Segurança:** HTTPS obrigatório; autenticação JWT para acesso a todos os *endpoints* protegidos; *passwords* com *hash*.
- **RNF02 — Usabilidade:** Interface *mobile-first* utilizável num *smartphone* no terreno, com uma mão, sem formação técnica prévia.
- **RNF03 — Integridade:** *Hash* SHA-256 dos metadados de cada registo de prova no momento de criação; *log* de custódia *append-only*.

### Should have

- **RNF04 — Performance:** Tempo de resposta inferior a 2 segundos para operações principais.
- **RNF05 — Manutenibilidade:** Código com testes automatizados nos módulos críticos (autenticação, custódia).

### Could have

- **RNF06 — Disponibilidade:** *Deploy* acessível remotamente para demonstração.

---

## 4. Estado de cumprimento (instantâneo · 3 mai 2026)

Verificação detalhada por requisito está no Capítulo 3 do [Relatório Intercalar](../report/intercalar.pdf) e na matriz [`iso27037-traceability.pdf`](./iso27037-traceability.pdf).

| Requisito | Estado | Evidência |
|---|---|---|
| RF01 | ✅ Implementado | `core/auth.py`, JWT cookies HttpOnly + CSRF (ADR-0009) |
| RF02 | ✅ Implementado | `Occurrence` modelo + frontend `occurrences_new` com *reverse geocoding* |
| RF03 | ✅ Implementado | `Evidence.metadata_hash` em `core/models.py` |
| RF04 | ✅ Implementado | Taxonomia de 18 tipos digitais (ADR-0010) + `DigitalDevice` legacy |
| RF05 | ✅ Implementado | `ChainOfCustody` *append-only* + *trigger* PostgreSQL (ADR-0006) |
| RF06 | ✅ Implementado | `core/pdf_export.py` + ReportLab |
| RF07 | ✅ Implementado | 12+ rotas em `/api/docs/` (Swagger UI) |
| RF08 | ✅ Implementado | `/dashboard/` com *stats* por estado e tipo |
| RF09 | ✅ Implementado | Pesquisa client-side + filtros multi-select (PR #1+#2) |
| RF10–13 | ⏳ Para fase final | — |
| RNF01 | ✅ A+ no Qualys SSL Labs · HSTS *preload* submetido |
| RNF02 | ✅ WCAG 2.1 AA · *touch targets* 48px · auditoria de design 18 abr |
| RNF03 | ✅ *Trigger* PG bloqueia UPDATE/DELETE · *hash* encadeado |
| RNF04 | ✅ < 2s na demo de produção (`forensiq.pt`) |
| RNF05 | ✅ 213 testes a passar · *coverage* 67,4% |
| RNF06 | ✅ `forensiq.pt` em produção (Fly.io · *region* fra) |

---

## 4.1 Estado de cumprimento actualizado (instantâneo · 13 jun 2026)

> **Nota de actualização (Sem. 14).** A tabela da secção 4 é o instantâneo de 3 mai (data do
> intercalar) e preserva-se inalterada como registo histórico. O instantâneo abaixo reflecte o
> estado **real do código a 13 jun 2026**, após o *refactor* de fundo da Fase 2/3 (ADR-0015 a
> ADR-0019) e os lotes de Junho. Ver `reconciliacao-2026-06-13.md` para o método e as métricas.

| Requisito | Estado (13 jun) | Evidência / nota de actualização |
|---|---|---|
| RF01 | ✅ | JWT em *cookies* HttpOnly + CSRF (`core/auth.py`, ADR-0009) |
| RF02 | ✅ | `Occurrence` (imutável) + *reverse geocoding* (proxy Nominatim) + taxonomia de crimes 3 níveis (ADR-0014) |
| RF03 | ✅ | `Evidence.integrity_hash` SHA-256 (inclui *bytes* da foto, EXIF removido); `core/models.py` |
| RF04 | ✅ (modelo alterado) | `DigitalDevice` **removido** na Sem. 13 (migration 0020) e subsumido por `Evidence` + `type_specific_data`: 18 tipos digitais + catálogo editável `EvidenceTypeRef` (ADR-0010/0018). IMEI/VIN/marca/modelo vivem na evidência digital-first |
| RF05 | ✅ (modelo evoluído) | `ChainOfCustody` deixou de ser máquina de estados linear e passou a **ledger de eventos** *append-only* com estado legal derivado (ADR-0015); *hash* SHA-256 encadeado (hv4) + *triggers* PostgreSQL |
| RF06 | ✅ | `core/pdf_export.py` (ReportLab); PDF re-classificado como guia de transporte + QR e verificação pública (ADR-0012) |
| RF07 | ✅ | 4 *ViewSets* REST (CRUD/append-only) + 11 *endpoints* funcionais (`core/urls.py`); OpenAPI em `/api/docs/` (drf-spectacular) |
| RF08 | ✅ | `/dashboard/` com métricas de fluxo (estado, *throughput*, SLA, *dwell*) + mapa do território |
| RF09 | ✅ | Modo tabela densa (gerador único `core.grid`) com filtros, *multi-select* e *drill-down* `?attn=` |
| **RF10** | ✅ **implementado** (excede a proposta) | 6 perfis incluindo coordenador (`CHEFE_SERVICO`) e magistrado (`CASE_AUTHORITY`) + instituições e credencial nacional (ADR-0017). Originalmente *Could have* |
| **RF11** | ✅ **implementado** | Verificação de IMEI via `imeidb.xyz` com cache e *throttle* (ADR-0008). Originalmente *Could have* |
| RF12 | ✅ parcial | Analytics de fluxo/SLA por estado e prazo; analítica por agente é parcial |
| **RF13** | ✅ **implementado** | Despachos judiciais como **actos certificados** (`VALIDACAO_APREENSAO`, `DESPACHO_PERICIA`) com autoridade estruturada e prazo (ADR-0014/0015/0017). Originalmente *Could have* |
| RNF01 | ✅ | A+ Qualys SSL Labs · A+ Mozilla Observatory · HSTS *preload* · CSP nível 3 com *nonce* |
| RNF02 | ✅ | WCAG 2.1 AA (axe) · *touch targets* 48px · *mobile-first* |
| RNF03 | ✅ | *Append-only* (Python + *trigger* PG) · *hash* encadeado · consola de auditoria de integridade |
| RNF04 | ✅ | < 2s nas operações principais em produção (`forensiq.pt`) |
| RNF05 | ✅ | **≈967 métodos de teste** na suite `core/` + **36 testes E2E** (Playwright). *Coverage* com *gate* CI a 80%. **Confirmar com `pytest` local** antes da entrega final |
| RNF06 | ✅ | `forensiq.pt` em produção (Fly.io · *region* fra) + plano de *disaster recovery* documentado |

**Âmbito que excedeu a proposta (extensões, Guia §6).** Para além de RF10/RF11/RF13: ledger de
eventos de custódia, custódia v2 em dois tempos (`Portador`/`ProvaEmTransito`), identificação
hierárquica até 3 níveis, `AuditLog` imutável com retenção RGPD, e acesso *need-to-know* por
instituição. Estas extensões estão fundamentadas nos ADRs 0014–0019 e no `changelog.md`.

---

## 5. Histórico de alterações

| Versão | Data | Alteração | Razão |
|---|---|---|---|
| 1.0 | 22 mar 2026 | Versão inicial | Proposta de projecto |
| 1.0-md | 3 mai 2026 | *Mirror* em Markdown + tabela de cumprimento | Conformidade com guia §5 do Prof. Pestana |
| 1.1-md | 13 jun 2026 | Snapshot de cumprimento actualizado (§4.1) + nota de âmbito | Reconciliação com o código pós-refactor Fase 2/3 (Sem. 14) |
