"""
ForensiQ — Utilitários de logging com suporte a correlation_id.

Filtro personalizado de logging que injeta o correlation_id em cada registo.
"""

import logging

from .middleware import get_correlation_id


class CorrelationIDFilter(logging.Filter):
    """
    Filtro de logging que injeta o correlation_id no contexto de cada registo.

    Permite incluir o correlation_id no formato de log via %(correlation_id)s.

    Exemplo de uso em LOGGING['formatters']:
        'verbose': {
            'format': '[{asctime}] [{correlation_id}] {levelname} {name} — {message}',
            'style': '{',
        }

    E em LOGGING['handlers']:
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['correlation_id'],
        }
    """

    def filter(self, record):
        """Injeta o correlation_id no LogRecord."""
        record.correlation_id = get_correlation_id()
        return True
