# ADR-0012: PDF da evidência como guia de transporte físico (re-classifica N2 do audit)

## Status

Accepted — **re-classifica N2** do `docs/AUDIT_2026-05-18-delta.md` (anteriormente listado como "🟠 Alto — PDF não assinado nem PDF/A-3u") como **não-aplicável**, não "adiado por custo". Anota também o §4.1 do mesmo audit, cuja matriz de conformidade ISO/IEC 27037 avalia o PDF contra um requisito que o produto não tem.

Substitui implicitamente o framing que se podia inferir do nome do módulo `core/pdf_export.py` ("relatório forense") — o artefacto continua a chamar-se relatório, mas o seu papel funcional é outro.

## Data

2026-05-27

## Context

A auditoria de 2026-05-18 (§4.1, página `docs/AUDIT_2026-05-18-delta.md`) avalia o PDF gerado por `core/pdf_export.py` contra a expectativa de **prova juridicamente auto-contida** — i.e., um documento que um perito externo possa receber, verificar isoladamente, e apresentar em tribunal sem ter de aceder ao sistema ForensiQ. Lista quatro falhas:

> - ❌ PDF não é assinado digitalmente.
> - ❌ Sem PDF/A-3u (preservação a longo prazo).
> - ❌ `ModDate` não definida — modificação post-export indetectável por verificador externo.
> - ❌ Sem hash do próprio PDF nos metadados.

E propõe (N2, §3, severidade 🟠 Alto, custo 3-5 dias) atacar via integração de **PyHanko** + certificado **X.509** + serviço de timestamping qualificado, deixando aberta a hipótese de obter uma CA (com custo recorrente, gestão de chaves, OCSP, etc.).

Esta avaliação assume que o ForensiQ se posiciona como **gerador de prova autónoma para tribunal**. Confrontado directamente com a proposta em 2026-05-27, o autor do projecto (João, perfil produto + engenharia) clarificou o intent real do artefacto:

> "O PDF assinado não tem grande valor. Ele serve apenas para acompanhar a prova física, os equipamentos, e serve apenas para validar quando chega ao laboratório. Isto devia mais se assemelhar a algo como os correios, tipo aquilo da DHL e coisas assim, em que são entregues e tem código de barras, quase como um tracker. Nunca tinha pensado nisto assim, mas é esse o intuito, e não fazer com que aquele documento seja prova da verdade."

O paralelo conceptual passa a ser **guia de transporte da DHL**, não documento jurídico autónomo. A prova jurídica autoritativa **já vive no sistema** (ADR-0009/0010) — `Evidence.integrity_hash` (SHA-256 sobre metadados + bytes da foto, ADR-0005/0006 da auditoria), `ChainOfCustody` append-only com hash chain (ADR-0010), triggers PostgreSQL de imutabilidade (migrações 0002 + 0008), bloqueio admin/API em três camadas. O PDF é um **instrumento operacional**: serve o agente em campo para entregar em mão, e o perito no laboratório para confirmar a recepção.

Atacar N2 conforme proposto seria construir tecnologia (assinatura X.509, PDF/A-3u, timestamping qualificado) para satisfazer um requisito que o produto **não tem**. Pior, comunicaria implicitamente — ao orientador, ao júri da defesa, e a um futuro leitor — que o ForensiQ ambiciona ser "gerador de prova de tribunal", criando expectativa errada sobre o âmbito real do projecto.

## Decision

1. **N2 do `docs/AUDIT_2026-05-18-delta.md` é re-classificado como "não-aplicável"** (não "adiado por custo arquitectural"). O finding registou correctamente uma diferença entre o PDF actual e PDFs forenses *no-tribunal*; a re-classificação reconhece que o PDF do ForensiQ não tem essa finalidade. A auditoria continua íntegra como documento histórico — a re-classificação fica documentada aqui e referenciada na §8.1 do audit.

2. **Definição explícita do propósito do PDF** (a integrar no relatório final, capítulo de Implementação):

   > O PDF gerado por `core/pdf_export.py` é um **guia de transporte físico** que acompanha a prova entre o local de apreensão e o laboratório forense. Tem dois utilizadores e dois momentos:
   >
   > - **Agente no campo (apreensão)**: imprime o PDF e entrega-o em mão, anexado à prova física, ao perito do laboratório. Funciona como talão de hand-off.
   > - **Perito no laboratório (recepção)**: usa o PDF para abrir a *check-list de intake* digital, confirmando item-a-item a chegada da prova esperada.
   >
   > O PDF **não é** prova juridicamente auto-contida. A prova autoritativa vive no sistema: `Evidence.integrity_hash`, `ChainOfCustody` append-only com hash chain, triggers PostgreSQL de imutabilidade, bloqueio admin/API em três camadas (ADR-0009, ADR-0010, migrações `0002_add_immutability_triggers` + `0008_extend_immutability`).

3. **Re-estruturar o PDF para reflectir o intent**, em duas vagas (ver detalhe na *Implementação* desta ADR):
   - **Vaga 1** (Sem.12): adicionar **QR codes** (1 grande na folha de rosto da ocorrência + 1 menor em cada secção de evidência, sujeito a revisão visual conjunta para evitar layout sobrecarregado) e criar endpoint público adaptativo `/v/<short-hash>`. O `occurrence.code` (OC-YYYY-NNNN, ex.: `OC-2026-0001`) e o `evidence.code` (código hierárquico derivado, ex.: `OC-2026-0001.1.1`, ADR-0016) continuam impressos em texto — são human-readable e suficientes para entrada manual em casos de QR ilegível.
   - **Vaga 2** (Sem.13): criar página de **check-list de intake** em `/occurrences/<int:occurrence_id>/intake/`, acessível apenas a perfil FORENSIC_EXPERT (ou staff/superuser), com checkbox por evidência esperada. Ao confirmar todas as recepções, regista-se em batch para cada item um evento de ledger `TRANSFERENCIA` → `LAB_PUBLICO` (ADR-0015), reaproveitando `/api/custody/cascade/` já existente.

4. **Modelo de autorização do scan**: o QR contém uma URL única `/v/<short-hash>`. Vista adaptativa segundo cookie de autenticação:
   - **Sem login**: mostra metadata pública mínima — `occurrence.code`, número de itens esperados, hashes de integridade (verificáveis externamente). Não revela descrições, GPS, agentes, ou tipos específicos de evidência.
   - **Com login + perfil FORENSIC_EXPERT** (ou staff): redirect para `/occurrences/<id>/` (vista completa actual).
   - **Com login + perfil FIRST_RESPONDER** que **é** o dono da ocorrência: redirect para `/occurrences/<id>/`.
   - **Com login + perfil FIRST_RESPONDER** que **não é** o dono: cai na vista pública mínima (não num 403) — não vê detalhe da ocorrência alheia, em linha com o modelo de ownership já documentado em ADR-0009 e fix B13 do audit.
   - O intake é, por desenho, FORENSIC_EXPERT-only. FIRST_RESPONDERs em campo entregam; não fazem intake. Esta divisão alinha com a separação de papéis já existente.

5. **Não introduzir** PyHanko, certificados X.509, PDF/A-3u, timestamping qualificado, ou qualquer infra-estrutura de assinatura digital. O `integrity_hash` continua impresso no PDF para verificação pontual, mas o PDF em si permanece intencionalmente um PDF "comum" gerado por ReportLab.

6. **Não introduzir** Code 128 ou outros códigos de barras lineares. A decisão foi tomada na discussão de 2026-05-27 após considerar três opções (só QR, só Code 128, ambos): o Code 128 só faz sentido se o site tiver endpoint de busca por código, que se decidiu não implementar (confiamos no QR + texto impresso para o fluxo normal). Esta decisão é revisível se o feedback do orientador ou da defesa pedir.

## Alternatives Considered

- **Atacar N2 conforme o audit propôs** (PyHanko + X.509 + timestamping). Rejeitado — constrói para um requisito que o produto não tem. ROI académico nulo. Comunica intent errado.

- **Manter status quo sem alterar o PDF** (deixar N2 aberto, sem ADR, listado como "limitação conhecida"). Rejeitado — viola o princípio do paper-trail do projecto. Cada divergência entre código e ambição documentada deve ser ou (a) fixada, ou (b) reclassificada explicitamente. "Aberto sem justificação" é tecnicamente dívida documental.

- **Modelo híbrido — PDF assinado + tracking** (manter assinatura X.509 *e* acrescentar QR). Rejeitado — over-engineering. Se o PDF é guia de transporte, não precisa de assinatura. Se o PDF é prova autónoma, não precisa de tracking (a custody chain está na BD). Misturar as duas finalidades dilui a clareza para o utilizador final e duplica trabalho.

- **Eliminar o PDF** (não existir guia de transporte; toda a comunicação agente↔perito feita só via app). Rejeitado — quebra o caso de uso real (ambiente de campo PSP), onde a prova física circula com papelada anexada. O guia de transporte é a interface entre o mundo físico e o mundo digital; eliminar o PDF é negar essa fronteira.

- **Code 128 + QR em paralelo, com nova página de busca por código**. Rejeitado — duplica códigos, requer scanner laser no laboratório que tipicamente não existe em ambiente policial, e introduz nova superfície UI (página de busca) que se decidiu não implementar.

## Consequences

### Positivas

- **Clarifica narrativa do projecto**. O capítulo de Implementação do relatório final ganha uma definição precisa do que o PDF é e não é. A defesa pública pode posicionar o ForensiQ correctamente: "gestão integrada de prova digital com guia de transporte digital", em vez de "gerador de prova de tribunal".
- **Fecha N2 honestamente**. A re-classificação é genuína; o finding não é varrido para debaixo do tapete. Quem ler o audit + este ADR percebe o porquê.
- **Reorienta esforço para o que tem valor**. As ~30-40h que iriam para PyHanko vão para QR codes + endpoint público + check-list de intake — features com utilidade operacional directa, demonstráveis em demo.
- **Custo zero em certificados / CAs**. Sem dependência de CA externa (custo recorrente + gestão de chaves + OCSP + revogação).
- **Defesa em profundidade preservada**. O `integrity_hash` continua impresso no PDF — verificação por terceiro continua possível, apenas sem confiar no PDF como contentor de assinatura.

### Negativas / Trade-offs

- **Muda framing comunicado externamente**. Quem viu o ForensiQ no relatório intercalar (Maio 2026) pode ter ficado com a impressão de "prova de tribunal". Há que comunicar a re-orientação ao orientador antes da defesa.
- **Requer redesign visual do PDF**. Adicionar QR codes (1 por ocorrência + 1 por evidência, sujeito a revisão) sem sobrecarregar o layout é trabalho de iteração visual. Não é só "colar um QR". Marcado como ponto de revisão conjunta na Sem.12.
- **Novo endpoint público (`/v/<short-hash>`)**. Aumenta a superfície de ataque com algo sem autenticação. Mitigação: vista pública mostra apenas códigos + número de itens + hashes (sem descrições, GPS, agentes); rate-limit via scope DRF dedicado (a definir em PR da Vaga 1, paralelo a `imei_lookup`/`reverse_geocode`); hash curto não-enumerável (HMAC-SHA256 do `occurrence.id` com chave por servidor, truncado a 12 chars). Documentar em ADR-0007 (SRI/Referrer Policy) na próxima passagem editorial.
- **Página intake EXPERT-only deixa um vector aberto**: AGENT que apreendeu mas não vai entregar pessoalmente — a sua ocorrência só faz check-in se houver um EXPERT a fazer scan. Aceitável para o caso de uso assumido (PSP entrega laboratório forense); não-aceitável para um modelo descentralizado (qualquer agente do mesmo destacamento poder receber). Registar como limitação no relatório final, secção de trabalho futuro.

### Impactos noutros documentos

- **`docs/AUDIT_2026-05-18-delta.md`**:
  - §3 (achados novos): linha N2 anotada com "✅ Re-classificado em Sem.12 (ADR-0012)" — não-aplicável.
  - §4.1 (`pdf_export.py` em profundidade): adicionar parágrafo a explicar que as 4 falhas listadas (sem assinatura, sem PDF/A-3u, sem ModDate, sem hash do PDF) são **consequência directa** do propósito real do artefacto, não bugs.
  - §5 Top-10: linha 3 (N2) marcada "✅ Re-classificado Sem.12 (ADR-0012)".
  - §8.1 (fechados): nova entrada para N2 a apontar a este ADR.
  - §8.2 (mantidos em aberto): remover N2 (já não está aberto, está re-classificado).
  - §8.3 (postura final): contagem actualizada para "5/5 N* 🟠 Alto fechados ou re-classificados".
- **`README.md`**: secção que descreve o PDF passa a chamá-lo "guia de transporte" em vez de "relatório forense".
- **`docs/architecture/photo-capture-status.md`**: já actualizado em 2026-05-27 (commit `ae0c0ed`) para S9 — sem novo trabalho aqui.
- **`docs/scope/iso27037-traceability.tex`**: revisitar para clarificar que a conformidade ISO 27037 do ForensiQ vive **no sistema** (hash, CoC, imutabilidade), não no PDF.
- **`docs/scope/changelog.md`**: entrada Sem.12 regista este ADR e a re-classificação.

## Implementação (notas para a Vaga 1 + Vaga 2)

### Vaga 1 — QR codes + endpoint público adaptativo (Sem.12)

- Biblioteca: `qrcode` (PyPI, MIT) ou `reportlab.graphics.qrencoder`. Avaliar qual integra melhor com o `flow` do ReportLab actual; preferir `qrcode` se a integração com `Drawing`/`Flowable` for trivial.
- Geração do hash curto: `hmac.new(settings.QR_VERIFY_SECRET, str(occurrence.id).encode(), hashlib.sha256).hexdigest()[:12]`. Nova env var `QR_VERIFY_SECRET` (independente de `SECRET_KEY`) para isolar revogação.
- Endpoint público: função Django pura `public_verify_view` em `core/frontend_views.py` (não uma `APIView` DRF), registada em `urls.py` como `path('v/<str:short_hash>/', ...)`. O rate-limit do scope DRF `verify_public` (`30/minute` em produção, mirror `10000/minute` em TESTING — padrão estabelecido em N8) é aplicado pelo helper `_throttle_public_verify`, que reusa o `ScopedRateThrottle` do DRF sobre o request Django, complementado por lockout por IP escalado (`_verify_is_locked`).
- Vista adaptativa: dá-se a vista completa (redirect HTTP 302 para `/occurrences/<id>/`) apenas se o utilizador for `is_staff` **ou** tiver perfil `FORENSIC_EXPERT` **ou** for `FIRST_RESPONDER` **e** dono da ocorrência (`occurrence.agent_id == user.id`). Em todos os outros casos — incluindo `FIRST_RESPONDER` não-dono — renderiza-se o template `public_verify.html` com dados mínimos (código, contagem, integrity_hashes em mono-text), não um 403.
- Posicionamento dos QRs no PDF: revisão visual conjunta na primeira iteração. Hipóteses iniciais:
  - QR da ocorrência no cabeçalho (canto superior direito, ~3×3 cm).
  - QR de cada evidência ao lado do título da secção (~1.5×1.5 cm). Risco de sobrecarregar — avaliar; se sim, mover para tabela de índice na folha de rosto.
- Testes: novo `core/tests_public_verify.py` cobrindo (a) hash determinístico, (b) hash desconhecido → 404, (c) sem login → vista pública com dados mínimos, (d) EXPERT logado → 302 para detalhe, (e) AGENT não-dono → 403, (f) AGENT dono → 302, (g) throttle dispara em 31ª chamada.

### Vaga 2 — Check-list de intake (Sem.13)

- Modelo: sem novas tabelas. A check-list é UI sobre `ChainOfCustody` existente — "recebido" significa registar para essa evidência um evento de ledger `TRANSFERENCIA` → `LAB_PUBLICO` (ADR-0015); o estado legal é derivado da sequência de eventos, não um campo de FSM.
- View: função `occurrence_intake_view` em `core/frontend_views.py` que valida o JWT em cookie, exige perfil `FORENSIC_EXPERT` (ou staff/superuser) e devolve `403_intake.html` caso contrário. URL `/occurrences/<int:occurrence_id>/intake/` (name `occurrence_intake`).
- Template: lista de evidências esperadas (`occurrence.evidences.all()`) com checkbox por item; ao submeter, POST para `/api/custody/cascade/` (já existente) que regista para todos os itens marcados um evento `TRANSFERENCIA` → `LAB_PUBLICO`.
- Detecção de "faltas": se utilizador submete sem todos os checkboxes marcados, mostrar warning amarelo "Itens não confirmados: X, Y, Z. Continuar mesmo assim?" — opcionalmente registar `ChainOfCustody.observations` com a nota "Item ausente na recepção".
- Trigger automático opcional: se *todos* os itens forem marcados, render botão "Receber tudo" que faz transição em batch sem requerer click individual.
- Testes: cobrir EXPERT pode aceder; AGENT recebe 403; submit parcial; submit total; concorrência entre dois EXPERTs.

## Referências

- `docs/AUDIT_2026-05-18-delta.md` — §4.1 (PDF em profundidade), §3 (N2), §5 (Top-10), §8 (decisão final).
- ADR-0009 — JWT em cookies HttpOnly; modelo de autorização base.
- ADR-0010 — Taxonomia digital-first; estrutura de `Evidence` + `ChainOfCustody`.
- ADR-0008 — Cache strategy; padrão de `ScopedRateThrottle` por scope.
- `core/migrations/0002_add_immutability_triggers.py` e `0008_extend_immutability.py` — defesa em camadas no nível BD.
- Discussão de 2026-05-27 (esta sessão de planeamento Sem.12-15) — captura do intent real do PDF.
- ReportLab — <https://docs.reportlab.com/reportlab/userguide/ch5_paragraphs/> (Flowable composition para inserir QR no flow do documento).
- `qrcode` library — <https://pypi.org/project/qrcode/> (alternativa a `reportlab.graphics.qrencoder` se necessário).
