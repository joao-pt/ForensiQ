"""
ForensiQ — Testes estruturais às referências `{% static '...' %}` em templates.

Apanha regressões em que um template referencia um ficheiro estático
inexistente. Em desenvolvimento ou em testes (com `StaticFilesStorage`)
isto passa silenciosamente e o template renderiza com URL quebrado.
Em produção, com `ManifestStaticFilesStorage` (WhiteNoise), o `{% static %}`
levanta ``ValueError: Missing staticfiles manifest entry for 'X'`` durante
o render e a página devolve HTTP 500.

Incidente concreto que motivou este teste (2026-05-28):

  `public_verify.html` e `public_verify_notfound.html` (ADR-0012 Vaga 1)
  referenciavam ``{% static 'css/base.css' %}`` — ficheiro que não existe
  (o nome correcto é ``css/main.css``). A suite de testes passava, mas em
  produção qualquer scan do QR por utilizador não-autenticado dava 500.

Cobertura:
- Cada `{% static '<path>' %}` em qualquer template aponta para um
  ficheiro real em ``STATICFILES_DIRS`` (ou ``STATIC_ROOT``).
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES_ROOT = Path(settings.BASE_DIR).parent / 'frontend' / 'templates'

# Resolução canónica do directório de estáticos. Não usamos
# ``settings.STATICFILES_DIRS`` porque ``test_settings.py`` define-o como
# lista vazia para evitar warnings, o que mascararia o problema. A path
# corresponde ao directório real onde vivem os ficheiros estáticos do
# projecto (alinhado com ``STATICFILES_DIRS`` em produção).
STATIC_ROOTS = [Path(settings.BASE_DIR).parent / 'frontend' / 'static']

STATIC_REF_RE = re.compile(r"""\{%\s*static\s+["']([^"']+)["']\s*%\}""")


def _resolve(rel_path: str) -> Path | None:
    for root in STATIC_ROOTS:
        candidate = root / rel_path
        if candidate.exists():
            return candidate
    return None


class TemplateStaticReferencesTest(SimpleTestCase):
    def test_todos_os_static_apontam_para_ficheiros_existentes(self):
        if not TEMPLATES_ROOT.exists():
            self.skipTest(f'Diretório de templates não encontrado: {TEMPLATES_ROOT}')

        missing: list[tuple[str, str]] = []
        for tpl in TEMPLATES_ROOT.rglob('*.html'):
            source = tpl.read_text(encoding='utf-8')
            for match in STATIC_REF_RE.finditer(source):
                rel = match.group(1)
                if _resolve(rel) is None:
                    missing.append((tpl.relative_to(TEMPLATES_ROOT).as_posix(), rel))

        if missing:
            details = '\n'.join(f'  - {tpl}: static="{path}"' for tpl, path in missing)
            self.fail(
                'Templates referenciam ficheiros estáticos inexistentes '
                '(rebenta em produção com ManifestStaticFilesStorage):\n' + details
            )
