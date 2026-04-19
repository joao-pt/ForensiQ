"""Consulta imeidb.xyz para enriquecimento IMEI.

Arquitectura:
- Sem retry automático (keep-it-simple) — se falhar, o agente preenche
  manualmente e o fluxo forense continua.
- Sem circuit breaker — a camada de cache (30 dias, ADR-0008) já amortiza
  a maioria das consultas e evita sobrecarga da API externa.
- Resposta normalizada para schema estável em ``_normalize``; o payload
  bruto (truncado) é guardado em ``raw`` para auditoria (ISO/IEC 27037).

Endpoint upstream
-----------------
``GET https://imeidb.xyz/api/imei/{imei}`` autenticado via header
``X-Api-Key`` (alternativa à query ``?token=`` — preferimos header para
não vazar o token em logs de proxy/CDN nem em ``Referer``).

Resposta da API tem o shape::

    {
      "success": true,
      "query": <imei>,
      "data": {
         "brand": ..., "model": ..., "manufacturer": ..., "name": ...,
         "tac": ..., "type": ...,
         "device_spec": {"os": ..., "os_family": ..., ...},
         ...
      }
    }

Erros podem vir com HTTP 200 + ``success: false`` (a API tem códigos
próprios: 401, 402, 429, 460), por isso verificamos a flag mesmo em 2xx.

Settings usadas (fornecidas por Wave 2b em ``forensiq_project.settings``):
- ``IMEIDB_API_TOKEN``   — chave da API (fly secret).
- ``IMEIDB_BASE_URL``    — URL base (default ``https://imeidb.xyz/api``).
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
    """URL base configurada, com default seguro."""
    return getattr(settings, 'IMEIDB_BASE_URL', 'https://imeidb.xyz/api')


def _api_token() -> str:
    return getattr(settings, 'IMEIDB_API_TOKEN', '')


def _timeout() -> float:
    return float(getattr(settings, 'IMEIDB_TIMEOUT_SECONDS', 10))


# Campos do raw payload que NÃO interessa persistir na cache/auditoria
# (imagens em base64, listas longas de aliases, etc.) — evita inflar o
# JSONField ``external_lookup_snapshot`` desnecessariamente.
_RAW_DROP_KEYS = ('device_image',)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def lookup_imei(imei: str) -> dict:
    """Consulta imeidb.xyz e devolve dados normalizados do dispositivo.

    Args:
        imei: string com exactamente 15 dígitos (já validada pelo caller
            via ``core.validators.validate_imei``).

    Returns:
        dict com chaves normalizadas: ``brand``, ``model`` (SKU técnico,
        ex.: ``A2161``), ``commercial_name`` (nome reconhecível, ex.:
        ``iPhone 11 Pro Max``), ``os``, ``storage``, ``release_date``,
        ``color``, ``manufacturer``, ``tac``, ``normalised_complete`` e
        ``raw`` (subset do payload original para auditoria ISO 27037).

    Raises:
        LookupError: em qualquer falha de rede, HTTP não-2xx, JSON
            inválido ou saldo esgotado. A mensagem é em PT-PT e pode
            ser exposta ao cliente.
    """
    token = _api_token()
    if not token:
        raise LookupError(
            'Serviço de consulta IMEI não está configurado. Preenche manualmente.'
        )

    url = f"{_base_url().rstrip('/')}/imei/{imei}"
    headers = {
        'X-Api-Key': token,
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

    _raise_for_status(response.status_code)

    try:
        payload = response.json()
    except ValueError:
        log.warning('imeidb non-json body imei=%s', imei)
        raise LookupError('Resposta de imeidb.xyz não é JSON válido.')

    if not isinstance(payload, dict):
        log.warning(
            'imeidb payload not a dict imei=%s type=%s',
            imei, type(payload).__name__,
        )
        raise LookupError('Resposta de imeidb.xyz em formato inesperado.')

    # A API por vezes responde 200 OK mas com success:false + code próprio.
    if payload.get('success') is False:
        api_code = payload.get('code')
        api_msg = payload.get('message') or ''
        log.warning(
            'imeidb success=false imei=%s code=%s msg=%s',
            imei, api_code, api_msg,
        )
        raise LookupError(_message_for_api_code(api_code, api_msg))

    return _normalize(payload)


# ---------------------------------------------------------------------------
# Helpers privados de erro / normalização
# ---------------------------------------------------------------------------

def _raise_for_status(status_code: int) -> None:
    """Mapeia códigos HTTP da imeidb.xyz para mensagens PT-PT."""
    if 200 <= status_code < 300:
        return
    if status_code == 401:
        raise LookupError(
            'Token de imeidb.xyz inválido. Contacta o administrador.'
        )
    if status_code == 402:
        raise LookupError(
            'Saldo da API imeidb.xyz esgotado. Preenche manualmente.'
        )
    if status_code in (404, 460):
        # 460 é o código próprio da imeidb.xyz para IMEI inválido/desconhecido.
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
    raise LookupError(
        f'Resposta inesperada de imeidb.xyz (HTTP {status_code}).'
    )


def _message_for_api_code(code, fallback_msg: str) -> str:
    """Mensagem PT-PT para o ``code`` no body da imeidb.xyz."""
    mapping = {
        401: 'Token de imeidb.xyz inválido. Contacta o administrador.',
        402: 'Saldo da API imeidb.xyz esgotado. Preenche manualmente.',
        429: 'Limite de consultas atingido em imeidb.xyz. Tenta mais tarde.',
        460: 'IMEI não encontrado em imeidb.xyz. Preenche manualmente.',
    }
    if isinstance(code, int) and code in mapping:
        return mapping[code]
    if fallback_msg:
        return f'imeidb.xyz: {fallback_msg}'
    return 'Resposta de imeidb.xyz em formato inesperado.'


def _trim_raw(data: dict) -> dict:
    """Remove campos pesados/desnecessários do raw para a auditoria/cache."""
    return {k: v for k, v in data.items() if k not in _RAW_DROP_KEYS}


def _normalize(payload: dict) -> dict:
    """Mapeia o payload da imeidb.xyz para o schema interno estável.

    Os campos úteis vivem dentro de ``payload['data']``:
    ``brand``, ``model``, ``manufacturer``, ``name``, ``tac``, ``type`` e o
    sub-dict ``device_spec`` com ``os``/``os_family``.

    Best-effort: se a API mudar o shape (chaves renomeadas), tentamos
    fallbacks razoáveis. A flag ``normalised_complete`` sinaliza se a
    normalização encontrou ``brand`` e ``model`` — permite ao caller
    detectar schema drift e evitar cachear respostas parciais por 30 dias.
    """
    # Aceita tanto o shape novo {data: {...}} como um payload achatado.
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    spec = data.get('device_spec') if isinstance(data.get('device_spec'), dict) else {}

    brand = data.get('brand') or data.get('manufacturer') or ''
    # SKU/modelo técnico (ex.: "A2161"). Mantemos o valor cru de `model`.
    model_sku = data.get('model') or data.get('device') or ''
    # Nome comercial. Preferimos `name`; se vier como "Apple iPhone 11 Pro Max"
    # tiramos o prefixo da marca para evitar duplicação na UI.
    commercial_name = data.get('name') or ''
    if commercial_name and brand and commercial_name.lower().startswith(
        brand.lower() + ' '
    ):
        commercial_name = commercial_name[len(brand) + 1:].strip()

    os_name = (
        spec.get('os')
        or spec.get('os_family')
        or data.get('os')
        or data.get('operating_system')
        or ''
    )

    # Para o flag de "schema completo" basta termos brand + identificação do
    # dispositivo (SKU OU nome comercial) — assim não inutilizamos respostas
    # em que a API só dá um dos dois.
    normalised_complete = bool(brand and (model_sku or commercial_name))

    return {
        'brand': brand,
        'model': model_sku,
        'commercial_name': commercial_name,
        'manufacturer': data.get('manufacturer') or '',
        'os': os_name,
        # Campos que a API por vezes não devolve (free tier) — mantemos
        # vazio para o frontend não preencher com lixo.
        'storage': data.get('storage') or data.get('memory') or '',
        'release_date': data.get('release_date') or data.get('released') or '',
        'color': data.get('color') or '',
        'tac': data.get('tac') or '',
        'type': data.get('type') or '',
        'normalised_complete': normalised_complete,
        'raw': _trim_raw(data),  # para external_lookup_snapshot (auditoria)
    }
