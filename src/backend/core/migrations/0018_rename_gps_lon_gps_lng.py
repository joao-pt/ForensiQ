"""T02 — convenção de nomes GPS: ``gps_lon`` -> ``gps_lng`` (ADR-0013).

Renomeia o campo ``gps_lon`` para ``gps_lng`` em ``Occurrence`` e ``Evidence``.
Substituição pura, sem alias nem retrocompatibilidade (princípio da Fase 2).

Invariantes preservados:

- **integrity_hash de Evidence** é invariante: a fórmula usa o *valor* do campo
  (``self.gps_lng``), não o seu nome — o hash de uma prova não muda com o rename.
- **Triggers de imutabilidade** (0002/0013) actuam ao nível da *linha* e não
  referenciam o nome da coluna; o ``RENAME COLUMN`` não os afecta.

Em Postgres actualiza ainda a função *documental* ``forensiq_evidence_immutable_fields()``
(criada em 0008) para listar ``gps_lng`` em vez de ``gps_lon`` — não é chamada
pelo trigger, mas mantém-se coerente. No-op em SQLite (testes).
"""

from django.db import migrations


def _immutable_fields_sql(longitude_field):
    return f"""
    CREATE OR REPLACE FUNCTION forensiq_evidence_immutable_fields()
    RETURNS TEXT[] AS $$
    BEGIN
        RETURN ARRAY[
            'occurrence_id',
            'type',
            'parent_evidence_id',
            'description',
            'photo',
            'gps_lat',
            '{longitude_field}',
            'timestamp_seizure',
            'serial_number',
            'agent_id',
            'integrity_hash',
            'type_specific_data',
            'external_lookup_snapshot',
            'external_lookup_source',
            'external_lookup_at',
            'created_at'
        ];
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    """


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(_immutable_fields_sql('gps_lng'))


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(_immutable_fields_sql('gps_lon'))


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_alter_auditlog_options_auditlog_sequence'),
    ]

    operations = [
        migrations.RenameField('occurrence', 'gps_lon', 'gps_lng'),
        migrations.RenameField('evidence', 'gps_lon', 'gps_lng'),
        migrations.RunPython(forward, reverse_code=reverse),
    ]
