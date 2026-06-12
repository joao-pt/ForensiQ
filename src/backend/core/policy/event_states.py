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

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# Prazo legal de validação da apreensão (CPP art. 178.º/6; default 72h via
# settings) — fonte ÚNICA da regra processual (auditoria D50): o ledger
# (flag validation_overdue em core.models) e o SLA (core.analytics) importam
# daqui em vez de redefinirem a constante.
VALIDATION_DEADLINE = timedelta(hours=settings.VALIDATION_DEADLINE_HOURS)

# Antecedência do AVISO «validação a vencer» (parâmetro operacional em
# settings, como PERICIA_DEADLINE_WARNING_DAYS). O «a vencer» é um recorte
# etário do 'por_validar' — NUNCA um estatuto novo de validation_status (o
# vocabulário é contrato da API e dos badges); o recorte de IDs vive em
# core.analytics.aging_sla, como o «em atraso» já vive.
VALIDATION_DEADLINE_WARNING = timedelta(hours=settings.VALIDATION_DEADLINE_WARNING_HOURS)


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


class ReceiverDocType(models.TextChoices):
    """Documento de identificação de quem RECEBE a prova fora do sistema
    (restituição — CPP art. 186.º, termo de entrega — ou entrega a depositário
    particular). Vocabulário do ledger: o valor entra CRU na fórmula de hash
    (hv3), pelo que os códigos são contrato irreversível."""

    CC = 'CC', 'Cartão de Cidadão'
    PASSAPORTE = 'PASSAPORTE', 'Passaporte'
    OUTRO = 'OUTRO', 'Outro documento'


# Pares (slug, rótulo) PARTILHADOS entre o eixo do custódio (CustodianType) e
# o tipo de instituição (InstitutionType, em core.models) — fonte ÚNICA dos
# rótulos (auditoria D33): um rótulo novo/alterado edita-se SÓ aqui; o mapa
# CUSTODIAN_TYPE_BY_INSTITUTION (custody_transitions) deriva as chaves daqui.
SHARED_CUSTODIAN_PAIRS = {
    'OPC': 'Órgão de polícia criminal',
    'LAB_PUBLICO': 'Laboratório público',
    'LAB_PRIVADO': 'Laboratório privado',
    'TRIBUNAL': 'Tribunal',
    'DEPOSITARIO': 'Depositário',
}


class CustodianType(models.TextChoices):
    """Quem detém a prova APÓS o evento (eixo ortogonal ao event_type).

    Os pares comuns com ``InstitutionType`` vêm de SHARED_CUSTODIAN_PAIRS;
    LOCAL_CRIME/PROPRIETARIO são próprios deste eixo (não são instituições)."""

    LOCAL_CRIME = 'LOCAL_CRIME', 'Local do crime'
    OPC = 'OPC', SHARED_CUSTODIAN_PAIRS['OPC']
    LAB_PUBLICO = 'LAB_PUBLICO', SHARED_CUSTODIAN_PAIRS['LAB_PUBLICO']
    LAB_PRIVADO = 'LAB_PRIVADO', SHARED_CUSTODIAN_PAIRS['LAB_PRIVADO']
    TRIBUNAL = 'TRIBUNAL', SHARED_CUSTODIAN_PAIRS['TRIBUNAL']
    DEPOSITARIO = 'DEPOSITARIO', SHARED_CUSTODIAN_PAIRS['DEPOSITARIO']
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

# ATOS de autoridade CERTIFICADOS (CPP art. 178.º/5-6 e 154.º): a validação da
# apreensão e o despacho para perícia são atos jurídicos, não deslocações — o
# evento identifica QUEM os proferiu em campos ESTRUTURADOS do ledger
# (``authority_nome``/``authority_cargo``, ``act_declared_at`` e, no despacho,
# ``act_deadline_days``), que entram na fórmula do hash (hv4 — ADR-0013). A
# guarda vive no ``clean()`` do modelo (``_clean_authority``: obrigatórios nos
# atos certificados, recusados como identidade órfã nos restantes eventos) e
# vale em todas as fronteiras de escrita (UI, API, cascade). O modal único da
# ocorrência só recolhe os campos. Fonte única do conjunto.
CERTIFIED_ACT_EVENTS = frozenset(
    {EventType.VALIDACAO_APREENSAO, EventType.DESPACHO_PERICIA}
)

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

        a_guarda_opc | em_pericia | pericia_concluida |
        em_transito | encaminhada | restituida | perdida_favor_estado | destruida

    Este eixo descreve SÓ a custódia/localização da prova (em mãos de quem está,
    em que fase de movimentação/perícia). Os ATOS jurídicos que não deslocam a
    prova — apreensão e validação da apreensão (CPP art. 178.º) — não são estados:
    ficam no ledger e derivam-se à parte (:func:`validation_status`). Misturar os
    dois eixos fazia a etiqueta "validada" desaparecer quando o item viajava.

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
    - DESPACHO_PERICIA/VALIDACAO_APREENSAO/génese como último → ``a_guarda_opc``
      (a prova não se moveu; o despacho/validação são atos, não deslocações).
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

    # DESPACHO_PERICIA / VALIDACAO_APREENSAO / génese como último: a prova não se
    # moveu — continua à guarda do OPC (a validação deriva-se no OUTRO eixo).
    return 'a_guarda_opc'


# Conjunto canónico de estados legais derivados (para validação de filtros).
LEGAL_STATES = frozenset(
    {
        'a_guarda_opc',
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

# Estados legais em que a prova já está (ou já passou) no destino do handoff —
# encaminhada/recebida, em perícia ou além, incluindo os terminais. Do ponto de
# vista do intake/receção, "já recebida": não volta a ser oferecida para receção.
# Subconjunto de LEGAL_STATES.
STATES_AT_OR_PAST_LAB = (
    frozenset({'encaminhada', 'em_pericia', 'pericia_concluida'}) | TERMINAL_LEGAL_STATES
)


# Disposição FINAL do item ao nível de EVENTO (restituição, destruição, perda a
# favor do Estado) — contraparte de TERMINAL_LEGAL_STATES no eixo dos eventos.
# Fonte única de quatro consumos: o critério de "concluído" do fluxo
# (``core.analytics``), a EXTINÇÃO de uma validação pendente — encerrada a
# custódia ou decidido o destino legal, deixa de haver apreensão mantida para
# validar (CPP art. 178.º) —, a extinção POSICIONAL do prazo da perícia
# (``pericia_deadline``) e a extinção da paragem aberta do dwell
# (``core.analytics.custody_dwell``).
DISPOSAL_EVENTS = TERMINAL_EVENTS | {EventType.PERDA_FAVOR_ESTADO}


def validation_status(eventos_ordenados, now):
    """Estatuto da VALIDAÇÃO da apreensão — eixo ORTOGONAL ao estado de custódia.

    A validação (CPP art. 178.º/6, prazo de 72h em ``VALIDATION_DEADLINE``) é um
    ato jurídico, não uma deslocação: não muda quem detém a prova nem onde está.
    Por isso não entra em :func:`derive_legal_state`; deriva-se aqui, sempre do
    ledger (nunca guardado), e apresenta-se como atributo próprio do item.

    Recebe os registos ``ChainOfCustody`` ordenados por sequence e o instante de
    referência ``now`` (passado pelo chamador — função pura) e devolve:

    - ``None`` — não aplicável: sem génese de apreensão (ex.: item autonomizado
      no laboratório, que herda a base legal do item-pai), ou exigência extinta
      por um evento de ``DISPOSAL_EVENTS`` sem validação registada;
    - ``'validada'`` — existe VALIDACAO_APREENSAO no ledger (valida-se uma vez;
      o registo fora de prazo fica assinalado no próprio evento);
    - ``'em_atraso'`` — apreensão há mais de ``VALIDATION_DEADLINE`` sem validação;
    - ``'por_validar'`` — apreensão dentro do prazo, validação ainda por registar.
    """
    seizure = seizure_of(eventos_ordenados)
    if seizure is None:
        return None
    tipos = [r.event_type for r in eventos_ordenados]
    if EventType.VALIDACAO_APREENSAO in tipos:
        return 'validada'
    if any(t in DISPOSAL_EVENTS for t in tipos):
        return None
    if now > validation_due_at(seizure.timestamp):
        return 'em_atraso'
    return 'por_validar'


def seizure_of(eventos_ordenados):
    """O evento de APREENSÃO que constitui a génese validável do item
    (``SEIZURE_GENESIS_EVENTS``), ou ``None``.

    Fonte única do lookup partilhado pelo estatuto (:func:`validation_status`),
    pela guarda do modelo (``_clean_validacao``) e pela consulta dos atos.
    """
    return next(
        (r for r in eventos_ordenados if r.event_type in SEIZURE_GENESIS_EVENTS),
        None,
    )


def validation_due_at(seizure_at):
    """Limite legal da validação da apreensão: instante da apreensão +
    ``VALIDATION_DEADLINE`` (CPP art. 178.º/6).

    Fonte única da fórmula — prazo em HORAS, aritmética de INSTANTES (ao
    contrário do prazo da perícia, que se conta em dias de calendário): o
    estatuto (:func:`validation_status`), a flag do registo
    (:func:`validation_acted_late`) e a consulta dos atos comparam todos
    contra ESTE instante.
    """
    return seizure_at + VALIDATION_DEADLINE


def validation_acted_late(seizure_at, acted_at):
    """O ato de validação foi praticado FORA do prazo legal (CPP art. 178.º/6)?

    Compara o instante do ato contra :func:`validation_due_at` — usada pela
    flag ``validation_overdue`` do modelo (no registo do evento — facto
    relevante, não bloqueia) e pela consulta dos atos (releitura de eventos
    históricos do ledger, onde a flag não está persistida). Pura: recebe os
    dois instantes, devolve bool.
    """
    return acted_at > validation_due_at(seizure_at)


# Conjunto canónico dos estatutos de validação deriváveis (sem o ``None``).
VALIDATION_STATUSES = frozenset({'validada', 'em_atraso', 'por_validar'})

# Estatutos que representam TRABALHO PENDENTE de validação — alimentam o tile
# do painel, os marcadores por linha das grelhas e o botão da ocorrência.
VALIDATION_PENDING_STATUSES = frozenset({'por_validar', 'em_atraso'})


# Antecedência (dias) com que a data-limite da perícia passa a "a vencer" —
# parâmetro operacional (settings, env override), não regra legal: o prazo em
# si é o fixado em cada despacho (``act_deadline_days``, hv4).
PERICIA_DEADLINE_WARNING_DAYS = settings.PERICIA_DEADLINE_WARNING_DAYS


def pericia_due_date(despacho):
    """Data-limite da perícia derivada de UM evento de despacho (hv4) — uma
    DATA de calendário (``datetime.date``) no fuso ativo.

    Fonte única da fórmula «data declarada do ato + prazo em dias». O prazo
    legal conta-se em DIAS, não em instantes: a aritmética faz-se sobre a
    DATA local da declaração (somar ``timedelta`` ao instante desviava ±1 dia
    quando o intervalo atravessava uma transição de hora legal). A data
    juridicamente relevante é a DECLARADA pela autoridade
    (``act_declared_at``); o timestamp do servidor fica como fallback
    (mesmo critério da flag ``validation_overdue``). ``None`` sem prazo
    estruturado (eventos pré-hv4)."""
    if not despacho.act_deadline_days:
        return None
    base = despacho.act_declared_at or despacho.timestamp
    if base is None:
        return None
    return timezone.localtime(base).date() + timedelta(days=despacho.act_deadline_days)


def pericia_prazo_resolucao(eventos_ordenados):
    """O despacho VIGENTE e o evento que lhe RESOLVEU o prazo, se algum.

    Fonte única da regra POSICIONAL do eixo (CPP art. 154.º/158.º): vários
    despachos são possíveis e vale o ÚLTIMO; o prazo desse despacho deixa de
    correr com o primeiro evento posterior que o resolve — CONCLUSAO_PERICIA
    (cumprido) ou uma disposição final de ``DISPOSAL_EVENTS`` (extinto) — e
    um despacho registado DEPOIS reabre o eixo (a PERDA_FAVOR_ESTADO não
    fecha o ledger; o prazo desse despacho não pode vencer em silêncio).

    Recebe os registos ordenados por sequence e devolve ``(despacho,
    resolucao)``: ``(None, None)`` sem despacho; ``resolucao`` a ``None``
    com o prazo vivo. :func:`pericia_deadline` deriva o estatuto daqui; a
    consulta dos atos mostra a RAZÃO (o próprio evento resolutor).
    """
    despacho = None
    resolucao = None
    for r in eventos_ordenados:
        if r.event_type == EventType.DESPACHO_PERICIA:
            despacho, resolucao = r, None
        elif despacho is not None and resolucao is None and (
            r.event_type == EventType.CONCLUSAO_PERICIA
            or r.event_type in DISPOSAL_EVENTS
        ):
            resolucao = r
    return despacho, resolucao


def pericia_deadline(eventos_ordenados, now):
    """Prazo da perícia ordenada por despacho — eixo derivado do ledger.

    O despacho fixa um prazo em dias para a CONCLUSÃO da perícia (CPP art.
    154.º; ``act_deadline_days``, hv4). Como a validação, é um estatuto
    derivado, nunca guardado: recebe os registos ``ChainOfCustody`` ordenados
    por sequence e o instante de referência ``now`` (função pura) e devolve
    ``None`` ou ``{'due': date, 'status': str, 'days_left': int}``.

    - ``None`` — não aplicável: sem despacho, prazo do último despacho já
      RESOLVIDO (cumprido/extinto — regra posicional em
      :func:`pericia_prazo_resolucao`), ou despacho sem prazo estruturado
      (pré-hv4);
    - ``status`` — ``'vencida'`` (a data-limite já passou), ``'a_vencer'``
      (faltam ≤ ``PERICIA_DEADLINE_WARNING_DAYS`` dias) ou ``'em_prazo'``.

    O prazo conta-se em DIAS de calendário no fuso ativo: vence no FIM do dia
    da data-limite (comparação por data, não por instante), coerente com a
    contagem processual de prazos em dias e com a data mostrada nos badges.
    ``days_left`` é a diferença em dias (negativa quando vencida).
    """
    despacho, resolucao = pericia_prazo_resolucao(eventos_ordenados)
    if despacho is None or resolucao is not None:
        return None
    due = pericia_due_date(despacho)
    if due is None:
        return None
    days_left = (due - timezone.localtime(now).date()).days
    if days_left < 0:
        status = 'vencida'
    elif days_left <= PERICIA_DEADLINE_WARNING_DAYS:
        status = 'a_vencer'
    else:
        status = 'em_prazo'
    return {'due': due, 'status': status, 'days_left': days_left}


# Conjunto canónico dos estatutos do prazo da perícia (sem o ``None``).
PERICIA_DEADLINE_STATUSES = frozenset({'em_prazo', 'a_vencer', 'vencida'})

# Estatutos que pedem ATENÇÃO do utilizador — alimentam os marcadores por
# linha das grelhas e as linhas de "Prazos & atenção" (painel e /stats/).
PERICIA_ATTENTION_STATUSES = frozenset({'a_vencer', 'vencida'})
