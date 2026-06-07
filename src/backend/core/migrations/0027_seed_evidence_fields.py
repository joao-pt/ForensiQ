"""Semeia a configuração de campos por tipo de evidência nas tabelas novas.

Snapshot fiel do antigo ``evidence_field_config`` (TRANSVERSAL_FIELDS +
EVIDENCE_TYPE_FIELDS), que deixa de ser hardcoded e passa a viver na BD
(EvidenceFieldDef + FieldOption), editável no admin. Self-contained: os dados
ficam aqui como seed inicial; a fonte de verdade viva é a tabela.
"""

from django.db import migrations

# evidence_type vazio = transversal (comum a todos os tipos).
TRANSVERSAL = [
    {'key': 'marca', 'label': 'Marca / Fabricante', 'input': 'text'},
    {'key': 'modelo', 'label': 'Modelo', 'input': 'text'},
    {'key': 'estado_energia', 'label': 'Estado de energia na apreensão', 'input': 'select',
     'options': ['Ligado', 'Desligado', 'Modo de avião', 'Não aplicável', 'Desconhecido']},
]

BY_TYPE = {
    'MOBILE_DEVICE': [
        {'key': 'imei', 'label': 'IMEI', 'input': 'text', 'validator': 'imei', 'lookup': 'imei'},
        {'key': 'imei_2', 'label': 'IMEI secundário (dual-SIM)', 'input': 'text', 'validator': 'imei'},
        {'key': 'operating_system', 'label': 'Sistema operativo', 'input': 'select',
         'options': ['Android', 'iOS / iPadOS', 'Outro', 'Desconhecido']},
        {'key': 'passcode', 'label': 'Código de desbloqueio (se autorizado)', 'input': 'text', 'sensitive': True},
    ],
    'SIM_CARD': [
        {'key': 'imsi', 'label': 'IMSI', 'input': 'text', 'validator': 'imsi'},
        {'key': 'iccid', 'label': 'ICCID', 'input': 'text', 'validator': 'iccid'},
        {'key': 'carrier', 'label': 'Operador', 'input': 'text'},
        {'key': 'pin_code', 'label': 'PIN (se autorizado)', 'input': 'text', 'sensitive': True},
    ],
    'VEHICLE': [
        {'key': 'vin', 'label': 'VIN', 'input': 'text', 'validator': 'vin', 'lookup': 'vin'},
    ],
    'VEHICLE_COMPONENT': [
        {'key': 'associated_vin', 'label': 'VIN do veículo associado', 'input': 'text', 'validator': 'vin'},
    ],
    'NETWORK_DEVICE': [
        {'key': 'mac', 'label': 'MAC', 'input': 'text', 'validator': 'mac'},
    ],
    'IOT_DEVICE': [
        {'key': 'mac', 'label': 'MAC', 'input': 'text', 'validator': 'mac'},
    ],
    'GPS_TRACKER': [
        {'key': 'imei', 'label': 'IMEI', 'input': 'text', 'validator': 'imei'},
        {'key': 'imsi', 'label': 'IMSI', 'input': 'text', 'validator': 'imsi'},
    ],
    'SMART_TAG': [
        {'key': 'tag_ecosystem', 'label': 'Ecossistema', 'input': 'select',
         'options': ['Apple AirTag', 'Samsung SmartTag', 'Tile', 'Chipolo', 'Outro', 'Desconhecido']},
        {'key': 'device_serial_number', 'label': 'Nº de série do localizador', 'input': 'text'},
    ],
    'COMPUTER': [
        {'key': 'operating_system', 'label': 'Sistema operativo', 'input': 'text'},
        {'key': 'encryption_status', 'label': 'Cifragem de disco', 'input': 'select',
         'options': ['Sem cifragem', 'BitLocker', 'FileVault', 'LUKS', 'Outra', 'Desconhecido']},
    ],
    'INTERNAL_DRIVE': [
        {'key': 'capacity', 'label': 'Capacidade', 'input': 'text'},
        {'key': 'interface', 'label': 'Interface', 'input': 'select',
         'options': ['SATA', 'NVMe', 'SAS', 'IDE/PATA', 'USB', 'Outro', 'Desconhecido']},
    ],
    'STORAGE_MEDIA': [
        {'key': 'capacity', 'label': 'Capacidade', 'input': 'text'},
    ],
    'MEMORY_CARD': [
        {'key': 'capacity', 'label': 'Capacidade', 'input': 'text'},
    ],
    'CCTV_DEVICE': [
        {'key': 'channels', 'label': 'Nº de canais', 'input': 'number'},
        {'key': 'system_datetime', 'label': 'Data/hora do sistema na recolha', 'input': 'text'},
    ],
    'DRONE': [
        {'key': 'aircraft_serial_number', 'label': 'Nº de série da aeronave', 'input': 'text'},
    ],
    'GAMING_CONSOLE': [
        {'key': 'console_id', 'label': 'ID da consola', 'input': 'text'},
    ],
    'DIGITAL_FILE': [
        {'key': 'source_device_description', 'label': 'Dispositivo-fonte (descrição)', 'input': 'text'},
    ],
    'RFID_NFC_CARD': [
        {'key': 'card_uid', 'label': 'UID do cartão', 'input': 'text'},
    ],
    'OTHER_DIGITAL': [
        {'key': 'device_category', 'label': 'Categoria do dispositivo', 'input': 'text'},
    ],
}


def seed_fields(apps, schema_editor):
    Field = apps.get_model('core', 'EvidenceFieldDef')
    Option = apps.get_model('core', 'FieldOption')

    def create(evidence_type, spec, order):
        field = Field.objects.create(
            evidence_type=evidence_type,
            key=spec['key'],
            label=spec['label'],
            input=spec.get('input', 'text'),
            required=spec.get('required', False),
            validator=spec.get('validator', ''),
            lookup=spec.get('lookup', ''),
            sensitive=spec.get('sensitive', False),
            order=order,
        )
        for i, value in enumerate(spec.get('options', [])):
            Option.objects.create(field=field, value=value, order=i)

    for i, spec in enumerate(TRANSVERSAL):
        create('', spec, i)
    for evidence_type, specs in BY_TYPE.items():
        for i, spec in enumerate(specs):
            create(evidence_type, spec, i)


def unseed_fields(apps, schema_editor):
    # CASCADE remove as FieldOption associadas.
    apps.get_model('core', 'EvidenceFieldDef').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_evidence_field_tables'),
    ]

    operations = [
        migrations.RunPython(seed_fields, unseed_fields),
    ]
