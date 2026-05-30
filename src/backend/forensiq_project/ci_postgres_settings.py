"""Settings de CI para exercitar a 3.ª camada de imutabilidade (triggers PG).

Herda de :mod:`forensiq_project.test_settings` (sem WhiteNoise, sem
throttles, *storage* de estáticos sem manifesto) e apenas troca a base de
dados para o PostgreSQL do serviço de CI. Assim, os testes decorados com
``@skipUnless(connection.vendor == 'postgresql')`` — em particular
``core.tests.ImmutabilityTriggerTest`` — correm de facto contra os triggers
reais (``prevent_*_modification``), que não existem em SQLite e que de outro
modo só seriam exercitados em produção.

Utilização (ver ``.github/workflows/ci.yml``, job ``test-postgres``)::

    DATABASE_URL=postgres://... \\
        python manage.py test core.tests.ImmutabilityTriggerTest \\
        --settings=forensiq_project.ci_postgres_settings
"""

import os

import dj_database_url

from .test_settings import *  # noqa: F401, F403

# Única diferença face a test_settings: a BD aponta para o PostgreSQL do
# serviço de CI (e não SQLite em memória), para os triggers de imutabilidade
# instalados pelas migrations 0002/0013 serem realmente avaliados.
DATABASES = {
    'default': dj_database_url.config(default=os.environ['DATABASE_URL']),
}
