"""Acrescenta `sequence` global ao AuditLog (audit 2026-05-18 §3 N10).

Estratégia em 3 passos para acomodar registos pré-existentes:

1. ``AddField`` com ``default=0`` e SEM ``unique=True`` — todos os
   registos ficam temporariamente com ``sequence=0``.
2. ``RunPython`` faz backfill: ordena por (``timestamp`` ASC, ``pk`` ASC)
   e atribui ``1, 2, 3, ...`` deterministicamente. Idempotente — se
   correr de novo, recalcula com a mesma ordem.
3. ``AlterField`` adiciona ``unique=True`` agora que todos os valores
   são únicos.

A reversão (``RunPython.noop``) deixa o `sequence=0` em todos os
registos — combinada com o `RemoveField` automático faz rollback
limpo.
"""

from django.db import migrations, models


def backfill_sequence(apps, schema_editor):
    """Atribui sequence sequencial ordenado por (timestamp, pk)."""
    AuditLog = apps.get_model('core', 'AuditLog')
    for i, log in enumerate(
        AuditLog.objects.order_by('timestamp', 'pk').iterator(),
        start=1,
    ):
        # `update()` no queryset para evitar disparar `Model.save()`
        # (que tem o override append-only e levantaria ValidationError
        # se a instância já tem pk). Backfill é operação de migração,
        # fora do regime de imutabilidade aplicacional.
        AuditLog.objects.filter(pk=log.pk).update(sequence=i)


def noop_reverse(apps, schema_editor):
    """Rollback: o campo será removido pelo `RemoveField` posterior."""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_alter_auditlog_action'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='auditlog',
            options={
                'ordering': ['-sequence'],
                'verbose_name': 'Registo de Auditoria',
                'verbose_name_plural': 'Registos de Auditoria',
            },
        ),
        # Passo 1: AddField sem unique constraint (default 0 para
        # registos existentes; backfill em passo 2).
        migrations.AddField(
            model_name='auditlog',
            name='sequence',
            field=models.BigIntegerField(
                db_index=True,
                default=0,
                help_text=(
                    'Ordem total dos registos de auditoria. Garante ordem '
                    'inequívoca entre eventos no mesmo microssegundo.'
                ),
                verbose_name='Sequência Global',
            ),
        ),
        # Passo 2: backfill ordenado por (timestamp, pk).
        migrations.RunPython(backfill_sequence, noop_reverse),
        # Passo 3: agora que todos os valores são distintos, adiciona
        # unique=True.
        migrations.AlterField(
            model_name='auditlog',
            name='sequence',
            field=models.BigIntegerField(
                db_index=True,
                default=0,
                help_text=(
                    'Ordem total dos registos de auditoria. Garante ordem '
                    'inequívoca entre eventos no mesmo microssegundo.'
                ),
                unique=True,
                verbose_name='Sequência Global',
            ),
        ),
    ]
