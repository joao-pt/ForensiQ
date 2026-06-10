"""
ForensiQ — Testes de higiene de backend (refactor Fase 2).

Cobre os findings:
- T12 `verify-public-throttle-orfao`: a vista pública `/v/<hash>/` aplica o
  scope de throttle `verify_public` e devolve 429 ao exceder o limite.
- T12 `api-schema-scope-orfao`: a vista de schema OpenAPI (`/api/schema/`)
  aplica o scope `schema` e devolve 429 ao exceder o limite.
- T17 `api-cascade-shape-inconsistente`: o erro do cascade usa a chave
  canónica `detail` (alinhada com o handler global).
- T17 `api-pdf-export-shape-erro`: falhas de geração de PDF usam `detail`.
- `correlation-id-aceita-input-cliente`: o `CorrelationIDMiddleware` ignora
  um `X-Correlation-ID` malformado (gera um novo) e propaga um válido.

Nota sobre throttling em testes (igual a `ImeiLookupThrottleTest` e
`NearbyPOIsView`): `override_settings(REST_FRAMEWORK={...})` reseta
`api_settings` mas NÃO o atributo de classe `SimpleRateThrottle.THROTTLE_RATES`
(capturado uma vez no import). Para forçar um rate apertado patcheamos
directamente esse atributo de classe.
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from core.middleware import CorrelationIDMiddleware
from core.models import ChainOfCustody, CustodianType, EventType, Evidence, Occurrence
from core.qr_verify import short_hash_for
from core.tests_factories import TEST_PASSWORD, CrimeTipoFactory

User = get_user_model()


# ---------------------------------------------------------------------------
# T12 — Throttle da vista pública /v/<hash>/  (scope `verify_public`)
# ---------------------------------------------------------------------------


class PublicVerifyThrottleTest(TestCase):
    """A superfície pública não-autenticada `/v/<hash>/` tem rate-limit."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user(
            username='agent_vp_throttle',
            password=TEST_PASSWORD,
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-VPT-01',
        )
        cls.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='OCC-VPT-001',
            description='Caso throttle verify',
            date_time=timezone.now(),
            gps_lat=Decimal('38.7'),
            gps_lng=Decimal('-9.1'),
            agent=cls.agent,
        )
        cls.short_hash = short_hash_for(cls.occurrence.id)

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=False)
        cache.clear()

    def test_429_apos_limite(self):
        """Ao exceder `verify_public` a vista devolve 429."""
        rates = {'verify_public': '2/minute'}
        url = f'/v/{self.short_hash}/'
        with mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', rates):
            r1 = self.client.get(url)
            r2 = self.client.get(url)
            r3 = self.client.get(url)
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_throttle_trava_hash_invalido(self):
        """O throttle aplica-se ANTES de resolver — trava enumeração."""
        rates = {'verify_public': '1/minute'}
        with mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', rates):
            r1 = self.client.get('/v/000000000000/')
            r2 = self.client.get('/v/111111111111/')
        # Primeiro: 404 (hash inválido, mas dentro do limite).
        self.assertEqual(r1.status_code, status.HTTP_404_NOT_FOUND)
        # Segundo: já passou do limite → 429 (não chega a resolver).
        self.assertEqual(r2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


# ---------------------------------------------------------------------------
# T12 — Throttle da vista de schema OpenAPI  (scope `schema`)
# ---------------------------------------------------------------------------


class SchemaThrottleTest(TestCase):
    """A vista pública `/api/schema/` aplica o scope `schema`."""

    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def test_schema_view_tem_scope_schema(self):
        from forensiq_project.urls import ThrottledSchemaView

        self.assertEqual(ThrottledSchemaView.throttle_scope, 'schema')

    def test_429_apos_limite(self):
        rates = {'schema': '1/minute'}
        with mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', rates):
            r1 = self.client.get('/api/schema/')
            r2 = self.client.get('/api/schema/')
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


# ---------------------------------------------------------------------------
# T17 — Contrato de erro: cascade usa `detail`
# ---------------------------------------------------------------------------


class CascadeErrorShapeTest(TestCase):
    """O erro do cascade usa a chave canónica `detail` (handler global)."""

    def setUp(self):
        self.client = APIClient()
        self.agent = User.objects.create_user(
            username='agent_cascade_shape',
            password=TEST_PASSWORD,
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-CSH-01',
        )
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='OCC-CSH-001',
            description='Caso cascade shape',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Telemóvel',
            agent=self.agent,
        )
        ChainOfCustody.objects.create(
            evidence=self.evidence,
            event_type=EventType.APREENSAO_OBJETO,
            custodian_type=CustodianType.OPC,
            agent=self.agent,
        )
        # Fecha a cadeia com um evento terminal — qualquer evento seguinte
        # é rejeitado pela guarda dos terminais → erro de validação.
        ChainOfCustody.objects.create(
            evidence=self.evidence,
            event_type=EventType.RESTITUICAO,
            custodian_type=CustodianType.PROPRIETARIO,
            agent=self.agent,
        )

    def test_cascade_invalido_devolve_detail(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.post(
            '/api/custody/cascade/',
            {
                'evidence_ids': [self.evidence.id],
                'event_type': 'VALIDACAO_APREENSAO',
                'custodian_type': 'OPC',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        # Shape canónico: `detail` presente; `error` ausente.
        self.assertIn('detail', resp.data)
        self.assertNotIn('error', resp.data)
        # Contexto adicional para o frontend (não é divergência de shape).
        self.assertEqual(resp.data['evidence_id'], self.evidence.id)


# ---------------------------------------------------------------------------
# T17 — Contrato de erro: falha de PDF usa `detail`
# ---------------------------------------------------------------------------


class PdfExportErrorShapeTest(TestCase):
    """Falhas de geração de PDF devolvem `detail` (não `error`)."""

    def setUp(self):
        self.client = APIClient()
        self.agent = User.objects.create_user(
            username='agent_pdf_shape',
            password=TEST_PASSWORD,
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-PDF-01',
        )
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='OCC-PDF-001',
            description='Caso PDF shape',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Telemóvel',
            agent=self.agent,
        )

    def test_evidence_pdf_falha_devolve_detail(self):
        self.client.force_authenticate(self.agent)
        with mock.patch('core.views.generate_evidence_pdf', side_effect=RuntimeError('boom')):
            resp = self.client.get(f'/api/evidences/{self.evidence.id}/pdf/')
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('detail', resp.data)
        self.assertNotIn('error', resp.data)

    def test_occurrence_pdf_falha_devolve_detail(self):
        self.client.force_authenticate(self.agent)
        with mock.patch('core.views.generate_occurrence_pdf', side_effect=RuntimeError('boom')):
            resp = self.client.get(f'/api/occurrences/{self.occurrence.id}/pdf/')
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('detail', resp.data)
        self.assertNotIn('error', resp.data)


# ---------------------------------------------------------------------------
# correlation-id — validação do header fornecido pelo cliente
# ---------------------------------------------------------------------------


class CorrelationIDValidationTest(TestCase):
    """O `CorrelationIDMiddleware` valida o `X-Correlation-ID` do cliente."""

    def setUp(self):
        self.factory = RequestFactory()
        # Middleware com um get_response que devolve uma resposta simples.
        self.middleware = CorrelationIDMiddleware(lambda req: _DummyResponse())

    def _run(self, header_value):
        headers = {}
        if header_value is not None:
            headers['HTTP_X_CORRELATION_ID'] = header_value
        request = self.factory.get('/api/health/', **headers)
        response = self.middleware(request)
        return response['X-Correlation-ID']

    def test_header_valido_e_propagado(self):
        valid = 'abc123-def456-7890'
        self.assertEqual(self._run(valid), valid)

    def test_uuid_valido_e_propagado(self):
        valid = '550e8400-e29b-41d4-a716-446655440000'
        self.assertEqual(self._run(valid), valid)

    def test_header_malformado_e_ignorado(self):
        """Caracteres fora do alfabeto permitido → gera novo UUID."""
        malicioso = 'inject\r\nSet-Cookie: x=1'
        result = self._run(malicioso)
        self.assertNotEqual(result, malicioso)
        # O substituto é um UUID4 válido (36 chars com hífens).
        self.assertEqual(len(result), 36)
        self.assertEqual(result.count('-'), 4)

    def test_header_demasiado_longo_e_ignorado(self):
        longo = 'a' * 65
        result = self._run(longo)
        self.assertNotEqual(result, longo)
        self.assertEqual(len(result), 36)

    def test_sem_header_gera_novo(self):
        result = self._run(None)
        self.assertEqual(len(result), 36)


class _DummyResponse(dict):
    """Resposta mínima que suporta `response['Header'] = valor`."""

    pass
