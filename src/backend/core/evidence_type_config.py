"""
ForensiQ — Acesso ao catálogo editável de tipos de evidência (ADR-0018).

O vocabulário de ``EvidenceType`` VIVE na base de dados (``EvidenceTypeRef``),
editável no admin (rótulo / activo / ordem por tipo), semeado por
``0030_seed_evidence_types``. Este módulo é a API de LEITURA que alimenta:

  - o ``choices`` (callable) do campo ``Evidence.type`` → display
    (``get_type_display``), validação (``full_clean``), admin e formulários;
  - o ``<select>`` do formulário de evidência e o filtro da API (só activos);
  - a guarda de whitelist do filtro da consola (só activos).

O *slug* (``code``) é a fonte de verdade congelada no registo e no hash
(ADR-0018) — é WRITE-ONCE; só rótulo/activo/ordem são editáveis. Sem cache de
estado (à semelhança de ``evidence_field_config``): os laços usam ``labels()``
uma vez para evitar N+1.
"""

from __future__ import annotations


def all_choices() -> list[tuple[str, str]]:
    """TODOS os tipos (activos e inactivos), ordenados — fonte do ``choices`` do
    campo ``Evidence.type``. Inclui inactivos para que ``get_type_display``
    resolva o rótulo de itens cujo tipo foi entretanto desactivado."""
    from core.models import EvidenceTypeRef

    return list(
        EvidenceTypeRef.objects.order_by('order', 'code').values_list('code', 'label')
    )


def active_choices() -> list[tuple[str, str]]:
    """Tipos ACTIVOS, ordenados — para o ``<select>`` do formulário e o filtro da API."""
    from core.models import EvidenceTypeRef

    return list(
        EvidenceTypeRef.objects.filter(is_active=True)
        .order_by('order', 'code')
        .values_list('code', 'label')
    )


def active_codes() -> set[str]:
    """Conjunto dos códigos ACTIVOS — whitelist de filtros/entrada."""
    from core.models import EvidenceTypeRef

    return set(
        EvidenceTypeRef.objects.filter(is_active=True).values_list('code', flat=True)
    )


def labels() -> dict[str, str]:
    """``{code: label}`` de TODOS os tipos, num só query — para laços (evita N+1)."""
    from core.models import EvidenceTypeRef

    return dict(EvidenceTypeRef.objects.values_list('code', 'label'))


def label_for(code: str) -> str:
    """Rótulo de um código, com fallback ao próprio código (tolerante)."""
    return labels().get(code, code)
