"""
ForensiQ — Testes estruturais ao namespace global JavaScript.

Apanha regressões em que dois ficheiros JS carregados no mesmo template
declaram o mesmo identifier no escopo global. Em scripts clássicos (não
ES modules) isso é um `SyntaxError: Identifier 'X' has already been
declared` que mata o segundo script inteiro — incluindo qualquer
`document.addEventListener('DOMContentLoaded', ...)` que ele tenha,
o que se manifesta como página "morta" sem mensagem clara ao utilizador.

Caso concreto que motivou este teste (2026-05-17):

  custody_states.js declarava `const STATE_FLOW` no escopo global.
  dashboard.js fazia `const { STATE_FLOW } = window.CustodyStates`
  também no top-level. Resultado: `/dashboard/` morria silenciosamente
  e o user lia "perito não tem ocorrências".

O fix estrutural foi encapsular helpers e page-scripts em IIFEs (pattern
já estabelecido em `toast.js`). Este teste assegura que ninguém regressa.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


STATIC_JS_ROOT = Path(settings.BASE_DIR).parent / 'frontend' / 'static' / 'js'
TEMPLATES_ROOT = Path(settings.BASE_DIR).parent / 'frontend' / 'templates'

# Identifiers que sabemos serem expostos intencionalmente ao global por
# múltiplos ficheiros (caso o pattern legítimo apareça). Por agora vazio.
EXPECTED_SHARED_GLOBALS: set[str] = set()


# Pattern do Django ``{% static 'js/...' %}`` dentro de ``<script src=...>``.
SCRIPT_TAG_RE = re.compile(
    r"""<script\s+[^>]*src=["']\s*\{%\s*static\s+["'](?P<path>[^"']+)["']\s*%\}\s*["']""",
    re.IGNORECASE,
)

# Top-level declarations. Detectamos pela combinação:
#   1) depth de chavetas == 0 no início da linha
#   2) padrão de declaração no inicio da linha (sem indentação)
DECL_SIMPLE_RE = re.compile(
    r'^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=',
)
DECL_DESTRUCTURE_RE = re.compile(
    r'^(?:const|let|var)\s+\{([^}]+)\}\s*=',
)
DECL_FUNCTION_RE = re.compile(
    r'^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(',
)
DECL_CLASS_RE = re.compile(
    r'^class\s+([A-Za-z_$][\w$]*)',
)
DESTRUCTURED_NAME_RE = re.compile(r'([A-Za-z_$][\w$]*)(?:\s*:\s*[A-Za-z_$][\w$]*)?')


def _strip_comments_and_strings(source: str) -> str:
    """Remove cordas e comentários simples para tornar a contagem de chavetas fiável.

    Não é um parser completo — backticks com expressões `${...}` aninhadas são
    aproximadas. Suficiente para os padrões usados no projecto (sem template
    literals multi-linha com chavetas).
    """
    out = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ''
        # Line comment.
        if c == '/' and nxt == '/':
            while i < n and source[i] != '\n':
                i += 1
            continue
        # Block comment.
        if c == '/' and nxt == '*':
            i += 2
            while i < n - 1 and not (source[i] == '*' and source[i + 1] == '/'):
                if source[i] == '\n':
                    out.append('\n')
                i += 1
            i += 2
            continue
        # String literals (single, double, backtick) — substituir por placeholder
        # do mesmo tipo, preservando newlines para que o número de linhas
        # permaneça consistente. Não distinguimos backtick aninhado — boa
        # aproximação para o que escrevemos.
        if c in ('"', "'", '`'):
            quote = c
            i += 1
            while i < n and source[i] != quote:
                if source[i] == '\\' and i + 1 < n:
                    if source[i + 1] == '\n':
                        out.append('\n')
                    i += 2
                    continue
                if source[i] == '\n':
                    out.append('\n')
                i += 1
            i += 1  # consume closing quote
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def extract_top_level_identifiers(js_source: str) -> set[str]:
    """Devolve o conjunto de identifiers declarados no escopo global do script.

    Considera ``const``, ``let``, ``var``, ``function``, ``class`` declarados
    quando a profundidade de chavetas é zero. Suporta destructuring
    (``const { A, B } = ...``). Ignora ``window.X = ...`` (essa atribuição
    polui o global intencionalmente mas não é um *binding* lexical e não
    causa o erro de redeclaração).
    """
    clean = _strip_comments_and_strings(js_source)
    lines = clean.split('\n')

    identifiers: set[str] = set()
    depth = 0  # nível de chavetas
    paren_depth = 0  # nível de parêntesis

    for raw in lines:
        # Detectar declarações apenas se entramos numa linha em depth==0,
        # antes de qualquer chaveta aberta nessa linha.
        if depth == 0 and paren_depth == 0:
            stripped = raw.lstrip()
            if stripped and raw[:len(raw) - len(stripped)] == '':
                m = DECL_SIMPLE_RE.match(stripped)
                if m:
                    identifiers.add(m.group(1))
                else:
                    md = DECL_DESTRUCTURE_RE.match(stripped)
                    if md:
                        for name_match in DESTRUCTURED_NAME_RE.finditer(md.group(1)):
                            identifiers.add(name_match.group(1))
                    else:
                        mf = DECL_FUNCTION_RE.match(stripped)
                        if mf:
                            identifiers.add(mf.group(1))
                        else:
                            mc = DECL_CLASS_RE.match(stripped)
                            if mc:
                                identifiers.add(mc.group(1))

        # Atualizar profundidade no fim da linha.
        for ch in raw:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            elif ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth -= 1

    return identifiers


def scripts_loaded_by_template(template_path: Path) -> list[str]:
    """Lista os caminhos estáticos JS referenciados no template (na ordem)."""
    html = template_path.read_text(encoding='utf-8')
    return [m.group('path') for m in SCRIPT_TAG_RE.finditer(html)]


def _resolve_static_js(static_path: str) -> Path | None:
    """Mapeia ``js/foo.js`` → ``<frontend>/static/js/foo.js``. Devolve None se
    o caminho não começa por ``js/``.
    """
    if not static_path.startswith('js/'):
        return None
    relative = static_path[len('js/'):]
    candidate = STATIC_JS_ROOT / relative
    return candidate if candidate.exists() else None


class TopLevelIdentifierParserTest(SimpleTestCase):
    """Smoke test ao parser: confirma que reconhece os padrões usados no projecto."""

    def test_simple_const(self):
        self.assertEqual(
            extract_top_level_identifiers("const FOO = 1;\n"),
            {'FOO'},
        )

    def test_destructure(self):
        self.assertEqual(
            extract_top_level_identifiers("const { A, B, C } = obj;\n"),
            {'A', 'B', 'C'},
        )

    def test_destructure_with_rename(self):
        self.assertEqual(
            extract_top_level_identifiers("const { A: a, B } = obj;\n"),
            {'A', 'B'},
        )

    def test_function(self):
        self.assertEqual(
            extract_top_level_identifiers("function bar() {}\n"),
            {'bar'},
        )

    def test_ignores_window_assignment(self):
        self.assertEqual(
            extract_top_level_identifiers("window.Foo = (() => ({}))();\n"),
            set(),
        )

    def test_ignores_iife_body(self):
        src = (
            "(() => {\n"
            "  const INNER = 1;\n"
            "  function helper() { const X = 2; }\n"
            "})();\n"
        )
        self.assertEqual(extract_top_level_identifiers(src), set())

    def test_const_inside_function_not_top_level(self):
        src = (
            "function outer() {\n"
            "  const INSIDE = 1;\n"
            "}\n"
            "const OUTSIDE = 2;\n"
        )
        self.assertEqual(
            extract_top_level_identifiers(src),
            {'outer', 'OUTSIDE'},
        )

    def test_strings_with_braces_dont_break_depth(self):
        src = (
            "const A = 'hello { world }';\n"
            "const B = \"more } stuff {\";\n"
            "const C = 1;\n"
        )
        self.assertEqual(
            extract_top_level_identifiers(src),
            {'A', 'B', 'C'},
        )


class TemplateScriptCollisionTest(SimpleTestCase):
    """Para cada template, garante zero colisões entre os scripts carregados."""

    def _all_templates(self) -> list[Path]:
        return sorted(p for p in TEMPLATES_ROOT.glob('*.html')
                      if not p.name.startswith('_'))

    def test_no_global_identifier_collisions(self):
        problems: list[str] = []
        for template in self._all_templates():
            scripts = scripts_loaded_by_template(template)
            by_id: dict[str, list[str]] = {}
            for static_path in scripts:
                resolved = _resolve_static_js(static_path)
                if resolved is None:
                    continue
                source = resolved.read_text(encoding='utf-8')
                ids = extract_top_level_identifiers(source)
                for name in ids:
                    by_id.setdefault(name, []).append(static_path)

            for name, sources in by_id.items():
                if len(sources) > 1 and name not in EXPECTED_SHARED_GLOBALS:
                    problems.append(
                        f'{template.name}: identifier "{name}" declarado por '
                        f'múltiplos scripts: {", ".join(sources)}'
                    )

        self.assertEqual(
            problems, [],
            msg='Conflitos de namespace global JavaScript detectados:\n  '
                + '\n  '.join(problems),
        )

    def test_custody_states_helper_doesnt_leak_to_global(self):
        """O helper custody_states.js deve expor APENAS window.CustodyStates."""
        path = STATIC_JS_ROOT / 'custody_states.js'
        ids = extract_top_level_identifiers(path.read_text(encoding='utf-8'))
        self.assertEqual(
            ids, set(),
            msg=f'custody_states.js declara identifiers no global: {ids}. '
                'Deve estar tudo encapsulado num IIFE e expor só '
                'window.CustodyStates.',
        )

    def test_transition_modal_helper_doesnt_leak_to_global(self):
        path = STATIC_JS_ROOT / 'transition_modal.js'
        ids = extract_top_level_identifiers(path.read_text(encoding='utf-8'))
        self.assertEqual(
            ids, set(),
            msg=f'transition_modal.js declara identifiers no global: {ids}. '
                'Deve estar tudo encapsulado num IIFE.',
        )
