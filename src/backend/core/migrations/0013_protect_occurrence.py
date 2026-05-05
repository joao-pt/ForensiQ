"""
Wave 3 — Imutabilidade de Occurrence ao nível PostgreSQL.

A migration 0002 cobriu core_evidence, core_chainofcustody e core_digitaldevice
com triggers BEFORE UPDATE/DELETE que rejeitam qualquer modificação. Faltava
core_occurrence: como o integrity_hash da Evidence só incorpora occurrence_id
(um inteiro de FK), uma alteração silenciosa do número NUIPC, morada, GPS ou
data_time da Occurrence não invalidaria nenhum hash a jusante. Esta migration
fecha essa janela.

Operação no-op em SQLite (testes) — em PostgreSQL, cria a função
prevent_occurrence_modification() e dois triggers BEFORE UPDATE/DELETE em
core_occurrence, com a mesma forma das que protegem core_chainofcustody na
migration 0002.

Referência: ISO/IEC 27037 §5.4 — preservação da integridade de metadados
contextuais da prova (cena de crime).
"""

from django.db import migrations


OCCURRENCE_FORWARD_SQL = """
    CREATE OR REPLACE FUNCTION prevent_occurrence_modification()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'Registos de ocorrência são imutáveis (ISO/IEC 27037). '
            'Operação bloqueada: %', TG_OP;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_occurrence_no_update
        BEFORE UPDATE ON core_occurrence
        FOR EACH ROW
        EXECUTE FUNCTION prevent_occurrence_modification();

    CREATE TRIGGER trg_occurrence_no_delete
        BEFORE DELETE ON core_occurrence
        FOR EACH ROW
        EXECUTE FUNCTION prevent_occurrence_modification();
"""

OCCURRENCE_REVERSE_SQL = """
    DROP TRIGGER IF EXISTS trg_occurrence_no_update ON core_occurrence;
    DROP TRIGGER IF EXISTS trg_occurrence_no_delete ON core_occurrence;
    DROP FUNCTION IF EXISTS prevent_occurrence_modification();
"""


def apply_triggers(apps, schema_editor):
    """Aplica os triggers apenas em PostgreSQL; no-op noutros vendors."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(OCCURRENCE_FORWARD_SQL)


def remove_triggers(apps, schema_editor):
    """Remove os triggers apenas em PostgreSQL; no-op noutros vendors."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(OCCURRENCE_REVERSE_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_alter_auditlog_action'),
    ]

    operations = [
        migrations.RunPython(apply_triggers, remove_triggers),
    ]
