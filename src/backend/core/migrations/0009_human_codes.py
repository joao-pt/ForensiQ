"""
Adiciona códigos humanos ANO-TIPO-SEQ a Occurrence, Evidence e ChainOfCustody.

- Occurrence.code: OCC-YYYY-NNNNN
- Evidence.code:   ITM-YYYY-NNNNN
- ChainOfCustody.code: CC-YYYY-NNNNN

Sequência reinicia por ano. Gerado automaticamente em Model.save().

A migração é **idempotente e auto-recuperável**: se uma execução anterior
ficou parcialmente aplicada (por exemplo o índice `_like` foi criado mas a
migração falhou antes do COMMIT), as operações detectam o estado existente
em PostgreSQL via `IF [NOT] EXISTS` e não falham.

Para o backfill de Evidence e ChainOfCustody desactiva temporariamente os
triggers de imutabilidade (apenas em PostgreSQL). Em SQLite (testes) não
existem triggers.

Nota de segurança (CWE-89): todas as queries DDL e UPDATE usam strings
totalmente estáticas (sem interpolação de identificadores vindos de input)
e os valores são parametrizados.
"""

from collections import defaultdict

from django.db import migrations, models


# ---------------------------------------------------------------------------
# Pre-cleanup: drop leaked _like indexes from any previous failed deploy.
# Apenas PostgreSQL (SQLite não usa varchar_pattern_ops).
# ---------------------------------------------------------------------------

PG_CLEANUP_SQL = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname ~ '^core_(occurrence|evidence|chainofcustody)_code_[a-f0-9]+(_like)?$'
    LOOP
        EXECUTE 'DROP INDEX IF EXISTS public.' || quote_ident(r.indexname);
    END LOOP;
END $$;
"""

PG_DROP_ANY_PREVIOUS_UNIQUE = """
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'core_occurrence_code_key') THEN
        ALTER TABLE core_occurrence DROP CONSTRAINT core_occurrence_code_key;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'core_evidence_code_key') THEN
        ALTER TABLE core_evidence DROP CONSTRAINT core_evidence_code_key;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'core_chainofcustody_code_key') THEN
        ALTER TABLE core_chainofcustody DROP CONSTRAINT core_chainofcustody_code_key;
    END IF;
END $$;
"""


def cleanup_leaked_artifacts(apps, schema_editor):
    """Limpa índices/constraints órfãos de execuções anteriores. Só PG."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(PG_CLEANUP_SQL)
        cursor.execute(PG_DROP_ANY_PREVIOUS_UNIQUE)


# ---------------------------------------------------------------------------
# AddField idempotente (PG: IF NOT EXISTS; SQLite: verificação via PRAGMA)
# ---------------------------------------------------------------------------

PG_ADD_COLUMN_OCCURRENCE = (
    "ALTER TABLE core_occurrence ADD COLUMN IF NOT EXISTS code "
    "varchar(20) NOT NULL DEFAULT ''"
)
PG_ADD_COLUMN_EVIDENCE = (
    "ALTER TABLE core_evidence ADD COLUMN IF NOT EXISTS code "
    "varchar(20) NOT NULL DEFAULT ''"
)
PG_ADD_COLUMN_CUSTODY = (
    "ALTER TABLE core_chainofcustody ADD COLUMN IF NOT EXISTS code "
    "varchar(20) NOT NULL DEFAULT ''"
)

SQLITE_PRAGMA_OCCURRENCE = "PRAGMA table_info(core_occurrence)"
SQLITE_PRAGMA_EVIDENCE = "PRAGMA table_info(core_evidence)"
SQLITE_PRAGMA_CUSTODY = "PRAGMA table_info(core_chainofcustody)"

SQLITE_ADD_COLUMN_OCCURRENCE = (
    "ALTER TABLE core_occurrence ADD COLUMN code varchar(20) NOT NULL DEFAULT ''"
)
SQLITE_ADD_COLUMN_EVIDENCE = (
    "ALTER TABLE core_evidence ADD COLUMN code varchar(20) NOT NULL DEFAULT ''"
)
SQLITE_ADD_COLUMN_CUSTODY = (
    "ALTER TABLE core_chainofcustody ADD COLUMN code varchar(20) NOT NULL DEFAULT ''"
)


def _sqlite_add_if_missing(cursor, pragma_sql, add_sql):
    cursor.execute(pragma_sql)
    cols = [row[1] for row in cursor.fetchall()]
    if 'code' not in cols:
        cursor.execute(add_sql)


def add_columns_idempotent(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == 'postgresql':
            cursor.execute(PG_ADD_COLUMN_OCCURRENCE)
            cursor.execute(PG_ADD_COLUMN_EVIDENCE)
            cursor.execute(PG_ADD_COLUMN_CUSTODY)
        else:  # sqlite (tests)
            _sqlite_add_if_missing(
                cursor, SQLITE_PRAGMA_OCCURRENCE, SQLITE_ADD_COLUMN_OCCURRENCE,
            )
            _sqlite_add_if_missing(
                cursor, SQLITE_PRAGMA_EVIDENCE, SQLITE_ADD_COLUMN_EVIDENCE,
            )
            _sqlite_add_if_missing(
                cursor, SQLITE_PRAGMA_CUSTODY, SQLITE_ADD_COLUMN_CUSTODY,
            )


def drop_columns_reverse(apps, schema_editor):
    """Reverso do AddField — só usado em rollback explícito."""
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        return  # SQLite: drop column requer rebuild — preferimos não-op em testes
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE core_occurrence DROP COLUMN IF EXISTS code')
        cursor.execute('ALTER TABLE core_evidence DROP COLUMN IF EXISTS code')
        cursor.execute('ALTER TABLE core_chainofcustody DROP COLUMN IF EXISTS code')


# ---------------------------------------------------------------------------
# Backfill — gera códigos por ordem cronológica dentro de cada ano.
# ---------------------------------------------------------------------------

SQL_UPDATE_OCCURRENCE = (
    'UPDATE core_occurrence SET code = %s WHERE id = %s'
)
SQL_UPDATE_EVIDENCE = (
    'UPDATE core_evidence SET code = %s WHERE id = %s'
)
SQL_UPDATE_CUSTODY = (
    'UPDATE core_chainofcustody SET code = %s WHERE id = %s'
)

SQL_DISABLE_EVIDENCE_TRG = (
    'ALTER TABLE core_evidence DISABLE TRIGGER trg_evidence_no_update'
)
SQL_ENABLE_EVIDENCE_TRG = (
    'ALTER TABLE core_evidence ENABLE TRIGGER trg_evidence_no_update'
)
SQL_DISABLE_CUSTODY_TRG = (
    'ALTER TABLE core_chainofcustody DISABLE TRIGGER trg_custody_no_update'
)
SQL_ENABLE_CUSTODY_TRG = (
    'ALTER TABLE core_chainofcustody ENABLE TRIGGER trg_custody_no_update'
)


def _group_by_year(rows, date_attr):
    buckets = defaultdict(list)
    for r in rows:
        if getattr(r, 'code', ''):
            continue
        year = getattr(r, date_attr).year
        buckets[year].append(r)
    return buckets


def _run_backfill(cursor, update_sql, buckets, prefix):
    for year, items in buckets.items():
        for idx, obj in enumerate(items, start=1):
            code = f'{prefix}-{year}-{idx:05d}'
            cursor.execute(update_sql, [code, obj.id])


def backfill_occurrence(apps, schema_editor):
    Occurrence = apps.get_model('core', 'Occurrence')
    rows = list(Occurrence.objects.all().order_by('date_time', 'id'))
    buckets = _group_by_year(rows, 'date_time')
    if not buckets:
        return
    with schema_editor.connection.cursor() as cursor:
        _run_backfill(cursor, SQL_UPDATE_OCCURRENCE, buckets, 'OCC')


def backfill_evidence(apps, schema_editor):
    Evidence = apps.get_model('core', 'Evidence')
    rows = list(Evidence.objects.all().order_by('timestamp_seizure', 'id'))
    buckets = _group_by_year(rows, 'timestamp_seizure')
    if not buckets:
        return
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        if is_pg:
            cursor.execute(SQL_DISABLE_EVIDENCE_TRG)
        try:
            _run_backfill(cursor, SQL_UPDATE_EVIDENCE, buckets, 'ITM')
        finally:
            if is_pg:
                cursor.execute(SQL_ENABLE_EVIDENCE_TRG)


def backfill_custody(apps, schema_editor):
    ChainOfCustody = apps.get_model('core', 'ChainOfCustody')
    rows = list(ChainOfCustody.objects.all().order_by('timestamp', 'id'))
    buckets = _group_by_year(rows, 'timestamp')
    if not buckets:
        return
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        if is_pg:
            cursor.execute(SQL_DISABLE_CUSTODY_TRG)
        try:
            _run_backfill(cursor, SQL_UPDATE_CUSTODY, buckets, 'CC')
        finally:
            if is_pg:
                cursor.execute(SQL_ENABLE_CUSTODY_TRG)


# ---------------------------------------------------------------------------
# Adicionar UNIQUE INDEX + _like INDEX (idempotente) após backfill.
# ---------------------------------------------------------------------------

PG_UNIQUE_OCCURRENCE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS core_occurrence_code_uniq "
    "ON core_occurrence (code)"
)
PG_UNIQUE_EVIDENCE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS core_evidence_code_uniq "
    "ON core_evidence (code)"
)
PG_UNIQUE_CUSTODY = (
    "CREATE UNIQUE INDEX IF NOT EXISTS core_chainofcustody_code_uniq "
    "ON core_chainofcustody (code)"
)
PG_LIKE_OCCURRENCE = (
    "CREATE INDEX IF NOT EXISTS core_occurrence_code_like_idx "
    "ON core_occurrence (code varchar_pattern_ops)"
)
PG_LIKE_EVIDENCE = (
    "CREATE INDEX IF NOT EXISTS core_evidence_code_like_idx "
    "ON core_evidence (code varchar_pattern_ops)"
)
PG_LIKE_CUSTODY = (
    "CREATE INDEX IF NOT EXISTS core_chainofcustody_code_like_idx "
    "ON core_chainofcustody (code varchar_pattern_ops)"
)

SQLITE_UNIQUE_OCCURRENCE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS core_occurrence_code_uniq "
    "ON core_occurrence (code)"
)
SQLITE_UNIQUE_EVIDENCE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS core_evidence_code_uniq "
    "ON core_evidence (code)"
)
SQLITE_UNIQUE_CUSTODY = (
    "CREATE UNIQUE INDEX IF NOT EXISTS core_chainofcustody_code_uniq "
    "ON core_chainofcustody (code)"
)


def add_indexes_idempotent(apps, schema_editor):
    """Cria UNIQUE INDEX + _like INDEX idempotentemente."""
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == 'postgresql':
            cursor.execute(PG_UNIQUE_OCCURRENCE)
            cursor.execute(PG_UNIQUE_EVIDENCE)
            cursor.execute(PG_UNIQUE_CUSTODY)
            cursor.execute(PG_LIKE_OCCURRENCE)
            cursor.execute(PG_LIKE_EVIDENCE)
            cursor.execute(PG_LIKE_CUSTODY)
        else:  # sqlite
            cursor.execute(SQLITE_UNIQUE_OCCURRENCE)
            cursor.execute(SQLITE_UNIQUE_EVIDENCE)
            cursor.execute(SQLITE_UNIQUE_CUSTODY)


def drop_indexes_reverse(apps, schema_editor):
    """Reverso — drop índices criados (mantém-se idempotente)."""
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS core_occurrence_code_uniq')
        cursor.execute('DROP INDEX IF EXISTS core_evidence_code_uniq')
        cursor.execute('DROP INDEX IF EXISTS core_chainofcustody_code_uniq')
        if vendor == 'postgresql':
            cursor.execute('DROP INDEX IF EXISTS core_occurrence_code_like_idx')
            cursor.execute('DROP INDEX IF EXISTS core_evidence_code_like_idx')
            cursor.execute('DROP INDEX IF EXISTS core_chainofcustody_code_like_idx')


def noop(apps, schema_editor):
    pass


# ---------------------------------------------------------------------------
# Definição declarativa do campo (usada para state_operations) — Django assume
# que a coluna+constraints existem assim que esta migração corre.
# ---------------------------------------------------------------------------

OCCURRENCE_FIELD = models.CharField(
    blank=True,
    db_index=True,
    default='',
    help_text='Gerado automaticamente no formato OCC-YYYY-NNNNN.',
    max_length=20,
    unique=True,
    verbose_name='Código do caso',
)
EVIDENCE_FIELD = models.CharField(
    blank=True,
    db_index=True,
    default='',
    help_text='Gerado automaticamente no formato ITM-YYYY-NNNNN.',
    max_length=20,
    unique=True,
    verbose_name='Código do item',
)
CUSTODY_FIELD = models.CharField(
    blank=True,
    db_index=True,
    default='',
    help_text='Gerado automaticamente no formato CC-YYYY-NNNNN.',
    max_length=20,
    unique=True,
    verbose_name='Código da transição',
)


class Migration(migrations.Migration):

    # atomic=False permite que cada step (cleanup → AddField → backfill →
    # AlterField) faça commit independente. Isto é essencial para a
    # auto-recuperação: se o pre-cleanup precisar de remover índices órfãos
    # de uma execução anterior, esse trabalho não pode ficar pendurado num
    # rollback se um step posterior falhar.
    atomic = False

    dependencies = [
        ('core', '0008_extend_immutability'),
    ]

    operations = [
        # Step 0: cleanup defensivo de artefactos órfãos (PG only).
        migrations.RunPython(cleanup_leaked_artifacts, noop),

        # Step 1: AddField — Django state diz "campo existe", BD recebe SQL
        # idempotente que tolera coluna pré-existente.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='occurrence',
                    name='code',
                    field=models.CharField(
                        blank=True,
                        default='',
                        help_text=(
                            'Gerado automaticamente no formato OCC-YYYY-NNNNN.'
                        ),
                        max_length=20,
                        verbose_name='Código do caso',
                    ),
                ),
                migrations.AddField(
                    model_name='evidence',
                    name='code',
                    field=models.CharField(
                        blank=True,
                        default='',
                        help_text=(
                            'Gerado automaticamente no formato ITM-YYYY-NNNNN.'
                        ),
                        max_length=20,
                        verbose_name='Código do item',
                    ),
                ),
                migrations.AddField(
                    model_name='chainofcustody',
                    name='code',
                    field=models.CharField(
                        blank=True,
                        default='',
                        help_text=(
                            'Gerado automaticamente no formato CC-YYYY-NNNNN.'
                        ),
                        max_length=20,
                        verbose_name='Código da transição',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_columns_idempotent, drop_columns_reverse),
            ],
        ),

        # Step 2: backfill dos registos existentes (skipa se code já preenchido).
        migrations.RunPython(backfill_occurrence, noop),
        migrations.RunPython(backfill_evidence, noop),
        migrations.RunPython(backfill_custody, noop),

        # Step 3: AlterField — declara unique=True, db_index=True no state;
        # cria o UNIQUE INDEX + _like INDEX no DB de forma idempotente.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='occurrence', name='code', field=OCCURRENCE_FIELD,
                ),
                migrations.AlterField(
                    model_name='evidence', name='code', field=EVIDENCE_FIELD,
                ),
                migrations.AlterField(
                    model_name='chainofcustody', name='code', field=CUSTODY_FIELD,
                ),
            ],
            database_operations=[
                migrations.RunPython(add_indexes_idempotent, drop_indexes_reverse),
            ],
        ),
    ]
