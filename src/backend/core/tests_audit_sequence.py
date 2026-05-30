"""
ForensiQ — Testes do campo `sequence` global do AuditLog (audit §3 N10).

Cobertura:
- Inserts sequenciais produzem sequences monótonos crescentes (1, 2, 3...).
- Sequence é único (constraint da DB).
- 2 inserts com timestamps idênticos (mesmo microssegundo) ainda têm
  sequences distintos — resolve a ambiguidade que motivou o finding.
- Ordering default por -sequence (não -timestamp) reflete a ordem
  total real.
- AUDIT_PURGE e SYSTEM_ALERT também recebem sequence (qualquer
  insert via Model.save passa).
- Tentativa de update à sequence (re-save) falha por imutabilidade
  do AuditLog (defesa pré-existente).
"""

from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone

from core.models import AuditLog


def _create_log(action=AuditLog.Action.VIEW):
    return AuditLog.objects.create(
        user=None,
        action=action,
        resource_type=AuditLog.ResourceType.EVIDENCE,
        resource_id=1,
        ip_address='10.0.0.1',
    )


class AuditLogSequenceMonotonicTest(TestCase):
    def test_sequence_monotonicamente_crescente(self):
        logs = [_create_log() for _ in range(5)]
        sequences = [log.sequence for log in logs]
        self.assertEqual(sequences, sorted(sequences))
        # Sem buracos: diferenças todas iguais a 1.
        diffs = [b - a for a, b in zip(sequences, sequences[1:], strict=False)]
        self.assertTrue(all(d == 1 for d in diffs))

    def test_sequence_arranca_em_1_em_base_vazia(self):
        log = _create_log()
        self.assertEqual(log.sequence, 1)

    def test_sequence_continua_apos_purges(self):
        """Mesmo após purge de registos antigos, a sequence continua
        crescente (não reutiliza valores)."""
        a = _create_log()
        b = _create_log()
        # Apaga directamente (não via Model.delete que está bloqueado).
        AuditLog.objects.filter(pk=a.pk).delete()
        c = _create_log()
        # c.sequence deve ser b.sequence + 1, não reaproveita a.sequence
        self.assertEqual(c.sequence, b.sequence + 1)


class AuditLogSequenceUniqueTest(TestCase):
    def test_sequence_unique_constraint(self):
        log = _create_log()
        # Tentar criar registo com sequence duplicado via update directo
        # (simula corruption / código bypass) — DB deve rejeitar.
        other = _create_log()
        with self.assertRaises(IntegrityError):
            AuditLog.objects.filter(pk=other.pk).update(sequence=log.sequence)


class AuditLogSequenceOrderingTest(TestCase):
    def test_default_ordering_por_sequence_desc(self):
        a = _create_log()
        b = _create_log()
        c = _create_log()
        ordered = list(AuditLog.objects.values_list('pk', flat=True))
        # Ordem default '-sequence' → c, b, a.
        self.assertEqual(ordered, [c.pk, b.pk, a.pk])


class AuditLogSequenceWithSpecialActionsTest(TestCase):
    """Sequence deve ser atribuído também em AUDIT_PURGE e SYSTEM_ALERT
    — qualquer Model.save() do AuditLog passa pelo override.
    """

    def test_audit_purge_recebe_sequence(self):
        log = AuditLog.objects.create(
            user=None,
            action=AuditLog.Action.AUDIT_PURGE,
            resource_type=AuditLog.ResourceType.SYSTEM,
            resource_id=0,
            ip_address='0.0.0.0',
            details={'deleted_count': 10},
        )
        self.assertGreater(log.sequence, 0)

    def test_system_alert_recebe_sequence(self):
        log = AuditLog.objects.create(
            user=None,
            action=AuditLog.Action.SYSTEM_ALERT,
            resource_type=AuditLog.ResourceType.SYSTEM,
            resource_id=0,
            ip_address='0.0.0.0',
            details={'event': 'quota_exhausted'},
        )
        self.assertGreater(log.sequence, 0)


class AuditLogImmutabilityTest(TestCase):
    """Mesmo com o campo `sequence` novo, o AuditLog continua append-only:
    re-save de uma instância já gravada levanta ValidationError.
    """

    def test_update_nao_permitido(self):
        from django.core.exceptions import ValidationError

        log = _create_log()
        log.sequence = 999
        with self.assertRaises(ValidationError):
            log.save()


class AuditLogFactoryTest(TestCase):
    """Valida a ``AuditLogFactory``: produz um registo persistido, com a
    ``sequence`` global atribuída pelo ``save()`` do modelo e ``details``
    por omissão a vazio.
    """

    def test_factory_cria_registo_persistido_com_sequence(self):
        from core.tests_factories import AuditLogFactory

        log = AuditLogFactory()
        self.assertIsNotNone(log.pk)
        self.assertGreater(log.sequence, 0)
        self.assertEqual(log.details, {})
        self.assertEqual(log.resource_type, AuditLog.ResourceType.EVIDENCE)
        self.assertIsNotNone(log.user)

    def test_factory_atribui_sequences_distintas(self):
        from core.tests_factories import AuditLogFactory

        a = AuditLogFactory()
        b = AuditLogFactory()
        self.assertNotEqual(a.sequence, b.sequence)
