# ADR-0012: O PDF da evidência é uma guia de transporte, não prova autónoma

## Estado

Aceite — 2026-05-27.

## Contexto

O ForensiQ gera, para cada ocorrência, um PDF com os itens de prova apreendidos. É
tentador olhar para esse documento como se ele próprio fosse prova: um relatório forense
auto-suficiente que um perito externo recebesse, verificasse isoladamente e levasse a
tribunal. Visto por essa lente, faltar-lhe-iam assinatura digital qualificada, o formato
PDF/A para preservação a longo prazo, uma data de modificação fiável e o hash do próprio
ficheiro nos metadados.

Mas esse não é o papel do documento. A prova com valor jurídico não está no PDF — está no
sistema: o `integrity_hash` de cada evidência (SHA-256 sobre os metadados e os bytes da
fotografia), a cadeia de custódia `ChainOfCustody` em modo *append-only* com hash encadeado,
e os *triggers* de imutabilidade ao nível da base de dados, que bloqueiam qualquer alteração.
É aí que reside a autoridade da prova, e é aí que a conformidade com a ISO/IEC 27037 se
sustenta.

O PDF tem outra função, operacional: acompanhar fisicamente a prova entre o local da
apreensão e o laboratório. O paralelo certo é o de uma **guia de transporte** — o talão que
segue uma encomenda, com um código que se lê à chegada para confirmar o que chegou. Não é o
documento que prova a verdade; é o que conduz a prova de um ponto de controlo ao seguinte.

## Decisão

1. **O PDF é uma guia de transporte físico.** Acompanha a prova entre o terreno e o
   laboratório e serve dois momentos: o agente entrega-o em mão, anexo à prova; o perito
   usa-o à chegada para confirmar, item a item, o que recebeu. Não é, nem pretende ser, prova
   juridicamente auto-contida — essa vive no sistema.

2. **Rastreio por QR code.** Cada PDF leva um QR da ocorrência e um por evidência, que
   apontam para um endpoint público de verificação (`/v/<hash>`). O código legível da
   ocorrência e de cada item continua impresso em texto, para entrada manual quando o QR
   estiver ilegível.

3. **Verificação pública adaptativa.** O endpoint mostra o mínimo a quem não tem sessão —
   código da ocorrência, número de itens esperados e hashes de integridade verificáveis —
   sem revelar descrições, coordenadas, agentes ou tipos de prova. A quem tem sessão e
   direito de acesso, encaminha para a vista completa.

4. **Confirmação de receção no laboratório.** Uma lista de conferência de entrada permite ao
   perito confirmar a chegada dos itens esperados; cada confirmação regista o evento de
   custódia correspondente no ledger. O estado legal é derivado da sequência de eventos, não
   de um campo de estado.

5. **Sem assinatura digital, X.509, PDF/A ou *timestamping* qualificado.** Construir essa
   infraestrutura serviria um requisito que o produto não tem e comunicaria uma ambição
   errada sobre o que o ForensiQ é. O `integrity_hash` continua impresso para verificação
   pontual; o PDF permanece, por desenho, um PDF comum.

6. **Sem códigos de barras lineares (Code 128).** Só fariam sentido com um *scanner* laser e
   uma página de busca por código que não se justifica neste fluxo — o QR, mais o texto
   impresso, cobre a necessidade.

## Alternativas consideradas

- **PDF como prova autónoma assinada** (PyHanko, certificado X.509, *timestamping*).
  Rejeitada: constrói tecnologia para um requisito inexistente e baralha o âmbito do projeto.
  A custódia e a integridade já vivem na base de dados.
- **Modelo híbrido — PDF assinado e com rastreio.** Rejeitada por excesso: se é guia de
  transporte, não precisa de assinatura; se fosse prova autónoma, não precisaria de rastreio.
  Misturar as duas finalidades dilui a clareza para quem usa o documento.
- **Eliminar o PDF** e fazer toda a comunicação pela aplicação. Rejeitada: no terreno a prova
  física circula com papelada anexa; a guia de transporte é a ponte entre o mundo físico e o
  digital, e negá-la quebra o caso de uso real.

## Consequências

- O papel do PDF fica claro: gestão de prova digital com guia de transporte, e não geração de
  prova de tribunal.
- Sem dependência de autoridades de certificação nem da gestão que isso arrasta (chaves,
  OCSP, revogação, custo recorrente).
- A conferência de entrada está reservada ao perito; num modelo mais distribuído (qualquer
  membro do mesmo serviço a poder receber) seria preciso alargá-la — fica como trabalho
  futuro.
- O endpoint público acrescenta superfície sem autenticação; mitiga-se com dados mínimos, um
  hash curto não enumerável (HMAC por servidor) e *rate-limiting*.

## Referências

- ADR-0009 — sessão em *cookies* HttpOnly e modelo de autorização base.
- ADR-0010 — taxonomia da prova e estrutura de `Evidence` e `ChainOfCustody`.
- ADR-0015 — ledger de custódia e estado legal derivado da sequência de eventos.
- ReportLab e a biblioteca `qrcode` — geração do PDF e dos QR codes.
