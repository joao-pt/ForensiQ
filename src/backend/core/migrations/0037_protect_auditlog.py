"""
Imutabilidade de AuditLog ao nível PostgreSQL (apenas UPDATE).

O trilho de auditoria (core_auditlog) é append-only quanto a *modificações*:
a classe AppendOnlyModel e o override de AuditLog.save() recusam qualquer
UPDATE na camada Django. Faltava a 2.ª linha de defesa que Evidence,
ChainOfCustody e DigitalDevice (migration 0002) e Occurrence (migration 0013)
possuem: um trigger que rejeita a alteração mesmo perante acesso SQL directo.
Sem ele, o próprio registo que prova "quem viu o quê" ficava exposto a um
insider-DBA que reescrevesse linhas existentes (trocar user_id/resource_id
para apagar o rasto de um acesso) — assimetria face às restantes tabelas.

Esta migration cria a função plpgsql prevent_auditlog_modification() e o
trigger BEFORE UPDATE trg_auditlog_no_update em core_auditlog.

Porque é que NÃO há trigger BEFORE DELETE (ao contrário de 0002/0013)
---------------------------------------------------------------------
A tabela core_auditlog NÃO é delete-never. O RGPD Art. 5(1)(e) (limitação
da conservação) obriga a expurgar logs de acesso (IP + utilizador + recurso)
findo o período de retenção. O management command `purge_audit_logs` faz
exactamente isso semanalmente via `AuditLog.objects.filter(...).delete()`
(DELETE SQL directo, sanccionado e auditado por uma entrada AUDIT_PURGE).
Um trigger BEFORE DELETE seria no-op em SQLite (os testes passariam) mas
bloquearia esse expurgo em PostgreSQL de produção — falha silenciosa em CI,
fatal em produção, e violaria a conformidade RGPD. Por isso o DELETE é
deixado deliberadamente fora do trigger:

  - alteração de registos existentes (tampering) -> bloqueada (este trigger);
  - delete acidental por instância -> bloqueado por AppendOnlyModel.delete();
  - expurgo de retenção em lote -> permitido, e rastreado por AUDIT_PURGE;
  - delete avulso por insider-DBA -> detectável por lacuna na `sequence`
    (monótona e única), e mitigado pela cifra at-rest do Neon.

Operação no-op em SQLite (testes) — triggers só existem em PostgreSQL.

Limitação conhecida (igual a 0002/0013): triggers BEFORE podem ser
desactivados via `SET session_replication_role = 'replica'`, comando que
em Neon.tech exige privilégios de superuser inacessíveis ao runtime Django
(role `forensiq_app`). O vector residual é insider-DBA, não ataque remoto.

Referência: ISO/IEC 27037 — preservação da integridade do trilho de auditoria;
RGPD Art. 5(1)(e) — limitação da conservação (justifica a ausência do DELETE).
"""

from django.db import migrations


AUDITLOG_FORWARD_SQL = """
    CREATE OR REPLACE FUNCTION prevent_auditlog_modification()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'Registos de auditoria são imutáveis (ISO/IEC 27037). '
            'Operação bloqueada: %', TG_OP;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_auditlog_no_update
        BEFORE UPDATE ON core_auditlog
        FOR EACH ROW
        EXECUTE FUNCTION prevent_auditlog_modification();
"""

AUDITLOG_REVERSE_SQL = """
    DROP TRIGGER IF EXISTS trg_auditlog_no_update ON core_auditlog;
    DROP FUNCTION IF EXISTS prevent_auditlog_modification();
"""


def apply_triggers(apps, schema_editor):
    """Aplica o trigger apenas em PostgreSQL; no-op noutros vendors."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(AUDITLOG_FORWARD_SQL)


def remove_triggers(apps, schema_editor):
    """Remove o trigger apenas em PostgreSQL; no-op noutros vendors."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(AUDITLOG_REVERSE_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_guiatransporte'),
    ]

    operations = [
        migrations.RunPython(apply_triggers, remove_triggers),
    ]
