"""
ForensiQ — Exception handler global para a API REST.

Converte `django.core.exceptions.ValidationError` em `HTTP 400`
(DRF por omissão devolve 500 para este erro), preservando a estrutura
`message_dict` quando disponível.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def forensiq_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, 'message_dict'):
            data = exc.message_dict
        elif hasattr(exc, 'messages'):
            data = {'detail': exc.messages}
        else:
            data = {'detail': [str(exc)]}
        return Response(data, status=status.HTTP_400_BAD_REQUEST)

    return drf_exception_handler(exc, context)
