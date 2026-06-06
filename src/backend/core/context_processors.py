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
    """Injecta a zona de CONSOLA ativa e as zonas disponíveis na casca.

    A consola (duas zonas — substitui a antiga lente por papel) é o working-set de
    leitura ativo: ``mine`` ("as minhas", âmbito de caso) ou ``institution``
    ("Instituição", processo inteiro da instituição). É resolvida exatamente como
    nas views (:func:`core.access.console_mode`, com memória de sessão), pelo que a
    casca e o conteúdo concordam.

    Livre de ORM para a resolução da zona (lê ``profile``/``clearance``/``is_staff``
    e a memória de sessão), barato em qualquer página; ``available_lenses`` faz uma
    leitura leve das pertenças. Devolve vazio a não-autenticados (a casca esconde o
    seletor quando há menos de duas zonas).
    """
    from core import access

    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {}
    options = access.available_lenses(user)
    active = access.console_mode(request, user)
    labels = {
        access.Lens.MINE: access.mine_label(user),
        access.Lens.INSTITUTION: 'Instituição',
    }
    return {
        'lens': active,
        # ``console_mode`` é o eixo da banda/cor da casca (CSS [data-console-mode]).
        'console_mode': active,
        # Sufixo de querystring para os links da casca preservarem a zona ativa
        # (ex.: href="/evidences/{{ lens_qs }}").
        'lens_qs': f'?lens={active}',
        'lens_options': (
            [{'key': k, 'label': labels[k], 'is_active': k == active} for k in options]
            if len(options) >= 2
            else []
        ),
    }


def inbound_nav(request):
    """Injecta a contagem de "prova a chegar" para o badge da casca (ADR-0016 v2).

    Surface leve de :func:`core.access.scope_inbound_transit`: um único COUNT por
    request e SÓ para membros de instituição (a caixa-de-entrada é institucional —
    chaveia no DESTINO da prova). Devolve vazio a não-autenticados e a quem não
    pertence a nenhuma instituição (sem badge nem link na sidebar). Fonte única da
    regra em ``access`` — aqui não se duplica o filtro.
    """
    from core import access

    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {}
    if not access._active_institution_ids(user):
        return {}  # a zona "prova a chegar" só existe para membros
    return {'inbound_member': True, 'inbound_count': access.scope_inbound_transit(user).count()}
