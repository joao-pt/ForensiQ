"""Higiene de templates: comentários ``{# #}`` têm de caber numa só linha.

O Django não reconhece um comentário ``{# ... #}`` que atravesse uma quebra de
linha — o lexer de tags não cruza o ``\\n`` —, por isso um comentário multi-linha
**renderiza como texto literal** no output (ex.: aparecia no menu lateral). Este
teste varre os templates e falha se algum comentário abrir ``{#`` sem fechar
``#}`` na mesma linha física. Correção: uma linha por comentário.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# ``{#`` que NÃO fecha ``#}`` antes do fim da linha → comentário multi-linha.
# Espelha o lexer do Django (``{#.*?#}`` sem DOTALL): se não fecha na linha, o
# Django não o trata como comentário.
_OPEN_UNCLOSED = re.compile(r'\{#(?:(?!#\}).)*$', re.MULTILINE)


class ShellAssetsContractTest(SimpleTestCase):
    """Contrato casca↔service worker (auditoria D118): cada asset da lista
    única SHELL_ASSETS tem de ser de facto referenciado por base.html — se a
    casca deixar de carregar (ou renomear) um ficheiro, o precache do sw.js
    não pode continuar a apontar-lhe às cegas."""

    def test_base_referencia_todos_os_shell_assets(self):
        from core.context_processors import SHELL_ASSETS

        roots = [Path(d) for d in settings.TEMPLATES[0]['DIRS']]
        base = next(r / 'base.html' for r in roots if (r / 'base.html').exists())
        src = base.read_text(encoding='utf-8')
        missing = [a for a in SHELL_ASSETS if a not in src]
        self.assertEqual(
            missing,
            [],
            'Assets do precache (SHELL_ASSETS) sem referência em base.html: '
            f'{missing} — atualizar a lista única em core/context_processors.py.',
        )


class TemplateCommentHygieneTest(SimpleTestCase):
    def test_sem_comentarios_multilinha(self):
        roots = [Path(d) for d in settings.TEMPLATES[0]['DIRS']]
        offenders = []
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob('*.html')):
                text = path.read_text(encoding='utf-8')
                for m in _OPEN_UNCLOSED.finditer(text):
                    line = text.count('\n', 0, m.start()) + 1
                    offenders.append(f'{path}:{line}')
        self.assertEqual(
            offenders,
            [],
            'Comentários {# #} multi-linha renderizam como texto literal no '
            'output; usar uma linha por comentário. Ofensores:\n'
            + '\n'.join(offenders),
        )
