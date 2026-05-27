"""
ForensiQ — Expurgo de AuditLog para conformidade RGPD Art. 5(1)(e).

O princípio da limitação da conservação exige que dados pessoais
(incluindo logs de acesso a recursos forenses, que contêm IP +
utilizador + tipo de recurso + ID) não sejam mantidos para além do
necessário para a finalidade declarada. Este comando aplica esse
princípio à tabela `core_auditlog`, eliminando registos mais antigos
que o limite definido em `settings.AUDIT_LOG_RETENTION_DAYS`.

Auditoria 2026-05-18 §2 B9 — fechado em Sem.12.

Usage::

    # Dry-run (mostra contagem sem apagar)
    python manage.py purge_audit_logs --dry-run

    # Apaga registos > 365 dias (default), batch de 1000
    python manage.py purge_audit_logs

    # Override de retenção via flag (precedência sobre env var)
    python manage.py purge_audit_logs --older-than=180

    # Cron-friendly (sem prompt interactivo)
    python manage.py purge_audit_logs --no-input

Cron Fly.io: o comando deve correr semanalmente
(``[[scheduled]]`` em `fly.toml` ou via cron interno do Dockerfile).
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import AuditLog


class Command(BaseCommand):
    help = (
        'Expurga registos de AuditLog mais antigos que '
        'AUDIT_LOG_RETENTION_DAYS (default 365). Cumpre RGPD '
        'Art. 5(1)(e) — princípio da limitação da conservação. '
        'Audit 2026-05-18 §2 B9.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--older-than',
            type=int,
            default=None,
            help=(
                'Sobrepõe `settings.AUDIT_LOG_RETENTION_DAYS`. '
                'Mínimo 1 dia (rejeitamos 0 para evitar truncamento acidental).'
            ),
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help=(
                'Tamanho do lote de eliminação (default 1000). Permite que a '
                'operação ceda a outras transacções entre lotes em produção.'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help=(
                'Mostra contagem do que seria apagado sem executar. '
                'Não regista entrada AUDIT_PURGE.'
            ),
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Não pede confirmação interactiva (uso em cron/CI).',
        )

    def handle(self, *args, **options):
        days = options['older_than']
        if days is None:
            days = getattr(settings, 'AUDIT_LOG_RETENTION_DAYS', 365)
        if days < 1:
            raise CommandError(
                f'--older-than={days} é inválido. Mínimo é 1 dia para '
                'evitar truncamento acidental da tabela inteira.'
            )

        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size deve ser >= 1.')

        dry_run = options['dry_run']
        no_input = options['no_input']

        cutoff = timezone.now() - timedelta(days=days)
        qs = AuditLog.objects.filter(timestamp__lt=cutoff)
        # `.count()` é uma query simples sobre o índice `-timestamp`.
        total = qs.count()

        self.stdout.write(
            f'AuditLog retention: cutoff = {cutoff.isoformat()} '
            f'({days} dias). Registos elegíveis: {total}.'
        )

        if total == 0:
            self.stdout.write(self.style.SUCCESS('Nada para apagar.'))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY-RUN] Apagaria {total} registos. '
                    'Nenhum registo AUDIT_PURGE foi criado.'
                )
            )
            return

        if not no_input:
            confirm = input(
                f'Confirma a eliminação de {total} registos de AuditLog '
                f'anteriores a {cutoff.date().isoformat()}? [escreve "sim"]: '
            )
            if confirm.strip().lower() not in ('sim', 'yes', 'y', 's'):
                self.stdout.write(self.style.ERROR('Cancelado.'))
                return

        # Apagamos em lotes — `QuerySet.delete()` faz DELETE SQL directo
        # sem chamar `AuditLog.delete()` da instance (N7 do audit
        # documenta este bypass como aberto; aqui usamo-lo deliberadamente
        # com paper-trail no próprio AuditLog via entrada AUDIT_PURGE).
        started = time.monotonic()
        deleted_total = 0
        while True:
            with transaction.atomic():
                pks = list(
                    AuditLog.objects.filter(timestamp__lt=cutoff).values_list('pk', flat=True)[
                        :batch_size
                    ]
                )
                if not pks:
                    break
                deleted_count, _ = AuditLog.objects.filter(pk__in=pks).delete()
                deleted_total += deleted_count
                self.stdout.write(f'  ...apagados {deleted_total}/{total}')

        elapsed = time.monotonic() - started

        # Meta-auditoria: regista o próprio expurgo no AuditLog.
        # IP `0.0.0.0` é o sentinel usado em audit.py:80 para origem
        # não-HTTP (background job).
        AuditLog.objects.create(
            user=None,
            action=AuditLog.Action.AUDIT_PURGE,
            resource_type=AuditLog.ResourceType.SYSTEM,
            resource_id=0,
            ip_address='0.0.0.0',  # noqa: S104 — sentinel não-HTTP (convenção `audit.py:80`)
            correlation_id='',
            details={
                'deleted_count': deleted_total,
                'cutoff_date': cutoff.isoformat(),
                'retention_days': days,
                'batch_size': batch_size,
                'execution_time_seconds': round(elapsed, 3),
                'reason': 'RGPD Art. 5(1)(e) — limitação da conservação',
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Apagados {deleted_total} registos em {elapsed:.2f}s. '
                'Entrada AUDIT_PURGE criada para meta-auditoria.'
            )
        )
