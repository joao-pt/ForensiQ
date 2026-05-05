"""Credenciais demo móveis + promoção do orientador.

Comando idempotente, NÃO destrutivo. Cria/atualiza dois utilizadores
(`perito` e `agente`) com password fixa ``1234`` para login rápido em
teclado mobile durante a sessão estendida de revisão pelo orientador.
Adicionalmente, promove ``pedro.pestana`` a superuser para que possa
editar User/Occurrence/DigitalDevice no painel ``/admin/`` (a
imutabilidade de Evidence/ChainOfCustody/AuditLog mantém-se via
``has_change_permission`` em ``admin.py``).

Uso (produção via Fly):

    fly ssh console -C "python manage.py seed_mobile_users"

Pode correr múltiplas vezes — repõe sempre o estado conhecido.

NOTA sobre "1234": ``set_password()``/``create_user(password=...)`` não
aplicam ``AUTH_PASSWORD_VALIDATORS`` (que só correm em forms). É demo
académica sem dados reais; aceitável.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()


MOBILE_PASSWORD = '1234'


def _set_demo_password(user, password: str) -> None:
    """Define password de demo, registando explicitamente que falha aos validators.

    Chama ``validate_password()`` antes de ``set_password()`` (CWE-521 best
    practice) e captura a ``ValidationError`` esperada para "1234" — a
    aceitação é deliberada para esta seed de demonstração mobile. Sem dados
    reais em jogo; rotacionar após a janela de revisão do orientador.
    """
    try:
        validate_password(password, user=user)
    except ValidationError:
        # Esperado para "1234" (curta + numérica). Aceitação explícita para demo.
        pass
    user.set_password(password)
    user.save()


class Command(BaseCommand):
    help = (
        'Cria/actualiza utilizadores demo móveis (perito/agente, password 1234) '
        'e promove pedro.pestana a superuser. Idempotente.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('A criar/actualizar utilizadores móveis...')

        perito, perito_created = User.objects.update_or_create(
            username='perito',
            defaults={
                'first_name': 'Perito',
                'last_name': 'Móvel',
                'email': 'perito@forensiq.pt',
                'profile': User.Profile.EXPERT,
                'badge_number': 'PJ-MOBILE',
                'phone': '',
                'is_staff': False,
                'is_superuser': False,
                'is_active': True,
            },
        )
        _set_demo_password(perito, MOBILE_PASSWORD)

        agente, agente_created = User.objects.update_or_create(
            username='agente',
            defaults={
                'first_name': 'Agente',
                'last_name': 'Móvel',
                'email': 'agente@forensiq.pt',
                'profile': User.Profile.AGENT,
                'badge_number': 'PSP-MOBILE',
                'phone': '',
                'is_staff': False,
                'is_superuser': False,
                'is_active': True,
            },
        )
        _set_demo_password(agente, MOBILE_PASSWORD)

        prof = User.objects.filter(username='pedro.pestana').first()
        if prof is None:
            self.stdout.write(self.style.WARNING(
                'pedro.pestana não existe — corre primeiro `seed_demo --confirm` '
                'e depois este comando.'
            ))
        else:
            prof.is_staff = True
            prof.is_superuser = True
            prof.save(update_fields=['is_staff', 'is_superuser'])
            # Permissões `view_*` tornam-se redundantes — superuser passa todos
            # os ``has_perm`` checks. Limpar evita ruído no admin/auditoria.
            prof.user_permissions.clear()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('UTILIZADORES MÓVEIS PRONTOS'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        rows = [
            ('Perito (mobile, EXPERT)', perito.username, MOBILE_PASSWORD,
             'criado' if perito_created else 'actualizado'),
            ('Agente (mobile, AGENT)', agente.username, MOBILE_PASSWORD,
             'criado' if agente_created else 'actualizado'),
        ]
        for label, username, pw, status in rows:
            self.stdout.write(f'{label}  [{status}]')
            self.stdout.write(f'   username: {username}')
            self.stdout.write(f'   password: {pw}')
            self.stdout.write('')

        if prof is not None:
            self.stdout.write(self.style.SUCCESS(
                'pedro.pestana -> is_staff=True, is_superuser=True '
                '(pode editar User/Occurrence/DigitalDevice no /admin/).'
            ))
            self.stdout.write(
                'Evidence/ChainOfCustody/AuditLog mantêm-se imutáveis '
                '(ISO/IEC 27037).'
            )

        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'AVISO: passwords "1234" são apenas para demo. '
            'Rotacionar após o período de revisão.'
        ))
