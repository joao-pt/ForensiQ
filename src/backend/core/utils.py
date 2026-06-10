"""
ForensiQ — Helpers transversais reutilizados em views, serializers e PDF.

Fonte ÚNICA de padrões de APRESENTAÇÃO/ORDENAÇÃO antes repetidos em dezenas de
pontos. Sem side effects; :func:`legal_state_of` lê a relação ``custody_chain``
(reaproveita o prefetch quando existe), os restantes são puros.
"""

from __future__ import annotations

from django.utils import timezone

from core.policy.event_states import derive_legal_state, validation_status


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


def legal_state_of(evidence, *, with_last=False):
    """Estado legal DERIVADO de UMA evidência (``None`` sem eventos de custódia).

    Fonte ÚNICA do micro-fluxo «materializar ``custody_chain`` → ordenar por
    ``sequence`` → ``derive_legal_state``» repetido em serializers, views e PDF.
    Lê via ``all()`` para reaproveitar o prefetch quando existe; ordena em
    memória (lista curta) para robustez contra ausência de prefetch.

    ``with_last=True`` devolve ``(estado, último_registo)`` para os consumidores
    que também precisam do último elo (ex.: PDF), sem repetir a materialização.
    """
    eventos = sort_custody_chain(evidence.custody_chain.all())
    state = derive_legal_state(eventos) if eventos else None
    if with_last:
        return state, (eventos[-1] if eventos else None)
    return state


def validation_status_of(evidence, now=None):
    """Estatuto de validação da apreensão de UMA evidência (eixo ORTOGONAL ao
    estado de custódia — :func:`core.policy.event_states.validation_status`).

    Mesmo micro-fluxo de :func:`legal_state_of` (materializar → ordenar →
    derivar; reaproveita o prefetch quando existe). ``None`` = não aplicável
    (sem apreensão própria, ou exigência extinta pela disposição final).
    """
    eventos = sort_custody_chain(evidence.custody_chain.all())
    return validation_status(eventos, now or timezone.now())
