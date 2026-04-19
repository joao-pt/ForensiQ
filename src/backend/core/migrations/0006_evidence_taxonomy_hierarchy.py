"""
Wave 2a — Nova taxonomia de evidências digitais + hierarquia pai-filho
+ campos JSON type-specific + snapshot de consulta externa.

Inclui:
1. Alargamento do `max_length` de `Evidence.type` (20 → 25) para caber
   nos novos códigos (ex: `VEHICLE_COMPONENT`, `RFID_NFC_CARD`).
2. Adição de `parent_evidence` (FK self, PROTECT).
3. Adição de `type_specific_data`, `external_lookup_snapshot`,
   `external_lookup_source`, `external_lookup_at`.
4. Data migration (forward + reverse) que remapeia os 5 tipos legados
   para os 18 novos tipos.
5. Alteração das `choices` no campo `type` para os 18 códigos novos.
6. Índice em `parent_evidence` para acelerar sub_components.

Importante: o trigger `trg_evidence_no_update` (criado em 0002) bloqueia
qualquer UPDATE, portanto a data migration desactiva-o temporariamente,
tal como a 0004 faz com o trigger de custody.
"""

from django.db import migrations, models
import django.db.models.deletion


_DISABLE_EVIDENCE_TRIGGER_SQL = (
    'ALTER TABLE "core_evidence" DISABLE TRIGGER trg_evidence_no_update'
)
_ENABLE_EVIDENCE_TRIGGER_SQL = (
    'ALTER TABLE "core_evidence" ENABLE TRIGGER trg_evidence_no_update'
)

# Mapeamento forward: 5 tipos legados → novos códigos
FORWARD_TYPE_MAP = {
    'DIGITAL_DEVICE': 'MOBILE_DEVICE',   # assume-se smartphone
    'DOCUMENT': 'OTHER_DIGITAL',         # papel não é prova digital
    'STORAGE_MEDIA': 'STORAGE_MEDIA',    # mantém
    'PHOTO': 'DIGITAL_FILE',             # fotografia digital
    'OTHER': 'OTHER_DIGITAL',
}

# Mapeamento reverse: 18 códigos novos → 5 legados (aproximação)
REVERSE_TYPE_MAP = {
    # Dispositivos que encaixam no legado DIGITAL_DEVICE
    'MOBILE_DEVICE': 'DIGITAL_DEVICE',
    'COMPUTER': 'DIGITAL_DEVICE',
    'GAMING_CONSOLE': 'DIGITAL_DEVICE',
    'GPS_TRACKER': 'DIGITAL_DEVICE',
    'SMART_TAG': 'DIGITAL_DEVICE',
    'CCTV_DEVICE': 'DIGITAL_DEVICE',
    'DRONE': 'DIGITAL_DEVICE',
    'IOT_DEVICE': 'DIGITAL_DEVICE',
    'NETWORK_DEVICE': 'DIGITAL_DEVICE',
    # Suportes
    'STORAGE_MEDIA': 'STORAGE_MEDIA',
    'MEMORY_CARD': 'STORAGE_MEDIA',
    'INTERNAL_DRIVE': 'STORAGE_MEDIA',
    # Ficheiros
    'DIGITAL_FILE': 'PHOTO',
    # Cartões/componentes sem match directo → OTHER
    'SIM_CARD': 'OTHER',
    'RFID_NFC_CARD': 'OTHER',
    'VEHICLE': 'OTHER',
    'VEHICLE_COMPONENT': 'OTHER',
    'OTHER_DIGITAL': 'OTHER',
}


def _with_triggers_disabled(schema_editor, fn):
    """Executa `fn()` com o trigger de imutabilidade de Evidence OFF.

    Em SQLite (testes) o trigger não existe — corre direct. Em Postgres
    desactiva e reactiva, mesmo que `fn()` levante excepção.
    """
    connection = schema_editor.connection
    is_postgres = connection.vendor == 'postgresql'
    if is_postgres:
        with connection.cursor() as cursor:
            cursor.execute(_DISABLE_EVIDENCE_TRIGGER_SQL)  # nosemgrep: python.django.security.injection.raw-query.raw-query
    try:
        fn()
    finally:
        if is_postgres:
            with connection.cursor() as cursor:
                cursor.execute(_ENABLE_EVIDENCE_TRIGGER_SQL)  # nosemgrep: python.django.security.injection.raw-query.raw-query


def remap_types_forward(apps, schema_editor):
    """Mapeia os 5 tipos legados para os 18 novos."""
    Evidence = apps.get_model('core', 'Evidence')

    def _do():
        for old, new in FORWARD_TYPE_MAP.items():
            if old == new:
                continue
            Evidence.objects.filter(type=old).update(type=new)

    _with_triggers_disabled(schema_editor, _do)


def remap_types_reverse(apps, schema_editor):
    """Mapeia os 18 tipos novos de volta para os 5 legados (best-effort)."""
    Evidence = apps.get_model('core', 'Evidence')

    def _do():
        for new, old in REVERSE_TYPE_MAP.items():
            if new == old:
                continue
            Evidence.objects.filter(type=new).update(type=old)

    _with_triggers_disabled(schema_editor, _do)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_composite_indexes'),
    ]

    operations = [
        # --- 1. Alargar max_length de `type` antes do remap ---
        migrations.AlterField(
            model_name='evidence',
            name='type',
            field=models.CharField(
                max_length=25,
                # Choices ainda são os 5 legados neste ponto — a data
                # migration abaixo preenche com os novos, e o último
                # AlterField muda as choices.
                choices=[
                    ('DIGITAL_DEVICE', 'Dispositivo Digital'),
                    ('DOCUMENT', 'Documento'),
                    ('STORAGE_MEDIA', 'Suporte de Armazenamento'),
                    ('PHOTO', 'Fotografia'),
                    ('OTHER', 'Outro'),
                ],
                verbose_name='Tipo de evidência',
            ),
        ),

        # --- 2. Adicionar os novos campos (nullable / defaults seguros) ---
        migrations.AddField(
            model_name='evidence',
            name='parent_evidence',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sub_components',
                to='core.evidence',
                verbose_name='Evidência-pai',
                help_text=(
                    'Se este item for um componente interno de outra evidência, '
                    'indica o pai (máx. 3 níveis).'
                ),
            ),
        ),
        migrations.AddField(
            model_name='evidence',
            name='type_specific_data',
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name='Dados específicos do tipo',
                help_text=(
                    'Campos específicos do tipo de evidência (IMEI, VIN, '
                    'IMSI, ICCID, MAC, etc.).'
                ),
            ),
        ),
        migrations.AddField(
            model_name='evidence',
            name='external_lookup_snapshot',
            field=models.JSONField(
                blank=True,
                null=True,
                verbose_name='Snapshot de consulta externa',
                help_text=(
                    'Resposta JSON da API externa (imeidb.xyz, vindecoder, '
                    'etc.) à data da consulta. Para auditoria e proveniência '
                    'ISO 27037.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='evidence',
            name='external_lookup_source',
            field=models.CharField(
                blank=True,
                default='',
                max_length=50,
                verbose_name='Fonte da consulta externa',
                help_text='Ex: "imeidb.xyz", "vindecoder.eu".',
            ),
        ),
        migrations.AddField(
            model_name='evidence',
            name='external_lookup_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Data/hora da consulta externa',
            ),
        ),

        # --- 3. Data migration: remapear os tipos legados ---
        migrations.RunPython(remap_types_forward, reverse_code=remap_types_reverse),

        # --- 4. Choices finais (18 códigos novos) ---
        migrations.AlterField(
            model_name='evidence',
            name='type',
            field=models.CharField(
                max_length=25,
                choices=[
                    ('MOBILE_DEVICE', 'Telemóvel / Smartphone / Tablet'),
                    ('COMPUTER', 'Computador (PC / portátil / servidor)'),
                    ('STORAGE_MEDIA', 'Suporte de Armazenamento Externo'),
                    ('GAMING_CONSOLE', 'Consola de Jogos'),
                    ('GPS_TRACKER', 'Rastreador GPS'),
                    ('SMART_TAG', 'Localizador Bluetooth (AirTag / SmartTag / Tile)'),
                    ('CCTV_DEVICE', 'CCTV / DVR / NVR'),
                    ('VEHICLE', 'Veículo (container)'),
                    ('DRONE', 'Drone / UAV'),
                    ('IOT_DEVICE', 'Dispositivo IoT'),
                    ('NETWORK_DEVICE', 'Equipamento de Rede'),
                    ('DIGITAL_FILE', 'Ficheiro Digital (captura)'),
                    ('RFID_NFC_CARD', 'Cartão RFID / NFC'),
                    ('OTHER_DIGITAL', 'Outro Dispositivo Digital'),
                    ('SIM_CARD', 'Cartão SIM'),
                    ('MEMORY_CARD', 'Cartão de Memória (SD / microSD / CF)'),
                    ('INTERNAL_DRIVE', 'Disco Interno (HDD / SSD / NVMe)'),
                    ('VEHICLE_COMPONENT', 'Componente Electrónico de Veículo'),
                ],
                verbose_name='Tipo de evidência',
            ),
        ),

        # --- 5. Índice em parent_evidence (apoia .sub_components) ---
        migrations.AddIndex(
            model_name='evidence',
            index=models.Index(fields=['parent_evidence'], name='ev_parent_idx'),
        ),
    ]
