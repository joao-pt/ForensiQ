"""Consulta imeidb.xyz para enriquecimento IMEI.

Arquitectura:
- Sem retry automático (keep-it-simple) — se falhar, o agente preenche
  manualmente e o fluxo forense continua.
- Sem circuit breaker — a camada de cache (30 dias, ADR-0008) já amortiza
  a maioria das consultas e evita sobrecarga da API externa.
- Resposta normalizada para schema estável em ``_normalize``; o payload
  bruto é guardado em ``raw`` para auditoria (ISO/IEC 27037).

Settings usadas (fornecidas por Wave 2b em ``forensiq_project.settings``):
- ``IMEIDB_API_TOKEN``   — token Bearer para autenticação.
- ``IMEIDB_BASE_URL``    — URL base da API (default ``https://imeidb.xyz/api``).
- ``IMEIDB_TIMEOUT_SECONDS`` — timeout em segundos (default 10).

Ver também ADR-0008 (cache de lookups externos) e ADR-0010 (taxonomia de
evidências e estratégia de enriquecimento — IMEI, VIN).
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings

log = logging.getLogger(__name__)


class LookupError(Exception):
    """Falha normalizada da consulta a imeidb.xyz.

    A mensagem é escrita em PT-PT e é segura para ser exposta ao cliente
    (evita fugas de detalhes internos). O ``detail`` HTTP 503 devolvido
    pelo endpoint reutiliza directamente ``str(exc)``.
    """


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _base_url() -> str:
    """Devolve a URL base configurada, com default seguro.

    Usa ``getattr`` em vez de acesso directo para não falhar em ambientes
    onde Wave 2b ainda não aplicou as settings (evita ImportError no
    ``django check`` de configuração incompleta).
    """
    return getattr(settings, 'IMEIDB_BASE_URL', 'https://imeidb.xyz/api')


def _api_token() -> str:
    return getattr(settings, 'IMEIDB_API_TOKEN', '')


def _timeout() -> float:
    return float(getattr(settings, 'IMEIDB_TIMEOUT_SECONDS', 10))


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def lookup_imei(imei: str) -> dict:
    """Consulta imeidb.xyz e devolve dados normalizados do dispositivo.

    Args:
        imei: string com exactamente 15 dígitos (já validada pelo caller
            via ``core.validators.validate_imei``).

    Returns:
        dict com chaves normalizadas: ``brand``, ``model``, ``os``,
        ``storage``, ``release_date``, ``color`` e ``raw`` (payload
        original para auditoria ISO 27037).

    Raises:
        LookupError: em qualquer falha de rede, HTTP não-2xx, JSON
            inválido ou saldo esgotado. A mensagem é em PT-PT e pode
            ser exposta ao cliente.
    """
    url = f"{_base_url().rstrip('/')}/check/{imei}"
    headers = {
        'Authorization': f'Bearer {_api_token()}',
        'Accept': 'application/json',
        'User-Agent': 'ForensiQ/1.0 (+https://forensiq.pt)',
    }
    try:
        with httpx.Client(timeout=_timeout()) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        log.warning('imeidb timeout imei=%s', imei)
        raise LookupError(
            'Tempo esgotado ao consultar imeidb.xyz. Preenche manualmente.'
        )
    except httpx.RequestError as exc:
        log.warning('imeidb network error imei=%s err=%s', imei, exc)
        raise LookupError(
            'Erro de rede ao consultar imeidb.xyz. Preenche manualmente.'
        )

    status_code = response.status_code
    if status_code == 402:
        raise LookupError(
            'Saldo da API imeidb.xyz esgotado. Preenche manualmente.'
        )
    if status_code == 404:
        raise LookupError(
            'IMEI não encontrado em imeidb.xyz. Preenche manualmente.'
        )
    if status_code == 429:
        raise LookupError(
            'Limite de consultas atingido em imeidb.xyz. Tenta mais tarde.'
        )
    if status_code >= 500:
        raise LookupError(
            f'imeidb.xyz indisponível (HTTP {status_code}). Tenta mais tarde.'
        )
    if status_code != 200:
        raise LookupError(
            f'Resposta inesperada de imeidb.xyz (HTTP {status_code}).'
        )

    try:
        payload = response.json()
    except ValueError:
        log.warning('imeidb non-json body imei=%s', imei)
        raise LookupError('Resposta de imeidb.xyz não é JSON válido.')

    if not isinstance(payload, dict):
        log.warning('imeidb payload not a dict imei=%s type=%s', imei, type(payload).__name__)
        raise LookupError('Resposta de imeidb.xyz em formato inesperado.')

    return _normalize(payload)


def _normalize(payload: dict) -> dict:
    """Mapeia o payload bruto da API para o schema interno estável.

    Best-effort: o formato exacto do JSON de imeidb.xyz pode variar por
    endpoint / plano. Tentamos as chaves mais prováveis e guardamos o
    payload original em ``raw`` para auditoria ISO/IEC 27037 (proveniência
    e não-repúdio).

    A flag ``normalised_complete`` sinaliza se a normalização encontrou
    ambos ``brand`` e ``model`` — permite ao caller detectar schema drift
    (chaves renomeadas em upstream) e evitar cachear respostas parciais.
    """
    brand = payload.get('brand') or payload.get('manufacturer') or ''
    model = payload.get('model') or payload.get('device') or ''
    normalised_complete = bool(brand and model)
    return {
        'brand': brand,
        'model': model,
        'os': payload.get('os') or payload.get('operating_system') or '',
        'storage': payload.get('storage') or payload.get('memory') or '',
        'release_date': (
            payload.get('release_date')
            or payload.get('released')
            or ''
        ),
        'color': payload.get('color') or '',
        'normalised_complete': normalised_complete,
        'raw': payload,  # para external_lookup_snapshot (auditoria)
    }
