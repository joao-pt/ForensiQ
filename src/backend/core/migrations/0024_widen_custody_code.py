"""Alarga ``ChainOfCustody.code`` de 32 → 48 caracteres.

O código do movimento deriva de ``evidence.code`` (até 32 chars) + o sufixo
``-M{sequência}``. Com max_length=32 o valor transbordava para itens com código
já longo (sub-componente profundo) ou a partir do 100.º evento (``-M100``): o
``full_clean()`` em ``ChainOfCustody.save()`` levantava um ValidationError de
max_length que NÃO é um IntegrityError, pelo que o retry não o apanhava e o
evento de custódia não podia ser gravado. 48 acomoda 32 + ``-M`` + sequência.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_modelo_v2_genese_aquisicao_selagem'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chainofcustody',
            name='code',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Movimento do item: {código do item}-M{sequência} (ex.: OC-2026-0001.1-M01).',
                max_length=48,
                unique=True,
                verbose_name='Código do movimento',
            ),
        ),
    ]
