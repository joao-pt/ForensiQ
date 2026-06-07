"""
ForensiQ — Helpers transversais reutilizados em views, serializers e PDF.

Fonte ÚNICA de padrões de APRESENTAÇÃO/ORDENAÇÃO antes repetidos em dezenas de
pontos. Puros: sem queries nem side effects.
"""

from __future__ import annotations


def get_user_display_name(user, default: str = 'sistema') -> str:
    """Nome de apresentação de um utilizador: nome completo, senão ``username``.

    Fonte ÚNICA do padrão ``get_full_name() or username`` repetido em views,
    serializers e PDF. ``default`` cobre o caso de não haver utilizador (ex.: uma
    ação do sistema sem agente associado).
    """
    if not user:
        return default
    return user.get_full_name() or user.username


def sort_custody_chain(events):
    """Ordena eventos do ledger pela ordem CANÓNICA (``sequence``), não por timestamp.

    Fonte ÚNICA do ``sorted(..., key=lambda r: r.sequence)`` repetido em views,
    serializers e PDF. Devolve uma lista nova (não muta a entrada).
    """
    return sorted(events, key=lambda r: r.sequence)
