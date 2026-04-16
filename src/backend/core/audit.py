"""
ForensiQ — Auditoria de acessos a recursos.

Funções utilitárias para registar acessos (VIEW, CREATE, EXPORT_PDF) em log imutável
com rastreamento via correlation_id.
"""

import ipaddress
import logging
import os

from django.http import HttpRequest

from .middleware import get_correlation_id
from .models import AuditLog

logger = logging.getLogger(__name__)


def _trusted_proxies():
    """
    Lista de IPs/redes de proxies confiáveis, a partir de TRUSTED_PROXIES
    (CSV no .env). Suporta prefixos CIDR (ex: '10.0.0.0/8,127.0.0.1').
    """
    raw = os.environ.get('TRUSTED_PROXIES', '')
    networks = []
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            logger.warning('TRUSTED_PROXIES entrada inválida ignorada: %s', token)
    return networks


def _remote_addr_trusted(remote_addr: str) -> bool:
    if not remote_addr:
        return False
    try:
        addr = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_proxies())


def get_client_ip(request: HttpRequest) -> str:
    """
    Extrai o endereço IP do cliente de forma segura.

    Só confia em X-Forwarded-For / X-Real-IP se REMOTE_ADDR pertencer
    à whitelist TRUSTED_PROXIES. Caso contrário devolve REMOTE_ADDR
    (o cliente não pode falsificar a origem TCP).

    Fallback final '0.0.0.0' para nunca devolver string vazia
    (AuditLog.ip_address é NOT NULL).
    """
    remote_addr = request.META.get('REMOTE_ADDR', '') or ''

    if _remote_addr_trusted(remote_addr):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            # Primeiro IP da cadeia = cliente original
            candidate = forwarded_for.split(',')[0].strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass
        real_ip = request.META.get('HTTP_X_REAL_IP')
        if real_ip:
            candidate = real_ip.strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass

    return remote_addr or '0.0.0.0'


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
