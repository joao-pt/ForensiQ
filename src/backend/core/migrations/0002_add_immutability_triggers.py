"""
Migração: triggers PostgreSQL para imutabilidade de Evidence e ChainOfCustody.

Garante que mesmo com acesso directo à base de dados, registos de prova
e cadeia de custódia não podem ser alterados ou eliminados.
Conformidade: ISO/IEC 27037 § 5.3.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        # --- Evidence: bloquear UPDATE e DELETE ---
        migrations.RunSQL(
            sql="""
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
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS trg_evidence_no_update ON core_evidence;
                DROP TRIGGER IF EXISTS trg_evidence_no_delete ON core_evidence;
                DROP FUNCTION IF EXISTS prevent_evidence_modification();
            """,
        ),

        # --- ChainOfCustody: bloquear UPDATE e DELETE ---
        migrations.RunSQL(
            sql="""
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
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS trg_custody_no_update ON core_chainofcustody;
                DROP TRIGGER IF EXISTS trg_custody_no_delete ON core_chainofcustody;
                DROP FUNCTION IF EXISTS prevent_custody_modification();
            """,
        ),

        # --- DigitalDevice: bloquear UPDATE e DELETE ---
        migrations.RunSQL(
            sql="""
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
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS trg_device_no_update ON core_digitaldevice;
                DROP TRIGGER IF EXISTS trg_device_no_delete ON core_digitaldevice;
                DROP FUNCTION IF EXISTS prevent_device_modification();
            """,
        ),
    ]
