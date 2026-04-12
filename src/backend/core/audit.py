"""
ForensiQ — Auditoria de acessos a recursos.

Funções utilitárias para registar acessos (VIEW, CREATE, EXPORT_PDF) em log imutável
com rastreamento via correlation_id.
"""

import logging

from django.http import HttpRequest

from .middleware import get_correlation_id
from .models import AuditLog

logger = logging.getLogger(__name__)


def get_client_ip(request: HttpRequest) -> str:
    """
    Extrai o endereço IP do cliente da requisição.

    Prioridade:
    1. X-Forwarded-For (para proxies/load balancers)
    2. X-Real-IP (nginx)
    3. REMOTE_ADDR (direto)
    """
    # X-Forwarded-For pode conter múltiplos IPs, pegarmos o primeiro
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()

    real_ip = request.META.get('HTTP_X_REAL_IP')
    if real_ip:
        return real_ip.strip()

    return request.META.get('REMOTE_ADDR', '')


def log_access(
    request: HttpRequest,
    action: str,
    resource_type: str,
    resource_id: int,
    details: dict = None,
) -> AuditLog:
    """
    Cria um registo de auditoria para um acesso a um recurso.

    Args:
        request: HttpRequest (para extrair user, IP, correlation_id)
        action: AuditLog.Action (VIEW, CREATE, EXPORT_PDF)
        resource_type: AuditLog.ResourceType (OCCURRENCE, EVIDENCE, DEVICE, CUSTODY)
        resource_id: ID da instância do recurso acedido
        details: dict opcional com contexto adicional

    Returns:
        AuditLog: instância criada (já persistida na BD)

    Exemplo:
        log_access(
            request=request,
            action=AuditLog.Action.VIEW,
            resource_type=AuditLog.ResourceType.EVIDENCE,
            resource_id=evidence.pk,
            details={'hash': evidence.integrity_hash},
        )
    """
    ip_address = get_client_ip(request)
    correlation_id = get_correlation_id()

    audit_log = AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        correlation_id=correlation_id,
        details=details or {},
    )

    logger.info(
        f'{action} {resource_type}({resource_id})',
        extra={
            'correlation_id': correlation_id,
            'user': request.user.username if request.user.is_authenticated else 'anonymous',
            'ip': ip_address,
        },
    )

    return audit_log
