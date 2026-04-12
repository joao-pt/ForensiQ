"""
Migração: triggers PostgreSQL para imutabilidade de Evidence e ChainOfCustody.

Garante que mesmo com acesso directo à base de dados, registos de prova
e cadeia de custódia não podem ser alterados ou eliminados.
Conformidade: ISO/IEC 27037 § 5.3.
"""

from django.db import connection, migrations


def is_postgresql():
    """Verifica se estamos a usar PostgreSQL (triggers não existem em SQLite)."""
    return connection.vendor == 'postgresql'


def run_pg_sql(sql):
    """Executa SQL apenas em PostgreSQL; noop em SQLite (testes)."""
    def forward(apps, schema_editor):
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute(sql)

    return forward


def reverse_pg_sql(sql):
    """Reverso SQL apenas em PostgreSQL."""
    def backward(apps, schema_editor):
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute(sql)

    return backward


# SQL para triggers de imutabilidade
EVIDENCE_FORWARD_SQL = """
    CREATE OR REPLACE FUNCTION prevent_evidence_modification()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'Registos de evidência são imutáveis (ISO/IEC 27037). '
            'Operação bloqueada: %%', TG_OP;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_evidence_no_update
        BEFORE UPDATE ON core_evidence
        FOR EACH ROW
        EXECUTE FUNCTION prevent_evidence_modification();

    CREATE TRIGGER trg_evidence_no_delete
        BEFORE DELETE ON core_evidence
        FOR EACH ROW
        EXECUTE FUNCTION prevent_evidence_modification();
"""

EVIDENCE_REVERSE_SQL = """
    DROP TRIGGER IF EXISTS trg_evidence_no_update ON core_evidence;
    DROP TRIGGER IF EXISTS trg_evidence_no_delete ON core_evidence;
    DROP FUNCTION IF EXISTS prevent_evidence_modification();
"""

CUSTODY_FORWARD_SQL = """
    CREATE OR REPLACE FUNCTION prevent_custody_modification()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'Registos de cadeia de custódia são imutáveis (ISO/IEC 27037). '
            'Operação bloqueada: %%', TG_OP;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_custody_no_update
        BEFORE UPDATE ON core_chainofcustody
        FOR EACH ROW
        EXECUTE FUNCTION prevent_custody_modification();

    CREATE TRIGGER trg_custody_no_delete
        BEFORE DELETE ON core_chainofcustody
        FOR EACH ROW
        EXECUTE FUNCTION prevent_custody_modification();
"""

CUSTODY_REVERSE_SQL = """
    DROP TRIGGER IF EXISTS trg_custody_no_update ON core_chainofcustody;
    DROP TRIGGER IF EXISTS trg_custody_no_delete ON core_chainofcustody;
    DROP FUNCTION IF EXISTS prevent_custody_modification();
"""

DEVICE_FORWARD_SQL = """
    CREATE OR REPLACE FUNCTION prevent_device_modification()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'Registos de dispositivos digitais são imutáveis (ISO/IEC 27037). '
            'Operação bloqueada: %%', TG_OP;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_device_no_update
        BEFORE UPDATE ON core_digitaldevice
        FOR EACH ROW
        EXECUTE FUNCTION prevent_device_modification();

    CREATE TRIGGER trg_device_no_delete
        BEFORE DELETE ON core_digitaldevice
        FOR EACH ROW
        EXECUTE FUNCTION prevent_device_modification();
"""

DEVICE_REVERSE_SQL = """
    DROP TRIGGER IF EXISTS trg_device_no_update ON core_digitaldevice;
    DROP TRIGGER IF EXISTS trg_device_no_delete ON core_digitaldevice;
    DROP FUNCTION IF EXISTS prevent_device_modification();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        # --- Evidence: bloquear UPDATE e DELETE ---
        migrations.RunPython(
            run_pg_sql(EVIDENCE_FORWARD_SQL),
            reverse_pg_sql(EVIDENCE_REVERSE_SQL),
        ),

        # --- ChainOfCustody: bloquear UPDATE e DELETE ---
        migrations.RunPython(
            run_pg_sql(CUSTODY_FORWARD_SQL),
            reverse_pg_sql(CUSTODY_REVERSE_SQL),
        ),

        # --- DigitalDevice: bloquear UPDATE e DELETE ---
        migrations.RunPython(
            run_pg_sql(DEVICE_FORWARD_SQL),
            reverse_pg_sql(DEVICE_REVERSE_SQL),
        ),
    ]
