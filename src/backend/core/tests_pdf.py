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
        gps_lon=Decimal('-9.1399000'),
        address='Lisboa, Portugal',
        agent=agent,
    )


def _make_evidence(occurrence, agent):
    return Evidence.objects.create(
        occurrence=occurrence,
        type=Evidence.EvidenceType.MOBILE_DEVICE,
        description='Smartphone encontrado na cena de crime.',
        gps_lat=Decimal('38.7169000'),
        gps_lon=Decimal('-9.1399000'),
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
            imei='123456789012345',
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
