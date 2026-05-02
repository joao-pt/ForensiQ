"""Adiciona EXPORT_CSV à enum AuditLog.Action.

Suporta o registo de exportações CSV (modo tabela densa) preservando
auditabilidade ISO/IEC 27037 — qualquer extracção massiva de dados de
prova fica registada com utilizador, IP, correlation_id e hash.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_alter_evidence_photo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('VIEW', 'Visualização'),
                    ('CREATE', 'Criação'),
                    ('EXPORT_PDF', 'Exportação PDF'),
                    ('EXPORT_CSV', 'Exportação CSV'),
                ],
                db_index=True,
                help_text='VIEW: visualização; CREATE: criação; EXPORT_PDF: exportação.',
                max_length=20,
                verbose_name='Ação',
            ),
        ),
    ]
