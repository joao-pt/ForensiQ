# Testes do ForensiQ — Estratégia e Guia

Documento de referência sobre **como o ForensiQ é testado**: que camadas
existem, que ferramentas as suportam, como as correr e que decisões/lições
ficaram pelo caminho. Pensado para ser consultado em trabalho futuro.

> Resumo de uma linha: testes de unidade/integração em Django cobrem a lógica
> (a base da pirâmide); testes **end-to-end de browser com Playwright** cobrem a
> interação real (o topo); o **axe-core** cobre acessibilidade e o **Lighthouse**
> a rapidez de laboratório.

---

## 1. A pirâmide de testes

```
        /\        E2E browser (Playwright)        e2e/           ~lento
       /  \       — fluxos, interação, CSP, a11y, rapidez
      /----\      Integração (vista + BD + serializer)  core/tests_*.py
     /------\     Unidade (modelos, validadores, serviços)        ~rápido
```

A base já existia e é forte (≈520 testes em `core/`, gate de cobertura a 80%).
Este trabalho acrescentou o **topo** — a camada que valida o que o utilizador
vê e faz no browser, que nenhum teste de unidade consegue cobrir (CSP, HTMX,
GPS, cascatas JS, drawers, upload de ficheiros, acessibilidade, rapidez
percebida).

---

## 2. Camadas, ferramentas e porquê

| Camada | Ferramenta | Porquê para o ForensiQ |
|---|---|---|
| Unidade + integração | **pytest / Django test runner** | Já existente; rápida, isolada, com factories e gate de cobertura. |
| E2E + interação | **Playwright (Python) + pytest-playwright** sobre o `live_server` do pytest-django | Conduz Chrome real (a CSP estrita não o afeta); integra com os factories e o test DB; arranca o servidor numa thread isolada — **evita o problema do `runserver` manual** (cache de templates em `DEBUG=False`, zombies). |
| GPS determinístico | `context.set_geolocation()` do Playwright | Coordenadas fixas → testa a captura GPS sem hardware. |
| Acessibilidade | **axe-core** via `axe-playwright-python` | Corre apesar da CSP estrita; deteta uma fração fiável das questões WCAG. |
| Rapidez (regressão, no CI) | **Navigation Timing + latência medida** no Playwright | Orçamentos de tempo que apanham regressões grosseiras (ex.: N+1). |
| Rapidez (absoluta, à mão) | **Google Lighthouse** | LCP/INP/CLS/TBT centrados no utilizador; relatório HTML. |
| Carga concorrente | *não-objetivo* (k6/Locust) | Fly é scale-to-zero / ambiente de teste; projeto académico solo. Documentado como deliberadamente fora de âmbito. |

---

## 3. Como correr

### 3.1 Unidade + integração (a base — rápida, corre sempre)

```powershell
# Django runner (igual ao CI), com cobertura:
python manage.py test core --settings=forensiq_project.test_settings
# ou pytest (recolhe só core/ — ver pyproject [tool.pytest] testpaths):
pytest
```

### 3.2 E2E de browser (Playwright)

Uma vez, instalar os binários do browser (em `%LOCALAPPDATA%\ms-playwright`):

```powershell
python -m playwright install chromium
```

Correr a suite E2E (settings próprio, ver §4):

```powershell
pytest e2e/ --ds=forensiq_project.e2e_settings
# útil em depuração: ver o browser e abrandar
pytest e2e/ --ds=forensiq_project.e2e_settings --headed --slowmo 300
```

A acessibilidade (`test_accessibility.py`) e os orçamentos de rapidez
(`test_performance.py`) **fazem parte desta suite** — correm juntos.

### 3.3 Rapidez absoluta (Lighthouse — à mão)

Precisa de um servidor a correr com dados. Receita reproduzível:

```powershell
$s = "--settings=forensiq_project.e2e_settings"
python manage.py migrate --noinput $s
python manage.py seed_crime_taxonomy $s
python manage.py seed_demo --reset --no-input `
    --agent-username lh_agent --agent-password LhPass123! `
    --expert-username lh_expert --expert-password LhPass123! $s
# arrancar o servidor (venv explícito, --noreload):
python manage.py runserver 127.0.0.1:8011 --noreload $s
```

Noutra consola, obter o cookie JWT e correr o Lighthouse:

```powershell
# cookie de um utilizador semeado:
$tok = python manage.py shell $s -c "from django.contrib.auth import get_user_model as g; from rest_framework_simplejwt.tokens import RefreshToken as R; print(str(R.for_user(g().objects.get(username='lh_agent')).access_token))"
# páginas públicas:
.\scripts\run_lighthouse.ps1 -BaseUrl http://127.0.0.1:8011 -Paths /login/
# páginas autenticadas:
.\scripts\run_lighthouse.ps1 -BaseUrl http://127.0.0.1:8011 -Cookie "fq_access=$tok" -Paths /dashboard/,/occurrences/,/evidences/,/stats/
```

Os relatórios HTML+JSON ficam em `docs/testing/reports/lighthouse/` (essa pasta
não é versionada — são regeneráveis; as métricas-chave ficam em
[resultados-2026-06-02.md](resultados-2026-06-02.md)).

---

## 4. Arquitetura do harness E2E

```
src/backend/
  forensiq_project/e2e_settings.py   # settings dedicado ao browser
  e2e/
    conftest.py        # glue Django↔Playwright (fixtures)
    pages.py           # "page objects" leves (cascata de crime, etc.)
    test_smoke.py      # gate de fundação
    test_auth.py  test_occurrences.py  test_evidences.py
    test_lists.py test_custody.py test_intake.py test_public_verify.py
    test_accessibility.py  test_performance.py
scripts/run_lighthouse.ps1
docs/testing/                        # esta documentação
```

**`e2e_settings.py`** herda de `test_settings` e ajusta o necessário para servir
a app REAL a um browser: repõe `STATICFILES_DIRS` (o `test_settings` esvazia-os),
usa SQLite em **ficheiro** (o `live_server` corre noutra thread e tem de ver os
dados cometidos) e isola o `MEDIA_ROOT`.

**`conftest.py`** fornece os fixtures:
- `auth_as(user)` — injeta o cookie JWT (autenticação rápida, sem passar pela
  UI em cada teste); `login_via_ui` exercita o formulário real de login;
- `make_user`, `seed`, `tiny_image` — dados reais via factories;
- `js_errors`, `csp_violations`, `failed_static` — diagnóstico por página;
- configuração do browser: locale pt-PT, fuso de Lisboa, **geolocalização fixa**
  com permissão, e **bloqueio de pedidos externos** (tiles de mapa) para os
  testes correrem offline e sem flakiness (as fontes do Google, que estão na
  allowlist da CSP, são permitidas).

A suite E2E vive **fora de `core/`** e tem o seu próprio settings, por isso o
`manage.py test core` do CI e um `pytest` simples nunca tentam arrancar o
Playwright (ver `pyproject.toml` → `testpaths = ["core"]`).

---

## 5. Cobertura atual (33 testes E2E)

| Módulo | Testes | O que cobre |
|---|---:|---|
| `test_smoke.py` | 4 | Login pela UI real; **todas** as páginas autenticadas renderizam (CSS servido, sem erros JS); **zero violações de CSP**; captura de GPS preenche coordenadas. |
| `test_auth.py` | 4 | Redireccionamento de página protegida → login; erro de credenciais visível; portão de perfil ADR-0017 (agente bloqueado da receção = 403; perito = 200). |
| `test_occurrences.py` | 4 | Criação completa com **cascata de crime N1→N2→N3**; dica de prioridade; validação nativa de campos; **erro server-side renderizado visível** (regressão do bug crítico anterior). |
| `test_evidences.py` | 3 | Campos específicos por tipo (mostrar/ativar só os do tipo escolhido); **upload de fotografia** (o fluxo que deu 500 em produção); required. |
| `test_lists.py` | 3 | Pesquisa filtra a grelha **por HTMX sem recarregar**; filtro por select; clique na linha abre o **drawer** de detalhe. |
| `test_custody.py` | 1 | Registo de evento no **ledger** de custódia (transição válida). |
| `test_intake.py` | 1 | **Receção** no laboratório (transferência para LAB_PUBLICO, perito-only). |
| `test_public_verify.py` | 2 | Verificação pública por QR (sem login): hash válido = 200; inválido = 404. |
| `test_accessibility.py` | 3 | **Zero** violações graves/críticas de a11y (incl. contraste WCAG AA) — testado no tema **claro E escuro**; login. |
| `test_performance.py` | 3 | Orçamento de render do servidor; latência da cascata; latência do filtro HTMX. |
| `test_keyboard.py` | 3 | A11y de teclado: skip link → conteúdo; login submetido com Enter; abrir o drawer com Enter numa linha. |
| `test_mobile.py` | 1 | Responsivo: o off-canvas da sidebar abre/fecha em viewport móvel (incl. Escape). |
| `test_visual.py` | 1 | Regressão visual do formulário de nova ocorrência (screenshot + diff; marcador `visual`, fora do CI). |

---

## 6. Gotchas e lições (referência)

Conhecimento ganho a montar isto — poupa horas a quem voltar ao tema.

1. **Playwright sync + Django bloqueiam-se.** O event-loop do Playwright (num
   greenlet) faz o Django achar que está em contexto async e recusar operações
   ORM síncronas. Fix: `os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE","true")`
   no topo do `conftest.py` (o loop é cooperativo, não há concorrência real).
2. **A CSP estrita bloqueia `wait_for_function("<string>")` durante o polling**
   (`unsafe-eval` não permitido — o Playwright usa `new Function` na página).
   Usar as asserções **`expect()`** (baseadas no protocolo, sem eval) ou passar
   uma **função** em vez de uma string. As chamadas one-shot `page.evaluate`
   passam (são `Runtime.evaluate`, isento de CSP).
3. **Um `<option>` dentro de `<select>` nunca é "visible"** para o Playwright.
   Esperar com `wait_for_selector(..., state="attached")`.
4. **O `<thead>` sticky interceta cliques** nas linhas da grelha. Disparar o
   clique com `locator.dispatch_event("click")` (o HTMX reage ao evento na mesma).
5. **Os cookies JWT só saem não-`Secure` com `DEBUG=True`** (`core/auth.py`:
   `secure = not settings.DEBUG`). Por isso o `e2e_settings` tem `DEBUG=True` —
   senão o browser recusaria o cookie sobre `http://localhost`.
6. **O `test_settings` esvazia `STATICFILES_DIRS`** — irrelevante para testes de
   unidade, fatal para um browser (sem CSS/JS). O `e2e_settings` repõe-nos.
7. **Browsers do Playwright** instalam-se em `%LOCALAPPDATA%\ms-playwright`. NÃO
   usar `PLAYWRIGHT_BROWSERS_PATH=0` (instala dentro do pacote e o runtime não os
   encontra).
8. **SQLite em ficheiro, não `:memory:`**, para o `live_server` (noutra thread)
   ver os dados cometidos pelos factories (`transactional_db`).
9. **Lighthouse no Windows** termina com `EPERM` ao limpar o perfil temporário
   do Chrome — é **cosmético**: o relatório já foi gerado antes do erro.
10. **Servir o browser:** usar sempre o `live_server` do pytest (isolado), não o
    `runserver` manual — evita o problema conhecido de templates em cache
    (`DEBUG=False`) e processos zombie.

---

## 7. Integração contínua (opcional)

A suite E2E **não** está no CI por defeito (precisa de descarregar o browser
≈110 MB e leva ≈1 min). Para a acrescentar ao `.github/workflows/ci.yml`:

```yaml
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r src/backend/requirements.txt -r src/backend/requirements-dev.txt
      - run: python -m playwright install --with-deps chromium
        working-directory: src/backend
      - run: pytest e2e/ --ds=forensiq_project.e2e_settings
        working-directory: src/backend
        env:
          SECRET_KEY: ci-dummy-secret-key
```

O Lighthouse fica fora do CI (pesado; o Fly é scale-to-zero).
