"""
ForensiQ — Testes do management command `purge_audit_logs`.

Cobertura da auditoria 2026-05-18 §2 B9 (fechado em Sem.12):
- Apaga registos > cutoff.
- Não apaga registos recentes.
- Modo dry-run não apaga e não cria meta-auditoria.
- Cria entrada `AUDIT_PURGE`/`SYSTEM` com `details` correctos.
- Idempotente — re-run sem trabalho não falha.
- Rejeita `--older-than=0` (proteção contra truncamento).
- Respeita `--no-input` (cron-friendly).
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import AuditLog, User
from core.tests_factories import AuditLogFactory, backdate


def _make_log(*, days_ago, action=AuditLog.Action.VIEW):
    """AuditLog retrodatado — criação e retrodatar nas fontes únicas
    (AuditLogFactory + backdate — auditoria D108)."""
    log = AuditLogFactory(user=None, action=action, resource_id=1, ip_address='10.0.0.1')
    return backdate(log, days=days_ago)


class PurgeAuditLogsTest(TestCase):
    """Cenários básicos de apagamento."""

    def setUp(self):
        # 3 antigos (400 dias) + 2 recentes (30 dias)
        self.old_logs = [_make_log(days_ago=400) for _ in range(3)]
        self.recent_logs = [_make_log(days_ago=30) for _ in range(2)]

    def test_purge_apaga_apenas_antigos(self):
        out = StringIO()
        call_command('purge_audit_logs', '--no-input', stdout=out)

        # Os 3 antigos foram apagados; os 2 recentes permanecem.
        for log in self.old_logs:
            self.assertFalse(AuditLog.objects.filter(pk=log.pk).exists())
        for log in self.recent_logs:
            self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())

    def test_purge_cria_entrada_meta_auditoria(self):
        call_command('purge_audit_logs', '--no-input', stdout=StringIO())

        meta = AuditLog.objects.filter(action=AuditLog.Action.AUDIT_PURGE)
        self.assertEqual(meta.count(), 1)
        entry = meta.first()
        self.assertEqual(entry.resource_type, AuditLog.ResourceType.SYSTEM)
        self.assertEqual(entry.resource_id, 0)
        self.assertEqual(entry.details['deleted_count'], 3)
        self.assertEqual(entry.details['retention_days'], 365)
        self.assertIn('cutoff_date', entry.details)
        self.assertIn('execution_time_seconds', entry.details)

    def test_idempotente(self):
        call_command('purge_audit_logs', '--no-input', stdout=StringIO())
        # 2ª execução: nada para apagar (os recentes ainda não vencem
        # e a entrada AUDIT_PURGE acabada de criar é recente).
        out = StringIO()
        call_command('purge_audit_logs', '--no-input', stdout=out)
        self.assertIn('Nada para apagar', out.getvalue())


class PurgeDryRunTest(TestCase):
    def setUp(self):
        self.old_logs = [_make_log(days_ago=400) for _ in range(3)]

    def test_dry_run_nao_apaga(self):
        out = StringIO()
        call_command('purge_audit_logs', '--dry-run', '--no-input', stdout=out)

        for log in self.old_logs:
            self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())
        self.assertIn('DRY-RUN', out.getvalue())
        self.assertIn('Apagaria 3 registos', out.getvalue())

    def test_dry_run_nao_cria_meta_auditoria(self):
        call_command('purge_audit_logs', '--dry-run', '--no-input', stdout=StringIO())
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.AUDIT_PURGE).exists())


class PurgeArgsTest(TestCase):
    def test_older_than_zero_rejeitado(self):
        with self.assertRaises(CommandError) as ctx:
            call_command('purge_audit_logs', '--older-than=0', '--no-input')
        self.assertIn('Mínimo é 1 dia', str(ctx.exception))

    def test_batch_size_zero_rejeitado(self):
        with self.assertRaises(CommandError):
            call_command('purge_audit_logs', '--batch-size=0', '--no-input')

    def test_older_than_override(self):
        _make_log(days_ago=10)  # recente para default 365, antigo para --older-than=5
        _make_log(days_ago=1)  # sempre recente
        out = StringIO()
        call_command('purge_audit_logs', '--older-than=5', '--no-input', stdout=out)
        # 1 elegível para apagar
        self.assertIn('Registos elegíveis: 1', out.getvalue())

    @override_settings(AUDIT_LOG_RETENTION_DAYS=7)
    def test_setting_respeitado(self):
        _make_log(days_ago=10)
        _make_log(days_ago=3)
        out = StringIO()
        call_command('purge_audit_logs', '--no-input', stdout=out)
        self.assertIn('7 dias', out.getvalue())


class PurgeBatchingTest(TestCase):
    def test_batch_size_pequeno_apaga_tudo(self):
        for _ in range(7):
            _make_log(days_ago=400)
        call_command(
            'purge_audit_logs',
            '--batch-size=2',
            '--no-input',
            stdout=StringIO(),
        )
        self.assertEqual(
            AuditLog.objects.exclude(action=AuditLog.Action.AUDIT_PURGE).count(),
            0,
        )


class AuditPurgeImmutableTest(TestCase):
    """Defesa em profundidade: o registo AUDIT_PURGE em si é imutável
    (mesmo regime do resto do AuditLog — `save()` bloqueia updates).
    """

    def setUp(self):
        # Cria um utilizador para satisfazer FK em testes futuros se necessário
        self.user = User.objects.create_user(username='ag_imm', password='Pwd12345!')
        _make_log(days_ago=400)
        call_command('purge_audit_logs', '--no-input', stdout=StringIO())

    def test_audit_purge_entry_nao_pode_ser_actualizado(self):
        from django.core.exceptions import ValidationError

        entry = AuditLog.objects.get(action=AuditLog.Action.AUDIT_PURGE)
        entry.details = {'tampered': True}
        with self.assertRaises(ValidationError):
            entry.save()
