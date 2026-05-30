"""
ForensiQ — Middleware customizado.

Inclui:
- CorrelationIDMiddleware: gera UUID único por requisição para logging/auditoria
- ContentSecurityPolicyMiddleware: define CSP header para mitigar XSS
"""

import logging
import re
import secrets
import uuid
from contextvars import ContextVar

from django.conf import settings

# Variável de contexto para armazenar o correlation_id thread-safe
_correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')

# Logger do módulo
logger = logging.getLogger(__name__)

# Formato aceite para o `X-Correlation-ID` fornecido pelo cliente: apenas
# caracteres alfanuméricos e hífen, comprimento máximo 64. Cobre UUIDs
# (com ou sem hífens) e identificadores curtos de tracing, mas rejeita
# qualquer payload arbitrário — o valor é ecoado no response header e
# escrito nos logs, logo não pode aceitar input não validado do cliente
# (mitigação de log/header injection — finding `correlation-id-aceita-input-cliente`).
_CORRELATION_ID_RE = re.compile(r'^[A-Za-z0-9-]{1,64}$')


def _sanitize_correlation_id(value: str | None) -> str | None:
    """Devolve o correlation_id do cliente se válido; caso contrário ``None``.

    ``None`` sinaliza ao chamador que deve gerar um novo UUID.
    """
    if value and _CORRELATION_ID_RE.match(value):
        return value
    return None


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
        # Tenta usar correlation_id do cliente (se fornecido E com formato
        # válido). Um header malformado/arbitrário é ignorado e substituído
        # por um UUID novo — o valor é ecoado no response e nos logs, pelo
        # que não pode ser input não validado do cliente.
        correlation_id = _sanitize_correlation_id(request.headers.get('X-Correlation-ID'))
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

    Política CSP (hardened, sem unsafe-inline/unsafe-eval em script-src nem style-src):
    - default-src 'self': bloqueia todos os recursos externos por defeito
    - script-src 'self' 'nonce-{nonce}': scripts só correm do próprio domínio
      ou quando têm o nonce emitido por request. Sem 'unsafe-inline' nem
      'unsafe-eval' — mitiga XSS reflectido/armazenado (CWE-79). O Leaflet é
      self-hosted (sem CDN externo; cdnjs removido no T08).
    - style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com: <style>
      blocks (Leaflet runtime injecta um) precisam de nonce; o setter
      element.style.X = ... do DOM API não é controlado pelo style-src.
    - connect-src: AJAX ao próprio domínio e geocoding OSM (Nominatim)
    - img-src: imagens do domínio, data URIs e tiles OSM
    - font-src: fontes do domínio e Google Fonts (IBM Plex)
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
    def _build_policy(nonce: str, *, report_only: bool) -> str:
        """Monta o header CSP com o nonce do request corrente.

        `upgrade-insecure-requests` é ignorado por browsers em policies
        Report-Only — incluímo-lo apenas no header enforced.
        """
        directives = [
            "default-src 'self'",
            # cdnjs.cloudflare.com removido (T08): o Leaflet passou a self-hosted
            # (drift do ADR-0007 alt. A2) e a swagger usa drf-spectacular-sidecar
            # local — nenhum asset vivo vem de cdnjs. Fontes IBM Plex via Google Fonts.
            f"script-src 'self' 'nonce-{nonce}'",
            f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com",
            "connect-src 'self' https://nominatim.openstreetmap.org",
            "img-src 'self' data: https://*.tile.openstreetmap.org",
            "font-src 'self' https://fonts.gstatic.com",
            "object-src 'none'",
            "frame-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        ]
        if not report_only:
            directives.append("upgrade-insecure-requests")
        return "; ".join(directives)

    def __call__(self, request):
        # Gera nonce criptograficamente seguro por request e anexa-o
        # ao request para uso em templates: `<script nonce="{{ request.csp_nonce }}">`.
        nonce = secrets.token_urlsafe(16)
        request.csp_nonce = nonce

        response = self.get_response(request)

        if 'Content-Security-Policy' not in response:
            report_only = settings.DEBUG
            policy = self._build_policy(nonce, report_only=report_only)
            if report_only:
                response['Content-Security-Policy-Report-Only'] = policy
            else:
                response['Content-Security-Policy'] = policy

        for header, value in self.EXTRA_SECURITY_HEADERS.items():
            response.setdefault(header, value)

        return response
