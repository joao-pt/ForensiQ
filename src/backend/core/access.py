"""
ForensiQ — Controlo de acesso *need-to-know* derivado do ledger (ADR-0017).

Dois eixos: **função** (``User.profile``) e **credencial** (``User.clearance``).
O acesso de LEITURA segue a cadeia de custódia ao nível do ITEM (ReBAC mínimo
derivado do ledger append-only — o ledger É o grafo custódio↔item); o acesso de
ESCRITA segue quem **detém** o item. Este módulo é a fonte única das regras de
scoping/permissão e substitui o modelo estático «agente vê as suas / perito vê
tudo».

A autoridade do caso (MP) é **derivada do ledger** (a instituição do serviço do
MP que aparece na cadeia), pois a ``Occurrence`` é imutável e não admite um campo
de atribuição mutável (ADR-0017 §6b — ponto materializado por derivação).
"""

import contextlib

from django.db.models import Q

from core.models import ChainOfCustody, Evidence, Occurrence, ProvaEmTransito, User

# Atos de despacho que a autoridade do caso (MP) pode praticar (ADR-0017 §5).
CASE_AUTHORITY_EVENTS = frozenset(
    {
        'VALIDACAO_APREENSAO',
        'DESPACHO_PERICIA',
        'RESTITUICAO',
        'PERDA_FAVOR_ESTADO',
    }
)

# Papéis só-leitura: nunca escrevem (ADR-0017 §5).
READ_ONLY_PROFILES = frozenset({User.Profile.CHEFE_SERVICO, User.Profile.AUDITOR})


# ---------------------------------------------------------------------------
# Pertenças e credencial
# ---------------------------------------------------------------------------


def _active_institution_ids(user):
    """IDs das instituições ativas a que o utilizador pertence.

    Memoizado na instância do utilizador para não repetir a query nos vários pontos
    que a chamam no mesmo render (``lens_nav`` e ``inbound_nav`` nos context
    processors, scopes nas views). Como ``request.user`` vive um único pedido, o
    cache é, na prática, por-pedido — e as pertenças não mudam a meio de um render.
    Recai na query se a instância não aceitar o atributo (ex.: ``AnonymousUser``).
    """
    if not getattr(user, 'is_authenticated', False):
        return []
    cached = getattr(user, '_fq_active_institution_ids', None)
    if cached is not None:
        return cached
    ids = list(
        user.institution_memberships.filter(is_active=True).values_list(
            'institution_id', flat=True
        )
    )
    with contextlib.suppress(AttributeError, TypeError):
        user._fq_active_institution_ids = ids
    return ids


def has_national_read(user):
    """Tem visibilidade nacional de leitura? (credencial NACIONAL ou staff)."""
    return bool(
        getattr(user, 'is_staff', False)
        or getattr(user, 'clearance', None) == User.Clearance.NACIONAL
    )


def _profile(user):
    return getattr(user, 'profile', None)


def has_full_read(user):
    """Leitura TOTAL — toda a prova e todos os processos.

    Inclui a leitura nacional (staff / credencial NACIONAL) e — por decisão do
    dono (2026-06-05) — o PERITO FORENSE: um perito pode ser questionado sobre
    processos de outras áreas/divisões, pelo que tem acesso de leitura a toda a
    prova e processos por FUNÇÃO, independentemente da credencial. É uma exceção
    explícita ao princípio geral do ADR-0017 («a credencial governa a leitura»):
    a função de perito é, ela própria, habilitante para leitura total. A ESCRITA
    continua governada por :func:`can_append_custody` (quem detém / override do
    perito / despacho da autoridade do caso).
    """
    return has_national_read(user) or _profile(user) == User.Profile.FORENSIC_EXPERT


# ---------------------------------------------------------------------------
# Scoping de LEITURA (querysets)
# ---------------------------------------------------------------------------


def scope_evidences(user, base_qs=None):
    """Evidências que o utilizador pode LER — *need-to-know* item-level (ADR-0017 §5).

    Verdadeiro (item visível) se: credencial NACIONAL · titular/recolhedor ·
    teve custódia (foi ``agent`` de algum evento) · membro de instituição que é/foi
    ``custodian_institution`` num evento · autoridade do caso (serviço do MP no ledger).
    """
    qs = Evidence.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    if has_full_read(user):
        return qs
    inst_ids = _active_institution_ids(user)
    cond = Q(agent=user) | Q(occurrence__agent=user) | Q(custody_chain__agent=user)
    if inst_ids:
        cond |= Q(custody_chain__custodian_institution_id__in=inst_ids)
    return qs.filter(cond).distinct()


def scope_occurrences(user, base_qs=None):
    """Ocorrências que o utilizador pode LER (âmbito de ocorrência, mais amplo).

    Reservado ao titular, à credencial nacional e à autoridade do caso. Quem só
    teve custódia de um item vê o item + cadeia, NÃO a ocorrência inteira
    (*least privilege* — ADR-0017 §5).
    """
    qs = Occurrence.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    if has_full_read(user):
        return qs
    cond = Q(agent=user)
    inst_ids = _active_institution_ids(user)
    if _profile(user) == User.Profile.CASE_AUTHORITY and inst_ids:
        # Autoridade do caso: ocorrências em que o seu serviço (MP) aparece no
        # ledger (derivação do §6b sem mutar a Occurrence imutável).
        cond |= Q(evidences__custody_chain__custodian_institution_id__in=inst_ids)
    return qs.filter(cond).distinct()


def scope_custody(user, base_qs=None):
    """Eventos de custódia dos itens que o utilizador pode LER."""
    qs = ChainOfCustody.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    if has_full_read(user):
        return qs
    return qs.filter(evidence__in=scope_evidences(user).values('pk'))


# ---------------------------------------------------------------------------
# Ramo custodial (item-level) — primitiva de âmbito por DETENÇÃO/custódia.
# Nota: a consola v2 (duas zonas) já não a expõe como "lente"; mantém-se como
# primitiva reutilizável (API/futuras vistas) e é coberta por testes.
# ---------------------------------------------------------------------------


def scope_evidences_custodial(user, base_qs=None):
    """Itens à guarda do utilizador/instituição — ramo *custodial* de
    :func:`scope_evidences`, isolado por DETENÇÃO/custódia.

    Visível só se o utilizador detém/deteve o item (foi ``agent`` de um evento)
    ou a sua instituição é/foi ``custodian_institution``. É um **subconjunto
    estrito** de :func:`scope_evidences`: usa as mesmas condições do ramo
    custodial, SEM o curto-circuito ``has_full_read`` — um perito (leitura total)
    que não detém nada vê este âmbito VAZIO (mostra o que detém, não tudo).

    Sem chamador de produção desde a consola v2 (a antiga lente "À guarda" foi
    removida); retida como primitiva de âmbito (API/testes), não morta.
    """
    qs = Evidence.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    inst_ids = _active_institution_ids(user)
    cond = Q(custody_chain__agent=user)
    if inst_ids:
        cond |= Q(custody_chain__custodian_institution_id__in=inst_ids)
    return qs.filter(cond).distinct()


def scope_custody_custodial(user, base_qs=None):
    """Eventos de custódia dos itens à guarda do utilizador/instituição
    (espelha :func:`scope_custody` sobre o subconjunto custodial)."""
    qs = ChainOfCustody.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    return qs.filter(evidence__in=scope_evidences_custodial(user).values('pk'))


def scope_inbound_transit(user, base_qs=None):
    """Provas a chegar À INSTITUIÇÃO do utilizador (caixa-de-entrada — ADR-0016 v2).

    Avisos ``ProvaEmTransito`` por reconhecer cuja ``destino_institution`` é uma
    instituição ativa do utilizador. É institucional por natureza: SEM
    curto-circuito ``has_full_read`` (um perito com leitura total mas sem
    pertença não tem nada *a chegar*) e SEM ramo pessoal — chaveia no DESTINO
    (para onde a prova vai), não no detentor atual.
    """
    qs = ProvaEmTransito.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    inst_ids = _active_institution_ids(user)
    if not inst_ids:
        return qs.none()
    return qs.filter(destino_institution_id__in=inst_ids, acknowledged_at__isnull=True)


def has_inbound_for_occurrence(user, occurrence):
    """O utilizador tem prova A CHEGAR (encaminhamento pendente) NESTA ocorrência?

    Verdadeiro se algum aviso ``ProvaEmTransito`` por reconhecer desta ocorrência
    tem por destino uma instituição ativa do utilizador — i.e. o item aparece na
    caixa "prova a chegar" dele. É a porta de LEITURA da receção (quem pode ABRIR o
    formulário de intake), alinhada com :func:`scope_inbound_transit` (mesma regra,
    restrita a uma ocorrência). A ESCRITA da receção continua governada por
    :func:`can_append_custody` no serializer — esta porta não a substitui.
    """
    if occurrence is None:
        return False
    inst_ids = _active_institution_ids(user)
    if not inst_ids:
        return False
    return ProvaEmTransito.objects.filter(
        evidence__occurrence=occurrence,
        destino_institution_id__in=inst_ids,
        acknowledged_at__isnull=True,
    ).exists()


def scope_occurrences_institutional(user, base_qs=None):
    """Ocorrências DA INSTITUIÇÃO do utilizador — a zona "Instituição" da consola.

    A instituição é DONA do processo: vê a ocorrência INTEIRA (sem filtro por
    item) sempre que QUALQUER item dela passou — ou está — pela custódia de uma
    instituição ativa do utilizador. SEM curto-circuito ``has_full_read`` e SEM
    ramo pessoal (titularidade): chaveia só na pertença institucional. Devolve
    ``none()`` se o utilizador não pertence a nenhuma instituição (a zona só
    existe para membros). É, deliberadamente, uma AMPLIAÇÃO de leitura por modo
    (processo inteiro), ortogonal à ESCRITA — que continua governada por
    :func:`can_append_custody`.
    """
    qs = Occurrence.objects.all() if base_qs is None else base_qs
    if not getattr(user, 'is_authenticated', False):
        return qs.none()
    inst_ids = _active_institution_ids(user)
    if not inst_ids:
        return qs.none()
    return qs.filter(
        evidences__custody_chain__custodian_institution_id__in=inst_ids
    ).distinct()


# ---------------------------------------------------------------------------
# Consola (duas zonas) — seletor de WORKING-SET de LEITURA exposto na UI
# ---------------------------------------------------------------------------


class Lens:
    """Zonas da CONSOLA — substituem a antiga lente de 3 eixos por papel.

    A consola é um seletor de *working-set* de leitura (qual fatia do universo
    acessível mostrar como vista de trabalho), NÃO uma fronteira de acesso — essa
    é imposta sempre por ``scope_*``/``can_*``. Tem duas zonas:

    - ``MINE`` — "as minhas": o âmbito de caso pessoal (:func:`scope_occurrences`).
      Para quem tem leitura total devolve TUDO, por função/credencial (ADR-0017) —
      o rótulo do chip reflete-o (ver :func:`mine_label`). É a vista-base (home).
    - ``INSTITUTION`` — "Instituição": TODAS as ocorrências da(s) instituição(ões)
      do utilizador, PROCESSO INTEIRO sem filtro por item
      (:func:`scope_occurrences_institutional`) — a instituição é dona do
      processo. Só disponível a membros; ao entrar, a UI muda de cor ("modo
      Instituição").

    Substitui a antiga ``CUSTODY`` (eixo de item, removida para não filtrar por item) e ``ALL`` (a leitura total deixa de
    ser um chip; quem a tem vê-a já na zona "as minhas").
    """

    MINE = 'mine'
    INSTITUTION = 'institution'


VALID_LENSES = frozenset({Lens.MINE, Lens.INSTITUTION})

# Ordem fixa de apresentação das zonas.
_LENS_ORDER = (Lens.MINE, Lens.INSTITUTION)

# Chave de memória da zona ativa na sessão (a navegação mantém o modo sem repetir
# o ``?lens=`` em cada link).
CONSOLE_SESSION_KEY = 'console_mode'


def can_use_lens(user, lens):
    """A zona da consola é utilizável pelo utilizador? (gate server-side).

    ``MINE`` está sempre disponível a quem está autenticado (é a vista-base).
    ``INSTITUTION`` ⟺ o utilizador pertence a pelo menos uma instituição ativa.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if lens == Lens.MINE:
        return True
    if lens == Lens.INSTITUTION:
        return bool(_active_institution_ids(user))
    return False


def available_lenses(user):
    """Zonas utilizáveis pelo utilizador, em ordem fixa de apresentação. Quem não
    pertence a nenhuma instituição só tem ``MINE`` (a UI esconde o seletor)."""
    return [lens for lens in _LENS_ORDER if can_use_lens(user, lens)]


def default_lens(user):
    """Zona inicial. Para a generalidade dos perfis é "as minhas" (a vista-base/
    home; a zona Instituição é uma escolha explícita que muda a cor da página).

    Exceção: os perfis SÓ-LEITURA de supervisão (CHEFE_SERVICO/AUDITOR) nunca são
    titulares de casos — a sua "as minhas" seria estruturalmente vazia —, pelo que
    arrancam na zona Instituição (oversight) quando pertencem a uma instituição.
    Sem pertença nem leitura total, ``MINE`` é o que resta (vista honestamente
    vazia de quem não tem âmbito atribuído).
    """
    if _profile(user) in READ_ONLY_PROFILES and can_use_lens(user, Lens.INSTITUTION):
        return Lens.INSTITUTION
    return Lens.MINE


def mine_label(user):
    """Rótulo HONESTO da zona "as minhas": quem tem leitura total vê de facto
    TODAS as ocorrências nesta zona (por função/credencial — ADR-0017), pelo que
    o chip diz "Todas"; os restantes veem só as suas."""
    return 'Todas as ocorrências' if has_full_read(user) else 'As minhas ocorrências'


def resolve_lens(user, requested):
    """Resolve a zona pedida pelo cliente (query param ou memória de sessão)
    contra o que o utilizador pode usar. Valor inválido/proibido/ausente →
    :func:`default_lens` (fallback silencioso). Aceita os valores antigos
    (``custody``/``all``): não estão em :data:`VALID_LENSES`, pelo que caem
    silenciosamente em ``MINE``.
    """
    if requested in VALID_LENSES and can_use_lens(user, requested):
        return requested
    return default_lens(user)


def console_mode(request, user):
    """Zona ativa da consola para este pedido: ``?lens=`` explícito → senão a
    memória de sessão → senão a default — sempre validada contra o utilizador.

    Não escreve a sessão (ver :func:`remember_console_mode`); é segura em qualquer
    request, mesmo sem ``SessionMiddleware`` (degrada para ``?lens=``/default).
    """
    requested = request.GET.get('lens')
    if requested is None:
        session = getattr(request, 'session', None)
        if session is not None:
            requested = session.get(CONSOLE_SESSION_KEY)
    return resolve_lens(user, requested)


def remember_console_mode(request, mode):
    """Memoriza a zona na sessão quando o pedido trouxe um ``?lens=`` EXPLÍCITO que
    foi de facto HONRADO (a navegação seguinte mantém o modo sem repetir o param).

    Só persiste se o valor pedido é uma zona válida, utilizável, e igual ao ``mode``
    resolvido — um valor legado/proibido (``?lens=custody`` ou ``institution`` sem
    pertença, que :func:`console_mode` rebaixa silenciosamente para ``MINE``) NÃO
    deve apagar a zona já lembrada. No-op sem sessão ou sem ``?lens=`` explícito."""
    requested = request.GET.get('lens')
    if requested is None or requested != mode or requested not in VALID_LENSES:
        return
    session = getattr(request, 'session', None)
    if session is not None:
        session[CONSOLE_SESSION_KEY] = mode


# ---------------------------------------------------------------------------
# Permissões object-level (LEITURA)
# ---------------------------------------------------------------------------


def can_view_evidence(user, evidence):
    """Pode LER este item + cadeia? (object-level — ADR-0017 §5)."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if has_full_read(user):
        return True
    if evidence.agent_id == user.id or evidence.occurrence.agent_id == user.id:
        return True
    inst_ids = set(_active_institution_ids(user))
    for rec in evidence.custody_chain.all():
        if rec.agent_id == user.id or rec.custodian_institution_id in inst_ids:
            return True
    return False


def is_occurrence_institutional(user, occurrence):
    """Object-level da zona "Instituição": o utilizador é MEMBRO de uma instituição
    que é/foi dona do processo (aparece como ``custodian_institution`` no ledger da
    ocorrência)? Espelha :func:`scope_occurrences_institutional` ao nível do objeto.

    NÃO é um predicado de ACESSO global (a API/serializers/verificação pública
    mantêm o need-to-know item-level do ADR-0017); é o gate de LEITURA da consola
    server-rendered — a instituição é dona do processo, vê-o inteiro nessa vista.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    inst_ids = _active_institution_ids(user)
    if not inst_ids:
        return False
    return ChainOfCustody.objects.filter(
        evidence__occurrence=occurrence,
        custodian_institution_id__in=inst_ids,
    ).exists()


def can_access_occurrence(user, occurrence):
    """Pode aceder à OCORRÊNCIA inteira? (titular / leitura total / autoridade do caso).

    Leitura total = staff, credencial NACIONAL ou perito forense (ver
    :func:`has_full_read`). É o predicado de acesso GLOBAL (API, guias PDF,
    verificação pública) — mantém o need-to-know do ADR-0017: um membro de
    instituição só vê a OCORRÊNCIA inteira por aqui se for a autoridade do caso
    (MP). O alargamento "processo inteiro da instituição" vive na consola
    server-rendered (ver :func:`is_occurrence_institutional`), não nesta porta.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if has_full_read(user):
        return True
    if occurrence.agent_id == user.id:
        return True
    if _profile(user) == User.Profile.CASE_AUTHORITY:
        return is_occurrence_institutional(user, occurrence)
    return False


# ---------------------------------------------------------------------------
# ESCRITA (registar evento de custódia)
# ---------------------------------------------------------------------------


def current_holder(evidence):
    """(custodian_user_id, custodian_institution_id) do ÚLTIMO evento do item.

    ``(None, None)`` se ainda não há eventos (génese por abrir).
    """
    last = (
        evidence.custody_chain.order_by('-sequence')
        .values('custodian_user_id', 'custodian_institution_id')
        .first()
    )
    if not last:
        return (None, None)
    return (last['custodian_user_id'], last['custodian_institution_id'])


def can_append_custody(user, evidence, event_type=None):
    """Pode registar um evento de custódia neste item? (ADR-0017 §5).

    Verdadeiro se: é o ``custodian_user`` atual (detém-no) · o item está em
    custódia institucional e é membro da instituição que o tem (claim) · é
    ``FORENSIC_EXPERT`` e vê o item (override operacional) · é ``CASE_AUTHORITY``
    e o evento é um ato de despacho num caso seu. ``CHEFE_SERVICO``/``AUDITOR``
    nunca escrevem.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    profile = _profile(user)
    # READ_ONLY (CHEFE_SERVICO/AUDITOR) NUNCA escrevem — verificado ANTES do bypass
    # de staff, senão um auditor/chefe que também tenha is_staff=True conseguiria
    # escrever (os campos profile e is_staff são ortogonais no modelo User).
    if profile in READ_ONLY_PROFILES:
        return False
    # Staff/superuser (sem perfil só-leitura) são operadores administrativos —
    # podem registar (ex.: intake de laboratório feito por staff).
    if getattr(user, 'is_staff', False):
        return True
    if profile == User.Profile.FORENSIC_EXPERT and can_view_evidence(user, evidence):
        return True

    holder_user, holder_inst = current_holder(evidence)
    if holder_user is not None and holder_user == user.id:
        return True  # detém pessoalmente (recebeu em push)
    inst_ids = set(_active_institution_ids(user))
    if holder_user is None and holder_inst is not None and holder_inst in inst_ids:
        return True  # custódia institucional → membro pode assumir (claim/pull)
    # Génese (o titular/recolhedor abre a cadeia): só quando não há detentor.
    if (
        holder_user is None
        and holder_inst is None
        and (evidence.agent_id == user.id or evidence.occurrence.agent_id == user.id)
    ):
        return True
    return (
        profile == User.Profile.CASE_AUTHORITY
        and event_type in CASE_AUTHORITY_EVENTS
        and can_access_occurrence(user, evidence.occurrence)
    )
