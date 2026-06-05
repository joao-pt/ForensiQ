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

from django.db.models import Q

from core.models import ChainOfCustody, Evidence, Occurrence, User

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
    """IDs das instituições ativas a que o utilizador pertence."""
    if not getattr(user, 'is_authenticated', False):
        return []
    return list(
        user.institution_memberships.filter(is_active=True).values_list(
            'institution_id', flat=True
        )
    )


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
# Ramo custodial (lente "À guarda da instituição") — item-level
# ---------------------------------------------------------------------------


def scope_evidences_custodial(user, base_qs=None):
    """Itens à guarda do utilizador/instituição — ramo *custodial* de
    :func:`scope_evidences`, isolado para a lente "À guarda da instituição".

    Visível só se o utilizador detém/deteve o item (foi ``agent`` de um evento)
    ou a sua instituição é/foi ``custodian_institution``. É um **subconjunto
    estrito** de :func:`scope_evidences`: usa as mesmas condições do ramo
    custodial, SEM o curto-circuito ``has_full_read`` — um perito (leitura total)
    que não detém nada vê esta lente VAZIA (mostra o que detém, não tudo).
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


# ---------------------------------------------------------------------------
# Lentes de acesso (consolas por papel) — eixos de LEITURA expostos na UI
# ---------------------------------------------------------------------------


class Lens:
    """Eixos de leitura que a UI expõe como "lente" (consolas por papel).

    Cada lente corresponde EXATAMENTE a um queryset que o backend impõe:

    - ``MINE`` — eixo de caso (:func:`scope_occurrences`): as minhas ocorrências.
    - ``CUSTODY`` — eixo de item (:func:`scope_evidences_custodial`): à guarda do
      meu serviço/de mim. É centrado em ITENS — não existe eixo institucional ao
      nível da ocorrência.
    - ``ALL`` — leitura total (só ``has_full_read``): toda a prova e processos.
    """

    MINE = 'mine'
    CUSTODY = 'custody'
    ALL = 'all'


VALID_LENSES = frozenset({Lens.MINE, Lens.CUSTODY, Lens.ALL})

# Ordem fixa de apresentação dos chips.
_LENS_ORDER = (Lens.MINE, Lens.CUSTODY, Lens.ALL)


def can_use_lens(user, lens):
    """O utilizador pode usar esta lente? (gate server-side).

    ``ALL`` ⟺ leitura total (``has_full_read``); ``MINE`` ⟺ autenticado e perfil
    não só-leitura (titular/operacional); ``CUSTODY`` ⟺ autenticado com perfil
    operacional. ``CHEFE_SERVICO``/``AUDITOR`` (só-leitura) não usam ``MINE``
    (não são titulares de casos).
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if lens == Lens.ALL:
        return has_full_read(user)
    profile = _profile(user)
    if lens == Lens.MINE:
        return profile is not None and profile not in READ_ONLY_PROFILES
    if lens == Lens.CUSTODY:
        return profile is not None
    return False


def available_lenses(user):
    """Lentes utilizáveis pelo utilizador, em ordem fixa de apresentação."""
    return [lens for lens in _LENS_ORDER if can_use_lens(user, lens)]


def default_lens(user):
    """Lente inicial do utilizador. A credencial amplia as lentes *disponíveis*,
    não muda o trabalho default (o eixo segue a FUNÇÃO). Garantidamente
    pertencente a :func:`available_lenses`.
    """
    profile = _profile(user)
    if profile == User.Profile.EVIDENCE_CUSTODIAN:
        preferred = Lens.CUSTODY
    elif profile in (User.Profile.FIRST_RESPONDER, User.Profile.CASE_AUTHORITY):
        preferred = Lens.MINE
    elif profile == User.Profile.FORENSIC_EXPERT:
        preferred = Lens.ALL
    elif profile in READ_ONLY_PROFILES:
        # Supervisão: leitura total se a credencial a permitir, senão o pouco que
        # o serviço tem à guarda.
        preferred = Lens.ALL if has_full_read(user) else Lens.CUSTODY
    else:
        # Staff/superuser sem perfil operacional.
        preferred = Lens.ALL
    if can_use_lens(user, preferred):
        return preferred
    available = available_lenses(user)
    return available[0] if available else Lens.MINE


def resolve_lens(user, requested):
    """Resolve a lente pedida pelo cliente (query param) contra o que o
    utilizador pode usar. Lente inválida/proibida/ausente → :func:`default_lens`
    (fallback silencioso — não vaza a existência do eixo).
    """
    if requested in VALID_LENSES and can_use_lens(user, requested):
        return requested
    return default_lens(user)


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


def can_access_occurrence(user, occurrence):
    """Pode aceder à OCORRÊNCIA inteira? (titular / leitura total / autoridade do caso).

    Leitura total = staff, credencial NACIONAL ou perito forense (ver
    :func:`has_full_read`).
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if has_full_read(user):
        return True
    if occurrence.agent_id == user.id:
        return True
    if _profile(user) == User.Profile.CASE_AUTHORITY:
        inst_ids = set(_active_institution_ids(user))
        if inst_ids and ChainOfCustody.objects.filter(
            evidence__occurrence=occurrence,
            custodian_institution_id__in=inst_ids,
        ).exists():
            return True
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
