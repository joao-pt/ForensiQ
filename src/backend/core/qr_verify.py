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

from core.models import Occurrence


def short_hash_for(occurrence_id: int) -> str:
    """Hash curto não-enumerável a partir do `Occurrence.id`.

    Determinístico (mesma occurrence_id + mesmo secret → mesmo hash).
    Resistente a enumeração casual via 48 bits de entropia + HMAC.
    """
    secret = getattr(settings, 'QR_VERIFY_SECRET', settings.SECRET_KEY)
    length = getattr(settings, 'QR_VERIFY_HASH_LEN', 12)
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    digest = hmac.new(secret, str(occurrence_id).encode('utf-8'), hashlib.sha256).hexdigest()
    return digest[:length]


def resolve_occurrence(short_hash: str) -> Occurrence | None:
    """Resolve um `short_hash` para a Occurrence correspondente.

    Implementação: itera as ocorrências comparando o hash recomputado.
    Aceitável dado o volume académico (~poucas centenas de
    ocorrências). Em produção a sério com 10k+ registos, considerar
    cache ou tabela de mapping com índice. Audit follow-up se
    necessário.
    """
    if not short_hash or len(short_hash) != getattr(settings, 'QR_VERIFY_HASH_LEN', 12):
        return None
    # Constant-time comparison para resistir a timing attacks teóricos.
    for occ in Occurrence.objects.only('id').iterator():
        if hmac.compare_digest(short_hash_for(occ.id), short_hash):
            return Occurrence.objects.get(pk=occ.id)
    return None
