"""
Adiciona campo `sequence` a ChainOfCustody e muda ordenação canónica.

O sequence é preenchido (1..N por evidência, ordenado pelo timestamp
existente) para registos existentes, garantindo que o constraint único
(evidence, sequence) é respeitado.
"""

from django.db import migrations, models


# SQL constantes (identificadores não são parametrizáveis em DDL).
# Nome da tabela é o db_table fixo do modelo core.ChainOfCustody.
_DISABLE_TRIGGER_SQL = 'ALTER TABLE "core_chainofcustody" DISABLE TRIGGER trg_custody_no_update'
_ENABLE_TRIGGER_SQL = 'ALTER TABLE "core_chainofcustody" ENABLE TRIGGER trg_custody_no_update'


def backfill_sequences(apps, schema_editor):
    ChainOfCustody = apps.get_model('core', 'ChainOfCustody')
    connection = schema_editor.connection

    # O trigger trg_custody_no_update (0002) bloqueia qualquer UPDATE.
    # Durante o backfill desactivamos o trigger — a imutabilidade é
    # reposta logo a seguir. Só suportado em PostgreSQL; em sqlite
    # (testes) o trigger não existe e o ALTER é saltado.
    is_postgres = connection.vendor == 'postgresql'

    if is_postgres:
        with connection.cursor() as cursor:
            cursor.execute(_DISABLE_TRIGGER_SQL)  # nosemgrep: python.django.security.injection.raw-query.raw-query

    try:
        evidence_ids = (
            ChainOfCustody.objects.values_list('evidence_id', flat=True).distinct()
        )
        for evidence_id in evidence_ids:
            records = list(
                ChainOfCustody.objects
                .filter(evidence_id=evidence_id)
                .order_by('timestamp', 'id')
            )
            for idx, record in enumerate(records, start=1):
                if record.sequence != idx:
                    ChainOfCustody.objects.filter(pk=record.pk).update(sequence=idx)
    finally:
        if is_postgres:
            with connection.cursor() as cursor:
                cursor.execute(_ENABLE_TRIGGER_SQL)  # nosemgrep: python.django.security.injection.raw-query.raw-query


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_digitaldevice_evidence_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='chainofcustody',
            name='sequence',
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    'Número sequencial (1..N) por evidência. Determina a ordem '
                    'canónica da cadeia de custódia, independente de resolução '
                    'temporal do timestamp.'
                ),
                verbose_name='Sequência',
            ),
        ),
        migrations.RunPython(backfill_sequences, reverse_code=noop_reverse),
        migrations.AlterModelOptions(
            name='chainofcustody',
            options={
                'ordering': ['evidence', 'sequence'],
                'verbose_name': 'Registo de Custódia',
                'verbose_name_plural': 'Registos de Custódia',
            },
        ),
        migrations.AddConstraint(
            model_name='chainofcustody',
            constraint=models.UniqueConstraint(
                fields=('evidence', 'sequence'),
                name='unique_custody_sequence_per_evidence',
            ),
        ),
    ]
