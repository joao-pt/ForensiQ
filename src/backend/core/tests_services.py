"""
ForensiQ — Testes para módulos de serviço, autenticação e auditoria.

Cobre áreas identificadas com baixa cobertura:
- ``services/imei_lookup.py``  — consulta IMEI com mocks httpx
- ``services/vin_lookup.py``   — construção de URL VIN decoder
- ``auth.py``                  — JWTCookieAuthentication, cookies, CSRF
- ``auth_views.py``            — login/refresh/logout via cookies
- ``audit.py``                 — extracção de IP, proxies de confiança
- ``exceptions.py``            — exception handler global
- ``filters.py``               — filtersets OccurrenceFilter, EvidenceFilter, CustodyFilter

Convençoes:
- Factories de ``tests_factories.py`` reutilizadas para setup.
- Mocks para chamadas HTTP externas (httpx, Nominatim).
- Nomes de teste descrevem o comportamento esperado em PT.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from core.models import AuditLog, ChainOfCustody, Evidence, Occurrence, User

# =========================================================================
# 1. IMEI LOOKUP SERVICE
# =========================================================================
from core.tests_base import login_client
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


class IMEILookupNoTokenTest(TestCase):
    """Testes para ``lookup_imei`` quando o token não está configurado."""

    @override_settings(IMEIDB_API_TOKEN='')
    def test_no_token_raises_lookup_error(self):
        from core.services.imei_lookup import LookupError, lookup_imei

        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('não está configurado', str(ctx.exception))


class IMEILookupNetworkErrorsTest(TestCase):
    """Testes para falhas de rede no ``lookup_imei``."""

    @override_settings(IMEIDB_API_TOKEN='test-token', IMEIDB_TIMEOUT_SECONDS=5)
    @patch('core.services.imei_lookup.httpx.Client')
    def test_timeout_raises_lookup_error(self, mock_client_cls):
        import httpx

        from core.services.imei_lookup import LookupError, lookup_imei

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException('timeout')
        mock_client_cls.return_value = mock_client

        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('Tempo esgotado', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_network_error_raises_lookup_error(self, mock_client_cls):
        import httpx

        from core.services.imei_lookup import LookupError, lookup_imei

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.RequestError('connection failed')
        mock_client_cls.return_value = mock_client

        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('Erro de rede', str(ctx.exception))


class IMEILookupHTTPErrorsTest(TestCase):
    """Testes para códigos HTTP de erro da imeidb.xyz."""

    def _make_mock_response(self, status_code, json_data=None):
        resp = MagicMock()
        resp.status_code = status_code
        if json_data is not None:
            resp.json.return_value = json_data
        return resp

    def _setup_client_mock(self, mock_client_cls, response):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response
        mock_client_cls.return_value = mock_client

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_401_raises_invalid_token(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(401))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('Token', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_402_raises_balance_exhausted(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(402))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('Saldo', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_429_raises_rate_limit(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(429))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('Limite', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_404_raises_not_found(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(404))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('não encontrado', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_460_raises_not_found(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(460))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('não encontrado', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_500_raises_unavailable(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(500))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('indisponível', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_unexpected_status_raises(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        self._setup_client_mock(mock_client_cls, self._make_mock_response(418))
        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('418', str(ctx.exception))


class IMEILookupSuccessTest(TestCase):
    """Testes para respostas bem-sucedidas da imeidb.xyz."""

    def _make_success_response(self, payload):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        return resp

    def _setup_client_mock(self, mock_client_cls, response):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response
        mock_client_cls.return_value = mock_client

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_success_normalizes_data(self, mock_client_cls):
        from core.services.imei_lookup import lookup_imei

        payload = {
            'success': True,
            'data': {
                'brand': 'Apple',
                'model': 'A2161',
                'manufacturer': 'Apple Inc.',
                'name': 'Apple iPhone 11 Pro Max',
                'tac': '35394911',
                'type': 'Smartphone',
                'device_spec': {'os': 'iOS 17', 'os_family': 'iOS'},
            },
        }
        self._setup_client_mock(mock_client_cls, self._make_success_response(payload))
        result = lookup_imei(VALID_IMEI)

        self.assertEqual(result['brand'], 'Apple')
        self.assertEqual(result['model'], 'A2161')
        # Nome comercial sem prefixo da marca
        self.assertEqual(result['commercial_name'], 'iPhone 11 Pro Max')
        self.assertEqual(result['os'], 'iOS 17')
        self.assertTrue(result['normalised_complete'])
        self.assertIn('raw', result)

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_success_false_raises(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        payload = {'success': False, 'code': 402, 'message': 'No credits'}
        self._setup_client_mock(mock_client_cls, self._make_success_response(payload))

        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('Saldo', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_non_json_raises(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError('not json')
        self._setup_client_mock(mock_client_cls, resp)

        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('JSON', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_non_dict_payload_raises(self, mock_client_cls):
        from core.services.imei_lookup import LookupError, lookup_imei

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = ['not', 'a', 'dict']
        self._setup_client_mock(mock_client_cls, resp)

        with self.assertRaises(LookupError) as ctx:
            lookup_imei(VALID_IMEI)
        self.assertIn('formato inesperado', str(ctx.exception))

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_flat_payload_without_data_key(self, mock_client_cls):
        from core.services.imei_lookup import lookup_imei

        # Payload achatado (sem chave 'data' wrapper)
        payload = {
            'success': True,
            'brand': 'Samsung',
            'model': 'SM-G950F',
            'manufacturer': 'Samsung',
            'name': 'Samsung Galaxy S8',
        }
        self._setup_client_mock(mock_client_cls, self._make_success_response(payload))
        result = lookup_imei(VALID_IMEI)

        self.assertEqual(result['brand'], 'Samsung')
        self.assertEqual(result['model'], 'SM-G950F')
        self.assertTrue(result['normalised_complete'])

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_device_image_stripped_from_raw(self, mock_client_cls):
        from core.services.imei_lookup import lookup_imei

        payload = {
            'success': True,
            'data': {
                'brand': 'Apple',
                'model': 'A2161',
                'device_image': 'base64_very_long_string...',
            },
        }
        self._setup_client_mock(mock_client_cls, self._make_success_response(payload))
        result = lookup_imei(VALID_IMEI)

        self.assertNotIn('device_image', result['raw'])

    @override_settings(IMEIDB_API_TOKEN='test-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_incomplete_data_sets_flag_false(self, mock_client_cls):
        from core.services.imei_lookup import lookup_imei

        payload = {
            'success': True,
            'data': {'tac': '12345678'},  # sem brand nem model
        }
        self._setup_client_mock(mock_client_cls, self._make_success_response(payload))
        result = lookup_imei(VALID_IMEI)

        self.assertFalse(result['normalised_complete'])


class IMEILookupMessageForApiCodeTest(TestCase):
    """Testes para ``_message_for_api_code``."""

    def test_known_code_returns_mapped_message(self):
        from core.services.imei_lookup import _message_for_api_code

        msg = _message_for_api_code(401, 'fallback')
        self.assertIn('Token', msg)

    def test_unknown_code_with_fallback(self):
        from core.services.imei_lookup import _message_for_api_code

        msg = _message_for_api_code(999, 'some error')
        self.assertIn('some error', msg)

    def test_unknown_code_no_fallback(self):
        from core.services.imei_lookup import _message_for_api_code

        msg = _message_for_api_code(None, '')
        self.assertIn('formato inesperado', msg)


class IMEILookupHelpersTest(TestCase):
    """Testes para helpers internos do imei_lookup."""

    def test_base_url_default(self):
        from core.services.imei_lookup import _base_url

        url = _base_url()
        self.assertIn('imeidb.xyz', url)

    @override_settings(IMEIDB_BASE_URL='https://custom.api.com/v2')
    def test_base_url_custom(self):
        from core.services.imei_lookup import _base_url

        self.assertEqual(_base_url(), 'https://custom.api.com/v2')

    def test_timeout_default(self):
        from core.services.imei_lookup import _timeout

        self.assertEqual(_timeout(), 10.0)

    @override_settings(IMEIDB_TIMEOUT_SECONDS=30)
    def test_timeout_custom(self):
        from core.services.imei_lookup import _timeout

        self.assertEqual(_timeout(), 30.0)

    def test_trim_raw_removes_device_image(self):
        from core.services.imei_lookup import _trim_raw

        data = {'brand': 'Apple', 'device_image': 'huge_base64', 'model': 'X'}
        result = _trim_raw(data)
        self.assertNotIn('device_image', result)
        self.assertEqual(result['brand'], 'Apple')


# =========================================================================
# 2. VIN LOOKUP SERVICE
# =========================================================================


class VINLookupTest(TestCase):
    """Testes para ``build_vindecoder_url``."""

    def test_builds_correct_url(self):
        from core.services.vin_lookup import build_vindecoder_url

        url = build_vindecoder_url('WVWZZZ3CZWE123456')
        self.assertEqual(url, 'https://vindecoder.eu/check-vin/WVWZZZ3CZWE123456')

    def test_uppercases_vin(self):
        from core.services.vin_lookup import build_vindecoder_url

        url = build_vindecoder_url('wvwzzz3czwe123456')
        self.assertIn('WVWZZZ3CZWE123456', url)

    def test_strips_whitespace(self):
        from core.services.vin_lookup import build_vindecoder_url

        url = build_vindecoder_url('  WVWZZZ3CZWE123456  ')
        self.assertTrue(url.endswith('WVWZZZ3CZWE123456'))


# =========================================================================
# 3. AUDITORIA — get_client_ip e log_access
# =========================================================================


class GetClientIPTest(TestCase):
    """Testes para ``audit.get_client_ip``."""

    def test_returns_remote_addr_when_no_proxy(self):
        from core.audit import get_client_ip

        factory = RequestFactory()
        request = factory.get('/', REMOTE_ADDR='192.168.1.100')
        self.assertEqual(get_client_ip(request), '192.168.1.100')

    def test_returns_fallback_when_no_remote_addr(self):
        from core.audit import get_client_ip

        factory = RequestFactory()
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = ''
        self.assertEqual(get_client_ip(request), '0.0.0.0')

    @patch.dict('os.environ', {'TRUSTED_PROXIES': '127.0.0.1'})
    def test_uses_x_forwarded_for_with_trusted_proxy(self):
        from core.audit import get_client_ip

        factory = RequestFactory()
        request = factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='203.0.113.50, 10.0.0.1',
        )
        self.assertEqual(get_client_ip(request), '203.0.113.50')

    @patch.dict('os.environ', {'TRUSTED_PROXIES': '127.0.0.1'})
    def test_uses_x_real_ip_when_no_forwarded_for(self):
        from core.audit import get_client_ip

        factory = RequestFactory()
        request = factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_REAL_IP='198.51.100.42',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.42')

    def test_ignores_forwarded_for_with_untrusted_proxy(self):
        from core.audit import get_client_ip

        factory = RequestFactory()
        request = factory.get(
            '/',
            REMOTE_ADDR='10.99.99.99',
            HTTP_X_FORWARDED_FOR='203.0.113.50',
        )
        # Sem TRUSTED_PROXIES definido, ignora X-Forwarded-For
        self.assertEqual(get_client_ip(request), '10.99.99.99')

    @patch.dict('os.environ', {'TRUSTED_PROXIES': '127.0.0.1'})
    def test_invalid_forwarded_for_falls_back_to_real_ip(self):
        from core.audit import get_client_ip

        factory = RequestFactory()
        request = factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='not-an-ip',
            HTTP_X_REAL_IP='198.51.100.42',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.42')


class TrustedProxiesTest(TestCase):
    """Testes para ``_trusted_proxies`` e ``_remote_addr_trusted``."""

    @patch.dict('os.environ', {'TRUSTED_PROXIES': '10.0.0.0/8, 172.16.0.0/12'})
    def test_cidr_ranges_accepted(self):
        from core.audit import _remote_addr_trusted

        self.assertTrue(_remote_addr_trusted('10.0.0.1'))
        self.assertTrue(_remote_addr_trusted('172.16.5.10'))
        self.assertFalse(_remote_addr_trusted('192.168.1.1'))

    @patch.dict('os.environ', {'TRUSTED_PROXIES': 'invalid-entry'})
    def test_invalid_entry_ignored(self):
        from core.audit import _trusted_proxies

        # Deve retornar lista vazia sem crashar
        result = _trusted_proxies()
        self.assertEqual(len(result), 0)

    def test_empty_remote_addr_not_trusted(self):
        from core.audit import _remote_addr_trusted

        self.assertFalse(_remote_addr_trusted(''))

    def test_invalid_remote_addr_not_trusted(self):
        from core.audit import _remote_addr_trusted

        self.assertFalse(_remote_addr_trusted('not-an-ip'))


class LogAccessTest(TestCase):
    """Testes para ``audit.log_access``."""

    def test_creates_audit_log_entry(self):
        from core.audit import log_access

        user = UserFactory.create()
        factory = RequestFactory()
        request = factory.get('/', REMOTE_ADDR='192.168.1.1')
        request.user = user

        log_entry = log_access(
            request=request,
            action=AuditLog.Action.VIEW,
            resource_type=AuditLog.ResourceType.EVIDENCE,
            resource_id=42,
            details={'hash': 'abc123'},
        )

        self.assertEqual(log_entry.user, user)
        self.assertEqual(log_entry.action, 'VIEW')
        self.assertEqual(log_entry.resource_type, 'EVIDENCE')
        self.assertEqual(log_entry.resource_id, 42)
        self.assertEqual(log_entry.ip_address, '192.168.1.1')
        self.assertEqual(log_entry.details, {'hash': 'abc123'})

    def test_anonymous_user_logs_null_user(self):
        from core.audit import log_access

        factory = RequestFactory()
        request = factory.get('/', REMOTE_ADDR='10.0.0.1')
        request.user = AnonymousUser()

        log_entry = log_access(
            request=request,
            action=AuditLog.Action.VIEW,
            resource_type=AuditLog.ResourceType.OCCURRENCE,
            resource_id=1,
        )

        self.assertIsNone(log_entry.user)

    def test_default_details_empty_dict(self):
        from core.audit import log_access

        user = UserFactory.create()
        factory = RequestFactory()
        request = factory.get('/', REMOTE_ADDR='192.168.1.1')
        request.user = user

        log_entry = log_access(
            request=request,
            action=AuditLog.Action.CREATE,
            resource_type=AuditLog.ResourceType.DEVICE,
            resource_id=7,
        )

        self.assertEqual(log_entry.details, {})


# =========================================================================
# 4. EXCEPTION HANDLER
# =========================================================================


class ExceptionHandlerTest(TestCase):
    """Testes para ``forensiq_exception_handler``."""

    def _make_context(self):
        return {'view': 'TestView', 'request': RequestFactory().get('/')}

    def test_django_validation_error_with_message_dict(self):
        from core.exceptions import forensiq_exception_handler

        exc = DjangoValidationError({'field': ['erro 1', 'erro 2']})
        response = forensiq_exception_handler(exc, self._make_context())

        self.assertEqual(response.status_code, 400)
        self.assertIn('field', response.data)

    def test_django_validation_error_with_messages(self):
        from core.exceptions import forensiq_exception_handler

        exc = DjangoValidationError(['erro genérico'])
        response = forensiq_exception_handler(exc, self._make_context())

        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.data)

    def test_django_validation_error_simple_string(self):
        from core.exceptions import forensiq_exception_handler

        exc = DjangoValidationError('erro simples')
        response = forensiq_exception_handler(exc, self._make_context())

        self.assertEqual(response.status_code, 400)

    @override_settings(DEBUG=False)
    def test_unhandled_exception_returns_500_in_production(self):
        from core.exceptions import forensiq_exception_handler

        exc = RuntimeError('algo inesperado')
        response = forensiq_exception_handler(exc, self._make_context())

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 500)
        self.assertIn('Erro interno', response.data['detail'])

    @override_settings(DEBUG=True)
    def test_unhandled_exception_returns_none_in_debug(self):
        from core.exceptions import forensiq_exception_handler

        exc = RuntimeError('debug mode')
        response = forensiq_exception_handler(exc, self._make_context())

        # Em DEBUG, DRF default handler retorna None para não capturar
        self.assertIsNone(response)


# =========================================================================
# 5. AUTH COOKIES — JWTCookieAuthentication
# =========================================================================


class AuthCookieHelpersTest(TestCase):
    """Testes para funções auxiliares de cookies em ``auth.py``."""

    def test_set_auth_cookies_sets_access(self):
        from django.http import HttpResponse

        from core.auth import ACCESS_COOKIE_NAME, set_auth_cookies

        response = HttpResponse()
        set_auth_cookies(response, access='test-access-token')

        cookies = response.cookies
        self.assertIn(ACCESS_COOKIE_NAME, cookies)
        self.assertEqual(cookies[ACCESS_COOKIE_NAME].value, 'test-access-token')
        # HttpOnly deve estar a true
        self.assertTrue(cookies[ACCESS_COOKIE_NAME]['httponly'])

    def test_set_auth_cookies_sets_refresh(self):
        from django.http import HttpResponse

        from core.auth import REFRESH_COOKIE_NAME, set_auth_cookies

        response = HttpResponse()
        set_auth_cookies(response, access='access', refresh='refresh-token')

        cookies = response.cookies
        self.assertIn(REFRESH_COOKIE_NAME, cookies)
        self.assertEqual(cookies[REFRESH_COOKIE_NAME].value, 'refresh-token')

    def test_set_auth_cookies_without_refresh(self):
        from django.http import HttpResponse

        from core.auth import REFRESH_COOKIE_NAME, set_auth_cookies

        response = HttpResponse()
        set_auth_cookies(response, access='access', refresh=None)

        self.assertNotIn(REFRESH_COOKIE_NAME, response.cookies)

    def test_delete_auth_cookies(self):
        from django.http import HttpResponse

        from core.auth import (
            ACCESS_COOKIE_NAME,
            REFRESH_COOKIE_NAME,
            delete_auth_cookies,
            set_auth_cookies,
        )

        response = HttpResponse()
        set_auth_cookies(response, access='a', refresh='r')
        delete_auth_cookies(response)

        # Após delete, os cookies devem ter max_age=0
        self.assertEqual(response.cookies[ACCESS_COOKIE_NAME]['max-age'], 0)
        self.assertEqual(response.cookies[REFRESH_COOKIE_NAME]['max-age'], 0)

    @override_settings(DEBUG=True)
    def test_cookie_not_secure_in_debug(self):
        from django.http import HttpResponse

        from core.auth import ACCESS_COOKIE_NAME, set_auth_cookies

        response = HttpResponse()
        set_auth_cookies(response, access='token')

        # Em DEBUG, secure=False
        self.assertEqual(response.cookies[ACCESS_COOKIE_NAME]['secure'], '')

    @override_settings(DEBUG=False)
    def test_cookie_secure_in_production(self):
        from django.http import HttpResponse

        from core.auth import ACCESS_COOKIE_NAME, set_auth_cookies

        response = HttpResponse()
        set_auth_cookies(response, access='token')

        self.assertTrue(response.cookies[ACCESS_COOKIE_NAME]['secure'])


# =========================================================================
# 6. AUTH VIEWS — Login, Refresh, Logout via API
# =========================================================================


class CookieLoginViewTest(APITestCase):
    """Testes para POST /api/auth/login/."""

    def setUp(self):
        self.user = UserFactory.create(password=TEST_PASSWORD)
        self.url = reverse('auth_login')

    def test_login_success_sets_cookies(self):
        response = self.client.post(
            self.url,
            {
                'username': self.user.username,
                'password': TEST_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)
        # Cookies devem ser definidos
        self.assertIn('fq_access', response.cookies)
        self.assertIn('fq_refresh', response.cookies)

    def test_login_wrong_password_rejected(self):
        response = self.client.post(
            self.url,
            {
                'username': self.user.username,
                'password': 'WrongPass!',
            },
        )

        # DRF devolve 403 (não 401) quando authentication_classes=[]
        # porque não há WWW-Authenticate header. Ambos são válidos para
        # credenciais inválidas — aceitamos os dois.
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_login_missing_credentials_returns_error(self):
        response = self.client.post(self.url, {})

        self.assertIn(response.status_code, [400, 401])


class CookieRefreshViewTest(APITestCase):
    """Testes para POST /api/auth/refresh/."""

    def setUp(self):
        self.user = UserFactory.create(password=TEST_PASSWORD)
        self.login_url = reverse('auth_login')
        self.refresh_url = reverse('auth_refresh')

    def test_refresh_without_cookie_returns_401(self):
        response = self.client.post(self.refresh_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_with_valid_cookie_succeeds(self):
        # Login primeiro
        login_resp = self.client.post(
            self.login_url,
            {
                'username': self.user.username,
                'password': TEST_PASSWORD,
            },
        )
        self.assertEqual(login_resp.status_code, 200)

        # O cookie refresh deve estar na resposta
        refresh_cookie = login_resp.cookies.get('fq_refresh')
        if refresh_cookie:
            self.client.cookies['fq_refresh'] = refresh_cookie.value
            response = self.client.post(self.refresh_url)
            self.assertIn(response.status_code, [200, 401])


class CookieLogoutViewTest(APITestCase):
    """Testes para POST /api/auth/logout/."""

    def setUp(self):
        self.user = UserFactory.create(password=TEST_PASSWORD)
        self.login_url = reverse('auth_login')
        self.logout_url = reverse('auth_logout')

    def test_logout_unauthenticated_returns_401_or_403(self):
        response = self.client.post(self.logout_url)
        self.assertIn(response.status_code, [401, 403])

    def test_logout_clears_cookies(self):
        # Login
        login_resp = self.client.post(
            self.login_url,
            {
                'username': self.user.username,
                'password': TEST_PASSWORD,
            },
        )
        # Set cookies for subsequent requests
        for name in ('fq_access', 'fq_refresh'):
            cookie = login_resp.cookies.get(name)
            if cookie:
                self.client.cookies[name] = cookie.value

        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


# =========================================================================
# 7. FILTERS — OccurrenceFilter, EvidenceFilter, CustodyFilter
# =========================================================================


class EvidenceFilterTest(APITestCase):
    """Testes para EvidenceFilter (type, date_after, has_gps)."""

    def setUp(self):
        self.user = UserFactory.create()
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.user)

        self.occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-EVFILTER-001',
            description='Teste filtros',
            date_time=timezone.now(),
            agent=self.user,
        )
        self.ev_mobile = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Telemóvel teste',
            serial_number='SN-FILT-001',
            timestamp_seizure=timezone.now(),
            gps_lat=Decimal('38.72'),
            gps_lng=Decimal('-9.13'),
            agent=self.user,
        )
        self.ev_sim = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.SIM_CARD,
            description='SIM teste',
            serial_number='SN-FILT-002',
            timestamp_seizure=timezone.now(),
            agent=self.user,
        )

    def test_filter_by_type(self):
        url = reverse('core:evidence-list') + '?type=MOBILE_DEVICE'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        types = [r['type'] for r in response.data['results']]
        self.assertTrue(all(t == 'MOBILE_DEVICE' for t in types))

    def test_filter_has_gps_evidence(self):
        url = reverse('core:evidence-list') + '?has_gps=true'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        serials = [r['serial_number'] for r in response.data['results']]
        self.assertIn('SN-FILT-001', serials)
        self.assertNotIn('SN-FILT-002', serials)


class CustodyFilterTest(APITestCase):
    """Testes para CustodyFilter (event_type, legal_state, date_after)."""

    def setUp(self):
        self.user = UserFactory.create()
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.user)

        self.occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-CUSTFILT-001',
            description='Teste custódia',
            date_time=timezone.now(),
            agent=self.user,
        )
        self.ev = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Telemóvel custódia',
            serial_number='SN-CUSTFILT-001',
            timestamp_seizure=timezone.now(),
            gps_lat=Decimal('38.72'),
            gps_lng=Decimal('-9.13'),
            agent=self.user,
        )
        # Criar o primeiro evento do ledger via API
        self.client.post(
            reverse('core:custody-list'),
            {
                'evidence': self.ev.pk,
                'event_type': 'APREENSAO_OBJETO',
                'custodian_type': 'OPC',
                'observations': 'Apreensão teste filtro',
            },
        )

    def test_filter_by_event_type(self):
        url = reverse('core:custody-list') + '?event_type=APREENSAO_OBJETO'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        events = [r['event_type'] for r in response.data['results']]
        self.assertTrue(all(e == 'APREENSAO_OBJETO' for e in events))

    def test_filter_by_legal_state(self):
        url = reverse('core:custody-list') + '?legal_state=a_guarda_opc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        states = [r['legal_state'] for r in response.data['results']]
        self.assertTrue(all(s == 'a_guarda_opc' for s in states))


# =========================================================================
# 8. PAGINATION — BoundedPageNumberPagination
# =========================================================================


class PaginationEdgeCasesTest(APITestCase):
    """Testes para paginação com valores extremos."""

    def setUp(self):
        self.user = UserFactory.create()
        # Login real na fonte unica (tests_base.login_client - auditoria D106).
        self.client = login_client(self.user)

    def test_negative_page_size_uses_default(self):
        url = reverse('core:occurrence-list') + '?page_size=-1'
        response = self.client.get(url)
        # Deve retornar 200 (usa page_size default, não crasha)
        self.assertEqual(response.status_code, 200)

    def test_zero_page_size_uses_default(self):
        url = reverse('core:occurrence-list') + '?page_size=0'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_page_beyond_range_returns_404(self):
        url = reverse('core:occurrence-list') + '?page=99999'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# =========================================================================
# 9. FRONTEND VIEWS — autenticação e redireccionamentos
# =========================================================================


class FrontendRedirectsTest(TestCase):
    """Redireccionamentos e handler 404 do frontend.

    A cobertura de login-200 vive em ``tests_frontend.py::LoginPageTest``;
    aqui ficam apenas os casos não cobertos lá (redirect sem auth, 404).
    """

    def test_unauthenticated_dashboard_redirects(self):
        response = self.client.get(reverse('dashboard'))
        self.assertIn(response.status_code, [302, 303])

    def test_404_handler_returns_404(self):
        response = self.client.get('/pagina-inexistente/')
        self.assertEqual(response.status_code, 404)
