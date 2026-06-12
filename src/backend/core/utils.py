"""
ForensiQ — Helpers transversais reutilizados em views, serializers e PDF.

Fonte ÚNICA de padrões de APRESENTAÇÃO/ORDENAÇÃO antes repetidos em dezenas de
pontos. Sem side effects; :func:`legal_state_of` lê a relação ``custody_chain``
(reaproveita o prefetch quando existe), os restantes são puros.
"""

from __future__ import annotations

from django.utils import timezone

from core.policy.custody_transitions import despacho_done
from core.policy.event_states import (
    derive_legal_state,
    pericia_deadline,
    validation_status,
)


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


def has_despacho(evidence):
    """A perícia deste item foi ORDENADA por despacho judicial? (CPP art.
    154.º/158.º — repetível; aqui interessa a presença, não a contagem).

    Predicado da policy (:func:`despacho_done`) sobre o ledger lido via
    ``all()`` (reaproveita o prefetch quando existe; a presença não depende
    da ordem). Derivado do ledger, nunca guardado.
    """
    return despacho_done([e.event_type for e in evidence.custody_chain.all()])


def pericia_deadline_of(evidence, now=None):
    """Prazo da perícia ordenada de UMA evidência (data-limite + estatuto,
    derivados do último despacho — :func:`core.policy.event_states.pericia_deadline`).

    Mesmo micro-fluxo de :func:`legal_state_of` (materializar → ordenar →
    derivar; reaproveita o prefetch quando existe). ``None`` = não aplicável
    (sem despacho, perícia concluída, ou exigência extinta pela disposição final).
    """
    eventos = sort_custody_chain(evidence.custody_chain.all())
    return pericia_deadline(eventos, now or timezone.now())


def current_seal_of(evidence):
    """N.º do selo EM VIGOR de UMA evidência — derivado do ledger, nunca guardado.

    Último ``new_seal_number`` não-vazio da cadeia ordenada (uma receção pode
    voltar a selar); fallback ao selo inicial da génese. Mesmo micro-fluxo de
    :func:`legal_state_of` (reaproveita o prefetch). ``''`` = sem selo.
    """
    eventos = sort_custody_chain(evidence.custody_chain.all())
    for rec in reversed(eventos):
        if rec.new_seal_number:
            return rec.new_seal_number
    return evidence.initial_seal_number or ''
