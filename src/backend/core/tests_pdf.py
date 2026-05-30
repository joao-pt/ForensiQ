"""
ForensiQ — Testes do módulo de exportação PDF.

Testa:
- Geração do PDF via função generate_evidence_pdf()
- Endpoint API GET /api/evidences/<id>/pdf/
  - Autenticação obrigatória (401 sem token)
  - Resposta com content-type application/pdf
  - Content-Disposition com nome de ficheiro correcto
  - Conteúdo não vazio (bytes válidos de PDF)
- Evidência sem dispositivos digitais e sem cadeia de custódia
- Evidência com dispositivos digitais e com cadeia de custódia

Nota de taxonomia (ADR-0010): os tipos genéricos legados (DIGITAL_DEVICE,
DOCUMENT, PHOTO) foram substituídos pela taxonomia digital-first:
  DIGITAL_DEVICE → MOBILE_DEVICE (smartphone/telemóvel apreendido)
  DOCUMENT       → OTHER_DIGITAL (fallback — papel deixou de existir)
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
    User,
)
from .pdf_export import generate_evidence_pdf, generate_occurrence_pdf

# ---------------------------------------------------------------------------
# Fixtures reutilizáveis
# ---------------------------------------------------------------------------


def _make_agent(username='agente_pdf', badge='AGT-PDF-01'):
    return User.objects.create_user(
        username=username,
        password='TestPass123!',
        profile=User.Profile.AGENT,
        badge_number=badge,
        first_name='Maria',
        last_name='Ferreira',
    )


def _make_occurrence(agent, number='OCC-PDF-001'):
    return Occurrence.objects.create(
        number=number,
        description='Ocorrência de teste para exportação PDF.',
        date_time=timezone.now(),
        gps_lat=Decimal('38.7169000'),
        gps_lng=Decimal('-9.1399000'),
        address='Lisboa, Portugal',
        agent=agent,
    )


def _make_evidence(occurrence, agent):
    return Evidence.objects.create(
        occurrence=occurrence,
        type=Evidence.EvidenceType.MOBILE_DEVICE,
        description='Smartphone encontrado na cena de crime.',
        gps_lat=Decimal('38.7169000'),
        gps_lng=Decimal('-9.1399000'),
        serial_number='SN-TEST-001',
        agent=agent,
    )


# ---------------------------------------------------------------------------
# Testes unitários — função generate_evidence_pdf()
# ---------------------------------------------------------------------------


class PDFGenerationUnitTest(TestCase):
    """Testes directos à função de geração PDF (sem HTTP)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_agent()
        cls.occurrence = _make_occurrence(cls.agent)
        cls.evidence = _make_evidence(cls.occurrence, cls.agent)

    def test_pdf_returns_bytes(self):
        """generate_evidence_pdf deve devolver bytes."""
        pdf = generate_evidence_pdf(self.evidence)
        self.assertIsInstance(pdf, bytes)

    def test_pdf_not_empty(self):
        """O PDF gerado não deve ser vazio."""
        pdf = generate_evidence_pdf(self.evidence)
        self.assertGreater(len(pdf), 0)

    def test_pdf_starts_with_pdf_signature(self):
        """O PDF deve começar com a assinatura mágica %PDF."""
        pdf = generate_evidence_pdf(self.evidence)
        self.assertTrue(pdf.startswith(b'%PDF'), 'O ficheiro não começa com %PDF')

    def test_pdf_minimum_size(self):
        """Um relatório PDF básico deve ter pelo menos 3 KB."""
        pdf = generate_evidence_pdf(self.evidence)
        self.assertGreater(len(pdf), 3_000, 'PDF demasiado pequeno — provavelmente incompleto')

    def test_pdf_with_devices_and_custody(self):
        """PDF com dispositivos e cadeia de custódia deve ser gerado sem erros."""
        # Adicionar dispositivo digital
        DigitalDevice.objects.create(
            evidence=self.evidence,
            type=DigitalDevice.DeviceType.SMARTPHONE,
            brand='Samsung',
            model='Galaxy S23',
            condition=DigitalDevice.DeviceCondition.FUNCTIONAL,
            imei='123456789012347',  # Luhn-válido (check digit 7)
            serial_number='SN-DEV-001',
        )
        # Adicionar registo de custódia
        ChainOfCustody.objects.create(
            evidence=self.evidence,
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
            observations='Apreensão inicial.',
        )
        pdf = generate_evidence_pdf(self.evidence)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 5_000)

    def test_pdf_evidence_without_gps(self):
        """PDF para evidência sem GPS deve ser gerado sem erros."""
        agent2 = _make_agent('agente_pdf2', 'AGT-PDF-02')
        occ2 = _make_occurrence(agent2, 'OCC-PDF-002')
        evidence_no_gps = Evidence.objects.create(
            occurrence=occ2,
            type=Evidence.EvidenceType.OTHER_DIGITAL,
            description='Ficheiro digital sem GPS.',
            agent=agent2,
        )
        pdf = generate_evidence_pdf(evidence_no_gps)
        self.assertTrue(pdf.startswith(b'%PDF'))


# ---------------------------------------------------------------------------
# Testes de integração — endpoint API GET /api/evidences/<id>/pdf/
# ---------------------------------------------------------------------------


class PDFAPIEndpointTest(TestCase):
    """Testes do endpoint REST para exportação PDF."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_agent('agente_api_pdf', 'AGT-API-PDF-01')
        cls.expert = User.objects.create_user(
            username='perito_api_pdf',
            password='TestPass123!',
            profile=User.Profile.EXPERT,
        )
        cls.occurrence = _make_occurrence(cls.agent, 'OCC-API-PDF-001')
        cls.evidence = _make_evidence(cls.occurrence, cls.agent)

    def setUp(self):
        self.client = APIClient()

    def _pdf_url(self, evidence_id=None):
        eid = evidence_id or self.evidence.pk
        return reverse('core:evidence-export-pdf', kwargs={'pk': eid})

    def test_pdf_endpoint_requires_authentication(self):
        """Sem autenticação, o endpoint deve devolver 401."""
        response = self.client.get(self._pdf_url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_agent_can_download_pdf(self):
        """Um agente autenticado deve conseguir descarregar o PDF."""
        self.client.force_authenticate(user=self.agent)
        response = self.client.get(self._pdf_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expert_can_download_pdf(self):
        """Um perito autenticado deve conseguir descarregar o PDF."""
        self.client.force_authenticate(user=self.expert)
        response = self.client.get(self._pdf_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_pdf_content_type(self):
        """A resposta deve ter Content-Type application/pdf."""
        self.client.force_authenticate(user=self.agent)
        response = self.client.get(self._pdf_url())
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_pdf_content_disposition(self):
        """A resposta deve incluir Content-Disposition com nome de ficheiro."""
        self.client.force_authenticate(user=self.agent)
        response = self.client.get(self._pdf_url())
        disposition = response.get('Content-Disposition', '')
        self.assertIn('attachment', disposition)
        self.assertIn('.pdf', disposition)

    def test_pdf_content_not_empty(self):
        """O corpo da resposta deve conter bytes de um PDF válido."""
        self.client.force_authenticate(user=self.agent)
        response = self.client.get(self._pdf_url())
        self.assertGreater(len(response.content), 0)
        self.assertTrue(
            response.content.startswith(b'%PDF'),
            'Resposta não é um PDF válido',
        )

    def test_pdf_nonexistent_evidence_returns_404(self):
        """Evidência inexistente deve devolver 404."""
        self.client.force_authenticate(user=self.agent)
        response = self.client.get(self._pdf_url(evidence_id=99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pdf_filename_contains_evidence_id(self):
        """O nome do ficheiro deve incluir o ID da evidência."""
        self.client.force_authenticate(user=self.agent)
        response = self.client.get(self._pdf_url())
        disposition = response.get('Content-Disposition', '')
        self.assertIn(f'{self.evidence.pk:04d}', disposition)


# ---------------------------------------------------------------------------
# PDF por ocorrência (resumo do processo) + sub-componentes integrados
# ---------------------------------------------------------------------------


class OccurrencePDFUnitTest(TestCase):
    """generate_occurrence_pdf gera bytes de PDF válido com itens e sub-itens."""

    def setUp(self):
        self.agent = _make_agent(username='agente_caso', badge='AGT-CASO')
        self.occurrence = _make_occurrence(self.agent, number='CASO-INT-01')
        self.phone = _make_evidence(self.occurrence, self.agent)
        # Sub-componente integrante (SIM dentro do telemóvel)
        self.sim = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.SIM_CARD,
            description='Cartão SIM inserido no telemóvel.',
            parent_evidence=self.phone,
            agent=self.agent,
        )

    def test_occurrence_pdf_bytes(self):
        pdf = generate_occurrence_pdf(self.occurrence)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 500)

    def test_occurrence_pdf_endpoint(self):
        client = APIClient()
        client.force_authenticate(user=self.agent)
        url = f'/api/occurrences/{self.occurrence.pk}/pdf/'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(f'{self.occurrence.pk:04d}', response.get('Content-Disposition', ''))
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_item_pdf_includes_sub_components_section(self):
        """O PDF de um item com sub-componentes inclui a secção 'Componentes Integrantes'."""
        pdf = generate_evidence_pdf(self.phone)
        self.assertTrue(pdf.startswith(b'%PDF'))
        # Não verificamos texto do PDF (renderizado binário); apenas que
        # a presença do sub-componente não rebenta a geração.

    def test_sub_components_in_serializer(self):
        """EvidenceSerializer expõe sub_components do pai."""
        client = APIClient()
        client.force_authenticate(user=self.agent)
        resp = client.get(f'/api/evidences/{self.phone.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('sub_components', resp.data)
        subs = resp.data['sub_components']
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]['id'], self.sim.pk)
        self.assertEqual(subs[0]['type'], Evidence.EvidenceType.SIM_CARD)


# ---------------------------------------------------------------------------
# Lifecycle do BytesIO (auditoria 2026-05-18 §3 N14)
# ---------------------------------------------------------------------------


class PdfBufferLifecycleTest(TestCase):
    """Garante que o ``BytesIO`` é fechado mesmo quando ``doc.build``
    levanta excepção — defesa contra leak de file descriptors em cenário
    de erro repetido.
    """

    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_agent(username='agente_lifecycle', badge='AGT-LC-01')
        cls.occurrence = _make_occurrence(cls.agent, number='OCC-LC-001')
        cls.evidence = _make_evidence(cls.occurrence, cls.agent)

    def _assert_buffer_fechado_quando_build_falha(self, target_func, *args):
        from unittest.mock import MagicMock, patch

        buffer_mock = MagicMock()
        buffer_mock.getvalue.return_value = b'%PDF-fake'
        doc_mock = MagicMock()
        doc_mock.build.side_effect = RuntimeError('falha simulada de build')

        # Stub do `_qr_verify_band` — partilharia o BytesIO mockado
        # com a geração do PNG do QR, mascarando o teste real.
        with (
            patch('core.pdf_export.BytesIO', return_value=buffer_mock),
            patch('core.pdf_export.SimpleDocTemplate', return_value=doc_mock),
            patch('core.pdf_export._qr_verify_band', return_value=[]),
            self.assertRaises(RuntimeError),
        ):
            target_func(*args)

        buffer_mock.close.assert_called_once()

    def test_buffer_fechado_quando_build_falha_em_evidence_pdf(self):
        self._assert_buffer_fechado_quando_build_falha(
            generate_evidence_pdf,
            self.evidence,
        )

    def test_buffer_fechado_quando_build_falha_em_occurrence_pdf(self):
        self._assert_buffer_fechado_quando_build_falha(
            generate_occurrence_pdf,
            self.occurrence,
        )


# ---------------------------------------------------------------------------
# N+1 mitigation (auditoria 2026-05-18 §3 N12)
# ---------------------------------------------------------------------------


class PdfNoNPlusOneTest(TestCase):
    """O endpoint `/api/occurrences/<id>/pdf/` deve aplicar prefetch_related
    para evitar N+1 quando a ocorrência tem várias evidências, cada uma
    com sub-componentes, dispositivos e cadeia de custódia. O número
    total de queries deve crescer ~O(1) com o número de evidências
    (e não ~O(N) como aconteceria sem prefetch).
    """

    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_agent(username='agente_nplus1', badge='AGT-NPL-01')
        cls.occurrence = _make_occurrence(cls.agent, number='OCC-NPL-001')
        # 3 evidências raiz, cada uma com 2 dispositivos digitais e
        # 4 registos de custódia (mais que suficiente para detectar N+1).
        for i in range(3):
            ev = Evidence.objects.create(
                occurrence=cls.occurrence,
                type=Evidence.EvidenceType.MOBILE_DEVICE,
                description=f'Item {i}',
                serial_number=f'SN-NPL-{i:03d}',
                agent=cls.agent,
                gps_lat=Decimal('38.7'),
                gps_lng=Decimal('-9.1'),
            )
            for j in range(2):
                DigitalDevice.objects.create(
                    evidence=ev,
                    type=DigitalDevice.DeviceType.SMARTPHONE,
                    brand='Brand',
                    model=f'M{j}',
                    condition=DigitalDevice.DeviceCondition.FUNCTIONAL,
                    imei='123456789012347',  # Luhn-válido (mesmo IMEI ok para teste)
                    serial_number=f'D-{i}-{j}',
                )
            # 1ª transição APREENDIDA (auto), depois 3 transições
            ChainOfCustody.objects.create(
                evidence=ev,
                new_state=ChainOfCustody.CustodyState.APREENDIDA,
                agent=cls.agent,
            )
            ChainOfCustody.objects.create(
                evidence=ev,
                new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
                agent=cls.agent,
            )
            ChainOfCustody.objects.create(
                evidence=ev,
                new_state=ChainOfCustody.CustodyState.RECEBIDA_LABORATORIO,
                agent=cls.agent,
            )

    def _query_count(self, response_factory):
        """Captura número exacto de queries executadas pelo factory."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = response_factory()
        return len(ctx), response

    def test_occurrence_pdf_endpoint_sem_n_plus_one(self):
        """Endpoint /api/occurrences/<id>/pdf/ — query count deve ser
        baixo e ~O(1) com N evidências. Sem prefetch, este caso
        (3 evidências × 2 dispositivos × 3 custody) faria 50+ queries.
        """
        client = APIClient()
        client.force_authenticate(user=self.agent)
        url = f'/api/occurrences/{self.occurrence.pk}/pdf/'
        n_queries, response = self._query_count(lambda: client.get(url))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        # Threshold: 30 cobre auth + throttle cache + select + 6
        # prefetches + audit log com folga. Acima disto indica
        # regressão do prefetch.
        self.assertLessEqual(
            n_queries,
            30,
            f'N+1 regressão: {n_queries} queries para 3 evidências ' '(esperado ≤30 com prefetch).',
        )

    def test_evidence_pdf_endpoint_sem_n_plus_one(self):
        """Endpoint /api/evidences/<id>/pdf/ para item com 2 dispositivos
        e 3 entradas de custódia — sem N+1 nos sub_components."""
        client = APIClient()
        client.force_authenticate(user=self.agent)
        evidence = self.occurrence.evidences.first()
        url = f'/api/evidences/{evidence.pk}/pdf/'
        n_queries, response = self._query_count(lambda: client.get(url))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            n_queries,
            25,
            f'N+1 regressão em evidence PDF: {n_queries} queries ' '(esperado ≤25 com prefetch).',
        )


# ---------------------------------------------------------------------------
# QR de verificação (ADR-0012 Vaga 1)
# ---------------------------------------------------------------------------


class PdfQrVerifyTest(TestCase):
    """O PDF deve incluir QR code apontando para `/v/<short_hash>/`
    da ocorrência. Não conseguimos ler o conteúdo do QR do PDF
    binário sem OCR, mas conseguimos verificar:
    - geração não rebenta com o QR embebido
    - o PDF resultante é maior que o threshold mínimo
    - a função `_build_verify_url` produz uma URL válida
    """

    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_agent(username='agente_qr', badge='AGT-QR-01')
        cls.occurrence = _make_occurrence(cls.agent, number='OCC-QR-001')
        cls.evidence = _make_evidence(cls.occurrence, cls.agent)

    def test_build_verify_url_estrutura(self):
        from core.pdf_export import _build_verify_url

        url = _build_verify_url(self.occurrence)
        self.assertTrue(url.startswith(('http://', 'https://')))
        self.assertIn('/v/', url)
        # Hash com 12 chars (default).
        path = url.rsplit('/v/', 1)[-1].rstrip('/')
        self.assertEqual(len(path), 12)

    def test_evidence_pdf_gera_com_qr(self):
        """O PDF de evidência inclui a banda QR — geração não rebenta."""
        pdf = generate_evidence_pdf(self.evidence)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 4_000)

    def test_occurrence_pdf_gera_com_qr(self):
        pdf = generate_occurrence_pdf(self.occurrence)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 4_000)
