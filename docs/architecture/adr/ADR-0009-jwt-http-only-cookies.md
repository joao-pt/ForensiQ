# ADR-0009: Autenticação JWT via Cookies HttpOnly + CSRF

## Status

Accepted — **supersede parcialmente ADR-0002 §8** ("Auth: SimpleJWT para tokens, configurável via `.env`"). A stack continua a assentar em `djangorestframework-simplejwt`, mas o transporte dos tokens passa de **Authorization header (localStorage no frontend)** para **cookies HttpOnly + CSRF double-submit**.

## Data

2026-04-19

## Context

A primeira iteração do ForensiQ (ADR-0002) assumia o padrão clássico de JWT em API pública: o cliente faz POST `/api/token/` com credenciais, recebe `access` + `refresh` no body, guarda-os em `localStorage` e envia `Authorization: Bearer <access>` em cada pedido. Esta abordagem tem três problemas relevantes no contexto forense:

1. **XSS expõe tokens.** `localStorage` é acessível a qualquer script no mesmo origin. Uma única vulnerabilidade de XSS (na timeline, nos detalhes da evidência, numa dependência de terceiros) exfiltra os tokens e concede acesso total à API. Para um SaaS policial com cadeia de custódia imutável, a integridade da sessão é crítica.
2. **O refresh viaja no body.** O frontend tem de guardar e reenviar o refresh explicitamente, duplicando a superfície de ataque.
3. **CSP não cobre o vector.** Mesmo com uma CSP apertada, basta um script permitido ou um `eval` indirecto para abrir o cofre.

O frontend já é servido pelo próprio Django (templates HTML + estáticos), ou seja, **não há cross-origin a proteger** — o que elimina a objecção clássica contra cookies (impossibilidade de os enviar sob CORS). O navegador trata os cookies HttpOnly de forma opaca: nenhum script de página consegue ler ou roubar o token.

Adicionalmente, com cookies aparece naturalmente o risco de CSRF. O Django já traz CSRF middleware ligado e o DRF integra-se através de `SessionAuthentication`. Falta apenas garantir que o fluxo JWT-em-cookie lê o token CSRF em cada pedido mutador.

## Decision

1. **Transporte:** O access e refresh tokens JWT são armazenados em **cookies HttpOnly**, com os nomes `fq_access` e `fq_refresh` (ver `core/auth.py`).
2. **Atributos dos cookies:**
   - `HttpOnly = True` — bloqueia leitura por JS (mitiga XSS).
   - `Secure = True` em produção (`False` em testes e dev local via `test_settings.py`).
   - `SameSite = "Lax"` — permite navegação normal (login redirect) e bloqueia envio em requests cross-site de terceiros.
   - `Path = "/"` e `Domain = None` (herda o domínio actual).
   - `Max-Age` ligado à vida do token (access ~15 min, refresh ~24 h — mantidos em `SIMPLE_JWT` settings).
3. **CSRF double-submit:** Em cada login bem-sucedido, além dos cookies JWT, o servidor também envia o cookie `csrftoken` (via `@ensure_csrf_cookie`). O frontend lê-o em JS e replica-o no header `X-CSRFToken` em pedidos `POST/PUT/PATCH/DELETE`. A autenticação DRF é feita por `core.auth.JWTCookieAuthentication`, que delega em `rest_framework_simplejwt` para validar o token e em `enforce_csrf()` para validar o header. Pedidos `GET` não exigem CSRF.
4. **Endpoints dedicados:** `POST /api/auth/login/` (emite cookies), `POST /api/auth/refresh/` (lê `fq_refresh` do cookie, rotaciona ambos), `POST /api/auth/logout/` (blacklist do refresh + `Max-Age=0` nos cookies). Todos com `AuthRateThrottle` (5/min) para travar força bruta.
5. **Rotação de refresh:** `simplejwt` configurado com `ROTATE_REFRESH_TOKENS=True` e `BLACKLIST_AFTER_ROTATION=True` — cada refresh emite um novo refresh e blacklist do anterior, reduzindo a janela de replay.
6. **Compatibilidade de testes:** `test_settings.py` aponta explicitamente para `core.auth.JWTCookieAuthentication` como classe de autenticação default, garantindo que testes IDOR/CSRF exercitam o mesmo caminho real. Os testes que forçam autenticação (`force_authenticate`) continuam a funcionar porque o DRF APIClient ignora a classe de autenticação nesse caminho.
7. **URL namespace:** `auth_login`, `auth_refresh`, `auth_logout` — substituem os antigos nomes `token_obtain_pair`, `token_refresh` (removidos nesta wave).

## Alternatives Considered

- **Manter `Authorization: Bearer` + `localStorage`.** Padrão dominante em SPAs com backend separado, mas vulnerável a XSS. Rejeitado pelos motivos acima.
- **`sessionStorage` em vez de `localStorage`.** Reduz persistência mas continua acessível a scripts do mesmo origin — não mitiga o vector XSS, apenas o tempo de exposição. Rejeitado.
- **Encriptar os tokens com chave do servidor antes de guardar em `localStorage`.** Adiciona complexidade sem ganhos reais — a chave de decifração teria de viajar para o cliente de alguma forma. Rejeitado.
- **Sessions nativos do Django (sem JWT).** Alternativa válida e mais simples, mas perderíamos interoperabilidade com clientes não-browser (ex.: app móvel, integração pericial) que dependam de validação stateless de tokens. Mantemos JWT para abrir essa porta no futuro.

## Consequences

### Positivas
- **XSS já não compromete tokens:** mesmo com injecção de script, os cookies HttpOnly continuam invisíveis ao JS.
- **CSRF coberto por double-submit** — o atacante num origin terceiro não consegue ler o cookie `csrftoken`.
- **Menor superfície no frontend:** o código do cliente passa a não lidar com tokens — apenas com o header `X-CSRFToken`.
- **Rotação de refresh com blacklist** limita o impacto de roubo via replay.
- **Testes reproduzem o caminho real** (mesma classe de autenticação que produção).

### Negativas / Trade-offs
- **Acoplamento ao navegador como cliente primário.** Clientes não-browser (ex.: scripts pericias, CLI interno) têm de gerir cookies manualmente. Aceitável no MVP — se aparecer uma app móvel, acrescenta-se um auth class alternativo em vez de refazer o actual.
- **Debug mais difícil.** Os tokens deixam de aparecer no DevTools → Application → Local Storage. Para desenvolvimento, criámos o endpoint `GET /api/users/me/` para confirmar a identidade autenticada.
- **Deploy TLS obrigatório em produção.** Sem `Secure=True` o transporte em HTTP seria perigoso. Já garantido pelo Fly.io (ADR-0005).

### Impactos em outros documentos
- **ADR-0002 §8** ("Auth: SimpleJWT para tokens, configurável via `.env`") — continua válido no que respeita à biblioteca; o transporte é agora descrito aqui.
- **ADR-0003 (API REST Design)** — os endpoints `/api/auth/*` passam a fazer parte da superfície pública; `/api/token/*` são removidos.

## Referências
- OWASP ASVS V3.4 — Session Cookie Attributes.
- MDN — [`Set-Cookie` header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie).
- OWASP — [Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
- `simplejwt` — [Token Blacklist App](https://django-rest-framework-simplejwt.readthedocs.io/en/latest/blacklist_app.html).
