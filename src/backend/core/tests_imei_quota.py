"""
ForensiQ — Testes da monitorização de quota IMEIDB.

Cobertura da auditoria 2026-05-18 §3 N9 (fechado em Sem.12):
- Cada chamada `lookup_imei` incrementa contador em cache.
- HTTP 402 (saldo esgotado) cria entrada `SYSTEM_ALERT` no AuditLog
  com `event=quota_exhausted`.
- HTTP 401 (token inválido) cria `SYSTEM_ALERT` com `event=token_invalid`.
- HTTP 429 (rate limit) cria `SYSTEM_ALERT` com `event=rate_limited`.
- Resposta 200 OK com `success:false, code:402` no body também cria
  `SYSTEM_ALERT` (a API upstream usa este formato em alguns cenários).
- IMEI é mascarado nos `details` (PII forense — cumpre N1).
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from core.models import AuditLog
from core.services.imei_lookup import (
    _CACHE_KEY_CALLS_24H,
    LookupError,
    lookup_imei,
)
from core.tests_factories import VALID_IMEI

# IMEI Luhn-válido usado em todos os testes (sample Apple iPhone 11 Pro Max TAC)
_VALID_IMEI = VALID_IMEI


def _mock_httpx_response(status_code, json_body=None):
    """Cria um mock httpx.Client que devolve a resposta indicada."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = response
    return client


class ImeiLookupCallCounterTest(TestCase):
    """Incremento do contador de chamadas (sucesso + falha)."""

    def setUp(self):
        cache.clear()

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_call_counter_incrementa_em_sucesso(self, mock_client, _token):
        mock_client.return_value = _mock_httpx_response(
            200,
            {
                'success': True,
                'data': {
                    'brand': 'Apple',
                    'model': 'A2161',
                    'name': 'iPhone 11 Pro Max',
                },
            },
        )
        self.assertIsNone(cache.get(_CACHE_KEY_CALLS_24H))
        lookup_imei(_VALID_IMEI)
        self.assertEqual(cache.get(_CACHE_KEY_CALLS_24H), 1)
        lookup_imei(_VALID_IMEI)
        self.assertEqual(cache.get(_CACHE_KEY_CALLS_24H), 2)

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_call_counter_incrementa_em_falha(self, mock_client, _token):
        mock_client.return_value = _mock_httpx_response(500)
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        # Contador conta TENTATIVAS, não sucessos.
        self.assertEqual(cache.get(_CACHE_KEY_CALLS_24H), 1)


class ImeiLookupCriticalAlertTest(TestCase):
    """SYSTEM_ALERT no AuditLog para eventos operacionais críticos."""

    def setUp(self):
        cache.clear()

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_http_402_cria_alerta_quota_exhausted(self, mock_client, _token):
        mock_client.return_value = _mock_httpx_response(402)
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        alert = AuditLog.objects.get(action=AuditLog.Action.SYSTEM_ALERT)
        self.assertEqual(alert.details['event'], 'quota_exhausted')
        self.assertEqual(alert.details['http_status'], 402)
        self.assertEqual(alert.details['source'], 'imeidb_lookup')
        # IMEI mascarado: não pode aparecer completo (PII — N1).
        self.assertNotIn(_VALID_IMEI, alert.details['imei_masked'])
        self.assertTrue(alert.details['imei_masked'].endswith('***'))

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_http_401_cria_alerta_token_invalid(self, mock_client, _token):
        mock_client.return_value = _mock_httpx_response(401)
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        alert = AuditLog.objects.get(action=AuditLog.Action.SYSTEM_ALERT)
        self.assertEqual(alert.details['event'], 'token_invalid')
        self.assertEqual(alert.details['http_status'], 401)

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_http_429_cria_alerta_rate_limited(self, mock_client, _token):
        mock_client.return_value = _mock_httpx_response(429)
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        alert = AuditLog.objects.get(action=AuditLog.Action.SYSTEM_ALERT)
        self.assertEqual(alert.details['event'], 'rate_limited')
        self.assertEqual(alert.details['http_status'], 429)

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_body_success_false_402_cria_alerta(self, mock_client, _token):
        """Upstream às vezes responde 200 + body.code=402 em vez de HTTP 402."""
        mock_client.return_value = _mock_httpx_response(
            200,
            {'success': False, 'code': 402, 'message': 'no balance'},
        )
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        alert = AuditLog.objects.get(action=AuditLog.Action.SYSTEM_ALERT)
        self.assertEqual(alert.details['event'], 'quota_exhausted')
        self.assertEqual(alert.details['http_status'], 200)
        self.assertEqual(alert.details['api_code'], 402)

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_http_404_nao_cria_alerta(self, mock_client, _token):
        """404 (IMEI não encontrado) é cenário normal — sem alerta."""
        mock_client.return_value = _mock_httpx_response(404)
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.SYSTEM_ALERT).exists())

    @patch('core.services.imei_lookup._api_token', return_value='fake-token')
    @patch('core.services.imei_lookup.httpx.Client')
    def test_http_500_nao_cria_alerta(self, mock_client, _token):
        """5xx upstream é problema deles, não da nossa quota."""
        mock_client.return_value = _mock_httpx_response(500)
        with self.assertRaises(LookupError):
            lookup_imei(_VALID_IMEI)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.SYSTEM_ALERT).exists())
