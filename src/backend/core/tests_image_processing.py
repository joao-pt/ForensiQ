"""
ForensiQ — Testes do strip de metadados EXIF em fotografias de evidência.

Cobertura da auditoria 2026-05-18 §2 S9: as fotos carregadas em
``Evidence.photo`` devem ser gravadas sem EXIF/IPTC/XMP, para evitar
exfiltração de dados sensíveis da cena (GPS da captura, modelo de
câmara, timestamps originais) através de exports legítimos do PDF
ou downloads do ficheiro original.

Invariantes garantidos:
- Uma foto carregada com EXIF é gravada sem EXIF.
- Duas fotos com pixels idênticos mas EXIF distinto produzem o **mesmo**
  ``integrity_hash`` (defesa em profundidade da cadeia de custódia).
- O formato original (JPEG/PNG/WEBP) é preservado.
"""

from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from core.tests_factories import TEST_PASSWORD, CrimeTipoFactory

from .models import Evidence, Occurrence, User


def _make_jpeg_with_exif(make='Apple', model='iPhone 15', size=(50, 50)):
    """JPEG mínimo com EXIF Make+Model. Devolve bytes."""
    img = Image.new('RGB', size, 'red')
    exif = img.getexif()
    exif[0x010F] = make  # Make
    exif[0x0110] = model  # Model
    exif[0x9003] = '2024:01:01 12:00:00'  # DateTimeOriginal
    buf = BytesIO()
    img.save(buf, 'JPEG', exif=exif.tobytes())
    return buf.getvalue()


def _make_jpeg_plain(size=(50, 50)):
    """JPEG mínimo SEM EXIF. Devolve bytes."""
    img = Image.new('RGB', size, 'red')
    buf = BytesIO()
    img.save(buf, 'JPEG')
    return buf.getvalue()


def _make_png_plain(size=(50, 50)):
    img = Image.new('RGB', size, 'blue')
    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


class _Fixture:
    """Setup partilhado: 1 agente + 1 ocorrência."""

    @classmethod
    def _setup_common(cls):
        cls.agent = User.objects.create_user(
            username='agente_exif',
            password=TEST_PASSWORD,
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-EXIF-01',
        )
        cls.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='OCC-EXIF-001',
            description='Ocorrência de teste para strip EXIF.',
            date_time=timezone.now(),
            gps_lat=Decimal('38.7169000'),
            gps_lng=Decimal('-9.1399000'),
            address='Lisboa, Portugal',
            agent=cls.agent,
        )


class EvidenceExifStripTest(_Fixture, TestCase):
    """A foto gravada não deve conter EXIF, mesmo que o upload o trouxesse."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_common()

    def test_jpeg_com_exif_e_gravado_sem_exif(self):
        upload = SimpleUploadedFile(
            'phone.jpg',
            _make_jpeg_with_exif(),
            content_type='image/jpeg',
        )
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone com EXIF.',
            serial_number='SN-EXIF-001',
            agent=self.agent,
            photo=upload,
        )
        ev.refresh_from_db()
        with ev.photo.open('rb') as fh:
            img = Image.open(fh)
            img.load()
            exif = img.getexif()
        # Pillow devolve um dict-like; vazio significa zero tags.
        self.assertEqual(
            dict(exif),
            {},
            f'EXIF não foi removido: {dict(exif)!r}',
        )

    def test_jpeg_sem_exif_permanece_sem_exif(self):
        """Smoke test: foto já limpa continua limpa após o save."""
        upload = SimpleUploadedFile(
            'clean.jpg',
            _make_jpeg_plain(),
            content_type='image/jpeg',
        )
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Foto sem EXIF de partida.',
            serial_number='SN-EXIF-002',
            agent=self.agent,
            photo=upload,
        )
        ev.refresh_from_db()
        with ev.photo.open('rb') as fh:
            img = Image.open(fh)
            img.load()
            self.assertEqual(dict(img.getexif()), {})


class EvidenceIntegrityHashInvariantToExifTest(_Fixture, TestCase):
    """O ``integrity_hash`` deve ser idêntico entre 2 fotos com mesmos
    pixels mas EXIF distinto — a única coisa que sai do strip é o EXIF,
    portanto os bytes que entram em ``_compute_photo_hash`` são iguais.

    Defesa em profundidade da cadeia de custódia: o hash não pode
    depender de metadados que podem ser removidos por qualquer
    ferramenta externa.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_common()

    def test_hash_invariante_a_exif(self):
        fixed_ts = timezone.now()
        upload_with_exif = SimpleUploadedFile(
            'with.jpg',
            _make_jpeg_with_exif(),
            content_type='image/jpeg',
        )
        upload_plain = SimpleUploadedFile(
            'plain.jpg',
            _make_jpeg_plain(),
            content_type='image/jpeg',
        )
        # Para que os outros campos do hash sejam idênticos, mantemos
        # os mesmos valores em ambas as evidências (mesma occurrence,
        # mesmo type, mesma description, mesmos GPS, MESMO
        # timestamp_seizure, MESMO serial_number, mesmo agent).
        common = dict(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Foto idêntica em pixels.',
            gps_lat=Decimal('38.7169000'),
            gps_lng=Decimal('-9.1399000'),
            timestamp_seizure=fixed_ts,
            serial_number='SN-INVARIANT',
            agent=self.agent,
        )
        ev1 = Evidence.objects.create(photo=upload_with_exif, **common)
        ev2 = Evidence.objects.create(photo=upload_plain, **common)

        self.assertEqual(
            ev1.integrity_hash,
            ev2.integrity_hash,
            'O integrity_hash deveria ser invariante a EXIF.',
        )


class EvidencePhotoFormatPreservedTest(_Fixture, TestCase):
    """O strip não pode converter o formato (JPEG → JPEG, PNG → PNG)."""

    @classmethod
    def setUpTestData(cls):
        cls._setup_common()

    def _assert_format_preserved(self, upload_bytes, content_type, expected_fmt):
        ext = expected_fmt.lower().replace('jpeg', 'jpg')
        upload = SimpleUploadedFile(
            f'item.{ext}',
            upload_bytes,
            content_type=content_type,
        )
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Foto para teste de formato.',
            serial_number=f'SN-FMT-{expected_fmt}',
            agent=self.agent,
            photo=upload,
        )
        ev.refresh_from_db()
        with ev.photo.open('rb') as fh:
            img = Image.open(fh)
            self.assertEqual(img.format, expected_fmt)

    def test_jpeg_preservado(self):
        self._assert_format_preserved(
            _make_jpeg_plain(),
            'image/jpeg',
            'JPEG',
        )

    def test_png_preservado(self):
        self._assert_format_preserved(
            _make_png_plain(),
            'image/png',
            'PNG',
        )
