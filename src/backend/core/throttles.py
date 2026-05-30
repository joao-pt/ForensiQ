"""
ForensiQ — Throttling customizado para endpoints sensíveis.

AuthRateThrottle: limita tentativas de autenticação a 5/minuto por IP.
Protecção contra ataques de força bruta aos endpoints JWT.
"""

from rest_framework.throttling import AnonRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """
    Rate limiting específico para endpoints de autenticação.

    Aplica-se por endereço IP (independente de autenticação),
    com limite definido em DEFAULT_THROTTLE_RATES['auth'].

    Conformidade OWASP: protecção contra brute-force em credenciais.
    """

    scope = 'auth'


class HealthcheckRateThrottle(AnonRateThrottle):
    """Rate limiting do endpoint público de healthcheck (`/api/health/`).

    O healthcheck é anónimo e cada chamada faz um ``SELECT 1`` à BD; sem
    freio, permite varredura de liveness e amplificação ligeira de carga/custo
    de BD por pedidos não autenticados. Aplica-se por IP (limite
    ``DEFAULT_THROTTLE_RATES['healthcheck']``); o valor é deliberadamente
    folgado para nunca travar probes legítimos do Fly.io/Kubernetes.
    """

    scope = 'healthcheck'
