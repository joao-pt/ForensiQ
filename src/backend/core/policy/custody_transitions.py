"""
ForensiQ — Política de domínio: guardas de transição da custódia (ADR-0019 §3).

Predicados PUROS que decidem, a partir do histórico do ledger (lista dos
``event_type`` já gravados, por ordem de sequence) e da proveniência da
evidência, que evento de custódia é válido a seguir. São a FONTE ÚNICA das
guardas de transição por eixo de ``event_type``:

- ``ChainOfCustody.clean()`` (``core.models``) chama estes predicados e traduz a
  recusa numa ``ValidationError`` com a mensagem legal — continua a ser quem lê o
  ledger, muta o objeto e sela o registo (ADR-0019 §4);
- o frontend (``_valid_next_events``) chama :func:`next_events` para oferecer SÓ
  as transições que o modelo aceitaria.

Assim a regra processual (CPP art. 154.º/158.º/178.º; ADR-0015/0016) vive num só
sítio e o ecrã não pode contrariar o modelo. Este módulo não toca ORM nem levanta
``ValidationError``: recebe primitivos e devolve decisões.
"""

from core.policy.event_states import (
    GENESIS_EVENTS,
    LAB_CUSTODIANS,
    SEIZURE_GENESIS_EVENTS,
    SHARED_CUSTODIAN_PAIRS,
    TERMINAL_EVENTS,
    CustodianType,
    EventType,
)

# Movimentação LEGADO (um só tempo): mantida no enum para ledgers históricos, já
# não oferecida como próximo evento (ADR-0016 v2).
LEGACY_MOVE_EVENTS = frozenset(
    {EventType.TRANSFERENCIA_CUSTODIA, EventType.ASSUNCAO_CUSTODIA}
)

# Destino do encaminhamento → custódio resultante (eixo CustodianType, ortogonal
# ao event_type). Derivar no servidor é o que faz o gate de laboratório disparar:
# encaminhar para um LAB_* leva custodian_type LAB_*. O Ministério Público (MP)
# não tem custódio próprio → custódio em branco (estado derivado 'encaminhada').
# As chaves são SLUGS de ``InstitutionType`` (mantidos como strings para este
# módulo ficar no fundo do grafo, sem importar ``core.models``; os slugs são
# contrato estável — ADR-0017/0018).
# Derivado da fonte única dos pares partilhados (auditoria D33): as chaves são
# exatamente os slugs de SHARED_CUSTODIAN_PAIRS — um tipo novo entra num só sítio.
CUSTODIAN_TYPE_BY_INSTITUTION = {
    slug: CustodianType(slug) for slug in SHARED_CUSTODIAN_PAIRS
}


def genesis_event_for(*, has_parent, is_digital_file):
    """Evento de génese aplicável por proveniência (ADR-0016 §2).

    - sub-componente (tem evidência-pai) → ``DERIVACAO_ITEM``;
    - cópia de dados (tipo ``DIGITAL_FILE``) → ``APREENSAO_DADOS``;
    - objeto físico (item-raiz) → ``APREENSAO_OBJETO``.
    """
    if has_parent:
        return EventType.DERIVACAO_ITEM
    if is_digital_file:
        return EventType.APREENSAO_DADOS
    return EventType.APREENSAO_OBJETO


def genesis_violation(event_type, *, has_parent, is_digital_file):
    """Por que razão ``event_type`` é recusado como génese desta proveniência?

    Devolve um código de recusa (que o ``clean()`` traduz na mensagem legal —
    ADR-0019 §4) ou ``None`` se o evento for EXATAMENTE a génese que
    :func:`genesis_event_for` determina. A coerência é por igualdade estrita,
    pelo que o modelo nunca aceita uma génese que o ecrã (:func:`next_events`)
    não ofereceria (ADR-0016 §2).

    Códigos: ``nao_genese`` (não é evento de génese); ``genese_com_pai``
    (apreensão num sub-componente — autonomiza-se por derivação);
    ``derivacao_sem_pai`` (derivação num item-raiz); ``dados_sem_digital``
    (``APREENSAO_DADOS`` fora de ``DIGITAL_FILE``); ``objeto_para_dados``
    (``APREENSAO_OBJETO`` numa cópia de dados — entra por apreensão de dados).
    """
    if event_type not in GENESIS_EVENTS:
        return 'nao_genese'
    if event_type == genesis_event_for(
        has_parent=has_parent, is_digital_file=is_digital_file
    ):
        return None
    if has_parent:
        return 'genese_com_pai'
    if event_type == EventType.DERIVACAO_ITEM:
        return 'derivacao_sem_pai'
    if event_type == EventType.APREENSAO_DADOS:
        return 'dados_sem_digital'
    return 'objeto_para_dados'


def ledger_has_terminal(prior_types):
    """Há um evento terminal (restituição/destruição) no ledger? Fecha-o — nenhum
    evento é aceite depois, em qualquer posição (semântica de presença, ADR-0015)."""
    return any(t in TERMINAL_EVENTS for t in prior_types)


def has_prior_seizure(prior_types):
    """Há uma apreensão validável (objeto/dados) no ledger? (CPP art. 178.º/6)."""
    return any(t in SEIZURE_GENESIS_EVENTS for t in prior_types)


def validation_done(prior_types):
    """A apreensão já foi validada? (só pode ser validada uma vez — CPP art. 178.º/6)."""
    return EventType.VALIDACAO_APREENSAO in prior_types


def despacho_done(prior_types):
    """Há um DESPACHO_PERICIA prévio no ledger? (CPP Art. 154.º/158.º)."""
    return EventType.DESPACHO_PERICIA in prior_types


def is_in_transit(prior_types):
    """A prova está em trânsito? (último evento = encaminhamento, ADR-0016 v2)."""
    return bool(prior_types) and prior_types[-1] == EventType.ENCAMINHAMENTO_CUSTODIA


def lab_gate_blocks(custodian_type, prior_types):
    """O gate de laboratório bloqueia este evento? (CPP Art. 154.º).

    Entregar prova a um laboratório (custódio LAB_*) exige um DESPACHO_PERICIA já
    no ledger — não se aplica à génese (1.º evento, sem prior).
    """
    return (
        bool(prior_types)
        and custodian_type in LAB_CUSTODIANS
        and not despacho_done(prior_types)
    )


def next_events(prior_types, *, has_parent=False, is_digital_file=False):
    """Os ``EventType`` que as guardas de transição aceitam como PRÓXIMO evento.

    Fonte única (ADR-0019 §3): o ``clean()`` valida com as mesmas guardas/predicados
    e o frontend oferece exatamente esta lista. Espelha só as regras BLOQUEANTES por
    eixo de ``event_type`` (não as de campo — portador/GPS — nem o gate de
    laboratório, que depende do custódio escolhido na receção/movimentação). A
    ordem segue a declaração de ``EventType``.

    - ledger vazio → só a génese aplicável à proveniência;
    - há terminal → nenhum;
    - em trânsito (último = encaminhamento) → só a receção;
    - caso geral: exclui a génese (só na posição 1), a movimentação legado e a
      receção fora de trânsito; ``VALIDACAO_APREENSAO`` exige apreensão prévia e
      ainda não validada; ``INICIO_PERICIA`` exige despacho prévio.
    """
    if not prior_types:
        return [genesis_event_for(has_parent=has_parent, is_digital_file=is_digital_file)]
    if ledger_has_terminal(prior_types):
        return []
    if is_in_transit(prior_types):
        return [EventType.RECEPCAO_CUSTODIA]
    out = []
    for et in EventType:
        if et in GENESIS_EVENTS:
            continue  # génese só na posição 1
        if et in LEGACY_MOVE_EVENTS:
            continue  # movimentação legado já não é oferecida
        if et == EventType.RECEPCAO_CUSTODIA:
            continue  # só fecha um encaminhamento em curso (tratado acima)
        if et == EventType.VALIDACAO_APREENSAO and (
            not has_prior_seizure(prior_types) or validation_done(prior_types)
        ):
            continue
        if et == EventType.INICIO_PERICIA and not despacho_done(prior_types):
            continue
        out.append(et)
    return out
