# Gestão de Riscos

**ForensiQ — Plataforma Modular de Gestão de Prova Digital para *First Responders***

| Campo | Valor |
|---|---|
| Versão | 1.1 · 3 mai 2026 (Markdown) |
| Versões anteriores | [`risks.tex`](./risks.tex) (1.0 · 22 mar) · [`risks-controls.pdf`](./risks-controls.pdf) (1.0 · 12 abr — controlos técnicos) |

---

## 1. Tabela de riscos do projecto

| ID | Risco | Probabilidade | Impacto | Mitigação | Estado actual |
|---|---|---|---|---|---|
| **R01** | Tempo insuficiente para MVP completo (PSP + estudos) | Alta | Alto | MVP-first rigoroso; prioridade 1-2-3 definida; funcionalidades avançadas só se núcleo sólido | 🟢 MVP completo em produção |
| **R02** | Dificuldade em aprender Django/DRF no tempo disponível | Média | Alto | Código com revisão obrigatória; começar pelo modelo de dados (ponto forte) | 🟢 213 testes a passar |
| **R03** | Orientador rejeitar proposta | Baixa | Crítico | Enviar elementos base com margem antes do prazo; incorporar *feedback* antes de 25 mar | 🟢 Proposta aceite |
| **R04** | Geolocalização não funcionar em contexto de demonstração | Média | Baixo | *Fallback*: coordenadas manuais; testar com telemóvel real antes da demo | 🟢 GPS + manual disponíveis |
| **R05** | *Hash* de integridade difícil de demonstrar em defesa | Baixa | Baixo | Demonstração directa na BD: mostrar que alterar um campo invalida o *hash* | 🟢 *Trigger* PG + UI inspector |
| **R06** | Demo interna síncrona não realizada na janela prevista (Sem 7) | Média | Médio | Demo assíncrona via produção `forensiq.pt`; documentar no Cap 3.4 do intercalar; oferecer demo síncrona em Sem 9-10 | 🟡 Aguarda confirmação do orientador |
| **R07** | Concentração de *commits* na recta final percepcionada como fragilidade | Média | Médio | Congelar repositório nos últimos 7 dias antes da entrega final; só *fixes*. Histórico já mostra cadência regular Sem 1-7 | 🟢 113 *commits* em 7 semanas, distribuídos |
| **R08** | Dependência externa (`imeidb.xyz`, *vindecoder*) ficar *offline* na demo | Baixa | Baixo | Cache em DB (ADR-0008); validador local Luhn cobre IMEI sem rede | 🟢 Cache + *fallback* local |
| **R09** | Volume de *uploads* (fotos) esgotar disco do Fly.io (1 GB) | Baixa | Médio | Volume `forensiq_media` monitorizado; rotação manual se >80%; demo gera fotos *placeholder* | 🟢 < 5 % usado |
| **R10** | RGPD: dados pessoais reais em *seed* de demo | Baixa | Crítico | `seed_demo` usa apenas pessoas fictícias e NUIPCs sintéticos; sem dados reais da PSP | 🟢 Confirmado em ADR + auditoria |

---

## 2. Riscos técnicos com controlos forenses

Os riscos técnicos que tocam directamente a integridade da prova digital têm controlos detalhados em [`risks-controls.pdf`](./risks-controls.pdf) (matriz completa) e [`iso27037-traceability.pdf`](./iso27037-traceability.pdf) (mapeamento à norma).

Sumário dos controlos:

- **Adulteração da prova após registo** → *trigger* PostgreSQL `BEFORE UPDATE/DELETE` em `core_evidence` (defesa em profundidade ao nível da BD além do ORM).
- **Adulteração da cadeia de custódia** → *hash* SHA-256 encadeado calculado dentro de `transaction.atomic` + `select_for_update`; verificação em qualquer momento via *endpoint* dedicado.
- **Roubo de *token*** → JWT em *cookies* HttpOnly + Secure + SameSite=Strict; rotação de *refresh* + *blacklist*; CSRF *double-submit*.
- **Injecção / XSS** → CSP nível 3 com *nonce* por *request*; sem *unsafe-inline*; *headers* validados em Mozilla Observatory (A+).
- **IDOR** → `get_queryset()` filtra por `request.user`; *ownership* validado em *writes*.

---

## 3. Histórico de actualização

| Data | Risco | Evento | Estado |
|---|---|---|---|
| 22 mar 2026 | — | Versão inicial (R01-R05) | — |
| 12 abr 2026 | R02, R05 | Adicionada matriz de controlos técnicos (`risks-controls.tex`) | — |
| 3 mai 2026 | R06-R10 | *Mirror* em Markdown + 5 novos riscos descobertos durante Sem 4-7 | — |
