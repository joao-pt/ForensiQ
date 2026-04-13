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
