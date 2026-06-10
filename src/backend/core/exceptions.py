"""
ForensiQ — Exception handler global para a API REST.

Converte `django.core.exceptions.ValidationError` em `HTTP 400`
(DRF por omissao devolve 500 para este erro), preservando a estrutura
`message_dict` quando disponivel.

Em producao, erros 500 sao substituidos por uma mensagem generica para
nao expor detalhes internos (nomes de tabelas, constraints, stack traces).
Erros 4xx mantem detalhe suficiente para feedback de formulario.
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger('forensiq.api')


def as_drf_payload(exc):
    """Normalização canónica de uma ``DjangoValidationError`` para payload 400 —
    a MESMA que o handler global aplica. Exposta para respostas que precisam de
    juntar contexto próprio (ex.: o cascade junta ``evidence_id``/``evidence_code``)
    sem re-implementar a normalização (auditoria D22)."""
    if hasattr(exc, 'message_dict'):
        return exc.message_dict
    if hasattr(exc, 'messages'):
        return {'detail': exc.messages}
    return {'detail': [str(exc)]}


def forensiq_exception_handler(exc, context):
    # --- Django ValidationError -> 400 ---
    if isinstance(exc, DjangoValidationError):
        return Response(as_drf_payload(exc), status=status.HTTP_400_BAD_REQUEST)

    response = drf_exception_handler(exc, context)

    # --- Erros nao tratados pelo DRF (500) em producao -> generico ---
    if response is None and not settings.DEBUG:
        logger.exception(
            'Erro interno nao tratado em %s',
            context.get('view', ''),
        )
        return Response(
            {'detail': 'Erro interno do servidor. Tente novamente mais tarde.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response
