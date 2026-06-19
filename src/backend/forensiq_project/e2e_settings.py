"""
ForensiQ — Configurações para testes E2E de browser (Playwright + live_server).

Herda de ``test_settings`` (PostgreSQL, DEBUG=True, throttling desligado) e ajusta o
estritamente necessário para servir a aplicação REAL a um browser headless:

  * **Estáticos do frontend repostos** — ``test_settings`` faz
    ``STATICFILES_DIRS = []`` (irrelevante para testes de unidade, mas fatal
    para um browser, que precisa do CSS/JS para renderizar e interagir);
  * **PostgreSQL** (herdado de ``test_settings``) — o ``live_server`` corre
    noutra thread e vê os dados porque o PostgreSQL é um servidor partilhado
    (``transactional_db``);
  * **MEDIA_ROOT isolado** — para os uploads de fotografia dos testes.

Os cookies JWT já saem não-``Secure`` porque ``DEBUG=True`` (ver ``core.auth``),
logo o browser aceita-os sobre ``http://localhost``.

Utilização:
    pytest e2e/ --ds=forensiq_project.e2e_settings
"""

import tempfile as _tempfile
from pathlib import Path as _Path

from .settings import STATICFILES_DIRS as _PROD_STATICFILES_DIRS
from .test_settings import *  # noqa: F401,F403

# 1) Estáticos do frontend — REPOSTOS (test_settings esvazia-os) a partir da
#    declaração de produção (auditoria D116), em vez de re-escrever o caminho.
STATICFILES_DIRS = _PROD_STATICFILES_DIRS

# 2) Base de dados: PostgreSQL herdado de ``test_settings`` (paridade total com
#    produção; projecto PostgreSQL-only). O ``live_server`` corre noutra thread
#    mas vê os dados porque o PostgreSQL é um servidor partilhado (ao contrário
#    do SQLite ``:memory:``, que era por-ligação). Não se redefine DATABASES.

# 3) Media isolada (uploads de fotografia dos testes E2E).
MEDIA_ROOT = str(_Path(_tempfile.gettempdir()) / 'forensiq_e2e_media')

# 4) Geocodificação inversa DESLIGADA: a vista ReverseGeocodeView faz short-circuit
#    quando a URL é vazia (devolve morada vazia), sem chamada externa ao Nominatim.
#    Mantém o e2e offline e determinístico (lat/lng vêm da geolocalização injetada).
NOMINATIM_REVERSE_URL = ''
