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

import contextlib
import logging

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)


# Chaves de cache para contadores de quota. TTL deliberadamente longo
# (24h) para sobreviver a restart de gunicorn worker e dar visibilidade
# operacional contínua. Auditoria 2026-05-18 §3 N9 — fechado em Sem.12.
_CACHE_KEY_CALLS_24H = 'imeidb:calls_24h'
_CACHE_KEY_LAST_402 = 'imeidb:last_402_at'
_CACHE_KEY_LAST_401 = 'imeidb:last_401_at'
_CACHE_KEY_LAST_429 = 'imeidb:last_429_at'
_CACHE_TTL_24H = 60 * 60 * 24


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


def _increment_call_counter() -> int:
    """Incrementa contador de chamadas nas últimas 24h. Devolve o valor pós-incremento.

    Usado para visibilidade operacional do consumo de saldo `imeidb.xyz`
    (auditoria 2026-05-18 §3 N9). DatabaseCache em produção, LocMem em
    testes. Em caso de qualquer falha de cache (backend down, race),
    devolve 0 silenciosamente — o counter é métrica, não comportamento.
    """
    try:
        cache.add(_CACHE_KEY_CALLS_24H, 0, _CACHE_TTL_24H)
        return cache.incr(_CACHE_KEY_CALLS_24H)
    except Exception:  # noqa: BLE001 — métrica não deve quebrar lookup
        return 0


def _record_critical_event(
    event: str, imei: str, *, http_status: int | None = None, api_code=None
) -> None:
    """Regista evento operacional crítico (quota esgotada, token inválido,
    rate-limited) no AuditLog como entrada `SYSTEM_ALERT`/`SYSTEM`.

    Eventos cobertos:
    - ``quota_exhausted`` (HTTP 402 ou api_code 402): saldo `imeidb.xyz` no fim.
    - ``token_invalid`` (HTTP 401 ou api_code 401): token foi revogado/inválido.
    - ``rate_limited`` (HTTP 429 ou api_code 429): API limita por quota burst.

    Cada entrada inclui timestamp do evento numa chave de cache dedicada
    (`imeidb:last_<status>_at`) para o stats endpoint admin futuro (e
    para inspecção rápida via Django shell). Falhas de gravação são
    silenciadas — alerta é defesa-em-profundidade, não pode quebrar
    o lookup que já está a falhar por outra razão.
    """
    now_iso = timezone.now().isoformat()
    cache_key_by_event = {
        'quota_exhausted': _CACHE_KEY_LAST_402,
        'token_invalid': _CACHE_KEY_LAST_401,
        'rate_limited': _CACHE_KEY_LAST_429,
    }.get(event)
    if cache_key_by_event:
        # Métrica não pode quebrar lookup; se cache backend falhar, segue.
        with contextlib.suppress(Exception):
            cache.set(cache_key_by_event, now_iso, _CACHE_TTL_24H)

    try:
        # Import tardio para evitar ciclos (models → services → models). A
        # origem não-HTTP vem da fonte única (audit.log_system_event — D34).
        from core.audit import log_system_event
        from core.models import AuditLog

        log_system_event(
            action=AuditLog.Action.SYSTEM_ALERT,
            resource_type=AuditLog.ResourceType.SYSTEM,
            resource_id=0,
            details={
                'source': 'imeidb_lookup',
                'event': event,
                'imei_masked': mask_imei(imei),
                'http_status': http_status,
                'api_code': api_code,
                'timestamp': now_iso,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning('imeidb critical event %s: failed to write AuditLog: %s', event, exc)


def mask_imei(imei) -> str:
    """Trunca o IMEI ao TAC (8 dígitos) para uso em logs operacionais.

    O IMEI completo é PII forense (ISO/IEC 27037) — identifica um único
    dispositivo. Em logs (Fly.io, ficheiros) basta o TAC (Type Allocation
    Code, primeiros 8 dígitos) para correlacionar com a marca/modelo sem
    expor o identificador único do equipamento. Auditoria 2026-05-18 §3 N1.
    """
    s = str(imei or '')
    if len(s) < 8:
        return '***'
    return f'{s[:8]}***'


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
        raise LookupError('Serviço de consulta IMEI não está configurado. Preenche manualmente.')

    url = f"{_base_url().rstrip('/')}/imei/{imei}"
    headers = {
        'X-Api-Key': token,
        'Accept': 'application/json',
        'User-Agent': 'ForensiQ/1.0 (+https://forensiq.pt)',
    }
    # Conta a chamada antes de tentar — alinha contador com tentativas,
    # não com sucesso (N9: queremos visibilidade de "tentou X vezes",
    # não só "teve sucesso X vezes").
    _increment_call_counter()
    try:
        with httpx.Client(timeout=_timeout()) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        log.warning('imeidb timeout imei=%s', mask_imei(imei))
        raise LookupError('Tempo esgotado ao consultar imeidb.xyz. Preenche manualmente.')
    except httpx.RequestError as exc:
        log.warning('imeidb network error imei=%s err=%s', mask_imei(imei), exc)
        raise LookupError('Erro de rede ao consultar imeidb.xyz. Preenche manualmente.')

    _raise_for_status(response.status_code, imei=imei)

    try:
        payload = response.json()
    except ValueError:
        log.warning('imeidb non-json body imei=%s', mask_imei(imei))
        raise LookupError('Resposta de imeidb.xyz não é JSON válido.')

    if not isinstance(payload, dict):
        log.warning(
            'imeidb payload not a dict imei=%s type=%s',
            mask_imei(imei),
            type(payload).__name__,
        )
        raise LookupError('Resposta de imeidb.xyz em formato inesperado.')

    # A API por vezes responde 200 OK mas com success:false + code próprio.
    if payload.get('success') is False:
        api_code = payload.get('code')
        api_msg = payload.get('message') or ''
        log.warning(
            'imeidb success=false imei=%s code=%s msg=%s',
            mask_imei(imei),
            api_code,
            api_msg,
        )
        # Em códigos críticos vindo no body (não no HTTP status), também
        # regista alerta — o upstream usa 200 + body.code para alguns
        # cenários (auditoria 2026-05-18 §3 N9). Evento + mensagem vêm da
        # MESMA tabela (_API_CODES — auditoria D47).
        event = _API_CODES[api_code][0] if api_code in _API_CODES else None
        if event:
            _record_critical_event(event, imei, http_status=200, api_code=api_code)
        raise LookupError(_message_for_api_code(api_code, api_msg))

    return _normalize(payload)


# ---------------------------------------------------------------------------
# Helpers privados de erro / normalização
# ---------------------------------------------------------------------------


# Tabela ÚNICA código→(evento crítico, mensagem PT) da imeidb.xyz (auditoria
# D47): _raise_for_status, _message_for_api_code e o ramo success=false do
# lookup consultam-na — o registo do evento e a mensagem nunca dessincronizam.
# Evento None = não-crítico (sem SYSTEM_ALERT). 460 é o código próprio da
# imeidb.xyz para IMEI inválido/desconhecido (equivalente a 404).
_API_CODES = {
    401: ('token_invalid', 'Token de imeidb.xyz inválido. Contacta o administrador.'),
    402: ('quota_exhausted', 'Saldo da API imeidb.xyz esgotado. Preenche manualmente.'),
    429: ('rate_limited', 'Limite de consultas atingido em imeidb.xyz. Tenta mais tarde.'),
    404: (None, 'IMEI não encontrado em imeidb.xyz. Preenche manualmente.'),
    460: (None, 'IMEI não encontrado em imeidb.xyz. Preenche manualmente.'),
}


def _raise_for_status(status_code: int, imei: str = '') -> None:
    """Mapeia códigos HTTP da imeidb.xyz para mensagens PT-PT (tabela única
    ``_API_CODES`` — auditoria D47).

    Em códigos críticos operacionais (401/402/429), regista entrada
    SYSTEM_ALERT no AuditLog via `_record_critical_event` antes de
    levantar a `LookupError` (auditoria 2026-05-18 §3 N9 — fechado em Sem.12).
    """
    if 200 <= status_code < 300:
        return
    if status_code in _API_CODES:
        event, msg = _API_CODES[status_code]
        if event:
            _record_critical_event(event, imei, http_status=status_code)
        raise LookupError(msg)
    if status_code >= 500:
        raise LookupError(f'imeidb.xyz indisponível (HTTP {status_code}). Tenta mais tarde.')
    raise LookupError(f'Resposta inesperada de imeidb.xyz (HTTP {status_code}).')


def _message_for_api_code(code, fallback_msg: str) -> str:
    """Mensagem PT-PT para o ``code`` no body da imeidb.xyz (tabela única
    ``_API_CODES`` — auditoria D47)."""
    if isinstance(code, int) and code in _API_CODES:
        return _API_CODES[code][1]
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
    if commercial_name and brand and commercial_name.lower().startswith(brand.lower() + ' '):
        commercial_name = commercial_name[len(brand) + 1 :].strip()

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
