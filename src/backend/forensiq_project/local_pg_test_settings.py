"""Testes contra PostgreSQL LOCAL nativo (paridade com a produção: PG 17).

Mesmo motor, mesmos triggers de imutabilidade (migrações 0002/0013), mesmo
hashing de password — testes tão reais e rigorosos como contra a cloud, mas em
``localhost``. Vantagens face ao Neon.tech: rápido (sem latência de internet por
query) e NÃO toca na cloud nem consome compute do plano. A configuração de
produção (``settings.py`` → ``DATABASE_URL`` Neon) fica intacta para o dev server.

Uso::

    python manage.py test core \\
        --settings=forensiq_project.local_pg_test_settings --keepdb --noinput

A ligação vem do ambiente, com defaults para o PostgreSQL instalado localmente
(``postgres``/``postgres`` @ ``localhost:5432``). O Django cria/usa ``test_forensiq``.
"""

import os

from .settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        # Liga à BD de manutenção ``postgres`` (existe sempre) só para o runner
        # poder criar/destruir a BD de teste indicada em TEST.NAME.
        'NAME': os.environ.get('LOCAL_PG_NAME', 'postgres'),
        'USER': os.environ.get('LOCAL_PG_USER', 'postgres'),
        'PASSWORD': os.environ.get('LOCAL_PG_PASSWORD', 'postgres'),  # nosemgrep: BD local de teste
        'HOST': os.environ.get('LOCAL_PG_HOST', 'localhost'),
        'PORT': os.environ.get('LOCAL_PG_PORT', '5432'),
        'CONN_MAX_AGE': 0,
        'TEST': {'NAME': 'test_forensiq'},
    }
}
