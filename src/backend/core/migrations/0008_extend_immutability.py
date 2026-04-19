"""
Wave 2a — Extensão da imutabilidade de Evidence aos novos campos.

Os triggers criados em 0002 (`trg_evidence_no_update`) já bloqueiam
QUALQUER UPDATE a linhas de `core_evidence` — logo, os novos campos
(`type_specific_data`, `parent_evidence_id`, `external_lookup_*`)
estão automaticamente protegidos ao nível do motor de DB.

Esta migration é primariamente **documental** e adiciona uma função
auxiliar PostgreSQL `evidence_field_is_immutable(col_name)` que o
trigger poderia usar no futuro para permitir whitelisting selectivo
(ex: se alguma vez quisermos permitir update a `description` para
fixes tipográficos em ambiente staging). Nesta iteração, mantém-se
a abordagem "imutável ao nível da linha": os novos campos são
imutáveis exactamente pelas mesmas razões que os campos originais.

Referência ISO/IEC 27037 § 5.3 — integridade dos metadados de prova.

A migration é no-op em SQLite (testes). Em Postgres cria/substitui
a função auxiliar; o trigger existente continua a ser a garantia
principal.
"""

from django.db import migrations


# Função auxiliar puramente documental — lista os campos imutáveis numa
# estrutura consultável via catálogo. Não é chamada pelo trigger actual;
# fica disponível para futuras políticas de granularidade fina.
EXTEND_IMMUTABILITY_FORWARD_SQL = """
    CREATE OR REPLACE FUNCTION forensiq_evidence_immutable_fields()
    RETURNS TEXT[] AS $$
    BEGIN
        RETURN ARRAY[
            'occurrence_id',
            'type',
            'parent_evidence_id',
            'description',
            'photo',
            'gps_lat',
            'gps_lon',
            'timestamp_seizure',
            'serial_number',
            'agent_id',
            'integrity_hash',
            'type_specific_data',
            'external_lookup_snapshot',
            'external_lookup_source',
            'external_lookup_at',
            'created_at'
        ];
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;

    COMMENT ON FUNCTION forensiq_evidence_immutable_fields() IS
        'ForensiQ ISO/IEC 27037: campos de Evidence cuja modificação '
        'é bloqueada pelo trigger trg_evidence_no_update (migração 0002). '
        'Inclui campos adicionados na migração 0006 (type_specific_data, '
        'parent_evidence, external_lookup_*).';
"""

EXTEND_IMMUTABILITY_REVERSE_SQL = """
    DROP FUNCTION IF EXISTS forensiq_evidence_immutable_fields();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(EXTEND_IMMUTABILITY_FORWARD_SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(EXTEND_IMMUTABILITY_REVERSE_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_create_cache_table'),
    ]

    operations = [
        migrations.RunPython(forward, reverse_code=reverse),
    ]
