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

from core.middleware import ContentSecurityPolicyMiddleware, CorrelationIDMiddleware
from core.models import ChainOfCustody, Evidence, Occurrence, User
from core.permissions import IsAgent, IsAgentOrExpert, IsExpert, IsOwnerOrReadOnly

# =========================================================================
# 1. VALIDADORES - testes unitarios puros (sem BD)
# =========================================================================
from core.tests_base import login_client, throttle_rate
from core.tests_factories import (
    TEST_PASSWORD,
    VALID_IMEI,
    ChainOfCustodyFactory,
    CrimeTipoFactory,
    EvidenceMobileFactory,
    ExpertFactory,
    OccurrenceFactory,
    UserFactory,
)
from core.throttles import AuthRateThrottle
from core.validators import (
    validate_imei,
    validate_imsi,
    validate_imsi_advisory,
    validate_vin,
    validate_vin_advisory,
)


class ValidateIMEITest(TestCase):
    """Cobertura de ``core.validators.validate_imei``."""

    def test_valid_imei_passes(self):
        validate_imei(VALID_IMEI)

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


class VinCheckDigitAdvisoryTest(TestCase):
    """Cobertura de ``core.validators.validate_vin_advisory`` (ISO 3779)."""

    # VIN sintético com 17 uns: soma=89, 89%11=1 → check digit '1' (posição 9).
    VALID_CHECK_DIGIT_VIN = '11111111111111111'
    # VIN americano real (Honda) — check digit 'X' calculado por FMVSS 115.
    VALID_NHTSA_VIN = '1M8GDM9AXKP042788'
    # Volkswagen europeu — estrutura válida, check digit NÃO confere.
    EUROPEAN_NON_NHTSA_VIN = 'WVWZZZ3CZWE123456'

    def test_valid_check_digit_returns_none(self):
        self.assertIsNone(validate_vin_advisory(self.VALID_CHECK_DIGIT_VIN))

    def test_nhtsa_compliant_vin_returns_none(self):
        self.assertIsNone(validate_vin_advisory(self.VALID_NHTSA_VIN))

    def test_european_vin_with_wrong_check_digit_returns_advisory(self):
        msg = validate_vin_advisory(self.EUROPEAN_NON_NHTSA_VIN)
        self.assertIsNotNone(msg)
        self.assertIn('ISO 3779', msg)

    def test_structurally_invalid_vin_returns_none(self):
        # VINs com letras proibidas ou comprimento errado já são rejeitados
        # por validate_vin; o advisory devolve None nesses casos.
        self.assertIsNone(validate_vin_advisory('TOO_SHORT'))
        self.assertIsNone(validate_vin_advisory('WVWZZZ3CZWI123456'))  # com I
        self.assertIsNone(validate_vin_advisory(None))

    def test_advisory_does_not_raise_on_invalid_check_digit(self):
        # validate_vin continua a aceitar VINs estruturalmente válidos
        # mesmo com check digit errado — o advisory é o único sinal.
        validate_vin(self.EUROPEAN_NON_NHTSA_VIN)  # não levanta


class ImsiAdvisoryTest(TestCase):
    """Cobertura de ``core.validators.validate_imsi_advisory`` (MCC PT/UE)."""

    def test_portuguese_mcc_268_returns_none(self):
        self.assertIsNone(validate_imsi_advisory('268011234567890'))

    def test_spanish_mcc_214_returns_none(self):
        self.assertIsNone(validate_imsi_advisory('214071234567890'))

    def test_unknown_mcc_999_returns_advisory(self):
        msg = validate_imsi_advisory('999011234567890')
        self.assertIsNotNone(msg)
        self.assertIn('999', msg)

    def test_structurally_invalid_imsi_returns_none(self):
        # IMSIs com formato errado já são rejeitados por validate_imsi;
        # o advisory devolve None nesses casos.
        self.assertIsNone(validate_imsi_advisory('123'))
        self.assertIsNone(validate_imsi_advisory('26801123456789A'))
        self.assertIsNone(validate_imsi_advisory(None))


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
            username='admin_no_profile',
            password=TEST_PASSWORD,
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
# 3. MIDDLEWARE
# =========================================================================
# Nota: a cobertura de ``forensiq_exception_handler`` (antes aqui) foi
# consolidada em ``tests_services.py::ExceptionHandlerTest`` (superconjunto,
# inclui o ramo DEBUG=True). T16.


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
# 6. DASHBOARD STATS - ownership isolation
# =========================================================================


class DashboardStatsOwnershipTest(APITestCase):
    """Verifica que os endpoints de stats respeitam ownership."""

    def setUp(self):
        self.agent_a = UserFactory.create(password=TEST_PASSWORD)
        self.agent_b = UserFactory.create(password=TEST_PASSWORD)
        self.expert = ExpertFactory.create(password=TEST_PASSWORD)

        self.occ_a = OccurrenceFactory.create(agent=self.agent_a)
        self.occ_b = OccurrenceFactory.create(agent=self.agent_b)
        self.ev_a = EvidenceMobileFactory.create(
            occurrence=self.occ_a,
            agent=self.agent_a,
        )
        self.ev_b = EvidenceMobileFactory.create(
            occurrence=self.occ_b,
            agent=self.agent_b,
        )

    def _login(self, user):
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        return login_client(user)

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
    """Cobertura de ``core.views.healthcheck`` (endpoint público de liveness)."""

    def test_healthcheck_returns_200_sem_auth(self):
        """Cliente sem credenciais obtém 200 + status 'ok' (não exige auth)."""
        from django.test import Client

        client = Client()
        resp = client.get('/api/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')


class HealthcheckThrottleTest(APITestCase):
    """O healthcheck público está protegido por HealthcheckRateThrottle (por IP)
    — fecha o finding `healthcheck-sem-throttle-info-leak`.
    """

    def setUp(self):
        from django.core.cache import cache

        # SimpleRateThrottle conta na default cache; limpar evita herdar
        # contagens de outros testes.
        cache.clear()

    def test_throttle_scope_is_healthcheck(self):
        from core.throttles import HealthcheckRateThrottle

        self.assertEqual(HealthcheckRateThrottle().scope, 'healthcheck')

    def test_429_apos_limite(self):
        from unittest.mock import patch

        # Throttle de UM scope na fonte unica (tests_base.throttle_rate - D115).
        with throttle_rate('healthcheck', '2/minute'):
            r1 = self.client.get('/api/health/')
            r2 = self.client.get('/api/health/')
            r3 = self.client.get('/api/health/')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)


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
        self.agent = UserFactory.create(password=TEST_PASSWORD)
        self.occ = OccurrenceFactory.create(agent=self.agent)
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.agent)

    def test_evidence_timestamp_seizure_is_readonly(self):
        """Confirma que timestamp_seizure nao pode ser manipulado pelo cliente."""
        fake_time = '2020-01-01T00:00:00Z'
        resp = self.client.post(
            '/api/evidences/',
            {
                'occurrence': self.occ.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Teste de timestamp',
                'serial_number': 'SN-TS-001',
                'timestamp_seizure': fake_time,
            },
        )
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
        resp = self.client.post(
            '/api/evidences/',
            {
                'occurrence': self.occ.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Teste de codigo',
                'serial_number': 'SN-CODE-001',
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(resp.data.get('code'))
        # Formato gerado por core/models.py:Evidence.save() — ITM-YYYY-NNNNN
        # (ITM = item; o prefixo original "EVI-" foi renomeado em PR posterior).
        self.assertRegex(resp.data['code'], r'^OC-\d{4}-\d{4}\.\d+$')


# =========================================================================
# 10. LOOKUP VIEWS - IMEI / VIN
# =========================================================================
# Nota: a integridade do hash-chain (records únicos, recompute encadeado) e
# o hash de integridade da evidência estão cobertos por
# ``tests.py::ChainOfCustodyModelTest::test_hash_chain_integrity``,
# ``CustodyHashFormulaTest`` e ``EvidenceModelTest::test_create_evidence_with_auto_hash``. T16.


class IMEILookupViewTest(APITestCase):
    """Cobertura de ``EvidenceIMEILookupView``."""

    def setUp(self):
        self.agent = UserFactory.create(password=TEST_PASSWORD)
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.agent)

    def test_invalid_imei_returns_400(self):
        resp = self.client.get('/api/evidences/lookup/imei/12345/')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_imei_luhn_returns_400(self):
        resp = self.client.get('/api/evidences/lookup/imei/490154203237519/')
        self.assertEqual(resp.status_code, 400)


class VINLookupViewTest(APITestCase):
    """Cobertura de ``EvidenceVINLookupView``."""

    def setUp(self):
        self.agent = UserFactory.create(password=TEST_PASSWORD)
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.agent)

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
        self.agent = UserFactory.create(password=TEST_PASSWORD)
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.agent)

    def test_occurrence_code_auto_generated(self):
        resp = self.client.post(
            '/api/occurrences/',
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-TEST-001',
                'description': 'Teste de codigo',
                'date_time': '2026-05-08T10:00:00Z',
                'gps_lat': '38.7223',
                'gps_lng': '-9.1393',
                'address': 'Lisboa',
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(resp.data.get('code'))
        self.assertTrue(resp.data['code'].startswith('OC-'))

    def test_occurrence_codes_are_unique(self):
        for i in range(3):
            resp = self.client.post(
                '/api/occurrences/',
                {
                    'crime_type': CrimeTipoFactory().id,
                    'number': f'NUIPC-UNIQ-{i:03d}',
                    'description': f'Teste {i}',
                    'date_time': '2026-05-08T10:00:00Z',
                    'gps_lat': '38.7223',
                    'gps_lng': '-9.1393',
                    'address': 'Lisboa',
                },
            )
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
        from io import StringIO

        from django.core.management import call_command

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
        self.assertEqual(agent.profile, User.Profile.FIRST_RESPONDER)
        self.assertEqual(expert.profile, User.Profile.FORENSIC_EXPERT)
        self.assertFalse(agent.is_superuser)
        self.assertFalse(expert.is_superuser)
        self.assertTrue(agent.check_password('SmokeAgent1!'))
        self.assertTrue(expert.check_password('SmokeExpert1!'))

    def test_users_only_is_idempotent(self):
        from io import StringIO

        from django.core.management import call_command

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
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                'seed_demo',
                '--users-only',
                '--no-input',
                stdout=StringIO(),
            )

    def test_same_username_for_both_profiles_raises(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

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


# =========================================================================
# 14. CSRF / CORS ORIGIN ALIGNMENT (audit 2026-05-18 §3 N11)
# =========================================================================


class CsrfCorsOriginAlignmentTest(TestCase):
    """Garante que CORS_ALLOWED_ORIGINS e CSRF_TRUSTED_ORIGINS partilham
    a mesma lista canónica (`_FRONTEND_ORIGINS` em settings.py) — evita
    drift silencioso entre as duas configurações.
    """

    def test_origins_alinhadas(self):
        from django.conf import settings

        self.assertEqual(
            set(settings.CORS_ALLOWED_ORIGINS),
            set(settings.CSRF_TRUSTED_ORIGINS),
        )

    def test_origins_prod_sempre_incluidas(self):
        from django.conf import settings

        prod = {
            'https://forensiq.pt',
            'https://www.forensiq.pt',
            'https://forensiq.fly.dev',
        }
        self.assertTrue(prod.issubset(set(settings.CORS_ALLOWED_ORIGINS)))
        self.assertTrue(prod.issubset(set(settings.CSRF_TRUSTED_ORIGINS)))


# =========================================================================
# 15. IMEI LOOKUP THROTTLE (audit 2026-05-18 §3 N8)
# =========================================================================


class ImeiLookupThrottleTest(APITestCase):
    """Verifica que `EvidenceIMEILookupView` aplica o scope `imei_lookup`
    e devolve 429 quando o limite é atingido — protege o saldo pago em
    `imeidb.xyz` contra abuso por agente isolado.
    """

    def setUp(self):
        from django.core.cache import cache

        self.agent = UserFactory.create(password=TEST_PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.agent)
        # SimpleRateThrottle conta na Django default cache; sem clear()
        # o contador herda contagens de outros testes.
        cache.clear()

    def test_imei_lookup_throttle_scope(self):
        from core.views import EvidenceIMEILookupView

        self.assertEqual(EvidenceIMEILookupView.throttle_scope, 'imei_lookup')

    def test_429_apos_limite(self):
        from unittest.mock import patch


        imei = VALID_IMEI  # Luhn-válido (sample TAC Apple)
        fake_payload = {
            'brand': 'Apple',
            'model': 'A2161',
            'commercial_name': 'iPhone 11 Pro Max',
            'manufacturer': 'Apple',
            'os': 'iOS',
            'storage': '',
            'release_date': '',
            'color': '',
            'tac': '49015420',
            'type': 'mobile',
            'normalised_complete': True,
            'raw': {},
        }
        url = f'/api/evidences/lookup/imei/{imei}/'

        # Throttle de UM scope na fonte unica (tests_base.throttle_rate - D115).
        with (
            throttle_rate('imei_lookup', '2/minute'),
            patch('core.views.lookup_imei', return_value=fake_payload),
        ):
            r1 = self.client.get(url)
            r2 = self.client.get(url)
            r3 = self.client.get(url)

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)
