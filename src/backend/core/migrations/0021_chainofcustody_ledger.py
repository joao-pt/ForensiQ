"""Migração: ChainOfCustody passa de máquina-de-estados a LEDGER DE EVENTOS.

T01+T20 (ADR-0013 + ADR-0015). Substituição limpa, sem legado (princípio da
Fase 2): removem-se os campos da máquina de estados (``previous_state`` /
``new_state``) e acrescentam-se os campos do ledger de eventos + GPS:

- ``event_type``      — acto processual registado (enum EventType, CPP).
- ``custodian_type``  — custódio após o evento (enum CustodianType).
- ``location_name``   — nome legível do POI (OSM/Nominatim).
- ``storage_location``— localização interna de armazenamento (texto livre).
- ``gps_lat`` / ``gps_lng`` / ``gps_accuracy_m`` — GPS por evento (ADR-0013).

Greenfield: NÃO há RunPython de dados — nenhum registo do ledger é reescrito
(o append-only mantém-se por princípio) e não existem dados a migrar.

Triggers de imutabilidade — NÃO recriar nem tocar a migração 0002:
``trg_custody_no_update`` / ``trg_custody_no_delete``
(``core/migrations/0002_add_immutability_triggers.py``) são ``BEFORE
UPDATE/DELETE ... FOR EACH ROW`` genéricos — não referenciam nomes de coluna,
logo bloqueiam a linha inteira e cobrem AUTOMATICAMENTE as colunas novas
(``event_type``, ``custodian_type``, ``location_name``, ``storage_location``,
``gps_lat``, ``gps_lng``, ``gps_accuracy_m``). Nenhuma migração de trigger é
necessária (ADR-0013 §8, ADR-0015 §9).
"""

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_delete_digitaldevice'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- verbose_name: "transição" → "evento" (ledger) ---
        migrations.AlterField(
            model_name='chainofcustody',
            name='agent',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='custody_actions',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Responsável pelo evento',
            ),
        ),
        migrations.AlterField(
            model_name='chainofcustody',
            name='timestamp',
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                verbose_name='Data/hora do evento',
            ),
        ),
        # --- Saem os campos da máquina de estados ---
        migrations.RemoveField(
            model_name='chainofcustody',
            name='previous_state',
        ),
        migrations.RemoveField(
            model_name='chainofcustody',
            name='new_state',
        ),
        # --- Entram os campos do ledger de eventos (ADR-0015) ---
        migrations.AddField(
            model_name='chainofcustody',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('APREENSAO', 'Apreensão'),
                    ('VALIDACAO', 'Validação da apreensão'),
                    ('DESPACHO_PERICIA', 'Despacho para perícia'),
                    ('TRANSFERENCIA', 'Transferência de custódia'),
                    ('INICIO_PERICIA', 'Início de perícia'),
                    ('CONCLUSAO_PERICIA', 'Conclusão de perícia'),
                    ('RESTITUICAO', 'Restituição'),
                    ('PERDA_FAVOR_ESTADO', 'Perda a favor do Estado'),
                    ('DESTRUICAO', 'Destruição'),
                ],
                default='APREENSAO',
                max_length=20,
                verbose_name='Tipo de evento',
            ),
            # Greenfield: a tabela está vazia. O default serve apenas para o
            # caso degenerado de uma linha pré-existente; o modelo NÃO declara
            # default (event_type é obrigatório no clean/serializer).
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='chainofcustody',
            name='custodian_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('LOCAL_CRIME', 'Local do crime'),
                    ('OPC', 'Órgão de polícia criminal'),
                    ('LAB_PUBLICO', 'Laboratório público'),
                    ('LAB_PRIVADO', 'Laboratório privado'),
                    ('TRIBUNAL', 'Tribunal'),
                    ('DEPOSITARIO', 'Depositário'),
                    ('PROPRIETARIO', 'Proprietário'),
                ],
                default='',
                max_length=20,
                verbose_name='Custódio após o evento',
            ),
        ),
        migrations.AddField(
            model_name='chainofcustody',
            name='location_name',
            field=models.CharField(
                blank=True,
                default='',
                max_length=255,
                verbose_name='Local (POI OSM)',
            ),
        ),
        migrations.AddField(
            model_name='chainofcustody',
            name='storage_location',
            field=models.CharField(
                blank=True,
                default='',
                max_length=120,
                verbose_name='Localização interna de armazenamento',
            ),
        ),
        migrations.AddField(
            model_name='chainofcustody',
            name='gps_lat',
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(-90),
                    django.core.validators.MaxValueValidator(90),
                ],
                verbose_name='Latitude GPS (evento)',
            ),
        ),
        migrations.AddField(
            model_name='chainofcustody',
            name='gps_lng',
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(-180),
                    django.core.validators.MaxValueValidator(180),
                ],
                verbose_name='Longitude GPS (evento)',
            ),
        ),
        migrations.AddField(
            model_name='chainofcustody',
            name='gps_accuracy_m',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    'Raio de incerteza em metros reportado pelo dispositivo. '
                    'Metadado de precisão — não altera a coordenada gravada.'
                ),
                verbose_name='Precisão GPS reportada (m)',
            ),
        ),
    ]
