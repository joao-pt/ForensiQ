# Evidência de testes externos — ForensiQ

PDFs gerados por serviços externos independentes que validam a postura
de segurança da plataforma em produção (`https://forensiq.pt`).

| Ficheiro | Serviço | Resultado | Data |
|---|---|---|---|
| `01-HSTS-Preload-Submission.pdf` | hstspreload.org (Chromium / Mozilla / Edge / Apple) | Submetido para inclusão na lista pré-carregada de HSTS | 2026-04-18 |
| `02-HTTP-Observatory-MDN.pdf` | Mozilla HTTP Observatory | Pontuação A+ (CSP, HSTS, Referrer-Policy, X-Content-Type-Options, etc.) | 2026-04-18 |
| `03-SSL-Server-Test-Qualys.pdf` | Qualys SSL Labs | Grau A+ (TLS 1.2/1.3, ECDHE, HSTS, OCSP stapling) | 2026-04-18 |

Estes documentos são utilizados como **evidência empírica** no Relatório
Intercalar (Fase 2) e Final (Fase 3) para sustentar as escolhas de
segurança do ForensiQ — em particular o cumprimento do RNF de "suporte
HTTPS em produção" e da conformidade com OWASP ASVS V14.4 (Configuração
de cabeçalhos de segurança HTTP).

## Reproduzir

| Teste | URL |
|---|---|
| HSTS Preload | <https://hstspreload.org/?domain=forensiq.pt> |
| HTTP Observatory | <https://developer.mozilla.org/en-US/observatory/analyze?host=forensiq.pt> |
| SSL Server Test | <https://www.ssllabs.com/ssltest/analyze.html?d=forensiq.pt> |

Re-executar trimestralmente ou após qualquer alteração à configuração
TLS / cabeçalhos.
