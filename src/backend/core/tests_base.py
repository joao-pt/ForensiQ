"""
ForensiQ — Base partilhada dos testes (autenticação, mocks HTTP, média, throttle).

Companheiro de ``core/tests_factories.py`` (factories/constantes): aqui vivem os
helpers COMPORTAMENTAIS que a auditoria de duplicação 2026-06-10 encontrou
re-implementados pelos módulos de teste:

- :func:`auth_cookie`      — cookie JWT no test client (D105; antes 10 cópias,
  duas delas com o literal ``'fq_access'`` em vez da constante);
- :func:`login_client`     — APIClient autenticado por LOGIN REAL (D106; o
  APIClient persiste os cookies da resposta — a cópia manual era redundante);
- :class:`BaseAPITestCase` — trio agente/perito/admin + ``authenticate_as``
  (D112; ``tests_api`` re-exporta para não partir imports);
- :func:`mock_httpx_response` / :func:`mock_httpx_client` — duplo do
  ``httpx.Client`` context-manager do imei_lookup (D107);
- :func:`make_image_bytes` / :func:`image_upload` — imagens Pillow mínimas
  para upload (D113);
- :func:`throttle_rate`    — reativa o throttling de UM scope num teste (D115).
"""

from contextlib import contextmanager
from io import BytesIO
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import User
from core.tests_factories import TEST_PASSWORD, ExpertFactory, UserFactory

# ---------------------------------------------------------------------------
# Autenticação de test clients
# ---------------------------------------------------------------------------


def auth_cookie(client, user):
    """Autentica ``client`` com o cookie JWT de acesso (fonte única — D105)."""
    client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(user))
    return client


def login_client(user, password=TEST_PASSWORD):
    """``APIClient`` autenticado por LOGIN REAL no endpoint ``auth_login``
    (D106). O 200 é asserido aqui; os cookies da resposta ficam mantidos pelo
    próprio ``APIClient`` para os pedidos seguintes."""
    client = APIClient()
    resp = client.post(
        reverse('auth_login'), {'username': user.username, 'password': password}
    )
    assert resp.status_code == 200, (
        f'login real falhou para {user.username}: HTTP {resp.status_code}'
    )
    return client


class BaseAPITestCase(TestCase):
    """Setup comum da API: agente, perito NACIONAL e superuser (D112)."""

    def setUp(self):
        self.client = APIClient()

        self.agent = UserFactory(
            username='agente_api',
            badge_number='AGT-API-01',
            first_name='Ana',
            last_name='Silva',
        )
        self.expert = ExpertFactory(
            username='perito_api',
            first_name='Carlos',
            last_name='Costa',
        )
        self.admin = User.objects.create_superuser(
            username='admin_api',
            password='AdminPass123!',
        )

    def authenticate_as(self, user):
        """Autentica o cliente via JWT."""
        self.client.force_authenticate(user=user)

    def get_jwt_token(self, username, password):
        """Obtém tokens JWT via endpoint de login (cookies, ADR-0009).

        Devolve a resposta completa. Os tokens ficam disponíveis nos
        cookies (`fq_access`, `fq_refresh`) em `response.cookies` e
        também em `self.client.cookies` para pedidos subsequentes.
        """
        url = reverse('auth_login')
        response = self.client.post(
            url,
            {
                'username': username,
                'password': password,
            },
        )
        return response


# ---------------------------------------------------------------------------
# Mock do httpx.Client (imei_lookup) — D107
# ---------------------------------------------------------------------------


def mock_httpx_response(status_code=200, json_body=None):
    """Resposta httpx falsa mínima (``.status_code`` + ``.json()``)."""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


def mock_httpx_client(response=None, *, side_effect=None):
    """Duplo do ``httpx.Client`` usado como context-manager pelo imei_lookup.

    Uso típico::

        with mock.patch('core.services.imei_lookup.httpx.Client') as cls:
            cls.return_value = mock_httpx_client(mock_httpx_response(200, {...}))
    """
    client = mock.MagicMock()
    client.__enter__ = mock.MagicMock(return_value=client)
    client.__exit__ = mock.MagicMock(return_value=False)
    if side_effect is not None:
        client.get.side_effect = side_effect
    else:
        client.get.return_value = response if response is not None else mock_httpx_response()
    return client


# ---------------------------------------------------------------------------
# Imagens mínimas para upload — D113
# ---------------------------------------------------------------------------


def make_image_bytes(fmt='JPEG', size=(8, 8), color=(120, 90, 60), exif=None, pad_to=None):
    """Bytes de uma imagem Pillow mínima; ``pad_to`` acrescenta padding até N
    bytes (testes de limite de tamanho), ``exif`` injeta metadados."""
    from PIL import Image

    buf = BytesIO()
    kwargs = {'exif': exif} if exif else {}
    Image.new('RGB', size, color).save(buf, fmt, **kwargs)
    data = buf.getvalue()
    if pad_to and len(data) < pad_to:
        data += b'\0' * (pad_to - len(data))
    return data


def image_upload(name='foto.jpg', fmt='JPEG', **kwargs):
    """``SimpleUploadedFile`` com uma imagem mínima (wrapper de
    :func:`make_image_bytes`)."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    content_type = 'image/png' if fmt.upper() == 'PNG' else 'image/jpeg'
    return SimpleUploadedFile(name, make_image_bytes(fmt=fmt, **kwargs), content_type=content_type)


# ---------------------------------------------------------------------------
# Throttling por scope — D115
# ---------------------------------------------------------------------------


@contextmanager
def throttle_rate(scope, rate):
    """Reativa o throttling de UM scope dentro do bloco (auditoria D115).

    ``override_settings`` NÃO chega: ``SimpleRateThrottle.THROTTLE_RATES`` é
    lido na importação do DRF e não é reposto — é preciso ``patch.object`` na
    classe. O ``cache.clear()`` garante que o contador do scope parte do zero.
    """
    from django.core.cache import cache
    from rest_framework.throttling import SimpleRateThrottle

    cache.clear()
    rates = {**SimpleRateThrottle.THROTTLE_RATES, scope: rate}
    with mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', rates):
        yield


__all__ = [
    'auth_cookie',
    'login_client',
    'BaseAPITestCase',
    'mock_httpx_response',
    'mock_httpx_client',
    'make_image_bytes',
    'image_upload',
    'throttle_rate',
]
