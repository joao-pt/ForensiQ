"""Índices compostos para Evidence e ChainOfCustody (perf: list/filter comuns)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_chainofcustody_sequence'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='evidence',
            index=models.Index(fields=['occurrence', '-timestamp_seizure'], name='ev_occ_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='evidence',
            index=models.Index(fields=['agent', '-timestamp_seizure'], name='ev_agent_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='chainofcustody',
            index=models.Index(fields=['evidence', 'sequence'], name='coc_ev_seq_idx'),
        ),
        migrations.AddIndex(
            model_name='chainofcustody',
            index=models.Index(fields=['agent', '-timestamp'], name='coc_agent_ts_idx'),
        ),
    ]
