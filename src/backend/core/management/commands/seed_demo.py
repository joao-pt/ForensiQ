"""Seed interactivo do ambiente de demonstração.

O comando suporta três modos:

* ``--users-only`` cria/actualiza apenas os dois utilizadores demo
  (perfis AGENT e EXPERT). Idempotente, não destrutivo.
* ``--reset`` apaga TODOS os dados em ``core_*`` e recria utilizadores +
  cinco ocorrências realistas com cadeia de custódia em vários estados.
* Sem flags: comporta-se como ``--reset`` se a base estiver vazia. Se já
  houver dados, falha com instruções claras (evita destruição acidental).

Credenciais para os dois utilizadores são pedidas interactivamente via
prompt (``input()`` para username, ``getpass.getpass()`` para password).
Em ambientes não-interactivos (CI, ``fly ssh console -C "..."``) podem
ser passadas via flags ``--agent-username``, ``--agent-password``,
``--expert-username``, ``--expert-password`` combinadas com ``--no-input``.

Este comando **nunca** cria ou promove superusers — responsabilidade
dissociada por design. Quem precisa de superuser para o ``/admin/``
corre o built-in do Django: ``python manage.py createsuperuser``.

Não mexe em ``MEDIA_ROOT/`` por defeito. Para limpeza completa use
``--reset --wipe-media``.

Exemplos:

    # Local interactivo (modo recomendado):
    python manage.py seed_demo --reset

    # Só utilizadores, sem mexer em dados:
    python manage.py seed_demo --users-only

    # Não-interactivo (CI, Fly):
    python manage.py seed_demo --reset --no-input \\
        --agent-username=ag1 --agent-password=Aa12345! \\
        --expert-username=pe1 --expert-password=Ee12345!
"""

from __future__ import annotations

import getpass
import shutil
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from core.models import (
    AuditLog,
    ChainOfCustody,
    CrimeTipo,
    DigitalDevice,
    Evidence,
    Occurrence,
)

User = get_user_model()


# Paleta de cores por tipo de evidência — coerente com a UI (badges).
# Os hex são usados como fundo das placeholders para distinção visual.
_TYPE_PALETTE = {
    Evidence.EvidenceType.MOBILE_DEVICE: ('#1E3A8A', 'Telemóvel'),
    Evidence.EvidenceType.COMPUTER: ('#166534', 'Computador'),
    Evidence.EvidenceType.STORAGE_MEDIA: ('#5B21B6', 'Armazenamento'),
    Evidence.EvidenceType.DRONE: ('#C2410C', 'Drone'),
    Evidence.EvidenceType.VEHICLE: ('#991B1B', 'Viatura'),
    Evidence.EvidenceType.VEHICLE_COMPONENT: ('#374151', 'Componente'),
    Evidence.EvidenceType.SIM_CARD: ('#0E7490', 'SIM'),
    Evidence.EvidenceType.MEMORY_CARD: ('#0F766E', 'Cartão SD'),
    Evidence.EvidenceType.GPS_TRACKER: ('#A16207', 'GPS Tracker'),
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip('#')
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def _load_font(size: int):
    """Procura uma TTF local; cai para o bitmap default se não houver."""
    for candidate in (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'DejaVuSans-Bold.ttf',
        'DejaVuSans.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/arial.ttf',
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_placeholder_photo(evidence_type: str, label: str, sub: str) -> ContentFile:
    """Gera uma fotografia JPEG simulada (1024x768) para o item demo."""
    color_hex, type_label = _TYPE_PALETTE.get(
        evidence_type,
        ('#1F2937', 'Item de prova'),
    )
    bg = _hex_to_rgb(color_hex)
    img = Image.new('RGB', (1024, 768), color=bg)
    draw = ImageDraw.Draw(img)
    accent = tuple(max(0, c - 40) for c in bg)
    draw.rectangle([(0, 0), (16, 768)], fill=accent)
    f_xl = _load_font(64)
    f_lg = _load_font(36)
    f_md = _load_font(24)
    draw.text((48, 48), type_label.upper(), font=f_md, fill=(255, 255, 255, 200))
    draw.text((48, 96), label, font=f_xl, fill='white')
    draw.text((48, 200), sub[:80], font=f_lg, fill=(255, 255, 255, 220))
    draw.text((48, 700), 'ForensiQ — DEMO (placeholder)', font=f_md, fill=(255, 255, 255, 180))
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=80, optimize=True)
    return ContentFile(buf.getvalue(), name='placeholder.jpg')


class Command(BaseCommand):
    help = (
        'Seed interactivo: cria utilizadores demo (AGENT/EXPERT) e, com '
        '--reset, popula a BD com cinco ocorrências realistas + itens.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Apaga TODOS os dados core_* antes de criar. Operação destrutiva.',
        )
        parser.add_argument(
            '--users-only',
            action='store_true',
            help='Cria/actualiza só os utilizadores demo, sem mexer em ocorrências.',
        )
        parser.add_argument(
            '--wipe-media',
            action='store_true',
            help='Com --reset, apaga também MEDIA_ROOT/evidencias/.',
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Modo não-interactivo; exige todas as flags --agent-* e --expert-*.',
        )
        parser.add_argument('--agent-username', help='Username para o perfil AGENT.')
        parser.add_argument('--agent-password', help='Password para o perfil AGENT.')
        parser.add_argument('--expert-username', help='Username para o perfil EXPERT.')
        parser.add_argument('--expert-password', help='Password para o perfil EXPERT.')

    # ----- entry point -----

    def handle(self, *args, **options):
        self._no_input = options['no_input']
        reset = options['reset']
        users_only = options['users_only']

        if reset and users_only:
            raise CommandError('--reset e --users-only são mutuamente exclusivos.')

        has_data = Occurrence.objects.exists() or Evidence.objects.exists()
        if has_data and not reset and not users_only:
            raise CommandError(
                'Base de dados já contém ocorrências ou itens.\n'
                'Re-corre com:\n'
                '  --reset       para apagar e recriar tudo (destrutivo)\n'
                '  --users-only  para apenas criar/actualizar os utilizadores'
            )

        # Recolha de credenciais (prompts ou flags).
        agent_username = self._get_credential(
            options.get('agent_username'),
            'agent-username',
            'Username para o utilizador AGENT',
            secret=False,
        )
        agent_password = self._get_credential(
            options.get('agent_password'),
            'agent-password',
            'Password para o utilizador AGENT',
            secret=True,
        )
        expert_username = self._get_credential(
            options.get('expert_username'),
            'expert-username',
            'Username para o utilizador EXPERT',
            secret=False,
        )
        expert_password = self._get_credential(
            options.get('expert_password'),
            'expert-password',
            'Password para o utilizador EXPERT',
            secret=True,
        )

        if agent_username == expert_username:
            raise CommandError('Username do AGENT e do EXPERT têm de ser distintos.')

        if reset:
            self._reset_database(wipe_media=options['wipe_media'])

        agent = self._upsert_user(
            username=agent_username,
            password=agent_password,
            profile=User.Profile.AGENT,
            first_name='Agente',
            last_name='Demo',
            email=f'{agent_username}@forensiq.demo',
            badge_number='AGENT-DEMO',
        )
        expert = self._upsert_user(
            username=expert_username,
            password=expert_password,
            profile=User.Profile.EXPERT,
            first_name='Perito',
            last_name='Demo',
            email=f'{expert_username}@forensiq.demo',
            badge_number='EXPERT-DEMO',
        )

        if users_only:
            self._print_summary([agent, expert], cases_created=False)
            return

        # Modo --reset (acabámos de truncar) ou BD vazia → criar cases.
        cases = self._create_cases(agent, expert)
        self._print_summary([agent, expert], cases_created=True, cases=cases)

    # ----- helpers de input -----

    def _get_credential(self, value, flag_name, prompt_label, *, secret):
        if value:
            return value.strip()
        if self._no_input:
            raise CommandError(f'--no-input exige que forneças --{flag_name} via argumento.')
        prompter = getpass.getpass if secret else input
        result = prompter(f'{prompt_label}: ').strip()
        if not result:
            raise CommandError(f'{prompt_label} não pode estar vazio.')
        return result

    # ----- helpers de DB -----

    def _upsert_user(self, *, username, password, **defaults):
        user, created = User.objects.update_or_create(
            username=username,
            defaults={
                **defaults,
                'is_staff': False,
                'is_superuser': False,
                'is_active': True,
            },
        )
        # CWE-521: validar antes de aplicar. Aqui não bloqueia — apenas avisa.
        # A escolha de password fraca é do operador (demo local).
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            self.stdout.write(
                self.style.WARNING(f"AVISO: password de '{username}' não cumpre os validators:")
            )
            for msg in exc.messages:
                self.stdout.write(self.style.WARNING(f'   • {msg}'))
            self.stdout.write(
                self.style.WARNING(
                    '   (Aceite na mesma — assume-se uso em demo, não em produção real.)'
                )
            )
        user.set_password(password)
        user.save(update_fields=['password'])
        verb = 'criado' if created else 'actualizado'
        self.stdout.write(f"   Utilizador '{username}' [{verb}, perfil={defaults['profile']}].")
        return user

    @transaction.atomic
    def _reset_database(self, *, wipe_media):
        self.stdout.write(self.style.WARNING('A apagar dados existentes...'))
        # Em PostgreSQL os triggers BEFORE DELETE (migration 0002) bloqueiam
        # qualquer DELETE — protecção ISO/IEC 27037. TRUNCATE não dispara
        # esses triggers, pelo que serve para o caso de seed/demo.
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("""
                    TRUNCATE TABLE
                        core_chainofcustody,
                        core_digitaldevice,
                        core_evidence,
                        core_occurrence,
                        core_auditlog,
                        core_user
                    RESTART IDENTITY CASCADE
                """)
        else:
            # SQLite (testes) — sem triggers, basta o queryset delete.
            ChainOfCustody.objects.all()._raw_delete(ChainOfCustody.objects.db)
            DigitalDevice.objects.all().delete()
            Evidence.objects.all()._raw_delete(Evidence.objects.db)
            Occurrence.objects.all().delete()
            AuditLog.objects.all()._raw_delete(AuditLog.objects.db)
            User.objects.all().delete()

        if wipe_media:
            media_root = Path(settings.MEDIA_ROOT)
            evidencias_dir = media_root / 'evidencias'
            if evidencias_dir.exists():
                self.stdout.write(self.style.WARNING(f'A apagar fotos em {evidencias_dir}...'))
                shutil.rmtree(evidencias_dir)
                evidencias_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write(self.style.SUCCESS('Tabelas truncadas.'))

    # ----- criação de casos forenses -----

    def _create_cases(self, agent, expert):
        """Cria 5 ocorrências realistas com itens e cadeia de custódia."""
        self.stdout.write('A criar ocorrências e itens...')

        # Dados de referência (taxonomia de crimes + política criminal) — o
        # reset truncou-os; re-semeia, pois a Occurrence exige crime_type
        # (ADR-0014). Idempotente.
        call_command('seed_crime_taxonomy')

        now = timezone.now()
        cases = []

        # Caso 1 — assalto à mão armada com telemóvel apreendido.
        c1 = Occurrence.objects.create(
            number='NUIPC.812/2026.LISBOA',
            crime_type=CrimeTipo.objects.get(codigo=40),  # Roubo na via pública (prioritário)
            description=(
                'Assalto à mão armada na Av. da Liberdade. Suspeito '
                'detido na fuga, telemóvel apreendido para análise de '
                'comunicações nas 24h precedentes.'
            ),
            date_time=now - timedelta(days=12, hours=4),
            gps_lat=Decimal('38.7197'),
            gps_lng=Decimal('-9.1467'),
            address='Av. da Liberdade 250, Lisboa',
            agent=agent,
        )
        e1a = Evidence.objects.create(
            occurrence=c1,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='iPhone 15 Pro Max, ecrã ligeiramente fissurado.',
            timestamp_seizure=now - timedelta(days=12, hours=3),
            gps_lat=Decimal('38.7197'),
            gps_lng=Decimal('-9.1467'),
            serial_number='F2LXV3PJ9K',
            agent=agent,
            type_specific_data={'imei': '353918023456789'},
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.MOBILE_DEVICE,
                'Lisboa · 01',
                'iPhone 15 Pro Max apreendido na Av. da Liberdade.',
            ),
        )
        e1b = Evidence.objects.create(
            occurrence=c1,
            type=Evidence.EvidenceType.SIM_CARD,
            description='Cartão SIM (operadora MEO) extraído do telemóvel.',
            parent_evidence=e1a,
            timestamp_seizure=now - timedelta(days=12, hours=3),
            gps_lat=None,
            gps_lng=None,
            serial_number='8935101234567890123',
            agent=agent,
            type_specific_data={'imsi': '268010012345678'},
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.SIM_CARD,
                'Lisboa · 02',
                'SIM MEO — sub-componente do iPhone.',
            ),
        )
        cases.append(
            (
                c1,
                [e1a, e1b],
                [
                    ChainOfCustody.CustodyState.APREENDIDA,
                    ChainOfCustody.CustodyState.EM_TRANSPORTE,
                ],
            )
        )

        # Caso 2 — cyberbullying, computador + smartphone.
        c2 = Occurrence.objects.create(
            number='NUIPC.0345/2026.PORTO',
            crime_type=CrimeTipo.objects.get(codigo=16),  # Ameaça e coacção
            description=(
                'Cyberbullying e ameaças via redes sociais. Computador '
                'portátil e smartphone do suspeito apreendidos com '
                'mandado de busca domiciliária.'
            ),
            date_time=now - timedelta(days=9, hours=2),
            gps_lat=Decimal('41.1496'),
            gps_lng=Decimal('-8.6109'),
            address='Rua de Santa Catarina 215, Porto',
            agent=agent,
        )
        e2a = Evidence.objects.create(
            occurrence=c2,
            type=Evidence.EvidenceType.COMPUTER,
            description='MacBook Pro 14" 2023, com adesivo "Skull" tampa.',
            timestamp_seizure=now - timedelta(days=9, hours=1),
            gps_lat=Decimal('41.1496'),
            gps_lng=Decimal('-8.6109'),
            serial_number='C02ABCDEFGHJ',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.COMPUTER,
                'Porto · 01',
                'MacBook Pro 14" 2023 — busca domiciliária.',
            ),
        )
        e2b = Evidence.objects.create(
            occurrence=c2,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Samsung Galaxy S23, capa preta de silicone.',
            timestamp_seizure=now - timedelta(days=9, hours=1),
            gps_lat=Decimal('41.1496'),
            gps_lng=Decimal('-8.6109'),
            serial_number='RZ8M407JKLM',
            agent=agent,
            type_specific_data={'imei': '358412345987650'},
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.MOBILE_DEVICE,
                'Porto · 02',
                'Samsung Galaxy S23 do suspeito.',
            ),
        )
        e2c = Evidence.objects.create(
            occurrence=c2,
            type=Evidence.EvidenceType.SIM_CARD,
            description='Cartão SIM (operadora NOS) extraído do Samsung.',
            parent_evidence=e2b,
            timestamp_seizure=now - timedelta(days=9, hours=1),
            gps_lat=None,
            gps_lng=None,
            serial_number='8935106789012345678',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.SIM_CARD,
                'Porto · 03',
                'SIM NOS — sub-componente do Samsung.',
            ),
        )
        cases.append(
            (
                c2,
                [e2a, e2b, e2c],
                [
                    ChainOfCustody.CustodyState.APREENDIDA,
                    ChainOfCustody.CustodyState.EM_TRANSPORTE,
                    ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
                    ChainOfCustody.CustodyState.EM_PERICIA,
                ],
            )
        )

        # Caso 3 — burla informática, drive externa (concluído).
        c3 = Occurrence.objects.create(
            number='NUIPC.1102/2026.COIMBRA',
            crime_type=CrimeTipo.objects.get(codigo=241),  # Burla informática/comunicações
            description=(
                'Burla informática com phishing bancário. Disco externo '
                'usado para armazenar credenciais comprometidas.'
            ),
            date_time=now - timedelta(days=23, hours=6),
            gps_lat=Decimal('40.2056'),
            gps_lng=Decimal('-8.4197'),
            address='Praça 8 de Maio, Coimbra',
            agent=agent,
        )
        e3 = Evidence.objects.create(
            occurrence=c3,
            type=Evidence.EvidenceType.STORAGE_MEDIA,
            description='Disco externo Seagate Backup Plus 2 TB, USB 3.0.',
            timestamp_seizure=now - timedelta(days=23, hours=5),
            gps_lat=None,
            gps_lng=None,
            serial_number='NA8ABCDXYZ',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.STORAGE_MEDIA,
                'Coimbra · 01',
                'Disco externo Seagate 2TB — burla bancária.',
            ),
        )
        cases.append(
            (
                c3,
                [e3],
                [
                    ChainOfCustody.CustodyState.APREENDIDA,
                    ChainOfCustody.CustodyState.EM_TRANSPORTE,
                    ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
                    ChainOfCustody.CustodyState.EM_PERICIA,
                    ChainOfCustody.CustodyState.CONCLUIDA,
                ],
            )
        )

        # Caso 4 — drone derrubado em zona reservada.
        c4 = Occurrence.objects.create(
            number='NUIPC.205/2026.BRAGA',
            crime_type=CrimeTipo.objects.get(codigo=172),  # Outros crimes
            description=(
                'Voo de drone não autorizado sobre instalação militar. '
                'Drone derrubado por contra-medida e cartão SD recuperado.'
            ),
            date_time=now - timedelta(days=4, hours=1),
            gps_lat=Decimal('41.5454'),
            gps_lng=Decimal('-8.4265'),
            address='Quartel-General de Braga',
            agent=agent,
        )
        e4a = Evidence.objects.create(
            occurrence=c4,
            type=Evidence.EvidenceType.DRONE,
            description='DJI Mavic 3 Pro, danos no propulsor frontal direito.',
            timestamp_seizure=now - timedelta(days=4),
            gps_lat=Decimal('41.5454'),
            gps_lng=Decimal('-8.4265'),
            serial_number='1581F5A0B0C0D',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.DRONE,
                'Braga · 01',
                'DJI Mavic 3 Pro — voo não autorizado.',
            ),
        )
        e4b = Evidence.objects.create(
            occurrence=c4,
            type=Evidence.EvidenceType.MEMORY_CARD,
            description='Cartão microSD 256 GB Sandisk Extreme.',
            parent_evidence=e4a,
            timestamp_seizure=now - timedelta(days=4),
            gps_lat=None,
            gps_lng=None,
            serial_number='SDC0010203',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.MEMORY_CARD,
                'Braga · 02',
                'microSD 256 GB recuperado do drone.',
            ),
        )
        cases.append(
            (
                c4,
                [e4a, e4b],
                [
                    ChainOfCustody.CustodyState.APREENDIDA,
                    ChainOfCustody.CustodyState.EM_TRANSPORTE,
                    ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
                ],
            )
        )

        # Caso 5 — viatura com componentes electrónicos.
        c5 = Occurrence.objects.create(
            number='NUIPC.1789/2026.FARO',
            crime_type=CrimeTipo.objects.get(codigo=31),  # Furto de veículo motorizado
            description=(
                'Veículo recuperado após furto. Apreendidos a unidade '
                'central infotainment e o tracker GPS encontrado no '
                'porta-luvas (não pertencia ao proprietário original).'
            ),
            date_time=now - timedelta(days=2),
            gps_lat=Decimal('37.0194'),
            gps_lng=Decimal('-7.9304'),
            address='Marina de Faro, Faro',
            agent=agent,
        )
        e5a = Evidence.objects.create(
            occurrence=c5,
            type=Evidence.EvidenceType.VEHICLE,
            description='Audi A4 Avant 2021, matrícula PT 12-AB-34.',
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=Decimal('37.0194'),
            gps_lng=Decimal('-7.9304'),
            serial_number='WAUZZZ8E5BA123456',
            agent=agent,
            type_specific_data={'vin': '1HGBH41JXMN109186'},
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.VEHICLE,
                'Faro · 01',
                'Audi A4 Avant 2021 — recuperado após furto.',
            ),
        )
        e5b = Evidence.objects.create(
            occurrence=c5,
            type=Evidence.EvidenceType.VEHICLE_COMPONENT,
            description='Unidade infotainment MMI Plus 8.4", número de '
            'fábrica visível no chassis traseiro.',
            parent_evidence=e5a,
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=None,
            gps_lng=None,
            serial_number='4M0035043G',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.VEHICLE_COMPONENT,
                'Faro · 02',
                'Unidade infotainment MMI 8.4".',
            ),
        )
        e5c = Evidence.objects.create(
            occurrence=c5,
            type=Evidence.EvidenceType.GPS_TRACKER,
            description='Localizador GPS magnético, Concox JM-VL01.',
            parent_evidence=e5a,
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=Decimal('37.0194'),
            gps_lng=Decimal('-7.9304'),
            serial_number='862785043210123',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.GPS_TRACKER,
                'Faro · 03',
                'Concox JM-VL01 oculto no porta-luvas.',
            ),
        )
        e5d = Evidence.objects.create(
            occurrence=c5,
            type=Evidence.EvidenceType.SIM_CARD,
            description='Cartão SIM Vodafone M2M usado pelo localizador GPS.',
            parent_evidence=e5c,
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=None,
            gps_lng=None,
            serial_number='8935107654321098765',
            agent=agent,
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.SIM_CARD,
                'Faro · 04',
                'SIM Vodafone — sub-componente do GPS tracker.',
            ),
        )
        cases.append(
            (
                c5,
                [e5a, e5b, e5c, e5d],
                [
                    ChainOfCustody.CustodyState.APREENDIDA,
                    ChainOfCustody.CustodyState.EM_TRANSPORTE,
                ],
            )
        )

        # Cadeia de custódia — progredir cada item até ao estado alvo.
        # ChainOfCustody.timestamp é sempre fixado em save() via
        # timezone.now() (NTP-synced server-side, ISO/IEC 27037).
        # A ordem canónica é dada pelo campo sequence (auto-incrementado).
        lab_states = (
            ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
            ChainOfCustody.CustodyState.EM_PERICIA,
            ChainOfCustody.CustodyState.CONCLUIDA,
        )
        for occurrence, evidences, target_states in cases:
            for ev in evidences:
                for state in target_states:
                    record = ChainOfCustody(
                        evidence=ev,
                        new_state=state,
                        agent=expert if state in lab_states else agent,
                        observations=f'Transição de demonstração para {state}.',
                    )
                    record.save()

        return cases

    # ----- output -----

    def _print_summary(self, users, *, cases_created, cases=None):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('SEED COMPLETO'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        for user in users:
            self.stdout.write(f'   {user.profile:<8}  {user.username}')
        self.stdout.write('')
        if cases_created and cases:
            num_items = sum(len(es) for _, es, _ in cases)
            num_custody = ChainOfCustody.objects.count()
            self.stdout.write(
                self.style.SUCCESS(
                    f'{len(cases)} ocorrências, {num_items} itens, '
                    f'{num_custody} transições de custódia.'
                )
            )
        self.stdout.write('')
        self.stdout.write(
            self.style.WARNING('Para superuser administrativo: `python manage.py createsuperuser`.')
        )
        self.stdout.write(self.style.WARNING('Rotacionar passwords após cessar o uso desta demo.'))
