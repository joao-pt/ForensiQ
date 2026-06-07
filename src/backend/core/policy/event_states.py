"""
ForensiQ — Política de domínio: vocabulário de eventos/custódios e derivação do
estado legal (ADR-0019).

Fonte ÚNICA das regras de lei/processo que classificam a custódia:

- o vocabulário processual (:class:`EventType`) e de detenção (:class:`CustodianType`);
- os conjuntos canónicos que ramificam por valor (génese, terminais, apreensão
  validável, custódios de laboratório, movimentação em dois tempos);
- a máquina de derivação :func:`derive_legal_state`, que traduz a sequência do
  ledger no estado legal do item.

Este módulo está no FUNDO do grafo de dependências: importa apenas o Django, NUNCA
``core.models``. É ``core.models`` que importa daqui e re-exporta os nomes, de modo
a que o ledger e as camadas a jusante (views, serializers, filtros, PDF) os usem
sem cópia própria. Assim a regra legal vive num só sítio, é testável sem ORM, e
nenhuma camada a pode contrariar (ver ``feedback_policy_single_source``; CPP
art. 154.º/158.º/178.º; ADR-0015/0016).
"""

from django.db import models


class EventType(models.TextChoices):
    """Acto processual registado em cada evento do ledger (ADR-0015/0016, CPP).

    Génese (1.º movimento) por proveniência (ADR-0016 §2):
    - ``APREENSAO_OBJETO`` — objeto físico apreendido (CPP art. 178.º).
    - ``APREENSAO_DADOS`` — dados adquiridos no terreno e copiados para suporte
      autónomo (Lei do Cibercrime art. 16.º/7-b); só para ``DIGITAL_FILE``.
    - ``DERIVACAO_ITEM`` — sub-componente autonomizado (em regra no laboratório);
      só para evidência com ``parent_evidence``.

    Movimentação em dois tempos (ADR-0016 — modelo de custódia v2):
    ``ENCAMINHAMENTO_CUSTODIA`` (a origem entrega a prova a um portador, com
    destino — a prova fica *em trânsito*, sem GPS) seguido de
    ``RECEPCAO_CUSTODIA`` (o destino confirma a chegada e ganha coordenadas). O
    portador entra na cadeia de hash como snapshot (ver :class:`Portador`).

    ``TRANSFERENCIA_CUSTODIA``/``ASSUNCAO_CUSTODIA`` são LEGADO (modelo de um só
    tempo): mantêm-se no enum para integridade de ledgers históricos, mas já
    não são oferecidos como próximo evento nem usados no seed novo.
    """

    # --- Génese (1.º movimento) ---
    APREENSAO_OBJETO = 'APREENSAO_OBJETO', 'Apreensão de objeto'
    APREENSAO_DADOS = 'APREENSAO_DADOS', 'Apreensão de dados informáticos'
    DERIVACAO_ITEM = 'DERIVACAO_ITEM', 'Autonomizado no laboratório'
    # --- Atos subsequentes ---
    VALIDACAO_APREENSAO = 'VALIDACAO_APREENSAO', 'Validação da apreensão'
    DESPACHO_PERICIA = 'DESPACHO_PERICIA', 'Despacho para perícia'
    INICIO_PERICIA = 'INICIO_PERICIA', 'Início de perícia'
    CONCLUSAO_PERICIA = 'CONCLUSAO_PERICIA', 'Conclusão de perícia'
    # --- Movimentação em dois tempos (ADR-0016 v2) ---
    ENCAMINHAMENTO_CUSTODIA = 'ENCAMINHAMENTO_CUSTODIA', 'Encaminhamento (em trânsito)'
    RECEPCAO_CUSTODIA = 'RECEPCAO_CUSTODIA', 'Receção'
    # --- Movimentação LEGADO (um só tempo; já não oferecida) ---
    TRANSFERENCIA_CUSTODIA = 'TRANSFERENCIA_CUSTODIA', 'Transferência de custódia'
    ASSUNCAO_CUSTODIA = 'ASSUNCAO_CUSTODIA', 'Assunção de custódia'
    RESTITUICAO = 'RESTITUICAO', 'Restituição'  # terminal
    PERDA_FAVOR_ESTADO = 'PERDA_FAVOR_ESTADO', 'Perda a favor do Estado'
    DESTRUICAO = 'DESTRUICAO', 'Destruição'  # terminal


class CustodianType(models.TextChoices):
    """Quem detém a prova APÓS o evento (eixo ortogonal ao event_type)."""

    LOCAL_CRIME = 'LOCAL_CRIME', 'Local do crime'
    OPC = 'OPC', 'Órgão de polícia criminal'
    LAB_PUBLICO = 'LAB_PUBLICO', 'Laboratório público'
    LAB_PRIVADO = 'LAB_PRIVADO', 'Laboratório privado'
    TRIBUNAL = 'TRIBUNAL', 'Tribunal'
    DEPOSITARIO = 'DEPOSITARIO', 'Depositário'
    PROPRIETARIO = 'PROPRIETARIO', 'Proprietário'


# Eventos que fecham o ledger — nenhum evento é aceite depois de um deles.
TERMINAL_EVENTS = {EventType.RESTITUICAO, EventType.DESTRUICAO}

# Eventos de génese (1.º movimento) — exatamente um, na posição 1 (ADR-0016 §2).
GENESIS_EVENTS = {
    EventType.APREENSAO_OBJETO,
    EventType.APREENSAO_DADOS,
    EventType.DERIVACAO_ITEM,
}

# Génese que constitui uma APREENSÃO validável (CPP art. 178.º/6; valida-se uma
# vez). A derivação de item (DERIVACAO_ITEM) não é uma apreensão autónoma.
SEIZURE_GENESIS_EVENTS = {EventType.APREENSAO_OBJETO, EventType.APREENSAO_DADOS}

# Custódios de laboratório. Gate (CPP Art. 154.º): um laboratório não admite
# prova — nem que seja para arquivo — sem um DESPACHO_PERICIA prévio no ledger.
LAB_CUSTODIANS = frozenset({CustodianType.LAB_PUBLICO, CustodianType.LAB_PRIVADO})

# Movimentação em dois tempos (ADR-0016 v2): encaminhar (em trânsito) → receber.
HANDOFF_EVENTS = frozenset(
    {EventType.ENCAMINHAMENTO_CUSTODIA, EventType.RECEPCAO_CUSTODIA}
)


def derive_legal_state(eventos_ordenados):
    """Estado legal DERIVADO da sequência de eventos (ADR-0015 §6).

    Função pura — única fonte das strings de estado em todo o backend
    (filtros, serializer, stats) e no frontend/CSS. Recebe a lista de
    registos ``ChainOfCustody`` de uma evidência **ordenada por sequence**
    e devolve uma de:

        a_guarda_opc | validada | em_pericia | pericia_concluida |
        em_transito | encaminhada | restituida | perdida_favor_estado | destruida

    O estado segue o ÚLTIMO acto relevante (a custódia é não-linear: várias
    perícias e encaminhamentos em ordem livre — CPP Art. 158.º), com duas
    excepções de presença: os terminais e a perda a favor do Estado.

    - último DESTRUICAO/RESTITUICAO → ``destruida``/``restituida`` (fecham).
    - existe PERDA_FAVOR_ESTADO (sem terminal posterior) → ``perdida_favor_estado``
      (estatuto legal forte; domina mesmo uma perícia em curso).
    - último INICIO_PERICIA → ``em_pericia``; último CONCLUSAO_PERICIA → ``pericia_concluida``.
    - último ENCAMINHAMENTO_CUSTODIA → ``em_transito`` (encaminhada, ainda não
      recebida — ADR-0016 v2); último RECEPCAO_CUSTODIA → ``a_guarda_opc`` se de
      volta ao OPC, senão ``encaminhada``.
    - último TRANSFERENCIA_CUSTODIA/ASSUNCAO_CUSTODIA (LEGADO) → ``a_guarda_opc`` se
      de volta ao OPC, senão ``encaminhada`` (lab/tribunal/depositário/proprietário).
    - DESPACHO_PERICIA/VALIDACAO_APREENSAO/génese como último → patamar atingido
      (``validada`` se já houve validação, senão ``a_guarda_opc``).
    """
    if not eventos_ordenados:
        return 'a_guarda_opc'

    tipos = [r.event_type for r in eventos_ordenados]
    ultimo = eventos_ordenados[-1]
    et = ultimo.event_type

    # Terminais (pelo último evento) fecham o ledger.
    if et == EventType.DESTRUICAO:
        return 'destruida'
    if et == EventType.RESTITUICAO:
        return 'restituida'

    # Perda a favor do Estado: estatuto legal forte — domina enquanto presente
    # (terminal posterior já tratado acima), incl. sobre uma perícia em curso.
    if EventType.PERDA_FAVOR_ESTADO in tipos:
        return 'perdida_favor_estado'

    # A partir daqui, o estado segue o ÚLTIMO acto relevante (não-linearidade).
    if et == EventType.INICIO_PERICIA:
        return 'em_pericia'
    if et == EventType.CONCLUSAO_PERICIA:
        return 'pericia_concluida'
    if et == EventType.ENCAMINHAMENTO_CUSTODIA:
        # Encaminhada mas ainda não recebida → em trânsito (ADR-0016 v2).
        return 'em_transito'
    if et in (
        EventType.RECEPCAO_CUSTODIA,
        EventType.TRANSFERENCIA_CUSTODIA,
        EventType.ASSUNCAO_CUSTODIA,
    ):
        # Receção / movimentação legado: de volta ao OPC = à guarda do OPC;
        # qualquer outro custódio = encaminhada.
        return 'a_guarda_opc' if ultimo.custodian_type == CustodianType.OPC else 'encaminhada'

    # DESPACHO_PERICIA / VALIDACAO_APREENSAO / génese como último: patamar atingido.
    if EventType.VALIDACAO_APREENSAO in tipos:
        return 'validada'
    return 'a_guarda_opc'


# Conjunto canónico de estados legais derivados (para validação de filtros).
LEGAL_STATES = frozenset(
    {
        'a_guarda_opc',
        'validada',
        'em_pericia',
        'pericia_concluida',
        'em_transito',
        'encaminhada',
        'restituida',
        'perdida_favor_estado',
        'destruida',
    }
)

# Estados legais TERMINAIS — o item esgotou o seu ciclo de custódia (restituído,
# perdido a favor do Estado ou destruído) e não admite mais eventos. Fonte única
# do conceito de "concluído"; a vista de Arquivo deriva daqui que uma ocorrência
# está arquivada (todos os itens em estado terminal). Subconjunto de LEGAL_STATES.
TERMINAL_LEGAL_STATES = frozenset(
    {
        'restituida',
        'perdida_favor_estado',
        'destruida',
    }
)
