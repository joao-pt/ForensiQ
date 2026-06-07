"""
ForensiQ — Configurações para testes E2E de browser (Playwright + live_server).

Herda de ``test_settings`` (SQLite, DEBUG=True, throttling desligado) e ajusta o
estritamente necessário para servir a aplicação REAL a um browser headless:

  * **Estáticos do frontend repostos** — ``test_settings`` faz
    ``STATICFILES_DIRS = []`` (irrelevante para testes de unidade, mas fatal
    para um browser, que precisa do CSS/JS para renderizar e interagir);
  * **SQLite em ficheiro** (não ``:memory:``) — o ``live_server`` corre noutra
    thread e tem de ver os dados que os factories cometem (``transactional_db``);
  * **MEDIA_ROOT isolado** — para os uploads de fotografia dos testes.

Os cookies JWT já saem não-``Secure`` porque ``DEBUG=True`` (ver ``core.auth``),
logo o browser aceita-os sobre ``http://localhost``.

Utilização:
    pytest e2e/ --ds=forensiq_project.e2e_settings
"""

import tempfile as _tempfile
from pathlib import Path as _Path

from .settings import BASE_DIR  # noqa: F401
from .test_settings import *  # noqa: F401,F403

# 1) Estáticos do frontend — REPOSTOS (test_settings esvazia-os).
STATICFILES_DIRS = [
    BASE_DIR.parent / 'frontend' / 'static',  # src/frontend/static/
]

# 2) Base de dados em ficheiro, partilhada entre a thread de teste e a do
#    servidor live. O :memory: do test_settings não é fiável com o live_server.
_E2E_DB = str(_Path(_tempfile.gettempdir()) / 'forensiq_e2e.sqlite3')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _E2E_DB,
        'TEST': {'NAME': _E2E_DB},
    }
}

# 3) Media isolada (uploads de fotografia dos testes E2E).
MEDIA_ROOT = str(_Path(_tempfile.gettempdir()) / 'forensiq_e2e_media')
