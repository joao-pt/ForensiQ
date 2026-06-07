"""Semeia o catálogo editável de tipos de evidência (ADR-0018).

Snapshot inicial a partir do enum canónico ``Evidence.EvidenceType``. A partir
daqui a fonte dos rótulos/ordem/estado é a TABELA ``EvidenceTypeRef`` (editável
no admin, sem deploy); o enum permanece apenas como constantes de ramificação
(tipos-folha, génese) e como origem deste seed. Idempotente.
"""

from django.db import migrations


def seed_types(apps, schema_editor):
    from core.models import Evidence  # enum canónico (constante, não toca na BD)

    EvidenceTypeRef = apps.get_model('core', 'EvidenceTypeRef')
    for order, (code, label) in enumerate(Evidence.EvidenceType.choices):
        EvidenceTypeRef.objects.update_or_create(
            code=code,
            defaults={'label': label, 'order': order, 'is_active': True},
        )


def unseed_types(apps, schema_editor):
    EvidenceTypeRef = apps.get_model('core', 'EvidenceTypeRef')
    EvidenceTypeRef.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_evidencetyperef_alter_evidence_type'),
    ]

    operations = [
        migrations.RunPython(seed_types, unseed_types),
    ]
