"""Adiciona DigitalDevice.commercial_name (nome comercial do dispositivo).

Separa o **nome comercial** (ex.: "iPhone 11 Pro Max") do **SKU/modelo
técnico** (ex.: "A2161") — necessário porque o TAC do IMEI mapeia para a
variante exacta (bandas LTE, memória, region-lock) e o procedimento
forense do perito muda entre variantes do mesmo nome comercial.

Sem backfill: o campo é opcional. Para registos existentes, ``model``
continua a conter o que o utilizador escreveu (texto livre histórico) e
``commercial_name`` fica vazio. A partir desta migração, o auto-fill via
imeidb.xyz preenche os dois separadamente.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_human_codes'),
    ]

    operations = [
        migrations.AddField(
            model_name='digitaldevice',
            name='commercial_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    'Nome reconhecido pelo first responder '
                    '(ex.: iPhone 11 Pro Max). Preenchido pelo '
                    'enriquecimento IMEI quando disponível.'
                ),
                max_length=120,
                verbose_name='Nome comercial',
            ),
        ),
        migrations.AlterField(
            model_name='digitaldevice',
            name='model',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    'Código técnico do modelo (ex.: A2161). Permite ao '
                    'perito identificar a variante exacta — bandas, '
                    'memória, region-lock.'
                ),
                max_length=100,
                verbose_name='Modelo (SKU)',
            ),
        ),
    ]
