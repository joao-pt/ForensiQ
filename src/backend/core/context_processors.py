"""
ForensiQ — Context processors do frontend.

Expõem metadata da aplicação aos templates (footer técnico, header),
sem cada view ter de adicionar manualmente ao contexto.

Para activar, registar em ``settings.TEMPLATES[0]['OPTIONS']['context_processors']``.
"""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _build_info():
    """Calcula metadata de build/runtime uma única vez por processo.

    Fontes (com fallback):
    - ``FQ_BUILD_LABEL`` (env)  — etiqueta humana (ex.: "Sem.13", "v0.3.0")
    - ``FLY_RELEASE_VERSION``   — versão Fly (numérica auto-incremental)
    - ``GIT_COMMIT`` / ``FLY_IMAGE_REF``  — hash curto do commit (8 chars)
    - ``FLY_REGION``            — região Fly (ex.: ``fra``)
    """
    commit = os.environ.get('GIT_COMMIT') or os.environ.get('FLY_RELEASE_VERSION') or 'dev'
    # FLY_RELEASE_VERSION é numérico curto; GIT_COMMIT é hash. Trunca a 8.
    commit_short = commit[:8] if commit else 'dev'

    region = os.environ.get('FLY_REGION', 'local')
    build_label = os.environ.get('FQ_BUILD_LABEL', 'main')

    return {
        'app_build_label': build_label,
        'app_commit': commit_short,
        'app_region': region,
        'app_csp_label': 'CSP strict',
    }


def app_metadata(request):
    """Injecta metadata de build no contexto de cada template."""
    return _build_info()
