"""Seed interactivo do ambiente de demonstração.

O comando suporta três modos:

* ``--users-only`` cria/actualiza apenas os dois utilizadores demo
  (FIRST_RESPONDER e FORENSIC_EXPERT) e as instituições base. Idempotente,
  não destrutivo.
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
import hashlib
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
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Occurrence,
    Portador,
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
        'Seed interactivo: cria utilizadores demo (FIRST_RESPONDER/'
        'FORENSIC_EXPERT) + instituições e, com --reset, popula a BD com '
        'cinco ocorrências realistas + itens.'
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
        parser.add_argument(
            '--demo-password',
            default='Forensiq#Demo2026',
            help=(
                'Password (DEMONSTRAÇÃO, não-produção) partilhada pelo roster de '
                'utilizadores por instituição. Tem default conhecido para a demo; '
                'substitua-a (ou use credenciais por utilizador) em qualquer uso real.'
            ),
        )

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

        demo_password = (options.get('demo_password') or 'Forensiq#Demo2026').strip()

        if agent_username == expert_username:
            raise CommandError('Username do AGENT e do EXPERT têm de ser distintos.')

        if reset:
            self._reset_database(wipe_media=options['wipe_media'])

        agent = self._upsert_user(
            username=agent_username,
            password=agent_password,
            profile=User.Profile.FIRST_RESPONDER,
            clearance=User.Clearance.NORMAL,
            first_name='Agente',
            last_name='Demo',
            email=f'{agent_username}@forensiq.demo',
            badge_number='AGENT-DEMO',
        )
        expert = self._upsert_user(
            username=expert_username,
            password=expert_password,
            profile=User.Profile.FORENSIC_EXPERT,
            clearance=User.Clearance.NACIONAL,
            first_name='Perito',
            last_name='Demo',
            email=f'{expert_username}@forensiq.demo',
            badge_number='EXPERT-DEMO',
        )

        # Organização (ADR-0017): instituições custódias básicas + pertenças.
        institutions = self._seed_organizations(agent, expert)

        # Roster de demonstração: VÁRIOS utilizadores por instituição, cobrindo os
        # 6 papéis do ADR-0017 em várias cidades/serviços. Sem isto a demo só tinha
        # um agente e um perito; assim exibe o modelo função+credencial+instituição
        # com pluralidade realista (várias esquadras, laboratórios, DIAP, tribunal).
        extra = self._seed_org_roster(institutions, demo_password)
        all_users = [agent, expert] + extra

        if users_only:
            self._print_summary(all_users, cases_created=False)
            return

        # Modo --reset (acabámos de truncar) ou BD vazia → criar cases.
        cases = self._create_cases(agent, expert, institutions)
        self._print_summary(all_users, cases_created=True, cases=cases)

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

    def _seed_organizations(self, agent, expert):
        """Cria instituições custódias básicas e liga os utilizadores (ADR-0017).

        A custódia é institucional: o agente pertence a um OPC, o perito a um
        laboratório público. Tribunal e serviço do MP ficam disponíveis para
        os fluxos de encaminhamento/validação. Idempotente.
        """
        # Instituições REAIS do sistema de justiça/forense português (nomes
        # oficiais, moradas e contactos públicos das páginas institucionais;
        # GPS geocodificado via OpenStreetMap/Nominatim e verificado). A operação
        # (casos, prova, pessoas) é fictícia — só a REFERÊNCIA é real, para a
        # simulação dar um retrato fiel. As siglas são chaves de junção internas:
        # PSP-LSB/LPC/TJ-LSB são usadas por _create_cases; o roster liga-se por
        # sigla. A instituição fixa fornece a coordenada da RECEÇÃO (ADR-0016 v2),
        # por isso cada uma traz lat/lng a 7 casas. Co-localizações são reais (a
        # PJ-LSB, o LPC e o GRA partilham a sede da PJ; o Campus da Justiça reúne
        # o tribunal criminal, o DIAP Regional e o GAB).
        specs = [
            # --- OPC — Órgãos de polícia criminal ---
            {
                'name': 'Polícia Judiciária — Diretoria de Lisboa e Vale do Tejo',
                'type': InstitutionType.OPC, 'sigla': 'PJ-LSB',
                'address': 'Rua Gomes Freire 174, 1169-007 Lisboa',
                'gps_lat': Decimal('38.7242504'), 'gps_lng': Decimal('-9.1400002'),
                'email': 'directoria.lisboa@pj.pt', 'phone': '+351 211 967 000',
            },
            {
                'name': 'Polícia Judiciária — Diretoria do Norte',
                'type': InstitutionType.OPC, 'sigla': 'PJ-PRT',
                'address': 'Rua Assis Vaz 113, 4200-096 Porto',
                'gps_lat': Decimal('41.1686723'), 'gps_lng': Decimal('-8.5949168'),
                'email': 'directoria.porto@pj.pt', 'phone': '+351 225 582 000',
            },
            {
                'name': 'Polícia de Segurança Pública — Comando Metropolitano de Lisboa',
                'type': InstitutionType.OPC, 'sigla': 'PSP-LSB',
                'address': 'Avenida de Moscavide 88, 1886-502 Moscavide',
                'gps_lat': Decimal('38.7807906'), 'gps_lng': Decimal('-9.1022257'),
                'email': 'cmlisboa@psp.pt', 'phone': '+351 217 654 242',
            },
            {
                'name': 'Polícia de Segurança Pública — Comando Metropolitano do Porto',
                'type': InstitutionType.OPC, 'sigla': 'PSP-PRT',
                'address': 'Largo 1.º de Dezembro, 4000-404 Porto',
                'gps_lat': Decimal('41.1428407'), 'gps_lng': Decimal('-8.6090011'),
                'email': 'cmporto@psp.pt', 'phone': '+351 222 092 000',
            },
            {
                'name': 'Guarda Nacional Republicana — Comando-Geral',
                'type': InstitutionType.OPC, 'sigla': 'GNR',
                'address': 'Largo do Carmo, 1200-092 Lisboa',
                'gps_lat': Decimal('38.7119294'), 'gps_lng': Decimal('-9.1408449'),
                'email': 'gnr@gnr.pt', 'phone': '+351 213 217 000',
            },
            # --- LAB_PUBLICO — Laboratórios públicos ---
            {
                'name': 'Laboratório de Polícia Científica da Polícia Judiciária',
                'type': InstitutionType.LAB_PUBLICO, 'sigla': 'LPC',
                'address': 'Rua Gomes Freire, 1169-007 Lisboa',
                'gps_lat': Decimal('38.7242504'), 'gps_lng': Decimal('-9.1400002'),
                'email': 'direccao.lpc@pj.pt', 'phone': '+351 211 967 000',
            },
            {
                'name': 'Instituto Nacional de Medicina Legal e Ciências Forenses, I.P. '
                        '— Delegação do Norte',
                'type': InstitutionType.LAB_PUBLICO, 'sigla': 'INMLCF-N',
                'address': 'Jardim Carrilho Videira, 4050-167 Porto',
                'gps_lat': Decimal('41.1481278'), 'gps_lng': Decimal('-8.6182326'),
                # Email geral do INMLCF (correio@inmlcf.mj.pt), confirmado em
                # justica.gov.pt. As delegações não publicam email próprio em texto
                # aberto; usa-se o contacto institucional geral nas três.
                'email': 'correio@inmlcf.mj.pt', 'phone': '+351 222 073 850',
            },
            {
                'name': 'Instituto Nacional de Medicina Legal e Ciências Forenses, I.P. '
                        '— Delegação do Centro',
                'type': InstitutionType.LAB_PUBLICO, 'sigla': 'INMLCF-C',
                'address': 'Pólo das Ciências da Saúde (Pólo III), Azinhaga de Santa Comba, '
                           '3000-548 Coimbra',
                # GPS corrigido na verificação: o ponto original caía na Baixa; este
                # resolve o campus Pólo III (Montes Claros), coerente com 3000-548.
                'gps_lat': Decimal('40.2194533'), 'gps_lng': Decimal('-8.4176226'),
                'email': 'correio@inmlcf.mj.pt', 'phone': '+351 239 854 220',
            },
            {
                'name': 'Instituto Nacional de Medicina Legal e Ciências Forenses, I.P. '
                        '— Delegação do Sul',
                'type': InstitutionType.LAB_PUBLICO, 'sigla': 'INMLCF-S',
                'address': 'Rua Manuel Bento de Sousa, n.º 3, 1169-201 Lisboa',
                'gps_lat': Decimal('38.7197895'), 'gps_lng': Decimal('-9.1381493'),
                'email': 'correio@inmlcf.mj.pt', 'phone': '+351 218 811 800',
            },
            # --- LAB_PRIVADO — Laboratórios privados ---
            {
                'name': 'Foren — Perícias Técnico-Científicas e Consultoria em Ciências Forenses',
                'type': InstitutionType.LAB_PRIVADO, 'sigla': 'FOREN',
                'address': 'Avenida Dr. Mário Moutinho 33-A, 1400-136 Lisboa',
                'gps_lat': Decimal('38.7121529'), 'gps_lng': Decimal('-9.2124609'),
                'email': 'info@foren.pt', 'phone': '+351 211 972 079',
            },
            {
                'name': 'Código ADN — Centro de Genética e Vida',
                'type': InstitutionType.LAB_PRIVADO, 'sigla': 'CODIGO-ADN',
                'address': 'Praça Mouzinho de Albuquerque 113, 5.º, 4100-359 Porto',
                'gps_lat': Decimal('41.1579217'), 'gps_lng': Decimal('-8.6291209'),
                'email': 'info@codigoadn.pt', 'phone': '+351 220 417 190',
            },
            {
                'name': 'Ncforenses — Ciências Forenses, Lda.',
                'type': InstitutionType.LAB_PRIVADO, 'sigla': 'NCFORENSES',
                'address': 'Rua de Pinto Bessa, n.º 522, R/C Esq., 4300-428 Porto',
                # Morada/GPS corrigidos na verificação: o site oficial (ncforenses.pt)
                # e os registos públicos indicam Rua de Pinto Bessa 522 (4300-428 Porto),
                # não Visconde de Bóbeda; GPS geocodificado ao nº 522 (Nominatim/OSM).
                'gps_lat': Decimal('41.1504842'), 'gps_lng': Decimal('-8.5918897'),
                'email': 'geral@ncforenses.pt', 'phone': '+351 224 022 684',
            },
            # --- TRIBUNAL ---
            {
                'name': 'Juízo Central Criminal de Lisboa (Tribunal Judicial da Comarca '
                        'de Lisboa) — Campus de Justiça',
                'type': InstitutionType.TRIBUNAL, 'sigla': 'TJ-LSB',
                'address': 'Avenida D. João II, n.º 1.08.01, Edifício A, 1990-097 Lisboa',
                'gps_lat': Decimal('38.7625153'), 'gps_lng': Decimal('-9.0983215'),
                'email': 'lisboa.centralcriminal@tribunais.org.pt', 'phone': '+351 213 218 300',
            },
            {
                'name': 'Tribunal Judicial da Comarca do Porto — Palácio da Justiça',
                'type': InstitutionType.TRIBUNAL, 'sigla': 'TJ-PRT',
                'address': 'Campo dos Mártires da Pátria, 4099-012 Porto',
                'gps_lat': Decimal('41.1452814'), 'gps_lng': Decimal('-8.6174251'),
                'email': 'porto.judicial@tribunais.org.pt', 'phone': '+351 220 949 400',
            },
            {
                'name': 'Tribunal Judicial da Comarca de Coimbra — Juízo Local Criminal',
                'type': InstitutionType.TRIBUNAL, 'sigla': 'TJ-CBR',
                'address': 'Palácio da Justiça, Rua da Sofia, 3000-389 Coimbra',
                'gps_lat': Decimal('40.2130436'), 'gps_lng': Decimal('-8.4307168'),
                'email': 'coimbra.ministeriopublico@tribunais.org.pt', 'phone': '+351 239 852 950',
            },
            {
                'name': 'Tribunal Judicial da Comarca de Faro — Núcleo de Faro',
                'type': InstitutionType.TRIBUNAL, 'sigla': 'TJ-FAR',
                'address': 'Rua Pedro Nunes, 8-10, 3.º Andar, 8000-405 Faro',
                'gps_lat': Decimal('37.0174374'), 'gps_lng': Decimal('-7.9241627'),
                'email': 'faro.judicial@tribunais.org.pt', 'phone': '+351 289 892 900',
            },
            # --- MP — Ministério Público ---
            {
                'name': 'Departamento de Investigação e Ação Penal Regional de Lisboa',
                'type': InstitutionType.MP, 'sigla': 'DIAP-LSB',
                'address': 'Avenida D. João II, n.º 1.08.01, Edifícios C, D e E, 1990-097 Lisboa',
                'gps_lat': Decimal('38.7620161'), 'gps_lng': Decimal('-9.0984064'),
                'email': 'lisboa.diapregional@tribunais.org.pt', 'phone': '+351 213 188 600',
            },
            {
                'name': 'Departamento de Investigação e Ação Penal Regional do Porto',
                'type': InstitutionType.MP, 'sigla': 'DIAP-PRT',
                'address': 'Rua de Camões, 155, 4049-074 Porto',
                'gps_lat': Decimal('41.1532754'), 'gps_lng': Decimal('-8.6103149'),
                'email': 'porto.diapregional@tribunais.org.pt', 'phone': '+351 225 513 510',
            },
            {
                'name': 'Departamento de Investigação e Ação Penal Regional de Coimbra',
                'type': InstitutionType.MP, 'sigla': 'DIAP-CBR',
                'address': 'Rua da Sofia, n.º 175-4.º, 3004-502 Coimbra',
                'gps_lat': Decimal('40.2136438'), 'gps_lng': Decimal('-8.4315312'),
                'email': 'coimbra.diapregional@tribunais.org.pt', 'phone': '+351 239 852 260',
            },
            {
                'name': 'Procuradoria da República da Comarca de Braga',
                'type': InstitutionType.MP, 'sigla': 'PR-BRAGA',
                'address': 'Praça da Justiça, 4719-004 Braga',
                'gps_lat': Decimal('41.5481782'), 'gps_lng': Decimal('-8.4125099'),
                'email': 'braga.ministeriopublico@tribunais.org.pt', 'phone': '+351 253 081 110',
            },
            # --- DEPOSITARIO — Depositários de bens apreendidos ---
            {
                'name': 'Gabinete de Recuperação de Ativos',
                'type': InstitutionType.DEPOSITARIO, 'sigla': 'GRA',
                'address': 'Rua Gomes Freire, n.º 174, 1169-007 Lisboa',
                'gps_lat': Decimal('38.7242504'), 'gps_lng': Decimal('-9.1400002'),
                'email': 'gra@pj.pt', 'phone': '+351 211 967 000',
            },
            {
                'name': 'Autoridade Tributária e Aduaneira',
                'type': InstitutionType.DEPOSITARIO, 'sigla': 'AT',
                'address': 'Rua da Prata, n.º 10, 1149-027 Lisboa',
                'gps_lat': Decimal('38.7088122'), 'gps_lng': Decimal('-9.1359944'),
                # Email deliberadamente vazio: a AT não publica um email institucional
                # geral — o contacto faz-se por e-balcão/formulário no Portal das
                # Finanças. Não se inventa um endereço (campo opcional).
                'email': '', 'phone': '+351 218 812 600',
            },
            {
                'name': 'Gabinete de Administração de Bens',
                'type': InstitutionType.DEPOSITARIO, 'sigla': 'GAB',
                'address': 'Avenida D. João II, Lote 1.08.01 D – Edifício H, '
                           'Campus da Justiça, 1990-097 Lisboa',
                'gps_lat': Decimal('38.7620161'), 'gps_lng': Decimal('-9.0984064'),
                'email': 'correio@igfej.mj.pt', 'phone': '+351 217 907 700',
            },
        ]
        institutions = {}
        for spec in specs:
            inst, _ = Institution.objects.update_or_create(
                name=spec['name'],
                type=spec['type'],
                defaults={
                    'sigla': spec['sigla'],
                    'is_active': True,
                    'address': spec['address'],
                    'gps_lat': spec['gps_lat'],
                    'gps_lng': spec['gps_lng'],
                    'email': spec['email'],
                    'phone': spec['phone'],
                },
            )
            institutions[spec['sigla']] = inst

        for user, inst in ((agent, institutions['PSP-LSB']), (expert, institutions['LPC'])):
            InstitutionMembership.objects.update_or_create(
                user=user,
                institution=inst,
                defaults={'is_active': True},
            )
        self.stdout.write(
            f'   Instituições: {len(institutions)} criadas/actualizadas; '
            f'pertenças: {agent.username}@PSP-LSB, {expert.username}@LPC.'
        )
        return institutions

    def _seed_org_roster(self, institutions, password):
        """Provisiona VÁRIOS utilizadores por instituição (demo, ADR-0017).

        Cobre os 6 papéis (FIRST_RESPONDER, FORENSIC_EXPERT, EVIDENCE_CUSTODIAN,
        CASE_AUTHORITY, CHEFE_SERVICO, AUDITOR) em várias organizações/cidades,
        com várias contas por organização. Todos com a MESMA password de
        DEMONSTRAÇÃO (``password``, não-produção, impressa no resumo). Idempotente
        (upsert por username); cada utilizador é ligado à sua instituição.

        Notas de modelagem para a demo do controlo de acesso:
        - inclui peritos com credencial NORMAL (perito.lpc2, perito.priv1) para
          exibir a leitura total do perito POR FUNÇÃO (Emenda ADR-0017 2026-06-05);
        - chefes/auditor/MP têm credencial NACIONAL (leitura nacional).
        """
        P = User.Profile
        C = User.Clearance
        # sigla -> [(username, profile, clearance, first_name, last_name, badge), ...]
        # Cada uma das 23 instituições recebe pelo menos um utilizador, com o(s)
        # papel(éis) coerente(s) com o seu tipo (ADR-0017): OPC→agente+chefia,
        # LAB→perito/legista (+custódio nos públicos), MP→procurador,
        # TRIBUNAL→escrivão (cofre), DEPOSITÁRIO→gestor de bens apreendidos.
        roster = [
            # --- OPC (órgãos de polícia criminal) ---
            ('PJ-LSB', [
                ('inspetor.pj.lsb', P.FIRST_RESPONDER, C.NORMAL, 'Bruno', 'Carvalho', 'PJ-LSB-101'),
                ('coord.pj.lsb', P.CHEFE_SERVICO, C.NACIONAL, 'Sandra', 'Esteves', 'PJ-LSB-CH'),
            ]),
            ('PJ-PRT', [
                ('inspetor.pj.prt', P.FIRST_RESPONDER, C.NORMAL, 'Hugo', 'Macedo', 'PJ-PRT-201'),
                ('coord.pj.prt', P.CHEFE_SERVICO, C.NACIONAL, 'Raquel', 'Barbosa', 'PJ-PRT-CH'),
            ]),
            ('PSP-LSB', [
                ('agente.lsb1', P.FIRST_RESPONDER, C.NORMAL, 'Rui', 'Almeida', 'PSP-LSB-101'),
                ('agente.lsb2', P.FIRST_RESPONDER, C.NORMAL, 'Sofia', 'Marques', 'PSP-LSB-102'),
                ('chefe.lsb', P.CHEFE_SERVICO, C.NACIONAL, 'Helena', 'Costa', 'PSP-LSB-CH'),
            ]),
            ('PSP-PRT', [
                ('agente.prt1', P.FIRST_RESPONDER, C.NORMAL, 'Tiago', 'Ferreira', 'PSP-PRT-201'),
                ('agente.prt2', P.FIRST_RESPONDER, C.NORMAL, 'Inês', 'Pinto', 'PSP-PRT-202'),
                ('chefe.prt', P.CHEFE_SERVICO, C.NACIONAL, 'Paulo', 'Sousa', 'PSP-PRT-CH'),
            ]),
            ('GNR', [
                ('agente.gnr1', P.FIRST_RESPONDER, C.NORMAL, 'Carla', 'Nunes', 'GNR-301'),
                ('chefe.gnr', P.CHEFE_SERVICO, C.NACIONAL, 'Mário', 'Lopes', 'GNR-CH'),
            ]),
            # --- LAB_PUBLICO (laboratórios públicos) ---
            ('LPC', [
                ('perito.lpc1', P.FORENSIC_EXPERT, C.NACIONAL, 'André', 'Reis', 'LPC-E1'),
                ('perito.lpc2', P.FORENSIC_EXPERT, C.NORMAL, 'Beatriz', 'Cardoso', 'LPC-E2'),
                ('custodio.lpc', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Jorge', 'Tavares', 'LPC-CUS'),
            ]),
            ('INMLCF-N', [
                ('legista.inml.n', P.FORENSIC_EXPERT, C.NORMAL, 'Vasco', 'Teixeira', 'INML-N-E1'),
            ]),
            ('INMLCF-C', [
                ('legista.inml.c', P.FORENSIC_EXPERT, C.NORMAL, 'Marta', 'Figueiredo', 'INML-C-E1'),
            ]),
            ('INMLCF-S', [
                ('legista.inml.s', P.FORENSIC_EXPERT, C.NACIONAL, 'Luís', 'Henriques', 'INML-S-E1'),
            ]),
            # --- LAB_PRIVADO (laboratórios privados) ---
            ('FOREN', [
                ('perito.priv1', P.FORENSIC_EXPERT, C.NORMAL, 'Núria', 'Gomes', 'PRIV-E1'),
                ('custodio.priv', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Diogo', 'Antunes', 'PRIV-CUS'),
            ]),
            ('CODIGO-ADN', [
                ('perito.adn', P.FORENSIC_EXPERT, C.NORMAL, 'Catarina', 'Morais', 'ADN-E1'),
            ]),
            ('NCFORENSES', [
                ('perito.ncf', P.FORENSIC_EXPERT, C.NORMAL, 'Filipe', 'Cordeiro', 'NCF-E1'),
            ]),
            # --- MP (Ministério Público) ---
            ('DIAP-LSB', [
                ('mp.lsb1', P.CASE_AUTHORITY, C.NACIONAL, 'Teresa', 'Lima', 'MP-LSB-1'),
                ('mp.lsb2', P.CASE_AUTHORITY, C.NACIONAL, 'Ricardo', 'Matos', 'MP-LSB-2'),
            ]),
            ('DIAP-PRT', [
                ('mp.prt1', P.CASE_AUTHORITY, C.NACIONAL, 'Cláudia', 'Rocha', 'MP-PRT-1'),
            ]),
            ('DIAP-CBR', [
                ('mp.cbr1', P.CASE_AUTHORITY, C.NACIONAL, 'Gonçalo', 'Freitas', 'MP-CBR-1'),
            ]),
            ('PR-BRAGA', [
                ('mp.braga1', P.CASE_AUTHORITY, C.NACIONAL, 'Susana', 'Maia', 'MP-BRG-1'),
            ]),
            # --- TRIBUNAL (escrivães / cofre do tribunal) ---
            ('TJ-LSB', [
                ('escrivao.tj', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Manuel', 'Cunha', 'TJ-LSB-ESC'),
            ]),
            ('TJ-PRT', [
                ('escrivao.tj.prt', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Anabela', 'Pereira', 'TJ-PRT-ESC'),
            ]),
            ('TJ-CBR', [
                ('escrivao.tj.cbr', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Nuno', 'Faria', 'TJ-CBR-ESC'),
            ]),
            ('TJ-FAR', [
                ('escrivao.tj.far', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Patrícia', 'Vieira', 'TJ-FAR-ESC'),
            ]),
            # --- DEPOSITARIO (gestores de bens apreendidos) ---
            ('GRA', [
                ('gestor.gra', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Fernando', 'Lourenço', 'GRA-CUS'),
            ]),
            ('AT', [
                ('deposit.at', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Isabel', 'Ramos', 'AT-CUS'),
            ]),
            ('GAB', [
                ('gestor.gab', P.EVIDENCE_CUSTODIAN, C.NORMAL, 'Ângelo', 'Pacheco', 'GAB-CUS'),
            ]),
        ]

        users = []
        self._roster_by_org = []
        for sigla, members in roster:
            inst = institutions.get(sigla)
            usernames = []
            for username, profile, clearance, fn, ln, badge in members:
                u = self._upsert_user(
                    username=username,
                    password=password,
                    profile=profile,
                    clearance=clearance,
                    first_name=fn,
                    last_name=ln,
                    email=f'{username}@forensiq.demo',
                    badge_number=badge,
                )
                if inst is not None:
                    InstitutionMembership.objects.update_or_create(
                        user=u, institution=inst, defaults={'is_active': True},
                    )
                users.append(u)
                usernames.append(username)
            self._roster_by_org.append((sigla, usernames))

        # Auditor nacional — supervisão transversal, sem instituição própria.
        auditor = self._upsert_user(
            username='auditor.geral',
            password=password,
            profile=P.AUDITOR,
            clearance=C.NACIONAL,
            first_name='Auditor',
            last_name='Geral',
            email='auditor.geral@forensiq.demo',
            badge_number='AUD-GERAL',
        )
        users.append(auditor)
        self._roster_by_org.append(('(nacional)', ['auditor.geral']))

        self._demo_password = password
        self.stdout.write(
            f'   Roster por instituição: {len(users)} utilizadores demo em '
            f'{len(self._roster_by_org)} grupos.'
        )
        return users

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
                        core_evidence,
                        core_occurrence,
                        core_auditlog,
                        core_institutionmembership,
                        core_institution,
                        core_user
                    RESTART IDENTITY CASCADE
                """)
        else:
            # SQLite (testes) — sem triggers, basta o queryset delete.
            ChainOfCustody.objects.all()._raw_delete(ChainOfCustody.objects.db)
            Evidence.objects.all()._raw_delete(Evidence.objects.db)
            Occurrence.objects.all().delete()
            AuditLog.objects.all()._raw_delete(AuditLog.objects.db)
            User.objects.all().delete()  # cascata remove as pertenças
            Institution.objects.all().delete()

        if wipe_media:
            media_root = Path(settings.MEDIA_ROOT)
            evidencias_dir = media_root / 'evidencias'
            if evidencias_dir.exists():
                self.stdout.write(self.style.WARNING(f'A apagar fotos em {evidencias_dir}...'))
                shutil.rmtree(evidencias_dir)
                evidencias_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write(self.style.SUCCESS('Tabelas truncadas.'))

    # ----- criação de casos forenses -----

    def _create_cases(self, agent, expert, institutions):
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
            bag_number='SACO-2026-0001',
            initial_seal_number='SELO-2026-0001',
            seal_packaging_description='Saco de prova selado no local da apreensão.',
            initial_condition=Evidence.SealCondition.INTACTO,
            sealed_by=agent,
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
        # Sequência de eventos (ledger, ADR-0015): apreendida e validada,
        # ainda à guarda do OPC.
        cases.append(
            (
                c1,
                [e1a, e1b],
                [
                    (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                    (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
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
            bag_number='SACO-2026-0002',
            initial_seal_number='SELO-2026-0002',
            seal_packaging_description='Saco de prova selado no local da apreensão.',
            initial_condition=Evidence.SealCondition.INTACTO,
            sealed_by=agent,
            acquisition_hash=hashlib.sha256(b'aquisicao-C02ABCDEFGHJ').hexdigest(),
            acquisition_hash_algo='SHA-256',
            acquisition_verification_status=Evidence.AcquisitionVerification.VERIFICADO,
            acquisition_verification_note='Cópia forense verificada (source == cópia) no terreno.',
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
            bag_number='SACO-2026-0003',
            initial_seal_number='SELO-2026-0003',
            seal_packaging_description='Saco de prova selado no local da apreensão.',
            initial_condition=Evidence.SealCondition.INTACTO,
            sealed_by=agent,
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
        # Despachada, encaminhada (portador) e recebida no laboratório, em perícia.
        cases.append(
            (
                c2,
                [e2a, e2b, e2c],
                [
                    (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                    (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                    (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                    (EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO),
                    (EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO),
                    (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
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
            bag_number='SACO-2026-0004',
            initial_seal_number='SELO-2026-0004',
            seal_packaging_description='Saco de prova selado no local da apreensão.',
            initial_condition=Evidence.SealCondition.INTACTO,
            sealed_by=agent,
            acquisition_hash=hashlib.sha256(b'aquisicao-NA8ABCDXYZ').hexdigest(),
            acquisition_hash_algo='SHA-256',
            acquisition_verification_status=Evidence.AcquisitionVerification.VERIFICADO,
            acquisition_verification_note='Cópia forense verificada (source == cópia) no terreno.',
            photo=_make_placeholder_photo(
                Evidence.EvidenceType.STORAGE_MEDIA,
                'Coimbra · 01',
                'Disco externo Seagate 2TB — burla bancária.',
            ),
        )
        # Perícia concluída e prova restituída ao proprietário (terminal/arquivada).
        cases.append(
            (
                c3,
                [e3],
                [
                    (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                    (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                    (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                    (EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO),
                    (EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO),
                    (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
                    (EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO),
                    (EventType.RESTITUICAO, CustodianType.PROPRIETARIO),
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
            bag_number='SACO-2026-0005',
            initial_seal_number='SELO-2026-0005',
            seal_packaging_description='Saco de prova selado no local da apreensão.',
            initial_condition=Evidence.SealCondition.INTACTO,
            sealed_by=agent,
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
        # Despachada e encaminhada ao laboratório público — EM TRÂNSITO (ainda por
        # receber): demonstra a caixa "prova a chegar" (ProvaEmTransito) no destino.
        cases.append(
            (
                c4,
                [e4a, e4b],
                [
                    (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                    (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                    (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                    (EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO),
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
            bag_number='SACO-2026-0006',
            initial_seal_number='SELO-2026-0006',
            seal_packaging_description='Viatura selada e imobilizada no local da apreensão.',
            initial_condition=Evidence.SealCondition.INTACTO,
            sealed_by=agent,
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
        # Apreendida e validada, ainda à guarda do OPC.
        cases.append(
            (
                c5,
                [e5a, e5b, e5c, e5d],
                [
                    (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                    (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                ],
            )
        )

        # Ledger de eventos — registar a sequência coerente de cada item.
        # ChainOfCustody.timestamp é sempre fixado em save() via timezone.now()
        # (NTP-synced server-side, ISO/IEC 27037); a ordem canónica é dada pelo
        # campo sequence. A custódia é institucional (ADR-0017): cada evento
        # carrega a instituição titular + a pessoa que detém/assina. A génese
        # depende da proveniência (ADR-0016 §2): objeto físico → APREENSAO_OBJETO;
        # cópia de dados → APREENSAO_DADOS; sub-componente → DERIVACAO_ITEM (e a
        # sua cadeia começa na derivação, sem validação própria).
        lab_custodians = (CustodianType.LAB_PUBLICO, CustodianType.LAB_PRIVADO)
        ct_to_inst = {
            CustodianType.OPC: institutions.get('PSP-LSB'),
            CustodianType.LAB_PUBLICO: institutions.get('LPC'),
            CustodianType.LAB_PRIVADO: institutions.get('LPC'),
            CustodianType.TRIBUNAL: institutions.get('TJ-LSB'),
        }
        # Portador (ADR-0016 v2): conduz a prova no ENCAMINHAMENTO; o snapshot
        # (matrícula/nome/apelido/posto) entra na cadeia de hash. Idempotente.
        portador, _ = Portador.objects.get_or_create(
            matricula='PSP-114520',
            defaults={'nome': 'Rui', 'apelido': 'Marques', 'posto': 'Agente Principal'},
        )
        for _occurrence, evidences, eventos in cases:
            for ev in evidences:
                if ev.parent_evidence_id is not None:
                    # Sub-componente: génese por derivação (cadeia própria mínima).
                    custodian_type = eventos[0][1] if eventos else CustodianType.OPC
                    ChainOfCustody(
                        evidence=ev,
                        event_type=EventType.DERIVACAO_ITEM,
                        custodian_type=custodian_type,
                        custodian_institution=ct_to_inst.get(custodian_type),
                        custodian_user=agent,
                        agent=agent,
                        observations='Sub-componente autonomizado a partir do item-pai.',
                    ).save()
                    continue

                genesis = (
                    EventType.APREENSAO_DADOS
                    if ev.type == Evidence.EvidenceType.DIGITAL_FILE
                    else EventType.APREENSAO_OBJETO
                )
                for idx, (event_type, custodian_type) in enumerate(eventos):
                    et = genesis if idx == 0 else event_type
                    # ENCAMINHAMENTO (ADR-0016 v2): a origem (OPC) entrega a prova a
                    # um portador; fica em trânsito (titular = instituição de destino,
                    # sem detentor pessoal, sem GPS). A receção/atos no lab são do perito.
                    if et == EventType.ENCAMINHAMENTO_CUSTODIA:
                        ChainOfCustody(
                            evidence=ev,
                            event_type=et,
                            custodian_type=custodian_type,
                            custodian_institution=ct_to_inst.get(custodian_type),
                            custodian_user=None,
                            bearer=portador,
                            agent=agent,
                            observations=f'Encaminhamento via portador {portador.matricula}.',
                        ).save()
                        continue
                    acting = expert if custodian_type in lab_custodians else agent
                    ChainOfCustody(
                        evidence=ev,
                        event_type=et,
                        custodian_type=custodian_type,
                        custodian_institution=ct_to_inst.get(custodian_type),
                        custodian_user=acting,
                        agent=acting,
                        observations=f'Evento de demonstração: {et} (custódio {custodian_type}).',
                    ).save()

        return cases

    # ----- output -----

    def _print_summary(self, users, *, cases_created, cases=None):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('SEED COMPLETO'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        for user in users:
            self.stdout.write(f'   {user.profile:<18} {user.clearance:<9} {user.username}')
        roster = getattr(self, '_roster_by_org', None)
        if roster:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Roster de demonstração (uma password para todos):'))
            for sigla, usernames in roster:
                self.stdout.write(f'   {sigla:<12} {", ".join(usernames)}')
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'Password do roster (DEMO, não-produção): {self._demo_password}'
            ))
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
