"""Marca os campos IDENTIFICADORES (entram na guia de transporte).

A guia de transporte identifica inequivocamente o equipamento por marca/modelo/
série e pelo identificador do tipo (IMEI/VIN/IMSI/ICCID/MAC/UID) — NÃO por
metadados forenses (sistema operativo, capacidade, operador, estado de energia).
Esta migração acrescenta a flag e marca os campos identificadores semeados em
0027. Fonte única: a flag vive na tabela, editável no admin.
"""

from django.db import migrations, models

# Chaves de ``type_specific_data`` que são IDENTIFICADORES onde quer que apareçam
# (marca/modelo são transversais; os restantes são identificadores formatados do
# tipo). Excluídos de propósito: estado_energia, operating_system, carrier,
# encryption_status, capacity, interface, channels, system_datetime,
# tag_ecosystem, source_device_description, device_category (metadados, não IDs).
IDENTIFIER_KEYS = [
    'marca',
    'modelo',
    'imei',
    'imei_2',
    'imsi',
    'iccid',
    'vin',
    'associated_vin',
    'mac',
    'device_serial_number',
    'aircraft_serial_number',
    'console_id',
    'card_uid',
]


def mark_identifiers(apps, schema_editor):
    Field = apps.get_model('core', 'EvidenceFieldDef')
    Field.objects.filter(key__in=IDENTIFIER_KEYS).update(is_identifier=True)


def unmark_identifiers(apps, schema_editor):
    Field = apps.get_model('core', 'EvidenceFieldDef')
    Field.objects.filter(key__in=IDENTIFIER_KEYS).update(is_identifier=False)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_derivacao_label_item_pai'),
    ]

    operations = [
        migrations.AddField(
            model_name='evidencefielddef',
            name='is_identifier',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Identifica inequivocamente o item e entra na guia de transporte '
                    '(marca, modelo, IMEI, VIN, IMSI, …). Distinto de metadados forenses '
                    '(sistema operativo, capacidade, operador) que não vão na guia.'
                ),
                verbose_name='Identificador',
            ),
        ),
        migrations.RunPython(mark_identifiers, unmark_identifiers),
    ]
