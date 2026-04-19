"""
ForensiQ — Middleware customizado.

Inclui:
- CorrelationIDMiddleware: gera UUID único por requisição para logging/auditoria
- ContentSecurityPolicyMiddleware: define CSP header para mitigar XSS
"""

import logging
import secrets
import uuid
from contextvars import ContextVar

from django.conf import settings

# Variável de contexto para armazenar o correlation_id thread-safe
_correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')

# Logger do módulo
logger = logging.getLogger(__name__)


def get_correlation_id() -> str:
    """Retorna o correlation_id do contexto atual."""
    return _correlation_id.get()


class CorrelationIDMiddleware:
    """
    Middleware que gera e propaga um UUID único (correlation_id) para cada requisição.

    Fluxo:
    1. Gera um UUID4 para a requisição (ou reutiliza se já existir no header X-Correlation-ID)
    2. Armazena na contextvars para acesso em logging e auditoria
    3. Adiciona ao response header X-Correlation-ID

    Permite rastrear requisições através de logs e entradas de auditoria.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Tenta usar correlation_id do cliente (se fornecido)
        # Caso contrário, gera um novo UUID
        correlation_id = request.headers.get('X-Correlation-ID')
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Define no contexto thread-local para acesso posterior
        _correlation_id.set(correlation_id)

        # Log: nova requisição com correlação
        logger.debug(
            'Nova requisição',
            extra={'correlation_id': correlation_id, 'method': request.method, 'path': request.path},
        )

        # Processa a requisição
        response = self.get_response(request)

        # Adiciona correlation_id ao response header
        response['X-Correlation-ID'] = correlation_id

        return response


class ContentSecurityPolicyMiddleware:
    """
    Middleware que adiciona o header Content-Security-Policy a todas as respostas.

    Política CSP (hardened, sem unsafe-inline/unsafe-eval em script-src):
    - default-src 'self': bloqueia todos os recursos externos por defeito
    - script-src 'self' 'nonce-{nonce}' https://cdnjs.cloudflare.com:
      scripts só correm do próprio domínio, CDN Cloudflare (Leaflet) ou
      quando têm o nonce emitido por request. Sem 'unsafe-inline' nem
      'unsafe-eval' — mitiga XSS reflectido/armazenado (CWE-79).
    - style-src 'self' 'unsafe-inline' ...: mantém-se 'unsafe-inline'
      apenas para CSS porque Leaflet e alguns componentes injectam style
      attributes. Migrar para nonce/hash é trabalho da Wave 2d.
    - connect-src: AJAX ao próprio domínio e geocoding OSM
    - img-src: imagens do domínio, data URIs e tiles OSM
    - font-src: fontes do domínio e CDNs usadas
    - base-uri 'self': bloqueia <base> injection
    - frame-ancestors 'none': anti-clickjacking (CWE-1021)
    - form-action 'self': restringe destino de formulários

    Nonce:
    - `secrets.token_urlsafe(16)` (~22 chars, 128 bits entropia) por request.
    - Exposto em `request.csp_nonce` — templates usam `<script nonce="{{ request.csp_nonce }}">`.

    Conformidade OWASP ASVS v4 V14.4 (CSP Level 3).
    Em desenvolvimento (DEBUG=True) usa Report-Only para não quebrar o DX.
    """

    # Cabeçalhos auxiliares de segurança (OWASP Secure Headers Project)
    EXTRA_SECURITY_HEADERS = {
        'Permissions-Policy': (
            'accelerometer=(), camera=(), geolocation=(self), gyroscope=(), '
            'magnetometer=(), microphone=(), payment=(), usb=()'
        ),
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Resource-Policy': 'same-origin',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _build_policy(nonce: str) -> str:
        """Monta o header CSP com o nonce do request corrente."""
        return (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "connect-src 'self' https://nominatim.openstreetmap.org; "
            "img-src 'self' data: https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "object-src 'none'; "
            "frame-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "upgrade-insecure-requests"
        )

    def __call__(self, request):
        # Gera nonce criptograficamente seguro por request e anexa-o
        # ao request para uso em templates: `<script nonce="{{ request.csp_nonce }}">`.
        nonce = secrets.token_urlsafe(16)
        request.csp_nonce = nonce

        response = self.get_response(request)

        policy = self._build_policy(nonce)

        if 'Content-Security-Policy' not in response:
            if settings.DEBUG:
                response['Content-Security-Policy-Report-Only'] = policy
            else:
                response['Content-Security-Policy'] = policy

        for header, value in self.EXTRA_SECURITY_HEADERS.items():
            response.setdefault(header, value)

        return response
