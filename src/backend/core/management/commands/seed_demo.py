"""Reset + seed do ambiente de demonstração.

Uso (produção via Fly):

    fly ssh console -C "python manage.py seed_demo --confirm"

Cria 3 utilizadores (AGENT, EXPERT, orientador), 5 ocorrências realistas
com cadeia de custódia em vários estados e 10+ itens. Truncar tabelas
core_* preserva o esquema; auth e migrations ficam intactos.

NÃO mexe em ``/data/media/`` — uma execução posterior do mesmo comando
deixa fotos antigas órfãs. Para limpeza completa use ``--wipe-media``.
"""

from __future__ import annotations

import secrets
import string
import shutil
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    AuditLog,
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
)

User = get_user_model()


def _random_password(length: int = 16) -> str:
    """Password com letras, dígitos e símbolos seguros (sem ambíguos)."""
    alphabet = string.ascii_letters + string.digits + '!@#$%&*'
    while True:
        pw = ''.join(secrets.choice(alphabet) for _ in range(length))
        # Garantir variedade — pelo menos 1 dígito e 1 símbolo.
        if any(c.isdigit() for c in pw) and any(c in '!@#$%&*' for c in pw):
            return pw


class Command(BaseCommand):
    help = 'Reset+seed da BD com utilizadores e casos de demonstração.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm', action='store_true',
            help='Obrigatório — confirma que se aceita perder TODOS os dados.',
        )
        parser.add_argument(
            '--wipe-media', action='store_true',
            help='Apaga também o conteúdo de MEDIA_ROOT/evidencias/.',
        )
        parser.add_argument(
            '--orientador-email', default='pedro.pestana@uab.pt',
            help='Email do orientador (default: pedro.pestana@uab.pt).',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError(
                'Operação destrutiva. Re-corre com --confirm para prosseguir.'
            )

        self.stdout.write(self.style.WARNING('A apagar dados existentes...'))
        with transaction.atomic():
            # Ordem importa por causa das FKs; ChainOfCustody → Evidence →
            # Occurrence; DigitalDevice → Evidence; AuditLog é independente.
            # Modelos imutáveis (ChainOfCustody, Evidence, AuditLog) bloqueiam
            # `.delete()` via override — usar `_raw_delete` para bypass.
            ChainOfCustody.objects.all()._raw_delete(ChainOfCustody.objects.db)
            DigitalDevice.objects.all().delete()
            Evidence.objects.all()._raw_delete(Evidence.objects.db)
            Occurrence.objects.all().delete()
            AuditLog.objects.all()._raw_delete(AuditLog.objects.db)
            User.objects.all().delete()

        if options['wipe_media']:
            media_root = Path(settings.MEDIA_ROOT)
            evidencias_dir = media_root / 'evidencias'
            if evidencias_dir.exists():
                self.stdout.write(self.style.WARNING(
                    f'A apagar fotos em {evidencias_dir}...'
                ))
                shutil.rmtree(evidencias_dir)
                evidencias_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write(self.style.SUCCESS('Tabelas truncadas.'))
        self.stdout.write('A criar utilizadores...')

        # --------------------------------------------------------------
        # 3 utilizadores
        # --------------------------------------------------------------
        users_to_print = []

        agent_pw = _random_password()
        agent = User.objects.create_user(
            username='agente.demo',
            password=agent_pw,
            first_name='João',
            last_name='Silva',
            email='agente.demo@forensiq.pt',
            profile=User.Profile.AGENT,
            badge_number='GNR-12345',
            phone='+351 912 345 678',
        )
        users_to_print.append(('AGENT (first responder)', agent.username, agent_pw))

        expert_pw = _random_password()
        expert = User.objects.create_user(
            username='perito.demo',
            password=expert_pw,
            first_name='Ana',
            last_name='Costa',
            email='perito.demo@forensiq.pt',
            profile=User.Profile.EXPERT,
            badge_number='PJ-LPC-007',
            phone='+351 933 555 010',
        )
        users_to_print.append(('EXPERT (perito forense)', expert.username, expert_pw))

        prof_pw = _random_password()
        prof = User.objects.create_user(
            username='pedro.pestana',
            password=prof_pw,
            first_name='Pedro',
            last_name='Duarte Pestana',
            email=options['orientador_email'],
            profile=User.Profile.EXPERT,
            badge_number='UAB-ORIENT',
            phone='',
            is_staff=True,
            is_superuser=False,
        )
        users_to_print.append(('Orientador (EXPERT + staff)', prof.username, prof_pw))

        # --------------------------------------------------------------
        # 5 ocorrências realistas (datas espaçadas)
        # --------------------------------------------------------------
        self.stdout.write('A criar ocorrências e evidências...')

        now = timezone.now()
        cases = []

        # Caso 1 — assalto à mão armada com tele móvel apreendido (em transporte).
        c1 = Occurrence.objects.create(
            number='NUIPC.812/2026.LISBOA',
            description=(
                'Assalto à mão armada na Av. da Liberdade. Suspeito '
                'detido na fuga, telemóvel apreendido para análise de '
                'comunicações nas 24h precedentes.'
            ),
            date_time=now - timedelta(days=12, hours=4),
            gps_lat=Decimal('38.7197'),
            gps_lon=Decimal('-9.1467'),
            address='Av. da Liberdade 250, Lisboa',
            agent=agent,
        )
        e1a = Evidence.objects.create(
            occurrence=c1, type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='iPhone 15 Pro Max, ecrã ligeiramente fissurado.',
            timestamp_seizure=now - timedelta(days=12, hours=3),
            gps_lat=Decimal('38.7197'), gps_lon=Decimal('-9.1467'),
            serial_number='F2LXV3PJ9K',
            agent=agent,
            type_specific_data={'imei': '353918023456789'},
        )
        e1b = Evidence.objects.create(
            occurrence=c1, type=Evidence.EvidenceType.SIM_CARD,
            description='Cartão SIM (operadora MEO) extraído do telemóvel.',
            parent_evidence=e1a,
            timestamp_seizure=now - timedelta(days=12, hours=3),
            gps_lat=None, gps_lon=None,
            serial_number='8935101234567890123',
            agent=agent,
            type_specific_data={'imsi': '268010012345678'},
        )
        cases.append((c1, [e1a, e1b], [
            ChainOfCustody.CustodyState.APREENDIDA,
            ChainOfCustody.CustodyState.EM_TRANSPORTE,
        ]))

        # Caso 2 — cyberbullying, computador + smartphone (em perícia).
        c2 = Occurrence.objects.create(
            number='NUIPC.0345/2026.PORTO',
            description=(
                'Cyberbullying e ameaças via redes sociais. Computador '
                'portátil e smartphone do suspeito apreendidos com '
                'mandado de busca domiciliária.'
            ),
            date_time=now - timedelta(days=9, hours=2),
            gps_lat=Decimal('41.1496'),
            gps_lon=Decimal('-8.6109'),
            address='Rua de Santa Catarina 215, Porto',
            agent=agent,
        )
        e2a = Evidence.objects.create(
            occurrence=c2, type=Evidence.EvidenceType.COMPUTER,
            description='MacBook Pro 14" 2023, com adesivo "Skull" tampa.',
            timestamp_seizure=now - timedelta(days=9, hours=1),
            gps_lat=Decimal('41.1496'), gps_lon=Decimal('-8.6109'),
            serial_number='C02ABCDEFGHJ',
            agent=agent,
        )
        e2b = Evidence.objects.create(
            occurrence=c2, type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Samsung Galaxy S23, capa preta de silicone.',
            timestamp_seizure=now - timedelta(days=9, hours=1),
            gps_lat=Decimal('41.1496'), gps_lon=Decimal('-8.6109'),
            serial_number='RZ8M407JKLM',
            agent=agent,
            type_specific_data={'imei': '358412345987650'},
        )
        cases.append((c2, [e2a, e2b], [
            ChainOfCustody.CustodyState.APREENDIDA,
            ChainOfCustody.CustodyState.EM_TRANSPORTE,
            ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
            ChainOfCustody.CustodyState.EM_PERICIA,
        ]))

        # Caso 3 — burla informática, drive externa (concluído).
        c3 = Occurrence.objects.create(
            number='NUIPC.1102/2026.COIMBRA',
            description=(
                'Burla informática com phishing bancário. Disco externo '
                'usado para armazenar credenciais comprometidas.'
            ),
            date_time=now - timedelta(days=23, hours=6),
            gps_lat=Decimal('40.2056'),
            gps_lon=Decimal('-8.4197'),
            address='Praça 8 de Maio, Coimbra',
            agent=agent,
        )
        e3 = Evidence.objects.create(
            occurrence=c3, type=Evidence.EvidenceType.STORAGE_MEDIA,
            description='Disco externo Seagate Backup Plus 2 TB, USB 3.0.',
            timestamp_seizure=now - timedelta(days=23, hours=5),
            gps_lat=None, gps_lon=None,
            serial_number='NA8ABCDXYZ',
            agent=agent,
        )
        cases.append((c3, [e3], [
            ChainOfCustody.CustodyState.APREENDIDA,
            ChainOfCustody.CustodyState.EM_TRANSPORTE,
            ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
            ChainOfCustody.CustodyState.EM_PERICIA,
            ChainOfCustody.CustodyState.CONCLUIDA,
        ]))

        # Caso 4 — drone derrubado em zona reservada (em laboratório).
        c4 = Occurrence.objects.create(
            number='NUIPC.205/2026.BRAGA',
            description=(
                'Voo de drone não autorizado sobre instalação militar. '
                'Drone derrubado por contra-medida e cartão SD recuperado.'
            ),
            date_time=now - timedelta(days=4, hours=1),
            gps_lat=Decimal('41.5454'),
            gps_lon=Decimal('-8.4265'),
            address='Quartel-General de Braga',
            agent=agent,
        )
        e4a = Evidence.objects.create(
            occurrence=c4, type=Evidence.EvidenceType.DRONE,
            description='DJI Mavic 3 Pro, danos no propulsor frontal direito.',
            timestamp_seizure=now - timedelta(days=4),
            gps_lat=Decimal('41.5454'), gps_lon=Decimal('-8.4265'),
            serial_number='1581F5A0B0C0D',
            agent=agent,
        )
        e4b = Evidence.objects.create(
            occurrence=c4, type=Evidence.EvidenceType.MEMORY_CARD,
            description='Cartão microSD 256 GB Sandisk Extreme.',
            parent_evidence=e4a,
            timestamp_seizure=now - timedelta(days=4),
            gps_lat=None, gps_lon=None,
            serial_number='SDC0010203',
            agent=agent,
        )
        cases.append((c4, [e4a, e4b], [
            ChainOfCustody.CustodyState.APREENDIDA,
            ChainOfCustody.CustodyState.EM_TRANSPORTE,
            ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
        ]))

        # Caso 5 — viatura com componentes electrónicos (em transporte).
        c5 = Occurrence.objects.create(
            number='NUIPC.1789/2026.FARO',
            description=(
                'Veículo recuperado após furto. Apreendidos a unidade '
                'central infotainment e o tracker GPS encontrado no '
                'porta-luvas (não pertencia ao proprietário original).'
            ),
            date_time=now - timedelta(days=2),
            gps_lat=Decimal('37.0194'),
            gps_lon=Decimal('-7.9304'),
            address='Marina de Faro, Faro',
            agent=agent,
        )
        e5a = Evidence.objects.create(
            occurrence=c5, type=Evidence.EvidenceType.VEHICLE,
            description='Audi A4 Avant 2021, matrícula PT 12-AB-34.',
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=Decimal('37.0194'), gps_lon=Decimal('-7.9304'),
            serial_number='WAUZZZ8E5BA123456',
            agent=agent,
            type_specific_data={'vin': '1HGBH41JXMN109186'},
        )
        e5b = Evidence.objects.create(
            occurrence=c5, type=Evidence.EvidenceType.VEHICLE_COMPONENT,
            description='Unidade infotainment MMI Plus 8.4", número de '
                        'fábrica visível no chassis traseiro.',
            parent_evidence=e5a,
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=None, gps_lon=None,
            serial_number='4M0035043G',
            agent=agent,
        )
        e5c = Evidence.objects.create(
            occurrence=c5, type=Evidence.EvidenceType.GPS_TRACKER,
            description='Localizador GPS magnético, Concox JM-VL01, com '
                        'cartão SIM Vodafone.',
            parent_evidence=e5a,
            timestamp_seizure=now - timedelta(days=2),
            gps_lat=Decimal('37.0194'), gps_lon=Decimal('-7.9304'),
            serial_number='862785043210123',
            agent=agent,
        )
        cases.append((c5, [e5a, e5b, e5c], [
            ChainOfCustody.CustodyState.APREENDIDA,
            ChainOfCustody.CustodyState.EM_TRANSPORTE,
        ]))

        # --------------------------------------------------------------
        # Cadeia de custódia — progredir cada item até ao estado alvo
        # --------------------------------------------------------------
        for occurrence, evidences, target_states in cases:
            for ev in evidences:
                last_ts = ev.timestamp_seizure
                for state in target_states:
                    last_ts = last_ts + timedelta(hours=8)
                    # Forçar timestamp via update após save (modelo usa
                    # timezone.now() do servidor por defeito).
                    record = ChainOfCustody(
                        evidence=ev,
                        new_state=state,
                        agent=expert if state in (
                            ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
                            ChainOfCustody.CustodyState.EM_PERICIA,
                            ChainOfCustody.CustodyState.CONCLUIDA,
                        ) else agent,
                        observations=(
                            f'Transição de demonstração para {state}.'
                        ),
                    )
                    record.save()
                    # Override timestamp para datas históricas plausíveis
                    # (sem afectar hash, recalcula em update).
                    ChainOfCustody.objects.filter(pk=record.pk).update(
                        timestamp=last_ts,
                    )

        # --------------------------------------------------------------
        # Output
        # --------------------------------------------------------------
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('SEED COMPLETO'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        for label, username, pw in users_to_print:
            self.stdout.write(f'{label}')
            self.stdout.write(f'   username: {username}')
            self.stdout.write(f'   password: {pw}')
            self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{len(cases)} ocorrências, '
            f'{sum(len(es) for _, es, _ in cases)} itens, '
            f'{ChainOfCustody.objects.count()} transições de custódia.'
        ))
        self.stdout.write(self.style.WARNING(
            'IMPORTANTE: rotaciona estas passwords após o primeiro login.'
        ))
