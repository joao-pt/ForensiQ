"""
ForensiQ — Middleware de correlação de requisições.

Gera um UUID único (correlation_id) para cada requisição HTTP e o adiciona
ao contexto thread-local via contextvars. O correlation_id está disponível
para o sistema de logging e para a auditoria.
"""

import uuid
import logging
from contextvars import ContextVar

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
