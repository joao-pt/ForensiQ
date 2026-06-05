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


def lens_nav(request):
    """Injecta a lente de acesso ativa e as lentes disponíveis na casca.

    A "lente" (consolas por papel — ADR-0017) é o eixo de leitura ativo:
    ``mine`` (minhas ocorrências), ``custody`` (à guarda da instituição, item-level)
    ou ``all`` (leitura total). É resolvida exatamente como nas views
    (:func:`core.access.resolve_lens`), pelo que a casca e o conteúdo concordam.

    Livre de ORM — lê só ``profile``/``clearance``/``is_staff`` de ``request.user``
    — pelo que é barato em qualquer página e devolve vazio a não-autenticados (a
    casca esconde os chips quando há menos de duas lentes).
    """
    from core import access

    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {}
    options = access.available_lenses(user)
    active = access.resolve_lens(user, request.GET.get('lens'))
    labels = {
        access.Lens.MINE: 'Minhas ocorrências',
        access.Lens.CUSTODY: 'À guarda da instituição',
        access.Lens.ALL: 'Tudo',
    }
    return {
        'lens': active,
        # Sufixo de querystring para os links da casca preservarem a lente ativa
        # (ex.: href="/evidences/{{ lens_qs }}").
        'lens_qs': f'?lens={active}',
        'lens_options': (
            [{'key': k, 'label': labels[k], 'is_active': k == active} for k in options]
            if len(options) >= 2
            else []
        ),
    }
