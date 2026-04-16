"""
Adiciona campo `sequence` a ChainOfCustody e muda ordenação canónica.

O sequence é preenchido (1..N por evidência, ordenado pelo timestamp
existente) para registos existentes, garantindo que o constraint único
(evidence, sequence) é respeitado.
"""

from django.db import migrations, models


def backfill_sequences(apps, schema_editor):
    ChainOfCustody = apps.get_model('core', 'ChainOfCustody')
    # Evidências com registos
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
                record.sequence = idx
                # .save() do modelo real tem o override restritivo; usar update()
                ChainOfCustody.objects.filter(pk=record.pk).update(sequence=idx)


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
