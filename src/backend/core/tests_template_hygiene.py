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
