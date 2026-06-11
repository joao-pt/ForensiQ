"""Seed de demonstração — popula a base de dados com um retrato fiel da operação.

Objetivo: abrir a webapp e encontrar tudo o que o sistema suporta já a funcionar,
com dados COERENTES com o desenho (ledger de custódia, georreferência, papéis,
taxonomia). Nada de "Agente DEMO" nem ocorrências sem GPS: todas as contas têm
nome real, todas as ocorrências (exceto UMA, deliberada, para o caso-limite "sem
georreferência") estão no mapa, e todos os movimentos da cadeia de custódia
ganham coordenadas — para a trajetória aparecer no mapa do item e da cadeia.

O que a seed cobre, por construção (ver `_verify` no fim):

* As 6 funções (ADR-0017) e as 2 credenciais, com nome próprio português, crachá
  e telefone — incluindo as contas operacionais (sem qualquer conta "*-DEMO").
* As 23 instituições reais do sistema de justiça/forense PT + 2 comandos nas
  ilhas (Madeira/Açores), todas com morada + GPS a 7 casas.
* Ocorrências nas três regiões (continente, Madeira, Açores) varrendo as 7
  categorias N1 da Tabela de Crimes, prioridade derivada da Lei (LEI) e override
  MANUAL, datas recentes e antigas, e exatamente UMA sem GPS (caso-limite).
* Pelo menos um item de CADA um dos 18 tipos de evidência, com `type_specific_data`
  válido (IMEI/IMSI/ICCID/VIN/MAC), campos sensíveis (passcode/PIN), aquisição de
  dados (DIGITAL_FILE → APREENSÃO_DADOS), selagem nas 4 condições, verificação de
  aquisição nos 3 estados, hierarquia de 3 níveis e os 4 tipos-folha.
* Cadeias que exercem TODOS os tipos de evento (incl. APREENSÃO_DADOS, PERDA A
  FAVOR DO ESTADO e DESTRUIÇÃO) e os 7 tipos de custódio, conduzindo itens aos 9
  estados legais derivados (≥2 cada), com GPS + precisão + POI + armazenamento em
  cada evento não-em-trânsito.
* Estados "deixados em aberto": provas em trânsito por receber (caixa de entrada
  de várias instituições), itens validados por encaminhar, e ≥3 ocorrências
  totalmente concluídas (Arquivo).
* Registo de auditoria (AuditLog) a cobrir as 6 ações × 5 tipos de recurso, para
  o feed de atividade do painel não nascer vazio.

Imutabilidade (ADR-0013/0015/0016): a prova e o ledger são append-only (save()
recusa updates; triggers PG bloqueiam UPDATE/DELETE). `ChainOfCustody.save()` fixa
sempre `timestamp = timezone.now()`, por isso a ÚNICA forma de criar uma cronologia
realista (e um hash encadeado coerente) é CONGELAR o relógio no momento do insert
— `mock` sobre `django.utils.timezone.now` — avançando-o entre eventos. Nunca se
faz UPDATE a um registo do ledger. Por isso a seed só corre sob `--reset` (o
TRUNCATE não dispara os triggers FOR EACH ROW) e recusa-se a acrescentar a uma BD
já populada (evita eventos duplicados).

Exemplos:

    # Recriar tudo (destrutivo — apaga e re-popula):
    python manage.py seed_demo --reset

    # Não-interactivo (CI / `fly ssh console`):
    python manage.py seed_demo --reset --no-input

    # Só instituições + utilizadores, sem casos:
    python manage.py seed_demo --users-only

Nunca cria superusers (responsabilidade dissociada): para o /admin/ corre o
built-in `python manage.py createsuperuser`.
"""

from __future__ import annotations

import hashlib
import shutil
from contextlib import contextmanager, suppress
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
    ProvaEmTransito,
)
from core.policy.event_states import LEGAL_STATES
from core.validators import luhn_check_digit

User = get_user_model()
ET = Evidence.EvidenceType
SC = Evidence.SealCondition
AV = Evidence.AcquisitionVerification


# ---------------------------------------------------------------------------
# Relógio congelado — backdating do ledger append-only (ADR-0015)
# ---------------------------------------------------------------------------


@contextmanager
def _frozen(dt):
    """Congela ``timezone.now()`` em ``dt`` durante o bloco.

    ``ChainOfCustody.save()``/``AuditLog`` (auto_now_add) consultam
    ``django.utils.timezone.now`` no momento do insert; congelá-lo é a única
    forma de carimbar um timestamp histórico mantendo o hash encadeado e o
    append-only intactos (sem UPDATE, que os triggers bloqueiam)."""
    with mock.patch('django.utils.timezone.now', return_value=dt):
        yield


class _Clock:
    """Cursor temporal monótono para uma cadeia (eventos por ordem cronológica)."""

    def __init__(self, start):
        self.t = start

    def advance(self, **delta):
        self.t += timedelta(**delta)
        return self.t

    def now(self):
        return self.t


def _luhn_complete(prefix: str) -> str:
    """``prefix`` + dígito de controlo de Luhn (IMEI/ICCID válidos) — o dígito
    vem do MESMO algoritmo que valida (core.validators.luhn_check_digit,
    auditoria D32): gerador e validador nunca divergem."""
    return prefix + luhn_check_digit(prefix)


def D(value: str) -> Decimal:
    return Decimal(value)


# ---------------------------------------------------------------------------
# Fotografias simuladas (registo fotográfico de prova — sem marca d'água "DEMO")
# ---------------------------------------------------------------------------

_TYPE_PALETTE = {
    ET.MOBILE_DEVICE: ('#1E3A8A', 'Telemóvel'),
    ET.COMPUTER: ('#166534', 'Computador'),
    ET.STORAGE_MEDIA: ('#5B21B6', 'Armazenamento'),
    ET.INTERNAL_DRIVE: ('#6D28D9', 'Disco interno'),
    ET.DRONE: ('#C2410C', 'Drone'),
    ET.VEHICLE: ('#991B1B', 'Viatura'),
    ET.VEHICLE_COMPONENT: ('#374151', 'Componente'),
    ET.SIM_CARD: ('#0E7490', 'SIM'),
    ET.MEMORY_CARD: ('#0F766E', 'Cartão SD'),
    ET.GPS_TRACKER: ('#A16207', 'GPS Tracker'),
    ET.SMART_TAG: ('#7C3AED', 'Localizador BLE'),
    ET.CCTV_DEVICE: ('#1F2937', 'CCTV / DVR'),
    ET.IOT_DEVICE: ('#0891B2', 'IoT'),
    ET.NETWORK_DEVICE: ('#4338CA', 'Rede'),
    ET.GAMING_CONSOLE: ('#BE123C', 'Consola'),
    ET.DIGITAL_FILE: ('#15803D', 'Ficheiro digital'),
    ET.RFID_NFC_CARD: ('#B45309', 'RFID / NFC'),
    ET.OTHER_DIGITAL: ('#475569', 'Outro digital'),
}


def _hex_to_rgb(value: str):
    v = value.lstrip('#')
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def _load_font(size: int):
    for candidate in (
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'DejaVuSans-Bold.ttf',
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_photo(evidence_type: str, ref: str, sub: str) -> ContentFile:
    """Fotografia JPEG simulada (1024×768) — placa de identificação do exhibit."""
    color_hex, type_label = _TYPE_PALETTE.get(evidence_type, ('#1F2937', 'Item de prova'))
    bg = _hex_to_rgb(color_hex)
    img = Image.new('RGB', (1024, 768), color=bg)
    draw = ImageDraw.Draw(img)
    accent = tuple(max(0, c - 40) for c in bg)
    draw.rectangle([(0, 0), (16, 768)], fill=accent)
    draw.text((48, 48), type_label.upper(), font=_load_font(24), fill=(255, 255, 255))
    draw.text((48, 96), ref, font=_load_font(64), fill='white')
    draw.text((48, 210), sub[:80], font=_load_font(34), fill=(235, 235, 235))
    draw.text((48, 706), 'ForensiQ · Registo fotográfico de prova', font=_load_font(22),
              fill=(220, 220, 220))
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=82, optimize=True)
    return ContentFile(buf.getvalue(), name='prova.jpg')


# ---------------------------------------------------------------------------
# Pontos georreferenciados (reais, 7 casas) — cenas de crime e postos locais
# ---------------------------------------------------------------------------

# Cenas continentais (dentro dos limites do hero "continental": 36.95–42.15 / -9.55–-6.18)
LISBOA_LIBERDADE = (D('38.7197000'), D('-9.1467000'))
LISBOA_ALVALADE = (D('38.7536000'), D('-9.1447000'))
LISBOA_BELEM = (D('38.6979000'), D('-9.2061000'))
LISBOA_ORIENTE = (D('38.7680000'), D('-9.0990000'))
PORTO_S_CATARINA = (D('41.1496100'), D('-8.6072200'))
PORTO_BOAVISTA = (D('41.1579000'), D('-8.6291000'))
COIMBRA_BAIXA = (D('40.2056000'), D('-8.4196000'))
BRAGA_QG = (D('41.5454000'), D('-8.4265000'))
FARO_MARINA = (D('37.0194000'), D('-7.9304000'))
SINTRA_SERRA = (D('38.7929000'), D('-9.3899000'))
# Ilhas (hero "madeira": 32.40–33.10 / -17.40–-16.50 ; "acores": 36.85–39.85 / -31.40–-24.70)
FUNCHAL_SE = (D('32.6500000'), D('-16.9080000'))
FUNCHAL_LIDO = (D('32.6360000'), D('-16.9400000'))
PONTA_DELGADA = (D('37.7400000'), D('-25.6680000'))
PONTA_DELGADA_PORTAS = (D('37.7390000'), D('-25.6760000'))


class Command(BaseCommand):
    help = (
        'Seed de demonstração realista: 6 funções × 2 credenciais, 25 instituições '
        '(3 regiões), ocorrências em todas as categorias N1, ≥1 item de cada tipo, '
        'cadeias em todos os estados legais e GPS em todos os movimentos.'
    )

    # ----------------------------------------------------------------- args
    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Apaga TODOS os dados core_* antes de criar (destrutivo).')
        parser.add_argument('--users-only', action='store_true',
                            help='Cria só instituições + utilizadores, sem casos.')
        parser.add_argument('--wipe-media', action='store_true',
                            help='Com --reset, apaga também MEDIA_ROOT/evidencias/.')
        parser.add_argument('--no-input', action='store_true',
                            help='Modo não-interactivo (assume confirmações).')
        parser.add_argument('--no-photos', action='store_true',
                            help='Não gera fotografias (acelera a seed).')
        parser.add_argument(
            '--demo-password', default='Forensiq#Demo2026',
            help='Password partilhada (DEMONSTRAÇÃO) por todas as contas. Rotacionar após uso.',
        )
        # Modo CI/smoke: --users-only --no-input cria SÓ estes dois (credenciais
        # explícitas, determinístico). Requeridos nesse modo (ver handle).
        parser.add_argument('--agent-username', default=None,
                            help='Username do agente (com --users-only --no-input).')
        parser.add_argument('--agent-password', default=None,
                            help='Password do agente (com --users-only --no-input).')
        parser.add_argument('--expert-username', default=None,
                            help='Username do perito (com --users-only --no-input).')
        parser.add_argument('--expert-password', default=None,
                            help='Password do perito (com --users-only --no-input).')

    # ----------------------------------------------------------------- entry
    def handle(self, *args, **options):
        reset = options['reset']
        users_only = options['users_only']
        no_input = options['no_input']
        self._no_photos = options['no_photos']
        if reset and users_only:
            raise CommandError('--reset e --users-only são mutuamente exclusivos.')

        # Modo CI/smoke: --users-only --no-input cria APENAS um agente + um perito
        # com credenciais explícitas (determinístico; sem roster nem instituições).
        if users_only and no_input:
            return self._seed_explicit_users(options)

        has_data = Occurrence.objects.exists() or Evidence.objects.exists()
        if has_data and not reset and not users_only:
            raise CommandError(
                'A base já contém ocorrências/itens.\n'
                '  --reset       apaga e recria tudo (destrutivo)\n'
                '  --users-only  só cria/actualiza instituições + utilizadores'
            )

        password = (options.get('demo_password') or 'Forensiq#Demo2026').strip()

        if reset:
            self._reset_database(wipe_media=options['wipe_media'])

        institutions = self._seed_institutions()
        users = self._seed_users(institutions, password)

        if users_only:
            self._summary(users, institutions, cases=False, password=password)
            return

        # Dados de referência (taxonomia + política criminal) — o reset truncou
        # ocorrências mas a taxonomia é reference data; reseed idempotente garante
        # que existe e está activa antes de criar ocorrências (ADR-0014).
        call_command('seed_crime_taxonomy')

        portadores = self._seed_portadores(users)
        self._build_world(users, institutions, portadores)
        self._seed_audit_logs(users)
        # Counter de estados derivados calculado UMA vez (auditoria D37) e
        # partilhado pela verificação e pelo sumário.
        states = self._derived_state_counts()
        self._verify(states)
        self._summary(users, institutions, cases=True, password=password, states=states)

    # ----------------------------------------------------------------- reset
    @transaction.atomic
    def _reset_database(self, *, wipe_media):
        self.stdout.write(self.style.WARNING('A apagar dados existentes...'))
        # Lista ÚNICA dos modelos a limpar, por ordem segura de dependências
        # (auditoria D38): o TRUNCATE deriva os nomes de tabela daqui
        # (m._meta.db_table) e o fallback ORM itera os MESMOS modelos — um
        # modelo novo entra num só sítio. raw=True usa _raw_delete (modelos
        # imutáveis com delete() bloqueado e sem cascatas a recolher); a
        # ProvaEmTransito sai antes do ledger (FK encaminhamento_event que o
        # _raw_delete não cascataria).
        wipe_models = (
            (ProvaEmTransito, False),
            (ChainOfCustody, True),
            (Evidence, True),
            (Occurrence, False),
            (AuditLog, True),
            (Portador, False),
            (InstitutionMembership, False),
            (User, False),
            (Institution, False),
        )
        if connection.vendor == 'postgresql':
            # TRUNCATE não dispara os triggers BEFORE DELETE (migration 0002/0008)
            # que protegem a imutabilidade — é o caminho documentado para fixtures.
            tables = ', '.join(m._meta.db_table for m, _ in wipe_models)
            with connection.cursor() as cursor:
                # Nomes de tabela vêm de _meta (não de input) — sem injecção.
                cursor.execute(
                    f'TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE'  # noqa: S608
                )
        else:
            for model, raw in wipe_models:
                qs = model.objects.all()
                if raw:
                    qs._raw_delete(qs.db)
                else:
                    qs.delete()

        if wipe_media:
            evidencias = Path(settings.MEDIA_ROOT) / 'evidencias'
            if evidencias.exists():
                shutil.rmtree(evidencias)
                evidencias.mkdir(parents=True, exist_ok=True)
        self.stdout.write(self.style.SUCCESS('Tabelas truncadas.'))

    # ----------------------------------------------------------------- institutions
    def _seed_institutions(self):
        """As 23 instituições reais do sistema de justiça/forense PT + 2 nas ilhas.

        Nomes/moradas/contactos públicos das páginas institucionais; GPS
        geocodificado (OSM/Nominatim) a 7 casas. A operação é fictícia — só a
        REFERÊNCIA é real, para a simulação dar um retrato fiel. A sigla é chave
        de junção interna (usada pelo roster e pelos casos). A instituição fixa
        fornece a coordenada da RECEÇÃO (ADR-0016 v2)."""
        OPC, LABPUB, LABPRIV = (InstitutionType.OPC, InstitutionType.LAB_PUBLICO,
                                InstitutionType.LAB_PRIVADO)
        TRIB, MP, DEP = (InstitutionType.TRIBUNAL, InstitutionType.MP,
                         InstitutionType.DEPOSITARIO)
        specs = [
            # --- OPC ---
            ('PJ-LSB', 'Polícia Judiciária — Diretoria de Lisboa e Vale do Tejo', OPC,
             'Rua Gomes Freire 174, 1169-007 Lisboa', '38.7242504', '-9.1400002',
             'directoria.lisboa@pj.pt', '+351 211 967 000'),
            ('PJ-PRT', 'Polícia Judiciária — Diretoria do Norte', OPC,
             'Rua Assis Vaz 113, 4200-096 Porto', '41.1686723', '-8.5949168',
             'directoria.porto@pj.pt', '+351 225 582 000'),
            ('PSP-LSB', 'Polícia de Segurança Pública — Comando Metropolitano de Lisboa', OPC,
             'Avenida de Moscavide 88, 1886-502 Moscavide', '38.7807906', '-9.1022257',
             'cmlisboa@psp.pt', '+351 217 654 242'),
            ('PSP-PRT', 'Polícia de Segurança Pública — Comando Metropolitano do Porto', OPC,
             'Largo 1.º de Dezembro, 4000-404 Porto', '41.1428407', '-8.6090011',
             'cmporto@psp.pt', '+351 222 092 000'),
            ('GNR', 'Guarda Nacional Republicana — Comando-Geral', OPC,
             'Largo do Carmo, 1200-092 Lisboa', '38.7119294', '-9.1408449',
             'gnr@gnr.pt', '+351 213 217 000'),
            ('PSP-FNC', 'Polícia de Segurança Pública — Comando Regional da Madeira', OPC,
             'Rua João de Deus 7, 9050-027 Funchal', '32.6463900', '-16.9095200',
             'cr.madeira@psp.pt', '+351 291 208 400'),
            ('PSP-PDL', 'Polícia de Segurança Pública — Comando Regional dos Açores', OPC,
             'Rua Marquês da Praia e Monforte 23, 9500-089 Ponta Delgada',
             '37.7411739', '-25.6755970', 'cr.acores@psp.pt', '+351 296 206 700'),
            # --- LAB_PUBLICO ---
            ('LPC', 'Laboratório de Polícia Científica da Polícia Judiciária', LABPUB,
             'Rua Gomes Freire, 1169-007 Lisboa', '38.7242504', '-9.1400002',
             'direccao.lpc@pj.pt', '+351 211 967 000'),
            ('INMLCF-N', 'Instituto Nacional de Medicina Legal e Ciências Forenses, I.P. '
             '— Delegação do Norte', LABPUB, 'Jardim Carrilho Videira, 4050-167 Porto',
             '41.1481278', '-8.6182326', 'correio@inmlcf.mj.pt', '+351 222 073 850'),
            ('INMLCF-C', 'Instituto Nacional de Medicina Legal e Ciências Forenses, I.P. '
             '— Delegação do Centro', LABPUB,
             'Pólo III (Pólo das Ciências da Saúde), 3000-548 Coimbra',
             '40.2194533', '-8.4176226', 'correio@inmlcf.mj.pt', '+351 239 854 220'),
            ('INMLCF-S', 'Instituto Nacional de Medicina Legal e Ciências Forenses, I.P. '
             '— Delegação do Sul', LABPUB, 'Rua Manuel Bento de Sousa 3, 1169-201 Lisboa',
             '38.7197895', '-9.1381493', 'correio@inmlcf.mj.pt', '+351 218 811 800'),
            # --- LAB_PRIVADO ---
            ('FOREN', 'Foren — Perícias Técnico-Científicas e Consultoria em Ciências Forenses',
             LABPRIV, 'Avenida Dr. Mário Moutinho 33-A, 1400-136 Lisboa',
             '38.7121529', '-9.2124609', 'info@foren.pt', '+351 211 972 079'),
            ('CODIGO-ADN', 'Código ADN — Centro de Genética e Vida', LABPRIV,
             'Praça Mouzinho de Albuquerque 113, 4100-359 Porto', '41.1579217', '-8.6291209',
             'info@codigoadn.pt', '+351 220 417 190'),
            ('NCFORENSES', 'Ncforenses — Ciências Forenses, Lda.', LABPRIV,
             'Rua de Pinto Bessa 522, 4300-428 Porto', '41.1504842', '-8.5918897',
             'geral@ncforenses.pt', '+351 224 022 684'),
            # --- TRIBUNAL ---
            ('TJ-LSB', 'Juízo Central Criminal de Lisboa — Campus de Justiça', TRIB,
             'Avenida D. João II 1.08.01, Edifício A, 1990-097 Lisboa',
             '38.7625153', '-9.0983215', 'lisboa.centralcriminal@tribunais.org.pt',
             '+351 213 218 300'),
            ('TJ-PRT', 'Tribunal Judicial da Comarca do Porto — Palácio da Justiça', TRIB,
             'Campo dos Mártires da Pátria, 4099-012 Porto', '41.1452814', '-8.6174251',
             'porto.judicial@tribunais.org.pt', '+351 220 949 400'),
            ('TJ-CBR', 'Tribunal Judicial da Comarca de Coimbra — Juízo Local Criminal', TRIB,
             'Palácio da Justiça, Rua da Sofia, 3000-389 Coimbra', '40.2130436', '-8.4307168',
             'coimbra.ministeriopublico@tribunais.org.pt', '+351 239 852 950'),
            ('TJ-FAR', 'Tribunal Judicial da Comarca de Faro — Núcleo de Faro', TRIB,
             'Rua Pedro Nunes 8-10, 8000-405 Faro', '37.0174374', '-7.9241627',
             'faro.judicial@tribunais.org.pt', '+351 289 892 900'),
            # --- MP ---
            ('DIAP-LSB', 'Departamento de Investigação e Ação Penal Regional de Lisboa', MP,
             'Avenida D. João II 1.08.01, Edifícios C/D/E, 1990-097 Lisboa',
             '38.7620161', '-9.0984064', 'lisboa.diapregional@tribunais.org.pt',
             '+351 213 188 600'),
            ('DIAP-PRT', 'Departamento de Investigação e Ação Penal Regional do Porto', MP,
             'Rua de Camões 155, 4049-074 Porto', '41.1532754', '-8.6103149',
             'porto.diapregional@tribunais.org.pt', '+351 225 513 510'),
            ('DIAP-CBR', 'Departamento de Investigação e Ação Penal Regional de Coimbra', MP,
             'Rua da Sofia 175-4.º, 3004-502 Coimbra', '40.2136438', '-8.4315312',
             'coimbra.diapregional@tribunais.org.pt', '+351 239 852 260'),
            ('PR-BRAGA', 'Procuradoria da República da Comarca de Braga', MP,
             'Praça da Justiça, 4719-004 Braga', '41.5481782', '-8.4125099',
             'braga.ministeriopublico@tribunais.org.pt', '+351 253 081 110'),
            # --- DEPOSITARIO ---
            ('GRA', 'Gabinete de Recuperação de Ativos', DEP,
             'Rua Gomes Freire 174, 1169-007 Lisboa', '38.7242504', '-9.1400002',
             'gra@pj.pt', '+351 211 967 000'),
            ('AT', 'Autoridade Tributária e Aduaneira', DEP,
             'Rua da Prata 10, 1149-027 Lisboa', '38.7088122', '-9.1359944',
             '', '+351 218 812 600'),
            ('GAB', 'Gabinete de Administração de Bens — Campus da Justiça', DEP,
             'Avenida D. João II, Lote 1.08.01 D, 1990-097 Lisboa', '38.7620161', '-9.0984064',
             'correio@igfej.mj.pt', '+351 217 907 700'),
        ]
        institutions = {}
        for sigla, name, type_, address, lat, lng, email, phone in specs:
            inst, _ = Institution.objects.update_or_create(
                name=name, type=type_,
                defaults={
                    'sigla': sigla, 'is_active': True, 'address': address,
                    'gps_lat': D(lat), 'gps_lng': D(lng), 'email': email, 'phone': phone,
                },
            )
            institutions[sigla] = inst
        self.stdout.write(f'   Instituições: {len(institutions)} (continente + Madeira + Açores).')
        return institutions

    # ----------------------------------------------------------------- users
    def _upsert_user(self, *, username, password, profile, clearance, first_name,
                     last_name, badge, phone):
        user, created = User.objects.update_or_create(
            username=username,
            defaults={
                'profile': profile, 'clearance': clearance, 'first_name': first_name,
                'last_name': last_name, 'email': f'{username}@forensiq.pt',
                'badge_number': badge, 'phone': phone,
                'is_staff': False, 'is_superuser': False, 'is_active': True,
            },
        )
        with suppress(ValidationError):
            validate_password(password, user=user)  # password de demonstração; escolha do operador
        user.set_password(password)
        user.save(update_fields=['password'])
        return user

    def _seed_explicit_users(self, options):
        """Modo CI/smoke (--users-only --no-input): cria/atualiza SÓ um agente
        (FIRST_RESPONDER) e um perito (FORENSIC_EXPERT) com credenciais explícitas.
        Idempotente (update_or_create); sem instituições nem casos."""
        agent_username = (options.get('agent_username') or '').strip()
        agent_password = options.get('agent_password') or ''
        expert_username = (options.get('expert_username') or '').strip()
        expert_password = options.get('expert_password') or ''
        if not (agent_username and agent_password and expert_username and expert_password):
            raise CommandError(
                'Com --users-only --no-input requerem-se --agent-username, '
                '--agent-password, --expert-username e --expert-password.'
            )
        if agent_username == expert_username:
            raise CommandError('--agent-username e --expert-username têm de ser diferentes.')

        P, C = User.Profile, User.Clearance
        self._upsert_user(
            username=agent_username, password=agent_password, profile=P.FIRST_RESPONDER,
            clearance=C.NORMAL, first_name='Agente', last_name='Smoke',
            badge='SMOKE-AG', phone='+351 900 000 001',
        )
        self._upsert_user(
            username=expert_username, password=expert_password, profile=P.FORENSIC_EXPERT,
            clearance=C.NACIONAL, first_name='Perito', last_name='Smoke',
            badge='SMOKE-PE', phone='+351 900 000 002',
        )
        self.stdout.write(self.style.SUCCESS(
            f'   2 utilizadores: {agent_username} (agente) + {expert_username} (perito).'))

    def _seed_users(self, institutions, password):
        """Roster realista: várias contas por instituição, cobrindo as 6 funções
        e as 2 credenciais, com nome próprio português. Sem contas "*-DEMO".

        Modelagem do controlo de acesso (ADR-0017): inclui peritos com credencial
        NORMAL (leitura total por FUNÇÃO) e um não-perito NACIONAL (credencial ≠
        função); chefes/auditor/MP são NACIONAL. O auditor pertence a 2
        instituições (consola transversal)."""
        P, C = User.Profile, User.Clearance
        roster = [
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
            ('PSP-FNC', [
                ('agente.fnc', P.FIRST_RESPONDER, C.NORMAL, 'Marco', 'Câmara', 'PSP-FNC-401'),
            ]),
            ('PSP-PDL', [
                ('agente.pdl', P.FIRST_RESPONDER, C.NORMAL, 'Duarte', 'Medeiros', 'PSP-PDL-501'),
            ]),
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
        users = {}
        idx = 10
        for sigla, members in roster:
            inst = institutions.get(sigla)
            for username, profile, clearance, fn, ln, badge in members:
                idx += 1
                phone = f'+351 9{idx % 10}{idx % 7}{idx % 9} {100 + idx:03d} {200 + idx:03d}'
                u = self._upsert_user(
                    username=username, password=password, profile=profile,
                    clearance=clearance, first_name=fn, last_name=ln, badge=badge, phone=phone,
                )
                if inst is not None:
                    InstitutionMembership.objects.update_or_create(
                        user=u, institution=inst, defaults={'is_active': True})
                users[username] = u

        # Auditor nacional — supervisão transversal, membro de 2 instituições.
        auditor = self._upsert_user(
            username='auditor.geral', password=password, profile=P.AUDITOR,
            clearance=C.NACIONAL, first_name='Auditor', last_name='Geral',
            badge='AUD-GERAL', phone='+351 939 000 000',
        )
        for sigla in ('PJ-LSB', 'LPC'):
            InstitutionMembership.objects.update_or_create(
                user=auditor, institution=institutions[sigla], defaults={'is_active': True})
        users['auditor.geral'] = auditor

        self.stdout.write(f'   Utilizadores: {len(users)} (6 funções × 2 credenciais, nomes reais).')
        return users

    # ----------------------------------------------------------------- portadores
    def _seed_portadores(self, users):
        specs = [
            ('PSP-114520', 'Rui', 'Marques', 'Agente Principal', None),
            ('GNR-220815', 'Hélder', 'Brito', 'Cabo', None),
            ('PJ-330440', 'Vânia', 'Saraiva', 'Inspetora', None),
            ('PSP-FNC-905', 'Sérgio', 'Abreu', 'Agente', None),
            ('TRANSP-7781', 'Carlos', 'Mendonça', 'Estafeta judicial', 'gestor.gra'),
        ]
        out = {}
        for matricula, nome, apelido, posto, uname in specs:
            p, _ = Portador.objects.get_or_create(
                matricula=matricula,
                defaults={'nome': nome, 'apelido': apelido, 'posto': posto,
                          'user': users.get(uname) if uname else None},
            )
            out[matricula] = p
        return out

    # ----------------------------------------------------------------- world
    def _build_world(self, users, institutions, portadores):
        """Constrói ocorrências, itens e cadeias cobrindo todas as variações.

        Cada caso da demonstração vive no seu método ``_caso_NN`` (mesmo
        conteúdo e ordem de sempre); ``w`` transporta o contexto partilhado
        (relógio, instituições, utilizadores, portadores e geradores de IDs
        válidos para os validadores de formato)."""
        self.stdout.write('A criar ocorrências, itens e cadeias de custódia...')
        self._occurrences = []
        inst = institutions
        w = SimpleNamespace(
            now=timezone.now(), inst=inst, u=users, portadores=portadores,
            port=portadores['PSP-114520'], port_gnr=portadores['GNR-220815'],
            # IDs válidos (validadores de formato): 14 díg → IMEI 15; prefixo → ICCID.
            imei=_luhn_complete, iccid=_luhn_complete,
            VIN_AUDI='WAUZZZ8K9KA902451',   # 17, sem I/O/Q
            ipt=lambda sigla: (inst[sigla].gps_lat, inst[sigla].gps_lng),
        )
        for caso in (
            self._caso_01,
            self._caso_02,
            self._caso_03,
            self._caso_04,
            self._caso_05,
            self._caso_06,
            self._caso_07,
            self._caso_08,
            self._caso_09,
            self._caso_10,
            self._caso_11,
            self._caso_12,
            self._caso_13,
            self._caso_14,
            self._caso_15,
            self._caso_16,
            self._caso_17,
            self._caso_18,
        ):
            caso(w)

        self.stdout.write(
            f'   {len(self._occurrences)} ocorrências, '
            f'{Evidence.objects.count()} itens, '
            f'{ChainOfCustody.objects.count()} movimentos de custódia.')


    def _caso_01(self, w):
        """CASO 1 — Lisboa · Roubo na via pública (40, prioritário por LEI) Telemóvel + SIM (sub) → em perícia no LPC. Aquisição live (não verif.)."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port, imei, iccid = w.port, w.imei, w.iccid
        c1 = self._occ(number='812/26.4PALSB', crime=40, agent=u['agente.lsb1'],
                       when=now - timedelta(days=12, hours=4), gps=LISBOA_LIBERDADE,
                       address='Avenida da Liberdade 250, Lisboa',
                       desc='Assalto à mão armada na Av. da Liberdade. Suspeito detido na '
                            'fuga; telemóvel apreendido para análise das comunicações.')
        e1a = self._ev(c1, ET.MOBILE_DEVICE, 'Apple iPhone 15 Pro Max, titânio natural, '
                       'ecrã ligeiramente fissurado.', u['agente.lsb1'],
                       when=now - timedelta(days=12, hours=3), gps=LISBOA_LIBERDADE,
                       serial='F2LXV3PJ9K',
                       tsd={'marca': 'Apple', 'modelo': 'iPhone 15 Pro Max',
                            'imei': imei('35391802345678'), 'imei_2': imei('35391802345699'),
                            'operating_system': 'iOS / iPadOS', 'estado_energia': 'Ligado',
                            'passcode': '014702'},
                       seal=SC.INTACTO, bag='SACO-2026-0001', seal_no='SELO-2026-0001',
                       sealed_by=u['agente.lsb1'],
                       acq_status=AV.NAO_VERIFICAVEL,
                       acq_note='Aquisição lógica live (dispositivo ligado/desbloqueado); '
                                'fonte == cópia não verificável.',
                       ext_snapshot={'tac': '35391802', 'brand': 'Apple',
                                     'model': 'iPhone 15 Pro Max', 'manufactured': '2023'},
                       ext_source='imeidb.xyz', ext_at=now - timedelta(days=11, hours=20),
                       photo=('Lisboa · 01', 'iPhone 15 Pro Max — Av. da Liberdade'))
        e1b = self._ev(c1, ET.SIM_CARD, 'Cartão SIM MEO extraído do iPhone.', u['agente.lsb1'],
                       when=now - timedelta(days=12, hours=3), parent=e1a,
                       serial='8935106' + '0123456789',
                       tsd={'imsi': '268060123456789', 'iccid': iccid('893510601234567890'),
                            'carrier': 'MEO', 'pin_code': '4081'})
        cl = _Clock(now - timedelta(days=12, hours=3))
        self._chain(e1a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.LOCAL_CRIME, inst['PSP-LSB'],
                    u['agente.lsb1'], LISBOA_LIBERDADE, cl.advance(minutes=20),
                    acc=8, loc='Av. da Liberdade (local da apreensão)', sealed=True,
                    obs='Apreendido na fuga do suspeito.'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-LSB'],
                    u['mp.lsb1'], ipt('PSP-LSB'), cl.advance(hours=20),
                    acc=12, store='Cofre de prova — Esquadra', custodian_user=u['agente.lsb1'],
                    obs='Apreensão validada pelo MP (< 72h).'),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PSP-LSB'],
                    u['mp.lsb1'], ipt('PSP-LSB'), cl.advance(hours=6),
                    custodian_user=u['agente.lsb1'], obs='Despacho para exame ao telemóvel.'),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['agente.lsb1'], None, cl.advance(hours=2), bearer=port,
                    obs='Encaminhado ao LPC via portador.'),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(hours=3), acc=15,
                    loc='Laboratório de Polícia Científica', store='Receção — bancada R2',
                    sealed=True, seal_cond=SC.INTACTO, custodian_user=u['perito.lpc1'],
                    obs='Rececionado no LPC, selo intacto.'),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(hours=18), acc=15,
                    loc='Lab. de Informática Forense', store='Posto de extração 3',
                    custodian_user=u['perito.lpc1'], obs='Início de extração lógica.'),
        ])
        self._chain(e1b, [
            self._g(EventType.DERIVACAO_ITEM, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), now - timedelta(days=10, hours=2),
                    acc=15, loc='Lab. de Informática Forense', custodian_user=u['perito.lpc1'],
                    obs='SIM autonomizado do telemóvel no laboratório.'),
        ])

    def _caso_02(self, w):
        """CASO 2 — Lisboa · Burla informática (241, NORMAL → MANUAL = prioritário) Computador → Disco interno → Ficheiro digital (3 níveis). Lab privado. Validação TARDIA (> 72h, assinala overdue). Perícia concluída."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port = w.port
        c2 = self._occ(number='345/26.1PFLSB', crime=241, agent=u['agente.lsb2'],
                       when=now - timedelta(days=20, hours=2), gps=LISBOA_ALVALADE,
                       address='Rua de Entrecampos 28, Lisboa', manual_priority=True,
                       desc='Burla informática com esquema de phishing bancário. Computador '
                            'do suspeito apreendido em busca domiciliária.')
        e2a = self._ev(c2, ET.COMPUTER, 'Computador portátil Dell XPS 15, autocolante na tampa.',
                       u['agente.lsb2'], when=now - timedelta(days=20, hours=1),
                       gps=LISBOA_ALVALADE, serial='C02ABCDEF1J2',
                       tsd={'marca': 'Dell', 'modelo': 'XPS 15 9530',
                            'operating_system': 'Windows 11 Pro', 'encryption_status': 'BitLocker',
                            'estado_energia': 'Desligado'},
                       seal=SC.INTACTO, bag='SACO-2026-0002', seal_no='SELO-2026-0002',
                       sealed_by=u['agente.lsb2'],
                       acq_hash=hashlib.sha256(b'aq-C02ABCDEF1J2').hexdigest(),
                       acq_algo='SHA-256', acq_status=AV.VERIFICADO,
                       acq_note='Imagem forense E01 verificada (source == cópia).',
                       photo=('Lisboa · 02', 'Dell XPS 15 — busca domiciliária'))
        e2b = self._ev(c2, ET.INTERNAL_DRIVE, 'Disco NVMe 1 TB removido do portátil.',
                       u['agente.lsb2'], when=now - timedelta(days=20, hours=1), parent=e2a,
                       serial='S5GXNX0W12345',
                       tsd={'capacity': '1 TB', 'interface': 'NVMe'})
        e2c = self._ev(c2, ET.DIGITAL_FILE, 'Imagem forense E01 do disco NVMe.',
                       u['perito.priv1'], when=now - timedelta(days=18), parent=e2b,
                       tsd={'source_device_description': 'NVMe S5GXNX0W12345 (Dell XPS 15)'},
                       acq_hash=hashlib.sha256(b'e01-image').hexdigest(), acq_algo='SHA-256',
                       acq_status=AV.PENDENTE)
        cl = _Clock(now - timedelta(days=20, hours=1))
        self._chain(e2a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-LSB'],
                    u['agente.lsb2'], LISBOA_ALVALADE, cl.advance(minutes=30), acc=10,
                    loc='Domicílio do suspeito (busca)', sealed=True, custodian_user=u['agente.lsb2'],
                    obs='Apreendido em busca domiciliária com mandado.'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-LSB'],
                    u['mp.lsb2'], ipt('PSP-LSB'), cl.advance(days=4, hours=2), acc=12,
                    store='Cofre de prova', custodian_user=u['agente.lsb2'],
                    obs='Validação tardia (> 72h) — assinalada como fora de prazo.'),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PSP-LSB'],
                    u['mp.lsb2'], ipt('PSP-LSB'), cl.advance(hours=6),
                    custodian_user=u['agente.lsb2'], obs='Despacho para exame informático.'),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['FOREN'],
                    u['agente.lsb2'], None, cl.advance(hours=4), bearer=port,
                    obs='Encaminhado ao laboratório privado Foren.'),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['FOREN'],
                    u['perito.priv1'], ipt('FOREN'), cl.advance(hours=2), acc=20,
                    loc='Foren — Laboratório', store='Sala limpa 1', sealed=True,
                    seal_cond=SC.INTACTO, custodian_user=u['perito.priv1']),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PRIVADO, inst['FOREN'],
                    u['perito.priv1'], ipt('FOREN'), cl.advance(hours=20), acc=20,
                    store='Estação de aquisição', custodian_user=u['perito.priv1']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PRIVADO, inst['FOREN'],
                    u['perito.priv1'], ipt('FOREN'), cl.advance(days=3), acc=20,
                    custodian_user=u['perito.priv1'], obs='Relatório pericial concluído.'),
        ])
        d18 = now - timedelta(days=18)
        self._chain(e2b, [self._g(EventType.DERIVACAO_ITEM, CustodianType.LAB_PRIVADO,
                    inst['FOREN'], u['perito.priv1'], ipt('FOREN'), d18, acc=20,
                    loc='Foren — Sala limpa 1', custodian_user=u['perito.priv1'],
                    obs='Disco interno removido do portátil.')])
        self._chain(e2c, [self._g(EventType.DERIVACAO_ITEM, CustodianType.LAB_PRIVADO,
                    inst['FOREN'], u['perito.priv1'], ipt('FOREN'), d18 + timedelta(hours=2),
                    acc=20, loc='Foren — Estação de aquisição', custodian_user=u['perito.priv1'],
                    obs='Imagem forense E01 adquirida a partir do disco.')])

    def _caso_03(self, w):
        """CASO 3 — Lisboa · Tráfico de estupefacientes (111, prioritário) SSD externo → perícia → depositário (GRA) → PERDA A FAVOR DO ESTADO. Selo VIOLADO na apreensão; re-selagem na receção."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port_gnr, portadores = w.port_gnr, w.portadores
        c3 = self._occ(number='1102/25.7JELSB', crime=111, agent=u['inspetor.pj.lsb'],
                       when=now - timedelta(days=60, hours=6), gps=LISBOA_BELEM,
                       address='Doca de Belém, Lisboa',
                       desc='Operação de tráfico; suporte externo com contabilidade paralela '
                            'apreendido. Perdido a favor do Estado por decisão judicial.')
        e3 = self._ev(c3, ET.STORAGE_MEDIA, 'Disco externo Samsung T7 2 TB, invólucro forçado.',
                      u['inspetor.pj.lsb'], when=now - timedelta(days=60, hours=5),
                      gps=LISBOA_BELEM, serial='S5A1NS0T700123',
                      tsd={'marca': 'Samsung', 'modelo': 'Portable SSD T7', 'capacity': '2 TB'},
                      seal=SC.VIOLADO, bag='SACO-2025-0114', seal_no='SELO-2025-0114',
                      sealed_by=u['inspetor.pj.lsb'],
                      acq_hash=hashlib.sha256(b'aq-T7').hexdigest(), acq_algo='SHA-256',
                      acq_status=AV.VERIFICADO,
                      photo=('Lisboa · 03', 'SSD Samsung T7 — selo violado'))
        cl = _Clock(now - timedelta(days=60, hours=5))
        self._chain(e3, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PJ-LSB'],
                    u['inspetor.pj.lsb'], LISBOA_BELEM, cl.advance(minutes=40), acc=9,
                    sealed=True, seal_cond=SC.VIOLADO, custodian_user=u['inspetor.pj.lsb'],
                    obs='Selo de fábrica violado no momento da apreensão.'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PJ-LSB'],
                    u['mp.lsb1'], ipt('PJ-LSB'), cl.advance(hours=30),
                    custodian_user=u['inspetor.pj.lsb']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PJ-LSB'],
                    u['mp.lsb1'], ipt('PJ-LSB'), cl.advance(hours=8),
                    custodian_user=u['inspetor.pj.lsb']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['inspetor.pj.lsb'], None, cl.advance(hours=3), bearer=port_gnr),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc2'], ipt('LPC'), cl.advance(hours=4), acc=15,
                    loc='Laboratório de Polícia Científica', store='Bancada R1',
                    sealed=True, seal_cond=SC.PARTIDO, new_seal='SELO-2025-0190',
                    relinquished_by=u['inspetor.pj.lsb'], custodian_user=u['perito.lpc2'],
                    obs='Selo partido em trânsito; re-selado na receção.'),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc2'], ipt('LPC'), cl.advance(days=2), acc=15,
                    custodian_user=u['perito.lpc2']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc2'], ipt('LPC'), cl.advance(days=5), acc=15,
                    custodian_user=u['perito.lpc2']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.DEPOSITARIO, inst['GRA'],
                    u['perito.lpc2'], None, cl.advance(days=2), bearer=portadores['TRANSP-7781']),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.DEPOSITARIO, inst['GRA'],
                    u['gestor.gra'], ipt('GRA'), cl.advance(hours=5), acc=10,
                    loc='Gabinete de Recuperação de Ativos', store='Depósito D-12',
                    sealed=True, seal_cond=SC.INTACTO, custodian_user=None,
                    obs='À guarda institucional do depositário (sem detentor pessoal).'),
            self._g(EventType.PERDA_FAVOR_ESTADO, CustodianType.DEPOSITARIO, inst['GRA'],
                    u['mp.lsb1'], ipt('GRA'), cl.advance(days=20), acc=10,
                    custodian_user=None, obs='Declarada a perda a favor do Estado.'),
        ])

    def _caso_04(self, w):
        """CASO 4 — Lisboa · Corrupção (106, prioritário) Equipamento de rede → tribunal (ENCAMINHADA). Cartão RFID (folha) validado."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port, portadores = w.port, w.portadores
        c4 = self._occ(number='77/26.9TELSB', crime=106, agent=u['inspetor.pj.lsb'],
                       when=now - timedelta(days=33, hours=3), gps=LISBOA_ORIENTE,
                       address='Parque das Nações, Lisboa',
                       desc='Esquema de corrupção; servidores e controlo de acessos apreendidos '
                            'na sede da empresa.')
        e4a = self._ev(c4, ET.NETWORK_DEVICE, 'Firewall Fortinet FortiGate 100F.',
                       u['inspetor.pj.lsb'], when=now - timedelta(days=33, hours=2),
                       gps=LISBOA_ORIENTE, serial='FGT100F0A0123456',
                       tsd={'marca': 'Fortinet', 'modelo': 'FortiGate 100F',
                            'mac': '00:1A:2B:3C:4D:5E', 'estado_energia': 'Ligado'},
                       seal=SC.INTACTO, bag='SACO-2026-0040', seal_no='SELO-2026-0040',
                       sealed_by=u['inspetor.pj.lsb'],
                       photo=('Lisboa · 04', 'FortiGate 100F — sede da empresa'))
        e4b = self._ev(c4, ET.RFID_NFC_CARD, 'Cartão de acessos MIFARE recolhido na receção.',
                       u['inspetor.pj.lsb'], when=now - timedelta(days=33, hours=2),
                       gps=LISBOA_ORIENTE, serial='', tsd={'card_uid': '04A2B6C1D73E80'},
                       seal=SC.AUSENTE)
        cl = _Clock(now - timedelta(days=33, hours=2))
        self._chain(e4a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PJ-LSB'],
                    u['inspetor.pj.lsb'], LISBOA_ORIENTE, cl.advance(minutes=50), acc=10,
                    sealed=True, custodian_user=u['inspetor.pj.lsb']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PJ-LSB'],
                    u['mp.lsb1'], ipt('PJ-LSB'), cl.advance(hours=24),
                    custodian_user=u['inspetor.pj.lsb']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PJ-LSB'],
                    u['mp.lsb1'], ipt('PJ-LSB'), cl.advance(hours=6),
                    custodian_user=u['inspetor.pj.lsb']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['inspetor.pj.lsb'], None, cl.advance(hours=3), bearer=port),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(hours=4), acc=15,
                    loc='Lab. de Informática Forense', sealed=True, seal_cond=SC.INTACTO,
                    custodian_user=u['perito.lpc1']),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(days=1), acc=15,
                    custodian_user=u['perito.lpc1']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(days=4), acc=15,
                    custodian_user=u['perito.lpc1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.TRIBUNAL, inst['TJ-LSB'],
                    u['perito.lpc1'], None, cl.advance(days=1), bearer=portadores['TRANSP-7781']),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.TRIBUNAL, inst['TJ-LSB'],
                    u['escrivao.tj'], ipt('TJ-LSB'), cl.advance(hours=6), acc=12,
                    loc='Juízo Central Criminal de Lisboa', store='Cofre do tribunal',
                    sealed=True, seal_cond=SC.INTACTO, custodian_user=None,
                    obs='Entrada no cofre do tribunal (prova juntada ao processo).'),
        ])
        cl = _Clock(now - timedelta(days=33, hours=1))
        self._chain(e4b, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PJ-LSB'],
                    u['inspetor.pj.lsb'], LISBOA_ORIENTE, cl.advance(minutes=10), acc=10,
                    obs='Cartão de acessos sem selo (recolhido avulso).'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PJ-LSB'],
                    u['mp.lsb1'], ipt('PJ-LSB'), cl.advance(hours=24),
                    custodian_user=u['inspetor.pj.lsb']),
        ])

    def _caso_05(self, w):
        """CASO 5 — Porto · Ameaça e coação (16, NORMAL) — telemóvel + SIM, validada."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        imei, iccid = w.imei, w.iccid
        c5 = self._occ(number='489/26.3PAPRT', crime=16, agent=u['agente.prt1'],
                       when=now - timedelta(days=6, hours=2), gps=PORTO_S_CATARINA,
                       address='Rua de Santa Catarina 215, Porto',
                       desc='Ameaças e coação por redes sociais; smartphone do suspeito '
                            'apreendido.')
        e5a = self._ev(c5, ET.MOBILE_DEVICE, 'Samsung Galaxy S23, capa preta de silicone.',
                       u['agente.prt1'], when=now - timedelta(days=6, hours=1),
                       gps=PORTO_S_CATARINA, serial='RZ8M407JKLM',
                       tsd={'marca': 'Samsung', 'modelo': 'Galaxy S23',
                            'imei': imei('35841234598765'), 'operating_system': 'Android',
                            'estado_energia': 'Modo de avião'},
                       seal=SC.INTACTO, bag='SACO-2026-0050', seal_no='SELO-2026-0050',
                       sealed_by=u['agente.prt1'],
                       photo=('Porto · 01', 'Samsung Galaxy S23'))
        e5b = self._ev(c5, ET.SIM_CARD, 'Cartão SIM NOS extraído do Samsung.', u['agente.prt1'],
                       when=now - timedelta(days=6, hours=1), parent=e5a, serial='8935103' + '9876543210',
                       tsd={'imsi': '268030987654321', 'iccid': iccid('893510398765432109'),
                            'carrier': 'NOS'})
        cl = _Clock(now - timedelta(days=6, hours=1))
        self._chain(e5a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-PRT'],
                    u['agente.prt1'], PORTO_S_CATARINA, cl.advance(minutes=25), acc=11,
                    sealed=True, custodian_user=u['agente.prt1']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-PRT'],
                    u['mp.prt1'], ipt('PSP-PRT'), cl.advance(hours=20),
                    store='Cofre de prova — Porto', custodian_user=u['agente.prt1']),
        ])
        self._chain(e5b, [self._g(EventType.DERIVACAO_ITEM, CustodianType.OPC, inst['PSP-PRT'],
                    u['agente.prt1'], PORTO_S_CATARINA, now - timedelta(days=5, hours=20),
                    acc=11, store='Cofre de prova — Porto', custodian_user=u['agente.prt1'],
                    obs='SIM autonomizado do telemóvel.')])

    def _caso_06(self, w):
        """CASO 6 — Porto · Furto de veículo motorizado (31, NORMAL) Viatura (raiz) → infotainment + GPS tracker + SIM(do tracker). Restituída."""
        now, inst, u, imei = w.now, w.inst, w.u, w.imei
        iccid, VIN_AUDI = w.iccid, w.VIN_AUDI
        c6 = self._occ(number='1789/26.0GBPRT', crime=31, agent=u['agente.prt2'],
                       when=now - timedelta(days=40), gps=PORTO_BOAVISTA,
                       address='Rotunda da Boavista, Porto',
                       desc='Viatura recuperada após furto; unidade de infotainment e '
                            'localizador GPS oculto apreendidos. Veículo restituído ao dono.')
        e6a = self._ev(c6, ET.VEHICLE, 'Audi A4 Avant 2021, matrícula AA-12-BB.', u['agente.prt2'],
                       when=now - timedelta(days=40), gps=PORTO_BOAVISTA, serial=VIN_AUDI,
                       tsd={'marca': 'Audi', 'modelo': 'A4 Avant', 'vin': VIN_AUDI},
                       seal=SC.INTACTO, bag='SACO-2026-0060', seal_no='SELO-2026-0060',
                       sealed_by=u['agente.prt2'],
                       ext_snapshot={'vin': VIN_AUDI, 'make': 'Audi', 'model': 'A4 Avant',
                                     'year': '2021'}, ext_source='vindecoder.eu',
                       ext_at=now - timedelta(days=39),
                       photo=('Porto · 02', 'Audi A4 Avant — recuperado'))
        e6b = self._ev(c6, ET.VEHICLE_COMPONENT, 'Unidade de infotainment MMI 8.4".',
                       u['agente.prt2'], when=now - timedelta(days=40), parent=e6a,
                       serial='4M0035043G', tsd={'associated_vin': VIN_AUDI})
        e6c = self._ev(c6, ET.GPS_TRACKER, 'Localizador GPS magnético Concox JM-VL01 (porta-luvas).',
                       u['agente.prt2'], when=now - timedelta(days=40), parent=e6a, gps=PORTO_BOAVISTA,
                       serial='862785043210123',
                       tsd={'marca': 'Concox', 'modelo': 'JM-VL01', 'imei': imei('86278504321012'),
                            'imsi': '268010222333444'})
        e6d = self._ev(c6, ET.SIM_CARD, 'SIM Vodafone M2M do localizador.', u['agente.prt2'],
                       when=now - timedelta(days=40), parent=e6c, serial='8935101' + '5566778899',
                       tsd={'imsi': '268010222333444', 'iccid': iccid('893510155667788990'),
                            'carrier': 'Vodafone'})
        cl = _Clock(now - timedelta(days=40))
        self._chain(e6a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-PRT'],
                    u['agente.prt2'], PORTO_BOAVISTA, cl.advance(minutes=45), acc=9,
                    sealed=True, custodian_user=u['agente.prt2'], obs='Viatura imobilizada e selada.'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-PRT'],
                    u['mp.prt1'], PORTO_BOAVISTA, cl.advance(hours=30), acc=9,
                    store='Parque de viaturas apreendidas', custodian_user=u['agente.prt2']),
        ])
        # Sub-componentes derivados ANTES do terminal do pai (guarda ADR-0016).
        for sub, sn in ((e6b, 'Infotainment removido para exame.'),
                        (e6c, 'Localizador GPS oculto autonomizado.')):
            self._chain(sub, [self._g(EventType.DERIVACAO_ITEM, CustodianType.OPC, inst['PSP-PRT'],
                        u['agente.prt2'], PORTO_BOAVISTA, now - timedelta(days=39),
                        acc=9, store='Sala de exame — Porto', custodian_user=u['agente.prt2'], obs=sn)])
        self._chain(e6d, [self._g(EventType.DERIVACAO_ITEM, CustodianType.OPC, inst['PSP-PRT'],
                    u['agente.prt2'], PORTO_BOAVISTA, now - timedelta(days=38, hours=20),
                    acc=9, store='Sala de exame — Porto', custodian_user=u['agente.prt2'],
                    obs='SIM extraído do localizador GPS.')])
        # Terminal do pai (restituição) DEPOIS das derivações.
        self._chain(e6a, [self._g(EventType.RESTITUICAO, CustodianType.PROPRIETARIO, None,
                    u['mp.prt1'], PORTO_BOAVISTA, now - timedelta(days=10), acc=9,
                    loc='Entrega ao proprietário', custodian_user=None,
                    obs='Viatura restituída ao legítimo proprietário.',
                    receiver_nome='Manuel Augusto Ferreira Pinto',
                    receiver_doc_tipo='CC', receiver_doc_numero='11483920 4 ZX1')])

    def _caso_07(self, w):
        """CASO 7 — Porto · Sabotagem informática (160, prioritário) — servidor em perícia. + Cartão SD (folha) destruído (estado terminal DESTRUIDA #1 via item próprio)."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port_gnr = w.port_gnr
        c7 = self._occ(number='902/26.6JAPRT', crime=160, agent=u['inspetor.pj.prt'],
                       when=now - timedelta(days=15, hours=5), gps=PORTO_BOAVISTA,
                       address='Avenida da Boavista 1200, Porto',
                       desc='Sabotagem informática a infraestrutura crítica; servidor e '
                            'suportes apreendidos.')
        e7a = self._ev(c7, ET.COMPUTER, 'Servidor Dell PowerEdge R740 (rack).', u['inspetor.pj.prt'],
                       when=now - timedelta(days=15, hours=4), gps=PORTO_BOAVISTA, serial='SVR7400PRT01',
                       tsd={'marca': 'Dell', 'modelo': 'PowerEdge R740',
                            'operating_system': 'Linux (Ubuntu Server 22.04)',
                            'encryption_status': 'LUKS', 'estado_energia': 'Ligado'},
                       seal=SC.INTACTO, bag='SACO-2026-0070', seal_no='SELO-2026-0070',
                       sealed_by=u['inspetor.pj.prt'],
                       acq_hash=hashlib.sha256(b'aq-R740').hexdigest(), acq_algo='SHA-256',
                       acq_status=AV.VERIFICADO,
                       photo=('Porto · 03', 'Servidor Dell PowerEdge R740'))
        e7b = self._ev(c7, ET.MEMORY_CARD, 'Cartão SD 128 GB encontrado no servidor.',
                       u['inspetor.pj.prt'], when=now - timedelta(days=15, hours=4), parent=e7a,
                       serial='SD128PRT99', tsd={'capacity': '128 GB'})
        cl = _Clock(now - timedelta(days=15, hours=4))
        self._chain(e7a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PJ-PRT'],
                    u['inspetor.pj.prt'], PORTO_BOAVISTA, cl.advance(hours=1), acc=12,
                    sealed=True, custodian_user=u['inspetor.pj.prt']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PJ-PRT'],
                    u['mp.prt1'], ipt('PJ-PRT'), cl.advance(hours=20), custodian_user=u['inspetor.pj.prt']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PJ-PRT'],
                    u['mp.prt1'], ipt('PJ-PRT'), cl.advance(hours=6), custodian_user=u['inspetor.pj.prt']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['NCFORENSES'],
                    u['inspetor.pj.prt'], None, cl.advance(hours=4), bearer=port_gnr),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['NCFORENSES'],
                    u['perito.ncf'], ipt('NCFORENSES'), cl.advance(hours=3), acc=18,
                    loc='Ncforenses — Laboratório', sealed=True, seal_cond=SC.INTACTO,
                    custodian_user=u['perito.ncf']),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PRIVADO, inst['NCFORENSES'],
                    u['perito.ncf'], ipt('NCFORENSES'), cl.advance(days=1), acc=18,
                    custodian_user=u['perito.ncf']),
        ])
        cl = _Clock(now - timedelta(days=15, hours=3))
        self._chain(e7b, [
            self._g(EventType.DERIVACAO_ITEM, CustodianType.OPC, inst['PJ-PRT'],
                    u['inspetor.pj.prt'], PORTO_BOAVISTA, cl.advance(hours=2), acc=12,
                    custodian_user=u['inspetor.pj.prt'], obs='Cartão SD autonomizado do servidor.'),
            self._g(EventType.DESTRUICAO, CustodianType.OPC, inst['PJ-PRT'],
                    u['mp.prt1'], ipt('PJ-PRT'), cl.advance(days=10), acc=12,
                    loc='Destruição certificada de suporte', custodian_user=None,
                    obs='Cópia de trabalho destruída após extração (terminal).'),
        ])

    def _caso_08(self, w):
        """CASO 8 — Coimbra · Falsidade informática (159, prioritário) APREENSÃO DE DADOS (DIGITAL_FILE raiz) → EM TRÂNSITO ao INMLCF-C (inbox)."""
        now, inst, u, port_gnr = w.now, w.inst, w.u, w.port_gnr
        c8 = self._occ(number='233/26.2PBCBR', crime=159, agent=u['agente.gnr1'],
                       when=now - timedelta(days=5, hours=8), gps=COIMBRA_BAIXA,
                       address='Praça 8 de Maio, Coimbra',
                       desc='Falsificação de documentos digitais; dados copiados no terreno '
                            'a partir de estação de trabalho não removível.')
        e8 = self._ev(c8, ET.DIGITAL_FILE, 'Cópia forense (live) de partilha de rede do suspeito.',
                      u['agente.gnr1'], when=now - timedelta(days=5, hours=7), gps=COIMBRA_BAIXA,
                      tsd={'source_device_description': 'Workstation HP Z2 (não removível, live)'},
                      acq_hash=hashlib.sha256(b'live-acq-cbr').hexdigest(), acq_algo='SHA-256',
                      acq_status=AV.PENDENTE,
                      seal=SC.INTACTO, bag='SACO-2026-0080', seal_no='SELO-2026-0080',
                      sealed_by=u['agente.gnr1'])
        cl = _Clock(now - timedelta(days=5, hours=7))
        self._chain(e8, [
            self._g(EventType.APREENSAO_DADOS, CustodianType.OPC, inst['GNR'],
                    u['agente.gnr1'], COIMBRA_BAIXA, cl.advance(hours=2), acc=10,
                    loc='Local da diligência — Coimbra', sealed=True, custodian_user=u['agente.gnr1'],
                    obs='Aquisição de dados no terreno (cópia em suporte autónomo).'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['GNR'],
                    u['mp.cbr1'], COIMBRA_BAIXA, cl.advance(hours=18), acc=10,
                    custodian_user=u['agente.gnr1']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['GNR'],
                    u['mp.cbr1'], COIMBRA_BAIXA, cl.advance(hours=6), custodian_user=u['agente.gnr1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['INMLCF-C'],
                    u['agente.gnr1'], None, cl.advance(hours=3), bearer=port_gnr,
                    obs='Encaminhado ao INMLCF-C — aguarda receção (em trânsito).'),
        ])

    def _caso_09(self, w):
        """CASO 9 — Braga (GNR) · Terrorismo (115, prioritário) Drone (selo PARTIDO) → perícia → DESTRUIÇÃO. Cartão SD (folha) → destruído. Ambos os itens terminais → ocorrência ARQUIVADA."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port_gnr = w.port_gnr
        c9 = self._occ(number='205/26.5GCBRG', crime=115, agent=u['agente.gnr1'],
                       when=now - timedelta(days=50, hours=1), gps=BRAGA_QG,
                       address='Quartel-General de Braga',
                       desc='Voo de drone não autorizado sobre instalação militar; aeronave '
                            'derrubada por contramedida.')
        e9a = self._ev(c9, ET.DRONE, 'DJI Mavic 3 Pro, danos no propulsor frontal direito.',
                       u['agente.gnr1'], when=now - timedelta(days=50), gps=BRAGA_QG,
                       serial='1581F5A0B0C0D',
                       tsd={'marca': 'DJI', 'modelo': 'Mavic 3 Pro',
                            'aircraft_serial_number': '1581F5A0B0C0D'},
                       seal=SC.PARTIDO, bag='SACO-2026-0090', seal_no='SELO-2026-0090',
                       sealed_by=u['agente.gnr1'],
                       photo=('Braga · 01', 'DJI Mavic 3 Pro — derrubado'))
        e9b = self._ev(c9, ET.MEMORY_CARD, 'microSD 256 GB Sandisk Extreme do drone.',
                       u['agente.gnr1'], when=now - timedelta(days=50), parent=e9a,
                       serial='SDC0010203', tsd={'capacity': '256 GB'})
        cl = _Clock(now - timedelta(days=50))
        self._chain(e9a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['GNR'],
                    u['agente.gnr1'], BRAGA_QG, cl.advance(hours=1), acc=8,
                    sealed=True, seal_cond=SC.PARTIDO, custodian_user=u['agente.gnr1']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['GNR'],
                    u['mp.braga1'], BRAGA_QG, cl.advance(hours=24), acc=8, custodian_user=u['agente.gnr1']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['GNR'],
                    u['mp.braga1'], BRAGA_QG, cl.advance(hours=6), custodian_user=u['agente.gnr1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['agente.gnr1'], None, cl.advance(hours=4), bearer=port_gnr),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(hours=5), acc=15,
                    loc='Laboratório de Polícia Científica', sealed=True, seal_cond=SC.VIOLADO,
                    new_seal='SELO-2026-0120', relinquished_by=u['agente.gnr1'],
                    custodian_user=u['perito.lpc1'], obs='Selo violado em trânsito; re-selado.'),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(days=2), acc=15, custodian_user=u['perito.lpc1']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(days=4), acc=15, custodian_user=u['perito.lpc1']),
        ])
        # Sub-componente derivado ANTES do terminal do pai (guarda ADR-0016).
        clb = _Clock(now - timedelta(days=49))
        self._chain(e9b, [
            self._g(EventType.DERIVACAO_ITEM, CustodianType.OPC, inst['GNR'], u['agente.gnr1'],
                    BRAGA_QG, clb.advance(hours=2), acc=8, custodian_user=u['agente.gnr1'],
                    obs='Cartão SD autonomizado do drone.'),
            self._g(EventType.DESTRUICAO, CustodianType.OPC, inst['GNR'], u['mp.braga1'],
                    BRAGA_QG, clb.advance(days=40), acc=8, custodian_user=None,
                    obs='Suporte destruído após extração (terminal).'),
        ])
        # Terminal do pai (destruição) DEPOIS da derivação do filho.
        self._chain(e9a, [self._g(EventType.DESTRUICAO, CustodianType.OPC, inst['GNR'],
                    u['mp.braga1'], BRAGA_QG, cl.advance(days=8), acc=8, custodian_user=None,
                    obs='Aeronave destruída por decisão judicial (terminal).')])

    def _caso_10(self, w):
        """CASO 10 — Faro (GNR) · Furto de veículo (31, NORMAL) SMART_TAG → perícia → RESTITUIÇÃO. Item único terminal → ARQUIVADA."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port_gnr = w.port_gnr
        c10 = self._occ(number='654/26.8GTFAR', crime=31, agent=u['agente.gnr1'],
                        when=now - timedelta(days=35, hours=2), gps=FARO_MARINA,
                        address='Marina de Faro',
                        desc='Localizador encontrado em viatura recuperada; analisado e '
                             'restituído ao proprietário.')
        e10 = self._ev(c10, ET.SMART_TAG, 'Apple AirTag oculto sob o tapete do condutor.',
                       u['agente.gnr1'], when=now - timedelta(days=35, hours=1), gps=FARO_MARINA,
                       serial='AT-7K2M9', tsd={'tag_ecosystem': 'Apple AirTag',
                       'device_serial_number': 'GX9K2M7Q1P', 'marca': 'Apple'},
                       seal=SC.INTACTO, bag='SACO-2026-0100', seal_no='SELO-2026-0100',
                       sealed_by=u['agente.gnr1'],
                       photo=('Faro · 01', 'Apple AirTag — viatura recuperada'))
        cl = _Clock(now - timedelta(days=35, hours=1))
        self._chain(e10, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['GNR'], u['agente.gnr1'],
                    FARO_MARINA, cl.advance(minutes=30), acc=9, sealed=True, custodian_user=u['agente.gnr1']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['GNR'], u['mp.cbr1'],
                    FARO_MARINA, cl.advance(hours=20), acc=9, custodian_user=u['agente.gnr1']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['GNR'], u['mp.cbr1'],
                    FARO_MARINA, cl.advance(hours=6), custodian_user=u['agente.gnr1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['agente.gnr1'], None, cl.advance(hours=4), bearer=port_gnr),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc2'], ipt('LPC'), cl.advance(hours=8), acc=15,
                    loc='Laboratório de Polícia Científica', sealed=True, seal_cond=SC.INTACTO,
                    custodian_user=u['perito.lpc2']),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc2'], ipt('LPC'), cl.advance(days=1), acc=15, custodian_user=u['perito.lpc2']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc2'], ipt('LPC'), cl.advance(days=3), acc=15, custodian_user=u['perito.lpc2']),
            self._g(EventType.RESTITUICAO, CustodianType.PROPRIETARIO, None, u['mp.cbr1'],
                    FARO_MARINA, cl.advance(days=5), acc=9, loc='Entrega ao proprietário',
                    custodian_user=None, obs='Localizador restituído ao proprietário do veículo.',
                    receiver_nome='Sofia Alexandra Mendes Cardoso',
                    receiver_doc_tipo='CC', receiver_doc_numero='09238471 2 ZY8'),
        ])

    def _caso_11(self, w):
        """CASO 11 — Lisboa · Lenocínio/pornografia de menores (199, prioritário) CCTV/DVR → perícia concluída. + microSD destruído (DESTRUIDA #2)."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port = w.port
        c11 = self._occ(number='318/26.1JDLSB', crime=199, agent=u['agente.lsb1'],
                        when=now - timedelta(days=25, hours=4), gps=LISBOA_ALVALADE,
                        address='Avenida de Roma 90, Lisboa',
                        desc='Recolha de sistema de videovigilância em investigação de crime '
                             'sexual contra menores.')
        e11a = self._ev(c11, ET.CCTV_DEVICE, 'DVR Hikvision 8 canais com 4 câmaras.',
                        u['agente.lsb1'], when=now - timedelta(days=25, hours=3), gps=LISBOA_ALVALADE,
                        serial='HK8CHDVR2026',
                        tsd={'marca': 'Hikvision', 'modelo': 'DS-7208', 'channels': 8,
                             'system_datetime': '2026-05-01 22:14 (desfasado +6 min)'},
                        seal=SC.INTACTO, bag='SACO-2026-0110', seal_no='SELO-2026-0110',
                        sealed_by=u['agente.lsb1'],
                        photo=('Lisboa · 05', 'DVR Hikvision 8 canais'))
        e11b = self._ev(c11, ET.MEMORY_CARD, 'microSD interno do DVR.', u['agente.lsb1'],
                        when=now - timedelta(days=25, hours=3), parent=e11a, serial='SD-DVR-01',
                        tsd={'capacity': '64 GB'})
        cl = _Clock(now - timedelta(days=25, hours=3))
        self._chain(e11a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-LSB'], u['agente.lsb1'],
                    LISBOA_ALVALADE, cl.advance(minutes=40), acc=10, sealed=True, custodian_user=u['agente.lsb1']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-LSB'], u['mp.lsb2'],
                    ipt('PSP-LSB'), cl.advance(hours=18), custodian_user=u['agente.lsb1']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PSP-LSB'], u['mp.lsb2'],
                    ipt('PSP-LSB'), cl.advance(hours=6), custodian_user=u['agente.lsb1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['agente.lsb1'], None, cl.advance(hours=3), bearer=port),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(hours=4), acc=15,
                    loc='Lab. de Vídeo Forense', sealed=True, seal_cond=SC.INTACTO,
                    custodian_user=u['perito.lpc1']),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(days=1), acc=15, custodian_user=u['perito.lpc1']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO, inst['LPC'],
                    u['perito.lpc1'], ipt('LPC'), cl.advance(days=5), acc=15, custodian_user=u['perito.lpc1']),
        ])
        cl = _Clock(now - timedelta(days=24, hours=20))
        self._chain(e11b, [
            self._g(EventType.DERIVACAO_ITEM, CustodianType.LAB_PUBLICO, inst['LPC'], u['perito.lpc1'],
                    ipt('LPC'), cl.advance(days=2), acc=15, custodian_user=u['perito.lpc1'],
                    obs='microSD autonomizado do DVR.'),
            self._g(EventType.DESTRUICAO, CustodianType.OPC, inst['PSP-LSB'], u['mp.lsb2'],
                    ipt('LPC'), cl.advance(days=12), acc=15, custodian_user=None,
                    obs='Suporte com cópia de trabalho destruído (terminal).'),
        ])

    def _caso_12(self, w):
        """CASO 12 — Porto · Branqueamento (102, prioritário) IoT (em trânsito) + Consola → perícia → PERDA A FAVOR DO ESTADO (#2)."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        port_gnr = w.port_gnr
        c12 = self._occ(number='540/26.3TAPRT', crime=102, agent=u['agente.prt1'],
                        when=now - timedelta(days=18, hours=3), gps=PORTO_S_CATARINA,
                        address='Rua de Cedofeita 300, Porto',
                        desc='Branqueamento via criptoativos; dispositivos de comunicação '
                             'apreendidos em residência.')
        e12a = self._ev(c12, ET.IOT_DEVICE, 'Coluna inteligente Amazon Echo Dot.', u['agente.prt1'],
                        when=now - timedelta(days=18, hours=2), gps=PORTO_S_CATARINA, serial='ECHO5PRT12',
                        tsd={'marca': 'Amazon', 'modelo': 'Echo Dot (5.ª ger.)',
                             'mac': 'A4-83-E7-2C-19-0F', 'estado_energia': 'Ligado'},
                        seal=SC.INTACTO, bag='SACO-2026-0120', seal_no='SELO-2026-0121',
                        sealed_by=u['agente.prt1'],
                        photo=('Porto · 04', 'Amazon Echo Dot'))
        e12b = self._ev(c12, ET.GAMING_CONSOLE, 'PlayStation 5 usada para comunicação encriptada.',
                        u['agente.prt1'], when=now - timedelta(days=18, hours=2), gps=PORTO_S_CATARINA,
                        serial='PS5-AA12345678',
                        tsd={'marca': 'Sony', 'modelo': 'PlayStation 5', 'console_id': '0000-1111-2222'},
                        seal=SC.INTACTO, bag='SACO-2026-0122', seal_no='SELO-2026-0122',
                        sealed_by=u['agente.prt1'],
                        photo=('Porto · 05', 'PlayStation 5'))
        cl = _Clock(now - timedelta(days=18, hours=2))
        self._chain(e12a, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-PRT'], u['agente.prt1'],
                    PORTO_S_CATARINA, cl.advance(minutes=30), acc=11, sealed=True, custodian_user=u['agente.prt1']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-PRT'], u['mp.prt1'],
                    ipt('PSP-PRT'), cl.advance(hours=20), custodian_user=u['agente.prt1']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PSP-PRT'], u['mp.prt1'],
                    ipt('PSP-PRT'), cl.advance(hours=6), custodian_user=u['agente.prt1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['NCFORENSES'],
                    u['agente.prt1'], None, cl.advance(hours=3), bearer=port_gnr,
                    obs='Encaminhado à Ncforenses — aguarda receção (em trânsito).'),
        ])
        cl = _Clock(now - timedelta(days=18, hours=1))
        self._chain(e12b, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-PRT'], u['agente.prt1'],
                    PORTO_S_CATARINA, cl.advance(minutes=30), acc=11, sealed=True, custodian_user=u['agente.prt1']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-PRT'], u['mp.prt1'],
                    ipt('PSP-PRT'), cl.advance(hours=20), custodian_user=u['agente.prt1']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PSP-PRT'], u['mp.prt1'],
                    ipt('PSP-PRT'), cl.advance(hours=6), custodian_user=u['agente.prt1']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['CODIGO-ADN'],
                    u['agente.prt1'], None, cl.advance(hours=3), bearer=port_gnr),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.LAB_PRIVADO, inst['CODIGO-ADN'],
                    u['perito.adn'], ipt('CODIGO-ADN'), cl.advance(hours=5), acc=18,
                    loc='Código ADN — Laboratório', sealed=True, seal_cond=SC.INTACTO,
                    custodian_user=u['perito.adn']),
            self._g(EventType.INICIO_PERICIA, CustodianType.LAB_PRIVADO, inst['CODIGO-ADN'],
                    u['perito.adn'], ipt('CODIGO-ADN'), cl.advance(days=1), acc=18, custodian_user=u['perito.adn']),
            self._g(EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PRIVADO, inst['CODIGO-ADN'],
                    u['perito.adn'], ipt('CODIGO-ADN'), cl.advance(days=3), acc=18, custodian_user=u['perito.adn']),
            self._g(EventType.PERDA_FAVOR_ESTADO, CustodianType.DEPOSITARIO, inst['AT'],
                    u['mp.prt1'], ipt('AT'), cl.advance(days=6), acc=10, custodian_user=None,
                    obs='Consola perdida a favor do Estado.'),
        ])

    def _caso_13(self, w):
        """CASO 13 — Sintra (GNR) · Incêndio florestal (74, prioritário) — OTHER_DIGITAL, validada."""
        now, inst, u = w.now, w.inst, w.u
        c13 = self._occ(number='91/26.4GFSNT', crime=74, agent=u['agente.gnr1'],
                        when=now - timedelta(days=8, hours=6), gps=SINTRA_SERRA,
                        address='Serra de Sintra',
                        desc='Fogo posto em zona florestal; temporizador eletrónico de ignição '
                             'recolhido no ponto de origem.')
        e13 = self._ev(c13, ET.OTHER_DIGITAL, 'Temporizador eletrónico de ignição artesanal.',
                       u['agente.gnr1'], when=now - timedelta(days=8, hours=5), gps=SINTRA_SERRA,
                       serial='IGN-TIMER-07',
                       tsd={'device_category': 'Temporizador / detonador eletrónico',
                            'estado_energia': 'Desligado'},
                       seal=SC.INTACTO, bag='SACO-2026-0130', seal_no='SELO-2026-0130',
                       sealed_by=u['agente.gnr1'],
                       photo=('Sintra · 01', 'Temporizador de ignição'))
        cl = _Clock(now - timedelta(days=8, hours=5))
        self._chain(e13, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.LOCAL_CRIME, inst['GNR'], u['agente.gnr1'],
                    SINTRA_SERRA, cl.advance(hours=1), acc=7, loc='Ponto de origem do incêndio',
                    sealed=True, custodian_user=u['agente.gnr1'], obs='Recolhido no local pela equipa.'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['GNR'], u['mp.cbr1'],
                    SINTRA_SERRA, cl.advance(hours=20), acc=7, custodian_user=u['agente.gnr1']),
        ])

    def _caso_14(self, w):
        """CASO 14 — Funchal (Madeira) · Violência doméstica (194, prioritário) — telemóvel, validada."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        imei = w.imei
        c14 = self._occ(number='142/26.6PAFNC', crime=194, agent=u['agente.fnc'],
                        when=now - timedelta(days=9, hours=3), gps=FUNCHAL_SE,
                        address='Rua da Carreira, Funchal',
                        desc='Violência doméstica; telemóvel da vítima apreendido para recolha '
                             'de mensagens e registos de chamadas.')
        e14 = self._ev(c14, ET.MOBILE_DEVICE, 'Xiaomi Redmi Note 12.', u['agente.fnc'],
                       when=now - timedelta(days=9, hours=2), gps=FUNCHAL_SE, serial='RN12FNC0099',
                       tsd={'marca': 'Xiaomi', 'modelo': 'Redmi Note 12', 'imei': imei('86001503312345'),
                            'operating_system': 'Android', 'estado_energia': 'Ligado'},
                       seal=SC.INTACTO, bag='SACO-2026-0140', seal_no='SELO-2026-0140',
                       sealed_by=u['agente.fnc'],
                       photo=('Funchal · 01', 'Xiaomi Redmi Note 12'))
        cl = _Clock(now - timedelta(days=9, hours=2))
        self._chain(e14, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-FNC'], u['agente.fnc'],
                    FUNCHAL_SE, cl.advance(minutes=30), acc=10, sealed=True, custodian_user=u['agente.fnc']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-FNC'], u['mp.lsb1'],
                    ipt('PSP-FNC'), cl.advance(hours=20), store='Cofre — CR Madeira',
                    custodian_user=u['agente.fnc']),
        ])

    def _caso_15(self, w):
        """CASO 15 — Funchal (Madeira) · Furto em residência (33, NORMAL) — à guarda do OPC."""
        now, inst, u = w.now, w.inst, w.u
        c15 = self._occ(number='160/26.1GBFNC', crime=33, agent=u['agente.fnc'],
                        when=now - timedelta(days=3, hours=5), gps=FUNCHAL_LIDO,
                        address='Estrada Monumental, Funchal',
                        desc='Furto com arrombamento; pen USB e disco recolhidos no local.')
        e15 = self._ev(c15, ET.STORAGE_MEDIA, 'Pen USB Kingston 64 GB.', u['agente.fnc'],
                       when=now - timedelta(days=3, hours=4), gps=FUNCHAL_LIDO, serial='KNG64FNC',
                       tsd={'marca': 'Kingston', 'capacity': '64 GB'},
                       seal=SC.INTACTO, bag='SACO-2026-0150', seal_no='SELO-2026-0150',
                       sealed_by=u['agente.fnc'],
                       photo=('Funchal · 02', 'Pen USB Kingston'))
        self._chain(e15, [self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-FNC'],
                    u['agente.fnc'], FUNCHAL_LIDO, now - timedelta(days=3, hours=3, minutes=30),
                    acc=10, store='Cofre — CR Madeira', sealed=True, custodian_user=u['agente.fnc'],
                    obs='À guarda do OPC, a aguardar validação.')])

    def _caso_16(self, w):
        """CASO 16 — Ponta Delgada (Açores) · Discriminação e ódio (63, NORMAL) — telemóvel, validada."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        imei = w.imei
        c16 = self._occ(number='88/26.9PAPDL', crime=63, agent=u['agente.pdl'],
                        when=now - timedelta(days=7, hours=2), gps=PONTA_DELGADA,
                        address='Avenida Infante D. Henrique, Ponta Delgada',
                        desc='Incitamento ao ódio em rede social; telemóvel do suspeito apreendido.')
        e16 = self._ev(c16, ET.MOBILE_DEVICE, 'Google Pixel 8.', u['agente.pdl'],
                       when=now - timedelta(days=7, hours=1), gps=PONTA_DELGADA, serial='PIX8PDL0077',
                       tsd={'marca': 'Google', 'modelo': 'Pixel 8', 'imei': imei('35712090012345'),
                            'operating_system': 'Android', 'estado_energia': 'Desligado'},
                       seal=SC.INTACTO, bag='SACO-2026-0160', seal_no='SELO-2026-0160',
                       sealed_by=u['agente.pdl'],
                       photo=('P. Delgada · 01', 'Google Pixel 8'))
        cl = _Clock(now - timedelta(days=7, hours=1))
        self._chain(e16, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-PDL'], u['agente.pdl'],
                    PONTA_DELGADA, cl.advance(minutes=30), acc=10, sealed=True, custodian_user=u['agente.pdl']),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-PDL'], u['mp.lsb2'],
                    ipt('PSP-PDL'), cl.advance(hours=20), store='Cofre — CR Açores',
                    custodian_user=u['agente.pdl']),
        ])

    def _caso_17(self, w):
        """CASO 17 — Ponta Delgada (Açores) · Tráfico (111, prioritário) APREENSÃO DE DADOS (DIGITAL_FILE) → em trânsito ao INMLCF-S (inbox #3)."""
        now, inst, u, port = w.now, w.inst, w.u, w.port
        c17 = self._occ(number='120/26.5JEPDL', crime=111, agent=u['agente.pdl'],
                        when=now - timedelta(days=4, hours=6), gps=PONTA_DELGADA_PORTAS,
                        address='Portas do Mar, Ponta Delgada',
                        desc='Tráfico por via marítima; dados de navegação copiados de consola '
                             'fixa da embarcação.')
        e17 = self._ev(c17, ET.DIGITAL_FILE, 'Cópia forense do plotter de navegação.', u['agente.pdl'],
                       when=now - timedelta(days=4, hours=5), gps=PONTA_DELGADA_PORTAS,
                       tsd={'source_device_description': 'Plotter Garmin GPSMAP (fixo na ponte)'},
                       acq_hash=hashlib.sha256(b'live-acq-pdl').hexdigest(), acq_algo='SHA-256',
                       acq_status=AV.PENDENTE,
                       seal=SC.INTACTO, bag='SACO-2026-0170', seal_no='SELO-2026-0170',
                       sealed_by=u['agente.pdl'])
        cl = _Clock(now - timedelta(days=4, hours=5))
        self._chain(e17, [
            self._g(EventType.APREENSAO_DADOS, CustodianType.OPC, inst['PSP-PDL'], u['agente.pdl'],
                    PONTA_DELGADA_PORTAS, cl.advance(hours=2), acc=12, loc='Cais — Portas do Mar',
                    sealed=True, custodian_user=u['agente.pdl'], obs='Aquisição de dados no terreno.'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-PDL'], u['mp.lsb2'],
                    PONTA_DELGADA_PORTAS, cl.advance(hours=18), acc=12, custodian_user=u['agente.pdl']),
            self._g(EventType.DESPACHO_PERICIA, CustodianType.OPC, inst['PSP-PDL'], u['mp.lsb2'],
                    PONTA_DELGADA_PORTAS, cl.advance(hours=6), custodian_user=u['agente.pdl']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.LAB_PUBLICO, inst['INMLCF-S'],
                    u['agente.pdl'], None, cl.advance(hours=3), bearer=port,
                    obs='Encaminhado ao INMLCF-S — aguarda receção (em trânsito).'),
        ])

    def _caso_18(self, w):
        """CASO 18 — Lisboa · Acesso ilegítimo (157, prioritário) — SEM GPS (caso-limite) Ocorrência sem georreferência; item → depositário (ENCAMINHADA #2)."""
        now, inst, u, ipt = w.now, w.inst, w.u, w.ipt
        portadores = w.portadores
        c18 = self._occ(number='401/26.7TELSB', crime=157, agent=u['agente.lsb2'],
                        when=now - timedelta(days=14, hours=2), gps=None,
                        address='Morada reservada (sem georreferência registada)',
                        desc='Acesso ilegítimo a sistema informático denunciado por terceiro; '
                             'local não georreferenciado na participação.')
        e18 = self._ev(c18, ET.COMPUTER, 'Computador de secretária HP ProDesk.', u['agente.lsb2'],
                       when=now - timedelta(days=14, hours=1), gps=None, serial='HPPD400G6LSB',
                       tsd={'marca': 'HP', 'modelo': 'ProDesk 400 G6',
                            'operating_system': 'Windows 10 Pro', 'encryption_status': 'Sem cifragem'},
                       seal=SC.INTACTO, bag='SACO-2026-0180', seal_no='SELO-2026-0180',
                       sealed_by=u['agente.lsb2'])
        cl = _Clock(now - timedelta(days=14, hours=1))
        self._chain(e18, [
            self._g(EventType.APREENSAO_OBJETO, CustodianType.OPC, inst['PSP-LSB'], u['agente.lsb2'],
                    None, cl.advance(minutes=30), custodian_user=u['agente.lsb2'],
                    obs='Apreensão sem captura de GPS (local não georreferenciado).'),
            self._g(EventType.VALIDACAO_APREENSAO, CustodianType.OPC, inst['PSP-LSB'], u['mp.lsb1'],
                    ipt('PSP-LSB'), cl.advance(hours=20), acc=12, store='Cofre de prova',
                    custodian_user=u['agente.lsb2']),
            self._g(EventType.ENCAMINHAMENTO_CUSTODIA, CustodianType.DEPOSITARIO, inst['GAB'],
                    u['agente.lsb2'], None, cl.advance(hours=4), bearer=portadores['TRANSP-7781']),
            self._g(EventType.RECEPCAO_CUSTODIA, CustodianType.DEPOSITARIO, inst['GAB'],
                    u['gestor.gab'], ipt('GAB'), cl.advance(hours=6), acc=10,
                    loc='Gabinete de Administração de Bens', store='Depósito B-04',
                    sealed=True, seal_cond=SC.INTACTO, custodian_user=None,
                    obs='À guarda institucional do depositário (encaminhada).'),
        ])

    # ----------------------------------------------------------------- helpers de criação
    def _occ(self, *, number, crime, agent, when, gps, address, desc, manual_priority=False):
        lat, lng = (gps if gps else (None, None))
        occ = Occurrence(
            number=number, crime_type=CrimeTipo.objects.get(codigo=crime), description=desc,
            date_time=when, gps_lat=lat, gps_lng=lng, address=address, agent=agent)
        if manual_priority:
            occ.priority_source = Occurrence.PrioritySource.MANUAL
        occ.save()
        self._occurrences.append(occ)
        return occ

    def _ev(self, occ, type_, description, agent, *, when, gps=None, parent=None, serial='',
            tsd=None, seal='', bag='', seal_no='', sealed_by=None, acq_hash='', acq_algo='',
            acq_status='', acq_note='', ext_snapshot=None, ext_source='', ext_at=None, photo=None):
        lat, lng = (gps if gps else (None, None))
        kwargs = dict(
            occurrence=occ, type=type_, description=description, timestamp_seizure=when,
            gps_lat=lat, gps_lng=lng, serial_number=serial, agent=agent,
            type_specific_data=tsd or {}, parent_evidence=parent,
            initial_condition=seal, bag_number=bag, initial_seal_number=seal_no,
            seal_packaging_description=('Acondicionado e selado no local.' if seal_no else ''),
            sealed_by=sealed_by, acquisition_hash=acq_hash, acquisition_hash_algo=acq_algo,
            acquisition_verification_status=acq_status, acquisition_verification_note=acq_note,
            external_lookup_snapshot=ext_snapshot, external_lookup_source=ext_source,
            external_lookup_at=ext_at)
        if photo and not self._no_photos:
            kwargs['photo'] = _make_photo(type_, photo[0], photo[1])
        ev = Evidence(**kwargs)
        ev.save()
        return ev

    def _g(self, event_type, custodian_type, institution, agent, gps, when, *, acc=None,
           loc='', store='', sealed=False, seal_cond='', new_seal='', relinquished_by=None,
           bearer=None, custodian_user=None, obs='',
           receiver_nome='', receiver_doc_tipo='', receiver_doc_numero=''):
        """Empacota os parâmetros de UM evento de custódia (aplicado por :meth:`_chain`)."""
        lat, lng = (gps if gps else (None, None))
        # Ato de VALIDAÇÃO: texto certificado (quem validou + data do despacho),
        # como o modal produz — a demo mostra a prática real e o texto entra na
        # fórmula do hash. O ``agent`` destes eventos no seed é o magistrado.
        if event_type == ChainOfCustody.EventType.VALIDACAO_APREENSAO:
            quando = timezone.localtime(when).strftime('%d/%m/%Y %H:%M')
            certificado = (
                f'Apreensão validada por {agent.get_full_name() or agent.username} '
                f'em {quando}.'
            )
            obs = f'{certificado} {obs}'.strip()
        return {
            'event_type': event_type, 'custodian_type': custodian_type,
            'custodian_institution': institution, 'custodian_user': custodian_user,
            'agent': agent, 'gps_lat': lat, 'gps_lng': lng, 'gps_accuracy_m': acc,
            'location_name': loc, 'storage_location': store, 'sealed': sealed,
            'seal_condition_on_receipt': seal_cond, 'new_seal_number': new_seal,
            'relinquished_by': relinquished_by, 'bearer': bearer, 'observations': obs,
            'receiver_nome': receiver_nome, 'receiver_doc_tipo': receiver_doc_tipo,
            'receiver_doc_numero': receiver_doc_numero,
            'when': when,
        }

    def _chain(self, evidence, steps):
        """Cria, por ordem, os eventos do ledger de ``evidence`` com relógio congelado.

        Pode ser chamado mais do que uma vez para o mesmo item (ex.: derivar um
        sub-componente entre dois eventos do pai); a sequência continua de onde
        ficou (auto-incrementada em ``save()``)."""
        for step in steps:
            when = step.pop('when')
            rec = ChainOfCustody(evidence=evidence, **step)
            with _frozen(when):
                rec.save()

    # ----------------------------------------------------------------- auditoria
    def _seed_audit_logs(self, users):
        """Regista atividade (AuditLog append-only) cobrindo 6 ações × 5 recursos.

        Carimba timestamps históricos com o relógio congelado; a ``sequence`` é
        atribuída automaticamente (monótona). Alimenta o feed de atividade do painel."""
        now = timezone.now()
        occ = Occurrence.objects.order_by('id').first()
        ev = Evidence.objects.order_by('id').first()
        coc = ChainOfCustody.objects.order_by('id').first()
        A, R = AuditLog.Action, AuditLog.ResourceType
        entries = [
            (users['agente.lsb1'], A.CREATE, R.OCCURRENCE, occ, {}, 11),
            (users['agente.lsb1'], A.CREATE, R.EVIDENCE, ev,
             {'hash': ev.integrity_hash if ev else ''}, 11),
            (users['perito.lpc1'], A.VIEW, R.EVIDENCE, ev, {}, 9),
            (users['perito.lpc1'], A.CREATE, R.CUSTODY, coc,
             {'event_type': coc.event_type if coc else ''}, 9),
            (users['mp.lsb1'], A.VIEW, R.OCCURRENCE, occ, {}, 8),
            (users['mp.lsb1'], A.EXPORT_PDF, R.OCCURRENCE, occ, {'pages': 4}, 7),
            (users['chefe.lsb'], A.EXPORT_CSV, R.CUSTODY, coc, {'rows': 120}, 6),
            (users['auditor.geral'], A.VIEW, R.CUSTODY, coc, {}, 5),
            (users['gestor.gra'], A.VIEW, R.EVIDENCE, ev, {}, 4),
            (users['custodio.lpc'], A.CREATE, R.CUSTODY, coc,
             {'event_type': 'RECEPCAO_CUSTODIA'}, 3),
            (None, A.SYSTEM_ALERT, R.SYSTEM, occ, {'quota': 'imei_lookup', 'status': '429'}, 2),
            (users['auditor.geral'], A.AUDIT_PURGE, R.SYSTEM, occ, {'deleted': 0}, 1),
            (users['perito.lpc1'], A.EXPORT_PDF, R.EVIDENCE, ev, {'pages': 2}, 1),
            (users['agente.prt1'], A.CREATE, R.DEVICE, ev, {}, 2),
            (users['agente.lsb2'], A.VIEW, R.DEVICE, ev, {}, 1),
        ]
        n = 0
        for user, action, resource, obj, details, days_ago in entries:
            if obj is None:
                continue
            with _frozen(now - timedelta(days=days_ago, hours=(n % 12))):
                AuditLog.objects.create(
                    user=user, action=action, resource_type=resource,
                    resource_id=obj.id, ip_address=f'10.0.0.{10 + n % 200}',
                    correlation_id='', details=details)
            n += 1
        self.stdout.write(f'   AuditLog: {n} registos de atividade.')

    # ----------------------------------------------------------------- verificação
    def _derived_state_counts(self):
        """``Counter`` de estados legais derivados de TODOS os itens — um só
        varrimento (auditoria D37), partilhado por ``_verify`` e ``_summary``.
        O agrupamento ledger→estado vem da fonte única
        (``analytics.legal_states_by_evidence``)."""
        from collections import Counter

        from core import analytics

        return Counter(
            analytics.legal_states_by_evidence(ChainOfCustody.objects.all()).values()
        )

    def _verify(self, state_counts):
        """Assertivas read-only: garante que toda a variação ficou de facto semeada."""
        problems = []

        # Tipos de evidência (18)
        seen_types = set(Evidence.objects.values_list('type', flat=True))
        missing_types = set(ET.values) - seen_types
        if missing_types:
            problems.append(f'Tipos de evidência em falta: {sorted(missing_types)}')

        # Tipos de evento
        seen_events = set(ChainOfCustody.objects.values_list('event_type', flat=True))
        expected_events = set(EventType.values) - {
            EventType.TRANSFERENCIA_CUSTODIA, EventType.ASSUNCAO_CUSTODIA}  # legado
        missing_events = expected_events - seen_events
        if missing_events:
            problems.append(f'Tipos de evento em falta: {sorted(missing_events)}')

        # Tipos de custódio
        seen_cust = set(ChainOfCustody.objects.exclude(custodian_type='')
                        .values_list('custodian_type', flat=True))
        missing_cust = set(CustodianType.values) - seen_cust
        if missing_cust:
            problems.append(f'Tipos de custódio em falta: {sorted(missing_cust)}')

        # Estados legais derivados (9, ≥2 cada) — Counter partilhado (D37).
        missing_states = LEGAL_STATES - set(state_counts)
        if missing_states:
            problems.append(f'Estados legais em falta: {sorted(missing_states)}')
        thin_states = {s: c for s, c in state_counts.items() if c < 2}
        if thin_states:
            problems.append(f'Estados legais com < 2 itens: {thin_states}')

        # Condições de selo na génese
        seen_seal = set(Evidence.objects.exclude(initial_condition='')
                        .values_list('initial_condition', flat=True))
        if set(SC.values) - seen_seal:
            problems.append(f'Condições de selo em falta: {sorted(set(SC.values) - seen_seal)}')

        # Verificação de aquisição
        seen_acq = set(Evidence.objects.exclude(acquisition_verification_status='')
                       .values_list('acquisition_verification_status', flat=True))
        if set(AV.values) - seen_acq:
            problems.append(f'Estados de aquisição em falta: {sorted(set(AV.values) - seen_acq)}')

        # GPS: movimentos não-em-trânsito têm coordenadas
        located = ChainOfCustody.objects.exclude(
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA).filter(gps_lat__isnull=False).count()
        if located < 30:
            problems.append(f'Poucos eventos georreferenciados ({located}); o mapa da cadeia ficaria escasso.')

        # Regiões do hero (continental, Madeira, Açores)
        regions = {
            'continental': (D('36.95'), D('42.15'), D('-9.55'), D('-6.18')),
            'madeira': (D('32.40'), D('33.10'), D('-17.40'), D('-16.50')),
            'acores': (D('36.85'), D('39.85'), D('-31.40'), D('-24.70')),
        }
        for name, (la, lo, ga, go) in regions.items():
            n = Occurrence.objects.filter(gps_lat__gte=la, gps_lat__lte=lo,
                                          gps_lng__gte=ga, gps_lng__lte=go).count()
            if n < 1:
                problems.append(f'Hero "{name}" sem ocorrências georreferenciadas.')

        # Prioridade LEI + MANUAL
        if not Occurrence.objects.filter(priority=Occurrence.Priority.PRIORITARIA,
                                         priority_source=Occurrence.PrioritySource.LEI).exists():
            problems.append('Sem ocorrência PRIORITÁRIA derivada da LEI.')
        if not Occurrence.objects.filter(priority_source=Occurrence.PrioritySource.MANUAL).exists():
            problems.append('Sem override de prioridade MANUAL.')

        # Caso-limite sem GPS
        if not Occurrence.objects.filter(gps_lat__isnull=True).exists():
            problems.append('Sem ocorrência de caso-limite (sem GPS).')

        # Provas em trânsito (inbox) + arquivo
        if ProvaEmTransito.objects.filter(acknowledged_at__isnull=True).count() < 3:
            problems.append('Menos de 3 provas em trânsito por receber (inbox ficaria escasso).')

        # Sem nomes "DEMO/teste"
        bad = User.objects.filter(first_name__iregex=r'demo|teste').count()
        if bad:
            problems.append(f'{bad} utilizadores com nome DEMO/teste.')

        if problems:
            self.stdout.write(self.style.ERROR('VERIFICAÇÃO encontrou lacunas:'))
            for p in problems:
                self.stdout.write(self.style.ERROR(f'   ✗ {p}'))
        else:
            self.stdout.write(self.style.SUCCESS(
                '   Verificação OK: 18 tipos, todos os eventos/custódios, 9 estados (≥2), '
                '4 selos, 3 aquisições, GPS nos movimentos, 3 regiões, LEI+MANUAL, '
                'sem nomes DEMO.'))

    # ----------------------------------------------------------------- resumo
    def _summary(self, users, institutions, *, cases, password, states=None):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 64))
        self.stdout.write(self.style.SUCCESS('SEED COMPLETO'))
        self.stdout.write(self.style.SUCCESS('=' * 64))
        if cases:
            # Counter partilhado com _verify (calculado uma vez — D37).
            states = states if states is not None else self._derived_state_counts()
            self.stdout.write(
                f'Ocorrências: {Occurrence.objects.count()} · Itens: {Evidence.objects.count()} · '
                f'Movimentos: {ChainOfCustody.objects.count()} · '
                f'Auditoria: {AuditLog.objects.count()}')
            self.stdout.write('Estados legais: ' + ', '.join(
                f'{s}={n}' for s, n in sorted(states.items())))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Contas sugeridas para testar (password única):'))
        suggested = [
            ('agente.lsb1', 'Agente / 1.º interveniente (PSP Lisboa) — vê "as minhas"'),
            ('inspetor.pj.lsb', 'Agente PJ Lisboa'),
            ('perito.lpc1', 'Perito forense (LPC) — leitura total por função'),
            ('mp.lsb1', 'Autoridade judiciária (MP Lisboa) — leitura nacional'),
            ('custodio.lpc', 'Custódio (LPC) — zona Instituição'),
            ('escrivao.tj', 'Custódio do tribunal — cofre TJ Lisboa'),
            ('gestor.gra', 'Depositário (GRA) — bens apreendidos'),
            ('chefe.lsb', 'Chefe de serviço (só-leitura) — oversight'),
            ('auditor.geral', 'Auditor nacional (só-leitura)'),
            ('agente.fnc', 'Agente Madeira (Funchal)'),
            ('agente.pdl', 'Agente Açores (Ponta Delgada)'),
        ]
        for username, role in suggested:
            if username in users:
                self.stdout.write(f'   {username:<18} {role}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'Password (DEMONSTRAÇÃO): {password}'))
        self.stdout.write(self.style.WARNING('Para o /admin/: python manage.py createsuperuser'))
