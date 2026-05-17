"""
ForensiQ - Testes adicionais para cobertura >80%.

Areas-alvo identificadas na sessao de 2026-05-08:
- Validadores (validate_imei, validate_vin, validate_imsi) - unit tests puros
- Permissoes (IsAgent, IsExpert, IsAgentOrExpert, IsOwnerOrReadOnly)
- Exception handler (forensiq_exception_handler)
- Conteudo do PDF (SHA-256, dispositivos, cadeia de custodia presentes)
- Middleware (CSP, CorrelationID)
- Dashboard stats (StatsView, DashboardStatsView) com ownership
- Throttles (AuthRateThrottle)

Convencoes:
- Cada classe testa um modulo / area funcional especifica.
- Factories de ``tests_factories.py`` reutilizadas para setup.
- Nomes de teste descrevem o comportamento esperado em PT.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient, APITestCase

from core.exceptions import forensiq_exception_handler
from core.middleware import ContentSecurityPolicyMiddleware, CorrelationIDMiddleware
from core.models import ChainOfCustody, Evidence, Occurrence, User
from core.permissions import IsAgent, IsAgentOrExpert, IsExpert, IsOwnerOrReadOnly
from core.throttles import AuthRateThrottle
from core.validators import validate_imei, validate_imsi, validate_vin
from core.tests_factories import (
    ChainOfCustodyFactory,
    DigitalDeviceFactory,
    EvidenceMobileFactory,
    ExpertFactory,
    OccurrenceFactory,
    UserFactory,
)


# =========================================================================
# 1. VALIDADORES - testes unitarios puros (sem BD)
# =========================================================================

class ValidateIMEITest(TestCase):
    """Cobertura de ``core.validators.validate_imei``."""

    def test_valid_imei_passes(self):
        validate_imei('490154203237518')

    def test_imei_too_short_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imei('12345678901234')

    def test_imei_too_long_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imei('1234567890123456')

    def test_imei_with_letters_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imei('49015420323751A')

    def test_imei_none_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imei(None)

    def test_imei_bad_luhn_raises(self):
        with self.assertRaises(DjangoValidationError) as ctx:
            validate_imei('490154203237519')
        self.assertIn('Luhn', str(ctx.exception))

    def test_imei_all_zeros_passes_luhn(self):
        validate_imei('000000000000000')

    def test_imei_with_spaces_stripped(self):
        validate_imei('  490154203237518  ')


class ValidateVINTest(TestCase):
    """Cobertura de ``core.validators.validate_vin``."""

    def test_valid_vin_passes(self):
        validate_vin('WVWZZZ3CZWE123456')

    def test_vin_too_short_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_vin('WVWZZZ3CZWE1234')

    def test_vin_too_long_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_vin('WVWZZZ3CZWE12345678')

    def test_vin_letter_i_raises(self):
        with self.assertRaises(DjangoValidationError) as ctx:
            validate_vin('WVWZZZ3CZWI123456')
        self.assertIn('I', str(ctx.exception))

    def test_vin_letter_o_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_vin('WVWZZZ3CZWO123456')

    def test_vin_letter_q_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_vin('WVWZZZ3CZWQ123456')

    def test_vin_none_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_vin(None)

    def test_vin_lowercase_accepted(self):
        validate_vin('wvwzzz3czwe123456')


class ValidateIMSITest(TestCase):
    """Cobertura de ``core.validators.validate_imsi``."""

    def test_valid_imsi_15_digits(self):
        validate_imsi('268011234567890')

    def test_valid_imsi_14_digits(self):
        validate_imsi('26801123456789')

    def test_imsi_13_digits_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imsi('2680112345678')

    def test_imsi_16_digits_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imsi('2680112345678901')

    def test_imsi_with_letters_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imsi('26801123456789A')

    def test_imsi_none_raises(self):
        with self.assertRaises(DjangoValidationError):
            validate_imsi(None)


# =========================================================================
# 2. PERMISSOES - testes unitarios com RequestFactory (sem views)
# =========================================================================

class IsAgentPermissionTest(TestCase):
    """Cobertura de ``core.permissions.IsAgent``."""

    def setUp(self):
        self.perm = IsAgent()
        self.rf = RequestFactory()

    def test_agent_write_allowed(self):
        user = UserFactory.create()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_permission(request, None))

    def test_expert_write_denied(self):
        user = ExpertFactory.create()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertFalse(self.perm.has_permission(request, None))

    def test_agent_read_allowed(self):
        user = UserFactory.create()
        request = self.rf.get('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_permission(request, None))

    def test_expert_read_allowed(self):
        user = ExpertFactory.create()
        request = self.rf.get('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_permission(request, None))

    def test_anonymous_denied(self):
        from django.contrib.auth.models import AnonymousUser
        request = self.rf.get('/fake/')
        request.user = AnonymousUser()
        self.assertFalse(self.perm.has_permission(request, None))


class IsExpertPermissionTest(TestCase):
    """Cobertura de ``core.permissions.IsExpert``."""

    def setUp(self):
        self.perm = IsExpert()
        self.rf = RequestFactory()

    def test_expert_write_allowed(self):
        user = ExpertFactory.create()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_permission(request, None))

    def test_agent_write_denied(self):
        user = UserFactory.create()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertFalse(self.perm.has_permission(request, None))


class IsAgentOrExpertPermissionTest(TestCase):
    """Cobertura de ``core.permissions.IsAgentOrExpert``."""

    def setUp(self):
        self.perm = IsAgentOrExpert()
        self.rf = RequestFactory()

    def test_agent_post_allowed(self):
        user = UserFactory.create()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_permission(request, None))

    def test_expert_post_allowed(self):
        user = ExpertFactory.create()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_permission(request, None))

    def test_user_without_profile_denied(self):
        """Superuser sem perfil AGENT/EXPERT nao pode escrever."""
        user = User.objects.create_superuser(
            username='admin_no_profile', password='TestPass123!',
            email='admin@test.com',
        )
        user.profile = ''
        user.save()
        request = self.rf.post('/fake/')
        request.user = user
        self.assertFalse(self.perm.has_permission(request, None))


class IsOwnerOrReadOnlyPermissionTest(TestCase):
    """Cobertura de ``core.permissions.IsOwnerOrReadOnly``."""

    def setUp(self):
        self.perm = IsOwnerOrReadOnly()
        self.rf = RequestFactory()

    def test_owner_can_edit(self):
        user = UserFactory.create()
        occ = OccurrenceFactory.create(agent=user)
        request = self.rf.patch('/fake/')
        request.user = user
        self.assertTrue(self.perm.has_object_permission(request, None, occ))

    def test_non_owner_cannot_edit(self):
        owner = UserFactory.create()
        other = UserFactory.create()
        occ = OccurrenceFactory.create(agent=owner)
        request = self.rf.patch('/fake/')
        request.user = other
        self.assertFalse(self.perm.has_object_permission(request, None, occ))

    def test_anyone_can_read(self):
        owner = UserFactory.create()
        other = UserFactory.create()
        occ = OccurrenceFactory.create(agent=owner)
        request = self.rf.get('/fake/')
        request.user = other
        self.assertTrue(self.perm.has_object_permission(request, None, occ))


# =========================================================================
# 3. EXCEPTION HANDLER
# =========================================================================

class ExceptionHandlerTest(TestCase):
    """Cobertura de ``core.exceptions.forensiq_exception_handler``."""

    def test_django_validation_error_with_message_dict(self):
        exc = DjangoValidationError({'number': ['Ja existe.']})
        resp = forensiq_exception_handler(exc, {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('number', resp.data)

    def test_django_validation_error_with_messages(self):
        exc = DjangoValidationError(['Erro generico.'])
        resp = forensiq_exception_handler(exc, {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)

    def test_django_validation_error_with_string(self):
        exc = DjangoValidationError('Erro simples.')
        resp = forensiq_exception_handler(exc, {})
        self.assertEqual(resp.status_code, 400)

    def test_non_django_error_returns_generic_500_in_production(self):
        """Excepcoes nao-DRF em producao sao mascaradas com 500 generico.

        Comportamento adicionado em chore(api) commit 2927437: o handler
        intercepta ``response is None`` (DRF nao sabia processar) e devolve
        Response 500 com mensagem generica em vez de propagar o stack
        trace para o cliente (OWASP A05:2021 Security Misconfiguration).

        O teste corre com DEBUG=False (test_settings.py), portanto a
        ramificacao de mascaramento dispara.
        """
        exc = ValueError('Algo inesperado')
        resp = forensiq_exception_handler(exc, {})
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 500)
        self.assertIn('detail', resp.data)
        # Nao deve vazar 'Algo inesperado' nem nada do tipo na resposta.
        self.assertNotIn('inesperado', resp.data['detail'])


# =========================================================================
# 4. MIDDLEWARE
# =========================================================================

class CorrelationIDMiddlewareTest(TestCase):
    """Cobertura de ``core.middleware.CorrelationIDMiddleware``."""

    def test_adds_correlation_id_header(self):
        rf = RequestFactory()
        request = rf.get('/fake/')

        def get_response(request):
            from django.http import HttpResponse
            return HttpResponse('OK')

        middleware = CorrelationIDMiddleware(get_response)
        response = middleware(request)
        self.assertIn('X-Correlation-ID', response)
        self.assertRegex(response['X-Correlation-ID'], r'^[0-9a-f-]{36}$')


class ContentSecurityPolicyMiddlewareTest(TestCase):
    """Cobertura de ``core.middleware.ContentSecurityPolicyMiddleware``."""

    def test_adds_csp_header(self):
        rf = RequestFactory()
        request = rf.get('/fake/')

        def get_response(request):
            from django.http import HttpResponse
            return HttpResponse('OK')

        middleware = ContentSecurityPolicyMiddleware(get_response)
        response = middleware(request)
        self.assertIn('Content-Security-Policy', response)
        csp = response['Content-Security-Policy']
        self.assertIn('default-src', csp)
        self.assertIn('frame-ancestors', csp)


# =========================================================================
# 5. PDF CONTENT VALIDATION
# =========================================================================

class PDFContentValidationTest(TestCase):
    """Verifica que o PDF contem elementos forenses obrigatorios.

    Correccao do item do code review:
    > ALTO - Falta validacao de conteudo do PDF
    > Testes verificam assinatura %PDF e tamanho, mas nao que hash
    > SHA-256, dispositivos e cadeia de custodia aparecem no PDF.
    """

    def setUp(self):
        self.agent = UserFactory.create()
        self.occ = OccurrenceFactory.create(agent=self.agent)
        self.evidence = EvidenceMobileFactory.create(
            occurrence=self.occ, agent=self.agent,
            description='Samsung Galaxy S24 apreendido em Lisboa',
        )
        self.device = DigitalDeviceFactory.create(
            evidence=self.evidence,
            brand='Samsung',
            model='Galaxy S24',
        )
        self.custody = ChainOfCustodyFactory.create(
            evidence=self.evidence,
            agent=self.agent,
        )

    def _extract_pdf_text(self, pdf_bytes):
        """Extrai texto do PDF usando pypdf.

        ReportLab comprime streams com ASCII85+FlateDecode, pelo que ler
        os bytes em bruto e procurar substrings nao funciona — o texto
        nao aparece descomprimido. Usamos pypdf para descodificar cada
        pagina e concatenar.
        """
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        return '\n'.join(page.extract_text() or '' for page in reader.pages)

    def test_evidence_pdf_contains_sha256_hash(self):
        from core.pdf_export import generate_evidence_pdf
        pdf_bytes = generate_evidence_pdf(self.evidence)
        text = self._extract_pdf_text(pdf_bytes)
        self.assertIn(self.evidence.integrity_hash[:16], text)

    def test_evidence_pdf_contains_evidence_type(self):
        from core.pdf_export import generate_evidence_pdf
        pdf_bytes = generate_evidence_pdf(self.evidence)
        text = self._extract_pdf_text(pdf_bytes)
        self.assertIn('Samsung', text)

    def test_evidence_pdf_contains_custody_info(self):
        from core.pdf_export import generate_evidence_pdf
        pdf_bytes = generate_evidence_pdf(self.evidence)
        text = self._extract_pdf_text(pdf_bytes)
        self.assertIn('APREENDIDA', text.upper())

    def test_occurrence_pdf_contains_evidence_list(self):
        from core.pdf_export import generate_occurrence_pdf
        pdf_bytes = generate_occurrence_pdf(self.occ)
        text = self._extract_pdf_text(pdf_bytes)
        self.assertIn('Samsung', text)


# =========================================================================
# 6. DASHBOARD STATS - ownership isolation
# =========================================================================

class DashboardStatsOwnershipTest(APITestCase):
    """Verifica que os endpoints de stats respeitam ownership."""

    def setUp(self):
        self.agent_a = UserFactory.create(password='TestPass123!')
        self.agent_b = UserFactory.create(password='TestPass123!')
        self.expert = ExpertFactory.create(password='TestPass123!')

        self.occ_a = OccurrenceFactory.create(agent=self.agent_a)
        self.occ_b = OccurrenceFactory.create(agent=self.agent_b)
        self.ev_a = EvidenceMobileFactory.create(
            occurrence=self.occ_a, agent=self.agent_a,
        )
        self.ev_b = EvidenceMobileFactory.create(
            occurrence=self.occ_b, agent=self.agent_b,
        )

    def _login(self, user):
        client = APIClient()
        resp = client.post('/api/auth/login/', {
            'username': user.username,
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, 200)
        return client

    def test_agent_a_sees_only_own_stats(self):
        client = self._login(self.agent_a)
        resp = client.get('/api/stats/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['occurrences'], 1)
        self.assertEqual(resp.data['evidences'], 1)

    def test_agent_b_sees_only_own_stats(self):
        client = self._login(self.agent_b)
        resp = client.get('/api/stats/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['occurrences'], 1)
        self.assertEqual(resp.data['evidences'], 1)

    def test_expert_sees_all_stats(self):
        client = self._login(self.expert)
        resp = client.get('/api/stats/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['occurrences'], 2)
        self.assertEqual(resp.data['evidences'], 2)

    def test_dashboard_stats_agent_isolation(self):
        client = self._login(self.agent_a)
        resp = client.get('/api/stats/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_occurrences'], 1)
        self.assertEqual(resp.data['total_evidences'], 1)

    def test_dashboard_stats_expert_sees_all(self):
        client = self._login(self.expert)
        resp = client.get('/api/stats/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_occurrences'], 2)
        self.assertEqual(resp.data['total_evidences'], 2)

    def test_dashboard_stats_unauthenticated_denied(self):
        client = APIClient()
        resp = client.get('/api/stats/dashboard/')
        self.assertEqual(resp.status_code, 401)


# =========================================================================
# 7. HEALTHCHECK
# =========================================================================

class HealthcheckTest(TestCase):
    """Cobertura de ``core.views.healthcheck``."""

    def test_healthcheck_returns_200(self):
        from django.test import Client
        client = Client()
        resp = client.get('/api/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')

    def test_healthcheck_no_auth_required(self):
        from django.test import Client
        client = Client()
        resp = client.get('/api/health/')
        self.assertEqual(resp.status_code, 200)


# =========================================================================
# 8. THROTTLE CONFIGURATION
# =========================================================================

class ThrottleConfigTest(TestCase):
    """Verifica que os throttles estao configurados correctamente."""

    def test_auth_throttle_scope_is_auth(self):
        throttle = AuthRateThrottle()
        self.assertEqual(throttle.scope, 'auth')

    def test_auth_throttle_inherits_anon(self):
        from rest_framework.throttling import AnonRateThrottle
        self.assertTrue(issubclass(AuthRateThrottle, AnonRateThrottle))


# =========================================================================
# 9. SERIALIZER EDGE CASES
# =========================================================================

class SerializerEdgeCasesTest(APITestCase):
    """Testes de edge cases em serializers."""

    def setUp(self):
        self.agent = UserFactory.create(password='TestPass123!')
        self.occ = OccurrenceFactory.create(agent=self.agent)
        self.client = APIClient()
        resp = self.client.post('/api/auth/login/', {
            'username': self.agent.username,
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, 200)

    def test_evidence_timestamp_seizure_is_readonly(self):
        """Confirma que timestamp_seizure nao pode ser manipulado pelo cliente."""
        fake_time = '2020-01-01T00:00:00Z'
        resp = self.client.post('/api/evidences/', {
            'occurrence': self.occ.pk,
            'type': 'MOBILE_DEVICE',
            'description': 'Teste de timestamp',
            'serial_number': 'SN-TS-001',
            'timestamp_seizure': fake_time,
        })
        self.assertEqual(resp.status_code, 201)
        self.assertNotEqual(resp.data.get('timestamp_seizure'), fake_time)

    def test_user_serializer_hides_email(self):
        """UserSerializer publico nao expoe email."""
        resp = self.client.get('/api/users/')
        self.assertEqual(resp.status_code, 200)
        if resp.data.get('results'):
            user_data = resp.data['results'][0]
        else:
            user_data = resp.data[0] if isinstance(resp.data, list) else {}
        self.assertNotIn('email', user_data)
        self.assertNotIn('phone', user_data)
        self.assertNotIn('badge_number', user_data)

    def test_me_endpoint_shows_email(self):
        """UserDetailSerializer (/me/) expoe email e badge."""
        resp = self.client.get('/api/users/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('email', resp.data)
        self.assertIn('badge_number', resp.data)

    def test_evidence_code_auto_generated(self):
        """Codigo de evidencia e gerado automaticamente pelo servidor."""
        resp = self.client.post('/api/evidences/', {
            'occurrence': self.occ.pk,
            'type': 'MOBILE_DEVICE',
            'description': 'Teste de codigo',
            'serial_number': 'SN-CODE-001',
        })
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(resp.data.get('code'))
        # Formato gerado por core/models.py:Evidence.save() — ITM-YYYY-NNNNN
        # (ITM = item; o prefixo original "EVI-" foi renomeado em PR posterior).
        self.assertRegex(resp.data['code'], r'^ITM-\d{4}-\d{5}$')


# =========================================================================
# 10. MODEL INTEGRITY - compute_record_hash includes ID
# =========================================================================

class RecordHashIntegrityTest(TestCase):
    """Verifica que o hash da cadeia de custodia e robusto.

    Correccao do item do code review:
    > ALTO - compute_record_hash() sem ID do registo
    """

    def setUp(self):
        self.agent = UserFactory.create()
        self.occ = OccurrenceFactory.create(agent=self.agent)
        self.ev = EvidenceMobileFactory.create(
            occurrence=self.occ, agent=self.agent,
        )

    def test_custody_records_have_unique_hashes(self):
        """Dois registos de custodia com dados semelhantes tem hashes distintos."""
        c1 = ChainOfCustody.objects.create(
            evidence=self.ev,
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
            observations='Apreensao teste',
        )
        c2 = ChainOfCustody.objects.create(
            evidence=self.ev,
            new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
            agent=self.agent,
            observations='Transporte teste',
        )
        self.assertNotEqual(c1.record_hash, c2.record_hash)

    def test_hash_chain_links_correctly(self):
        """O record_hash do segundo registo encadeia com o do primeiro.

        ChainOfCustody nao armazena `previous_hash` como campo; o
        encadeamento e feito em ``compute_record_hash(previous_hash=...)``
        que e funcao pura. Verificamos que recomputar o hash de ``c2``
        passando ``c1.record_hash`` como entrada reproduz exactamente o
        valor que foi gravado, e que e diferente do hash de ``c1``.
        """
        c1 = ChainOfCustody.objects.create(
            evidence=self.ev,
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
            observations='Primeiro registo',
        )
        c2 = ChainOfCustody.objects.create(
            evidence=self.ev,
            new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
            agent=self.agent,
            observations='Segundo registo',
        )
        self.assertNotEqual(c1.record_hash, c2.record_hash)
        self.assertEqual(
            c2.compute_record_hash(previous_hash=c1.record_hash),
            c2.record_hash,
        )

    def test_evidence_integrity_hash_not_empty(self):
        """Cada evidencia criada tem um hash SHA-256 de integridade."""
        self.assertIsNotNone(self.ev.integrity_hash)
        self.assertEqual(len(self.ev.integrity_hash), 64)


# =========================================================================
# 11. LOOKUP VIEWS - IMEI / VIN
# =========================================================================

class IMEILookupViewTest(APITestCase):
    """Cobertura de ``EvidenceIMEILookupView``."""

    def setUp(self):
        self.agent = UserFactory.create(password='TestPass123!')
        self.client = APIClient()
        resp = self.client.post('/api/auth/login/', {
            'username': self.agent.username,
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, 200)

    def test_invalid_imei_returns_400(self):
        resp = self.client.get('/api/evidences/lookup/imei/12345/')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_imei_luhn_returns_400(self):
        resp = self.client.get('/api/evidences/lookup/imei/490154203237519/')
        self.assertEqual(resp.status_code, 400)


class VINLookupViewTest(APITestCase):
    """Cobertura de ``EvidenceVINLookupView``."""

    def setUp(self):
        self.agent = UserFactory.create(password='TestPass123!')
        self.client = APIClient()
        resp = self.client.post('/api/auth/login/', {
            'username': self.agent.username,
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, 200)

    def test_valid_vin_returns_url(self):
        resp = self.client.get('/api/evidences/lookup/vin/WVWZZZ3CZWE123456/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('url', resp.data)
        self.assertIn('vindecoder', resp.data['url'])

    def test_invalid_vin_returns_400(self):
        resp = self.client.get('/api/evidences/lookup/vin/INVALID/')
        self.assertEqual(resp.status_code, 400)

    def test_vin_with_forbidden_letters_returns_400(self):
        resp = self.client.get('/api/evidences/lookup/vin/WVWZZZ3CZWI123456/')
        self.assertEqual(resp.status_code, 400)


# =========================================================================
# 12. OCCURRENCE CODE AUTO-GENERATION
# =========================================================================

class OccurrenceCodeTest(APITestCase):
    """Verifica que codigos de ocorrencia sao gerados automaticamente."""

    def setUp(self):
        self.agent = UserFactory.create(password='TestPass123!')
        self.client = APIClient()
        resp = self.client.post('/api/auth/login/', {
            'username': self.agent.username,
            'password': 'TestPass123!',
        })
        self.assertEqual(resp.status_code, 200)

    def test_occurrence_code_auto_generated(self):
        resp = self.client.post('/api/occurrences/', {
            'number': 'NUIPC-TEST-001',
            'description': 'Teste de codigo',
            'date_time': '2026-05-08T10:00:00Z',
            'gps_lat': '38.7223',
            'gps_lon': '-9.1393',
            'address': 'Lisboa',
        })
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(resp.data.get('code'))
        self.assertTrue(resp.data['code'].startswith('OCC-'))

    def test_occurrence_codes_are_unique(self):
        for i in range(3):
            resp = self.client.post('/api/occurrences/', {
                'number': f'NUIPC-UNIQ-{i:03d}',
                'description': f'Teste {i}',
                'date_time': '2026-05-08T10:00:00Z',
                'gps_lat': '38.7223',
                'gps_lon': '-9.1393',
                'address': 'Lisboa',
            })
            self.assertEqual(resp.status_code, 201)
        codes = Occurrence.objects.values_list('code', flat=True)
        self.assertEqual(len(set(codes)), len(codes))


# =========================================================================
# 13. SEED COMMAND - smoke test do seed_demo --users-only --no-input
# =========================================================================

class SeedDemoUsersOnlyTest(TestCase):
    """Smoke test do management command ``seed_demo`` em modo --users-only.

    Verifica que o command corre sem erro em modo nao-interactivo, cria
    dois utilizadores com os perfis correctos e e idempotente (re-correr
    nao duplica nem falha).
    """

    def test_users_only_creates_two_users(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command(
            'seed_demo',
            '--users-only',
            '--no-input',
            '--agent-username=smoke-agent',
            '--agent-password=SmokeAgent1!',
            '--expert-username=smoke-expert',
            '--expert-password=SmokeExpert1!',
            stdout=out,
        )

        agent = User.objects.get(username='smoke-agent')
        expert = User.objects.get(username='smoke-expert')
        self.assertEqual(agent.profile, User.Profile.AGENT)
        self.assertEqual(expert.profile, User.Profile.EXPERT)
        self.assertFalse(agent.is_superuser)
        self.assertFalse(expert.is_superuser)
        self.assertTrue(agent.check_password('SmokeAgent1!'))
        self.assertTrue(expert.check_password('SmokeExpert1!'))

    def test_users_only_is_idempotent(self):
        from django.core.management import call_command
        from io import StringIO

        for _ in range(2):
            call_command(
                'seed_demo',
                '--users-only',
                '--no-input',
                '--agent-username=idem-agent',
                '--agent-password=IdemAgent1!',
                '--expert-username=idem-expert',
                '--expert-password=IdemExpert1!',
                stdout=StringIO(),
            )

        self.assertEqual(
            User.objects.filter(username__in=['idem-agent', 'idem-expert']).count(),
            2,
        )

    def test_no_input_without_flags_raises(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO

        with self.assertRaises(CommandError):
            call_command(
                'seed_demo', '--users-only', '--no-input', stdout=StringIO(),
            )

    def test_same_username_for_both_profiles_raises(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO

        with self.assertRaises(CommandError):
            call_command(
                'seed_demo',
                '--users-only',
                '--no-input',
                '--agent-username=same',
                '--agent-password=Same1234!',
                '--expert-username=same',
                '--expert-password=Same1234!',
                stdout=StringIO(),
            )
