"""
ForensiQ — Pacote de política de domínio (ADR-0019).

Casa única das regras de lei/processo que classificam a custódia, separadas da
persistência (``core.models``), da apresentação (views/templates) e da API
(serializers). As camadas consomem daqui; nunca guardam cópia própria de uma
regra. Ver ``feedback_policy_single_source``.

Submódulos:
- :mod:`core.policy.event_states` — vocabulário de eventos/custódios, conjuntos
  canónicos e derivação do estado legal.
- :mod:`core.policy.custody_transitions` — predicados puros das guardas de
  transição (que evento é válido a seguir), fonte única que o ``clean()`` do
  modelo e o frontend chamam.

O que NÃO vive aqui (por desenho): as fórmulas de hash e o ``save()``/``delete()``
append-only (contrato de integridade, em ``core.models``), os validadores técnicos
(``core.validators``) e a política de acesso ReBAC (``core.access``).
"""

from core.policy.custody_transitions import (
    CUSTODIAN_TYPE_BY_INSTITUTION,
    genesis_event_for,
    lab_gate_blocks,
    next_events,
)
from core.policy.event_states import (
    GENESIS_EVENTS,
    HANDOFF_EVENTS,
    LAB_CUSTODIANS,
    LEGAL_STATES,
    SEIZURE_GENESIS_EVENTS,
    TERMINAL_EVENTS,
    TERMINAL_LEGAL_STATES,
    CustodianType,
    EventType,
    derive_legal_state,
)

__all__ = [
    'CUSTODIAN_TYPE_BY_INSTITUTION',
    'GENESIS_EVENTS',
    'HANDOFF_EVENTS',
    'LAB_CUSTODIANS',
    'LEGAL_STATES',
    'SEIZURE_GENESIS_EVENTS',
    'TERMINAL_EVENTS',
    'TERMINAL_LEGAL_STATES',
    'CustodianType',
    'EventType',
    'derive_legal_state',
    'genesis_event_for',
    'lab_gate_blocks',
    'next_events',
]
