"""
ForensiQ — Middleware customizado.

Inclui:
- CorrelationIDMiddleware: gera UUID único por requisição para logging/auditoria
- ContentSecurityPolicyMiddleware: define CSP header para mitigar XSS
"""

import uuid
import logging
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

    Política CSP:
    - default-src 'self': bloqueia todos os recursos externos por defeito
    - script-src: permite scripts do próprio domínio e CDN Cloudflare (Leaflet)
    - style-src: permite estilos inline (necessário para Leaflet) e CDN
    - connect-src: permite AJAX ao próprio domínio e geocoding OSM
    - img-src: permite imagens do domínio, data URIs e tiles OSM
    - font-src: permite fontes do domínio e CDN
    - base-uri: restringe <base> ao próprio domínio
    - frame-ancestors: bloqueia embedding em iframes (clickjacking)
    - form-action: restringe destino de formulários

    Conformidade OWASP: mitigação de XSS via CSP Level 2.
    Em desenvolvimento, a política é mais permissiva (report-only).
    """

    # Política CSP para produção
    CSP_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "connect-src 'self' https://nominatim.openstreetmap.org; "
        "img-src 'self' data: https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com; "
        "font-src 'self' https://cdnjs.cloudflare.com; "
        "object-src 'none'; "
        "frame-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "upgrade-insecure-requests"
    )

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

    def __call__(self, request):
        response = self.get_response(request)

        if 'Content-Security-Policy' not in response:
            if settings.DEBUG:
                response['Content-Security-Policy-Report-Only'] = self.CSP_POLICY
            else:
                response['Content-Security-Policy'] = self.CSP_POLICY

        for header, value in self.EXTRA_SECURITY_HEADERS.items():
            response.setdefault(header, value)

        return response
