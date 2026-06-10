"""
Helpers reutilizáveis para os testes E2E — "page objects" leves.

Encapsulam interações com seletores frágeis (a cascata de crime carregada por
JS, esperas por opções assíncronas) para os testes lerem como prosa.
"""

import re


def select_crime(page, cat_id, sub_id, type_id):
    """
    Conduz a cascata de crime N1→N2→N3 no formulário de nova ocorrência.

    As subcategorias e tipos são carregados por ``crime-cascade.js`` via fetch
    (option.value = id), por isso esperamos a opção aparecer antes de a escolher.
    """
    # `state="attached"`: um <option> dentro de <select> nunca é "visible" para o
    # Playwright; basta existir no DOM (foi adicionado pelo fetch da cascata).
    page.select_option("#f-crime-cat", value=str(cat_id))
    page.wait_for_selector(
        f"#f-crime-sub:not([disabled]) option[value='{sub_id}']", state="attached"
    )
    page.select_option("#f-crime-sub", value=str(sub_id))
    page.wait_for_selector(
        f"#f-crime:not([disabled]) option[value='{type_id}']", state="attached"
    )
    page.select_option("#f-crime", value=str(type_id))


def is_occurrence_detail(url):
    """True se a URL é a página de detalhe de uma ocorrência (/occurrences/<n>/)."""
    return bool(re.search(r"/occurrences/\d+/$", url))


def is_evidence_detail(url):
    """True se a URL é a página de detalhe de uma evidência (/evidences/<n>/)."""
    return bool(re.search(r"/evidences/\d+/$", url))


def app_pages(occ_id, ev_id):
    """Rotas autenticadas da app — lista CANÓNICA única (auditoria D114).

    Cada suite (smoke, axe, CSP, performance) consome-a inteira ou filtra
    pelos marcadores ``leaflet``/``htmx`` — uma página nova entra AQUI e fica
    coberta por todos os varrimentos de uma vez (antes eram 4 listas com drift).
    """
    return {
        'dashboard': {'path': '/dashboard/', 'leaflet': True, 'htmx': True},
        'occurrences': {'path': '/occurrences/', 'leaflet': True, 'htmx': True},
        'occurrence_new': {'path': '/occurrences/new/'},
        'occurrence_detail': {'path': f'/occurrences/{occ_id}/', 'htmx': True},
        'intake': {'path': f'/occurrences/{occ_id}/intake/'},
        'evidences': {'path': '/evidences/', 'leaflet': True, 'htmx': True},
        'evidence_new': {'path': '/evidences/new/'},
        'evidence_detail': {'path': f'/evidences/{ev_id}/', 'htmx': True},
        'custody': {'path': f'/evidences/{ev_id}/custody/', 'htmx': True},
        'custodies': {'path': '/custodies/', 'leaflet': True, 'htmx': True},
        'reports': {'path': '/reports/', 'htmx': True},
        'stats': {'path': '/stats/'},
        'audit': {'path': '/audit/investigation/'},
        'settings': {'path': '/settings/'},
        'verificacoes': {'path': '/verificacoes/', 'htmx': True},
    }
