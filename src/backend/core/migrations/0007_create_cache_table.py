"""
Wave 2a — Cria a tabela `forensiq_cache` para DatabaseCache (ADR-0008).

Usa `manage.py createcachetable` para gerar a tabela com o schema
canónico do Django (cache_key, value, expires). Forward idempotente
(createcachetable é no-op se a tabela existir). Reverse dropa a tabela
com SQL directo (o Django não expõe um dropcachetable).

Referência: ADR-0008 — Estratégia de Cache para Lookups Externos (IMEI, VIN).
"""

from django.core.management import call_command
from django.db import migrations


CACHE_TABLE_NAME = 'forensiq_cache'

# SQL estático — nome da tabela é uma constante literal definida neste
# ficheiro, não provém de input externo. Identificador já citado para
# PostgreSQL (compatível com SQLite em CI).
_DROP_CACHE_TABLE_SQL = 'DROP TABLE IF EXISTS "forensiq_cache"'


def create_cache_table(apps, schema_editor):
    """Cria a tabela de cache via management command do Django."""
    # `createcachetable` infere o nome da tabela a partir de settings.CACHES.
    # Em modo fresh-install, o nome é lido directamente. Como redundância,
    # passa-se o nome explícito para evitar dependência de settings já
    # terem o bloco CACHES configurado no momento da migração.
    call_command('createcachetable', CACHE_TABLE_NAME, verbosity=0)


def drop_cache_table(apps, schema_editor):
    """Remove a tabela de cache com SQL literal (nome fixo)."""
    schema_editor.execute(_DROP_CACHE_TABLE_SQL)  # nosemgrep: python.django.security.injection.raw-query.raw-query


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_evidence_taxonomy_hierarchy'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, reverse_code=drop_cache_table),
    ]
