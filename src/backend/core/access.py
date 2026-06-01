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
    if has_national_read(user):
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
    if has_national_read(user):
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
    if has_national_read(user):
        return qs
    return qs.filter(evidence__in=scope_evidences(user).values('pk'))


# ---------------------------------------------------------------------------
# Permissões object-level (LEITURA)
# ---------------------------------------------------------------------------


def can_view_evidence(user, evidence):
    """Pode LER este item + cadeia? (object-level — ADR-0017 §5)."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if has_national_read(user):
        return True
    if evidence.agent_id == user.id or evidence.occurrence.agent_id == user.id:
        return True
    inst_ids = set(_active_institution_ids(user))
    for rec in evidence.custody_chain.all():
        if rec.agent_id == user.id or rec.custodian_institution_id in inst_ids:
            return True
    return False


def can_access_occurrence(user, occurrence):
    """Pode aceder à OCORRÊNCIA inteira? (titular / NACIONAL / autoridade do caso)."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if has_national_read(user):
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
    if profile in READ_ONLY_PROFILES:
        return False
    if profile == User.Profile.FORENSIC_EXPERT and can_view_evidence(user, evidence):
        return True

    holder_user, holder_inst = current_holder(evidence)
    if holder_user is not None and holder_user == user.id:
        return True  # detém pessoalmente (recebeu em push)
    inst_ids = set(_active_institution_ids(user))
    if holder_user is None and holder_inst is not None and holder_inst in inst_ids:
        return True  # custódia institucional → membro pode assumir (claim/pull)
    if holder_user is None and holder_inst is None:
        # Génese: o titular/recolhedor abre a cadeia.
        if evidence.agent_id == user.id or evidence.occurrence.agent_id == user.id:
            return True
    if profile == User.Profile.CASE_AUTHORITY and event_type in CASE_AUTHORITY_EVENTS:
        if can_access_occurrence(user, evidence.occurrence):
            return True
    return False
