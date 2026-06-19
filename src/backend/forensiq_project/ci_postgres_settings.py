"""DEPRECADO — alias de ``test_settings``.

Com o projecto PostgreSQL-only, ``test_settings`` já corre contra PostgreSQL
(via ``DATABASE_URL``); este módulo, que existia apenas para forçar PostgreSQL
no antigo job de triggers do CI (entretanto fundido no job principal), deixou de
ser necessário. Mantém-se como alias, para não partir referências antigas do
tipo ``--settings=forensiq_project.ci_postgres_settings``.
"""

from .test_settings import *  # noqa: F401, F403
