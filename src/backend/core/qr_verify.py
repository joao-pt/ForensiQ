"""
ForensiQ — Verificação pública via QR (ADR-0012 Vaga 1).

O PDF da ocorrência embebe um QR code que aponta para
``/v/<short_hash>/``. Vista adaptativa:

- Sem login (ou login sem perfil EXPERT/AGENT-dono): renderiza
  template ``public_verify.html`` com dados mínimos não-sensíveis
  — ``occurrence.code``, número de evidências esperadas, hashes
  de integridade dos itens. Permite ao perito confirmar que recebeu
  o talão certo, sem expor descrições, GPS, agentes ou metadados
  forenses sensíveis.
- Com login + perfil suficiente: redirect HTTP 302 para
  ``/occurrence/<code>`` (vista autenticada completa).

O `short_hash` é derivado por HMAC-SHA256(``QR_VERIFY_SECRET``,
``str(occurrence.id)``), truncado a `QR_VERIFY_HASH_LEN` (12 chars
por defeito = 48 bits de entropia). Não-enumerável sem conhecer o
secret. Rotacionável via env var sem invalidar JWT/sessões.
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache

from core.models import GuiaTransporte, Occurrence


def _short_hash(message: str) -> str:
    """HMAC-SHA256(secret, message) truncado — base dos tokens públicos curtos.
    48 bits de entropia (12 hex), não-enumerável; rotacionável via
    ``QR_VERIFY_SECRET`` sem invalidar JWT/sessões."""
    secret = getattr(settings, 'QR_VERIFY_SECRET', settings.SECRET_KEY)
    length = getattr(settings, 'QR_VERIFY_HASH_LEN', 12)
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    return hmac.new(secret, message.encode('utf-8'), hashlib.sha256).hexdigest()[:length]


def short_hash_for(occurrence_id: int) -> str:
    """Hash curto não-enumerável de um `Occurrence` (mensagem = ``str(id)``)."""
    return _short_hash(str(occurrence_id))


def short_hash_for_guia(guia_id: int) -> str:
    """Hash curto de uma `GuiaTransporte` (mensagem ``guia:<id>`` — espaço de nomes
    separado do das ocorrências, sem colisão de tokens)."""
    return _short_hash(f'guia:{guia_id}')


def verify_url_for(occurrence_id: int) -> str:
    """URL pública ABSOLUTA de verificação ``/v/<short_hash>/`` (ADR-0012).

    Fonte ÚNICA da composição (auditoria D43) — o PDF (QR da guia) e o centro
    de verificação consomem daqui; um único default de ``SITE_URL`` e um único
    formato de rota.
    """
    base = getattr(settings, 'SITE_URL', 'https://forensiq.pt').rstrip('/')
    return f'{base}/v/{short_hash_for(occurrence_id)}/'


def verify_url_for_guia(guia_id: int) -> str:
    """URL pública ABSOLUTA de verificação de uma REMESSA ``/v/g/<short_hash>/`` — o
    destino do QR da guia de transporte (confirma o que vem na remessa)."""
    base = getattr(settings, 'SITE_URL', 'https://forensiq.pt').rstrip('/')
    return f'{base}/v/g/{short_hash_for_guia(guia_id)}/'


# Resolução O(1) dos tokens públicos. O endpoint /v/ é anónimo: iterar a
# tabela inteira a recomputar HMAC por request era um vector de DoS por
# varrimento. Cacheamos um mapa {short_hash: id}, reconstruído só quando a
# contagem de registos muda (criação/remoção) ou quando o TTL expira —
# nunca por request. Cada pedido público fica num COUNT indexado + um
# lookup de dicionário. Um atacante não consegue criar ocorrências (exige
# autenticação), logo tráfego de hashes aleatórios nunca força reconstrução.
# O TTL curto propaga também a rotação de QR_VERIFY_SECRET dentro de ≤TTL.
_CACHE_KEY_OCC_MAP = 'qrverify:occ_hashmap'
_CACHE_KEY_GUIA_MAP = 'qrverify:guia_hashmap'
_QR_MAP_TTL_SECONDS = 60


def _resolve_via_map(cache_key: str, model, hash_fn, short_hash: str):
    """Resolve ``short_hash`` → instância via mapa ``{hash: id}`` cacheado.

    Reconstrói o mapa apenas quando a contagem de registos difere da
    cacheada (ou o TTL expira); caso contrário serve do cache. No caminho
    de sucesso faz uma única query (lookup do id resolvido) — sem a 2.ª
    query do varrimento anterior. A comparação por dicionário é suficiente:
    nenhum material secreto é comparado (o segredo está no HMAC, nunca aqui)
    e a existência do token já é observável pela resposta HTTP, pelo que a
    comparação em tempo-constante deixou de acrescentar proteção.
    """
    if not short_hash or len(short_hash) != getattr(settings, 'QR_VERIFY_HASH_LEN', 12):
        return None
    count = model.objects.count()
    cached = cache.get(cache_key)
    if cached is not None and cached.get('count') == count:
        mapping = cached['map']
    else:
        mapping = {hash_fn(pk): pk for pk in model.objects.values_list('id', flat=True)}
        cache.set(cache_key, {'count': count, 'map': mapping}, _QR_MAP_TTL_SECONDS)
    pk = mapping.get(short_hash)
    if pk is None:
        return None
    return model.objects.filter(pk=pk).first()


def resolve_occurrence(short_hash: str) -> Occurrence | None:
    """Resolve um `short_hash` para a Occurrence correspondente.

    Resolução O(1) por mapa cacheado ``{hash: id}`` (ver `_resolve_via_map`):
    o endpoint público /v/ deixa de recomputar HMAC sobre toda a tabela por
    request, fechando o vector de DoS por varrimento. O mapa reflecte novos
    registos e a rotação de ``QR_VERIFY_SECRET`` dentro de ≤_QR_MAP_TTL_SECONDS.
    """
    return _resolve_via_map(_CACHE_KEY_OCC_MAP, Occurrence, short_hash_for, short_hash)


def resolve_guia(short_hash: str) -> GuiaTransporte | None:
    """Resolve um `short_hash` para a GuiaTransporte (mesmo mapa cacheado O(1)
    de :func:`resolve_occurrence`)."""
    return _resolve_via_map(_CACHE_KEY_GUIA_MAP, GuiaTransporte, short_hash_for_guia, short_hash)
