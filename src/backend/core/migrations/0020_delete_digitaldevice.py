"""
Migração: remoção do modelo DigitalDevice (T05 — princípio "sem legado").

O DigitalDevice foi subsumido por Evidence + type_specific_data (ADR-0010):
todo o dado que vivia no modelo (IMEI, marca, modelo, estado, etc.) passa a
ser representado como Evidence digital-first. Esta migração apaga a tabela
`core_digitaldevice`.

Nota sobre os triggers PostgreSQL (migração 0002): os triggers de
imutabilidade disparam em UPDATE/DELETE de LINHAS, não em DDL — `DROP TABLE`
(via DeleteModel) não é bloqueado. Mas a FUNÇÃO `prevent_device_modification`
e os triggers `trg_device_no_update` / `trg_device_no_delete` ficariam órfãos
em Postgres, pelo que os removemos explicitamente antes do DeleteModel.
Em SQLite (testes) não existem triggers — a RunPython é no-op.
"""

from django.db import migrations


def drop_device_triggers(apps, schema_editor):
    """Remove triggers + função de imutabilidade do DigitalDevice (só Postgres)."""
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            'DROP TRIGGER IF EXISTS trg_device_no_update ON core_digitaldevice;'
        )
        schema_editor.execute(
            'DROP TRIGGER IF EXISTS trg_device_no_delete ON core_digitaldevice;'
        )
        schema_editor.execute(
            'DROP FUNCTION IF EXISTS prevent_device_modification() CASCADE;'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_taxonomia_crimes_prioridade'),
    ]

    operations = [
        # 1. Limpar triggers/função órfãos em Postgres (no-op em SQLite).
        migrations.RunPython(drop_device_triggers, migrations.RunPython.noop),
        # 2. Apagar a tabela do modelo.
        migrations.DeleteModel(name='DigitalDevice'),
    ]
