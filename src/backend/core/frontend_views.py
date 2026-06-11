"""
ForensiQ — Views do frontend (server-side rendering de templates).

Estas views servem os templates HTML do frontend.
A autenticação e lógica de negócio são tratadas no frontend via JWT + API REST.

SEGURANÇA: as páginas protegidas verificam a presença de um token JWT válido
num cookie (definido pelo frontend após login). Isto impede que o HTML da
aplicação seja servido a utilizadores não autenticados, mesmo que os dados
sensíveis só sejam carregados via API.
"""

import json
import logging
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html
from rest_framework.exceptions import AuthenticationFailed, ValidationError as DRFValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError

from core import access, analytics, evidence_field_config, evidence_type_config, integrity
from core.audit import get_client_ip, log_access
from core.auth import JWTCookieAuthentication
from core.grid import GridColumn, grid_list_response, serialize_columns
from core.labels import (
    ACTION_CSS,
    ACTION_SHORT,
    LEGAL_STATE_CSS,
    LEGAL_STATE_LABELS,
    VALIDATION_STATUS_CSS,
    VALIDATION_STATUS_LABELS,
)
from core.list_filters import ColFilter
from core.models import (
    SEIZURE_GENESIS_EVENTS,
    STATES_AT_OR_PAST_LAB,
    TERMINAL_LEGAL_STATES,
    VALIDATION_PENDING_STATUSES,
    AuditLog,
    ChainOfCustody,
    CrimeCategoria,
    CrimeTipo,
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionType,
    Occurrence,
    Portador,
    ReceiverDocType,
)
from core.policy import custody_transitions
from core.utils import (
    get_user_display_name,
    legal_state_of,
    sort_custody_chain,
    validation_status_of,
)

logger = logging.getLogger(__name__)


class _ScopeView:
    """Objecto mínimo que expõe ``throttle_scope`` ao ``ScopedRateThrottle``.

    O ``ScopedRateThrottle`` do DRF lê o scope a partir de ``view.throttle_scope``;
    como ``public_verify_view`` é uma vista Django pura (não DRF), passamos este
    shim em vez de uma APIView.
    """

    def __init__(self, scope):
        self.throttle_scope = scope


def _throttle_public_verify(request):
    """Aplica o rate-limit do scope ``verify_public`` a uma vista Django pura.

    Reusa o ``ScopedRateThrottle`` do DRF (mesma família dos endpoints da API —
    ver ``views.ReverseGeocodeView`` / ``EvidenceIMEILookupView``) sobre o pedido
    Django, identificando o cliente por IP quando anónimo. Devolve ``True`` se o
    pedido é permitido; ``False`` se excedeu o limite (chamador devolve 429).
    """
    throttle = ScopedRateThrottle()
    return throttle.allow_request(request, _ScopeView('verify_public'))


# --- Anti-brute-force do /v/ : lockout por IP além do throttle por minuto ---
# O throttle (30/min) limita o ritmo; o lockout trava um atacante persistente:
# após muitos 404 consecutivos (tentativas de adivinhar o hash de 48 bits), o IP
# fica bloqueado por uma janela. Usa a cache (tabela forensiq_cache).
_VERIFY_FAIL_LIMIT = 20
_VERIFY_LOCK_SECONDS = 900  # 15 min


def _verify_is_locked(ip):
    from django.core.cache import cache

    return bool(ip) and bool(cache.get(f'verify_lock:{ip}'))


def _verify_register_fail(ip):
    from django.core.cache import cache

    if not ip:
        return
    n = (cache.get(f'verify_fail:{ip}') or 0) + 1
    cache.set(f'verify_fail:{ip}', n, _VERIFY_LOCK_SECONDS)
    if n >= _VERIFY_FAIL_LIMIT:
        cache.set(f'verify_lock:{ip}', True, _VERIFY_LOCK_SECONDS)


def _verify_clear_fails(ip):
    from django.core.cache import cache

    if ip:
        cache.delete(f'verify_fail:{ip}')


def _user_from_jwt_cookie(request):
    """Utilizador autenticado pelo cookie JWT, ou ``None`` (token ausente,
    inválido ou expirado). Fonte única da descodificação —
    :class:`core.auth.JWTCookieAuthentication` — consumida pelo decorator
    :func:`jwt_cookie_user` e pelo ramo de auth OPCIONAL do ``/v/``
    (auditoria D12)."""
    try:
        result = JWTCookieAuthentication().authenticate(request)
    except (TokenError, AuthenticationFailed):
        return None
    return result[0] if result else None


def jwt_cookie_user(view_func):
    """Resolve ``request.user`` a partir do cookie JWT, para páginas
    server-rendered (Fase 3 — Django + HTMX).

    Reusa :class:`core.auth.JWTCookieAuthentication` (via
    :func:`_user_from_jwt_cookie`) para popular ``request.user`` — permitindo às
    views ler o ORM com a identidade e o ownership corretos. Redireciona para
    ``/login/`` se ausente ou inválido. O login mantém-se intacto (continua a
    emitir o cookie ``fq_access``).
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = _user_from_jwt_cookie(request)
        if user is None:
            return HttpResponseRedirect('/login/')
        request.user = user
        return view_func(request, *args, **kwargs)

    return wrapper


def _priority_badge(occurrence):
    """Mapeia o domínio binário (PRIORITARIA/NORMAL + LEI/MANUAL) na linguagem
    visual P1/P2 (decisão de produto, Fase 3). NORMAL não recebe badge."""
    if occurrence.priority != Occurrence.Priority.PRIORITARIA:
        return None
    if occurrence.priority_source == Occurrence.PrioritySource.LEI:
        return {'level': 'P1', 'cls': 'p1', 'title': 'Prioritária — derivada da lei'}
    return {'level': 'P2', 'cls': 'p2', 'title': 'Prioritária — override manual'}


# Legenda de urgência (vista mobile): a bolinha por linha substitui a coluna
# Prioridade escondida. Mesmos níveis/cores de _priority_badge (P1 lei, P2 override
# manual, normal). Fonte ÚNICA — reutilizável por outras tabelas no rollout.
URGENCY_LEGEND_OCCURRENCE = (
    {'cls': 'p1', 'label': 'Prioritária (lei)'},
    {'cls': 'p2', 'label': 'Prioritária (manual)'},
    {'cls': 'none', 'label': 'Normal'},
)

# Legenda da bolinha por ESTADO LEGAL (evidências/custódias): as cores seguem
# LEGAL_STATE_CSS (fonte única em core.labels), agrupadas por bucket de cor.
URGENCY_LEGEND_EVIDENCE = (
    {'cls': 'info', 'label': 'À guarda do OPC'},
    {'cls': 'warn', 'label': 'Em perícia / trânsito'},
    {'cls': 'ok', 'label': 'Perícia concluída'},
    {'cls': 'danger', 'label': 'Perdida a favor do Estado'},
    {'cls': 'muted', 'label': 'Restituída / destruída'},
)


def _decorate_occurrences_validation(occurrences):
    """Anota ``occ.val_dot`` quando a ocorrência tem itens com VALIDAÇÃO pendente
    (síntese por processo do eixo de validação — CPP art. 178.º/6): âmbar =
    por validar no prazo, vermelho = há item em atraso. Bulk (1 query do ledger
    + 1 do mapa item→processo) via fonte única ``core.analytics``."""
    ids = [o.id for o in occurrences]
    for o in occurrences:
        o.val_dot = None
    if not ids:
        return
    statuses = analytics.validation_statuses_by_evidence(
        ChainOfCustody.objects.filter(evidence__occurrence_id__in=ids)
    )
    occ_by_ev = dict(
        Evidence.objects.filter(occurrence_id__in=ids).values_list('id', 'occurrence_id')
    )
    pend = {}
    for ev_id, vs in statuses.items():
        if vs in VALIDATION_PENDING_STATUSES:
            d = pend.setdefault(occ_by_ev.get(ev_id), {'n': 0, 'late': False})
            d['n'] += 1
            d['late'] = d['late'] or vs == 'em_atraso'
    for o in occurrences:
        d = pend.get(o.id)
        if d:
            o.val_dot = {
                'cls': 'danger' if d['late'] else 'warn',
                'title': (
                    f"{d['n']} item(ns) a aguardar validação"
                    + (' — em atraso' if d['late'] else '')
                ),
            }


def _decorate_occurrences_page(occurrences):
    """Decoração das LISTAS paginadas de ocorrências (grelha + painel do
    dashboard): apresentação base + marcador de validação pendente por processo
    (bulk — só sobre a página, nunca o queryset todo)."""
    _decorate_occurrences(occurrences)
    _decorate_occurrences_validation(occurrences)


def _decorate_occurrences(occurrences):
    """Anota cada ocorrência com campos de apresentação (sem tocar no modelo)."""
    for occ in occurrences:
        occ.pri = _priority_badge(occ)
        occ.dot = occ.pri                        # bolinha de urgência (telemóvel) = prioridade
        ct = occ.crime_type
        occ.crime_label = f'{ct.codigo} — {ct.descritivo}' if ct else '—'
        occ.agent_label = get_user_display_name(occ.agent)
        occ.aria_code = occ.code or occ.number   # rótulo da linha (fallback NUIPC)


# Ordenações expostas na UI → expressão de ORM (lista branca: impede injeção
# de campos arbitrários de ordenação via query param).
_OCC_SORTS = {
    'recent': '-date_time',
    'oldest': 'date_time',
    'number': 'number',
    'created': '-created_at',
}


# ---------------------------------------------------------------------------
# Base-querysets por recurso (joins canónicos — auditoria D11) e dados de
# referência (filtro ativo + ordenação + formato do label — auditoria D10):
# UMA fonte por expressão, consumida por scopes, lentes, detalhes e formulários.
# ---------------------------------------------------------------------------


def _occurrence_base_qs():
    return Occurrence.objects.select_related('agent', 'crime_type')


def _evidence_base_qs():
    return Evidence.objects.select_related(
        'occurrence', 'agent', 'parent_evidence'
    ).prefetch_related('custody_chain')


def _custody_base_qs():
    return ChainOfCustody.objects.select_related('evidence', 'evidence__occurrence', 'agent')


def _occurrence_items_qs(occ):
    """Itens do processo, em ordem de árvore (raízes primeiro) — partilhado pelo
    detalhe da ocorrência e pelos encaminháveis."""
    return _evidence_base_qs().filter(occurrence=occ).order_by('parent_evidence_id', 'id')


def _crime_categories():
    return CrimeCategoria.objects.order_by('codigo')


def _crime_cat_choices():
    """(id, rótulo) das categorias de crime — o rótulo vem de
    ``CrimeCategoria.__str__`` ('{codigo} — {nome}', fonte única do formato)."""
    return tuple((c.id, str(c)) for c in _crime_categories())


def _active_institutions():
    return Institution.objects.filter(is_active=True).order_by('name')


def _active_portadores():
    return Portador.objects.filter(is_active=True).order_by('apelido', 'nome')


def _readable(base_qs, pk, *predicates):
    """Objeto por ``pk`` se ALGUM dos predicados autorizar a leitura; ``None`` se
    não existe ou está fora de acesso — esqueleto único das portas de
    detalhe/drawer por recurso (auditoria D2)."""
    try:
        obj = base_qs.get(pk=pk)
    except (base_qs.model.DoesNotExist, ValueError, TypeError):
        return None
    return obj if any(p(obj) for p in predicates) else None


def _drawer_response(request, user, drawer_id, *, fetch, decorate, template, ctx_key, not_found):
    """Fragmento HTMX do painel direito (detalhe Local) — esqueleto único dos
    drawers por recurso (auditoria D2)."""
    obj = fetch(user, drawer_id)
    if obj is None:
        return HttpResponseNotFound(not_found)
    decorate([obj])
    return render(request, template, {ctx_key: obj})


def _drawer_dispatch(request, user, drawer_view):
    """Atalho comum das listas: com ``?drawer=<id>`` devolve o fragmento do
    painel de detalhe; sem ele devolve ``None`` (a lista segue)."""
    drawer_id = request.GET.get('drawer')
    return drawer_view(request, user, drawer_id) if drawer_id else None


def _scope_occurrences(user):
    """Ocorrências legíveis pelo utilizador — *need-to-know* derivado do ledger
    (ADR-0017; fonte única em :mod:`core.access`)."""
    return access.scope_occurrences(user, base_qs=_occurrence_base_qs())


def _readable_occurrence(user, pk):
    """Ocorrência por ``pk`` se o utilizador a pode LER na consola server-rendered;
    ``None`` se não existe ou está fora de acesso. É a porta de DETALHE/drawer:
    mais ampla que a LISTA pessoal (``scope_occurrences``) — abre por acesso global
    (titular / leitura total / autoridade do caso, :func:`can_access_occurrence`)
    OU por pertença institucional (a instituição é dona do processo, abre o
    processo inteiro — :func:`is_occurrence_institutional`). A API/PDF/verificação
    pública mantêm o need-to-know item-level (não passam por aqui)."""
    return _readable(
        _occurrence_base_qs(), pk,
        lambda occ: access.can_access_occurrence(user, occ),
        lambda occ: access.is_occurrence_institutional(user, occ),
    )


def _occurrence_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de uma ocorrência."""
    def deco(objs):
        _decorate_occurrences(objs)
        objs[0].evidence_count = objs[0].evidences.count()

    return _drawer_response(
        request, user, drawer_id,
        fetch=_readable_occurrence, decorate=deco,
        template='partials/_occurrence_drawer.html', ctx_key='occ',
        not_found='Ocorrência não encontrada.',
    )


# ---------------------------------------------------------------------------
# Evidências (lista server-rendered)
# ---------------------------------------------------------------------------

# LEGAL_STATE_LABELS / LEGAL_STATE_CSS: fonte única em core.labels (importados no topo).

_EVD_SORTS = {
    'recent': '-timestamp_seizure',
    'oldest': 'timestamp_seizure',
    'code': 'code',
    'occurrence': 'occurrence__number',
}


def _scope_evidences(user):
    """Evidências legíveis pelo utilizador — *need-to-know* item-level
    (ADR-0017; fonte única em :mod:`core.access`)."""
    return access.scope_evidences(user, base_qs=_evidence_base_qs())


def _evidence_state(evidence):
    """(label, css) do estado legal derivado da cadeia de custódia."""
    st = legal_state_of(evidence)
    if st is None:
        return ('Sem custódia', 'muted')
    return (LEGAL_STATE_LABELS.get(st, st), LEGAL_STATE_CSS.get(st, 'muted'))


def _decorate_evidences(evidences):
    # labels() uma vez (evita N+1 com o choices-callable de Evidence.type — ADR-0018).
    type_labels = evidence_type_config.labels()
    for e in evidences:
        e.type_label = type_labels.get(e.type, e.type)
        e.agent_label = get_user_display_name(e.agent)
        e.occ_label = e.occurrence.code or e.occurrence.number
        e.state_label, e.state_css = _evidence_state(e)
        e.state_badge = {'css': e.state_css, 'label': e.state_label}
        e.dot = {'cls': e.state_css, 'title': e.state_label}   # bolinha mobile = estado legal
        # Estatuto de VALIDAÇÃO da apreensão — eixo ortogonal ao estado (CPP
        # art. 178.º/6); None = não aplicável (sem badge). O val_dot é o
        # marcador compacto por linha, SÓ quando há trabalho pendente.
        vs = validation_status_of(e)
        e.validation_status = vs
        e.validation_badge = (
            {'css': VALIDATION_STATUS_CSS[vs], 'label': VALIDATION_STATUS_LABELS[vs]}
            if vs else None
        )
        e.val_dot = (
            {'cls': VALIDATION_STATUS_CSS[vs], 'title': VALIDATION_STATUS_LABELS[vs]}
            if vs in VALIDATION_PENDING_STATUSES else None
        )
        e.aria_code = e.code or 'item de prova'
        # marca/modelo são campos transversais em type_specific_data (JSON, ADR-0018);
        # expostos aqui (1 fonte) para a grelha e o drawer os mostrarem.
        tsd = e.type_specific_data or {}
        e.marca = tsd.get('marca', '')
        e.modelo = tsd.get('modelo', '')


def _readable_evidence(user, pk):
    """Evidência por ``pk`` se o utilizador a pode LER na consola server-rendered;
    ``None`` caso contrário. Item-level need-to-know (``can_view_evidence``) OU o
    item pertence a uma ocorrência que o utilizador lê por pertença institucional
    (a instituição é dona do processo → vê o processo INTEIRO, incl. itens-irmãos
    que a sua instituição nunca custodiou — coerente com a zona "Instituição" da
    consola, que lista o processo todo). A ESCRITA continua governada pelo
    serializer (``can_append_custody``, fail-closed), independente desta porta."""
    return _readable(
        _evidence_base_qs(), pk,
        lambda ev: access.can_view_evidence(user, ev),
        lambda ev: access.is_occurrence_institutional(user, ev.occurrence),
    )


def _evidence_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de uma evidência."""
    return _drawer_response(
        request, user, drawer_id,
        fetch=_readable_evidence, decorate=_decorate_evidences,
        template='partials/_evidence_drawer.html', ctx_key='ev',
        not_found='Evidência não encontrada.',
    )


def login_view(request):
    """Página de login (pública)."""
    return render(request, 'login.html')


def public_verify_view(request, short_hash):
    """Vista adaptativa de verificação pública de ocorrência (ADR-0012).

    URL: ``/v/<short_hash>/`` — destino dos QR codes do PDF de
    transporte. Comportamento por nível de auth:

    - Com cookie JWT válido (EXPERT ou AGENT-dono): redirect para
      ``/occurrences/<id>/`` (vista autenticada completa).
    - Sem auth ou auth insuficiente: renderiza ``public_verify.html``
      com dados mínimos não-sensíveis (código da ocorrência, número
      de evidências, hashes de integridade — sem descrições, GPS,
      ou metadados forenses).

    O `short_hash` é resolvido por `qr_verify.resolve_occurrence`,
    que usa HMAC para validar sem expor a relação directa com
    `occurrence.id`.
    """
    from core.qr_verify import resolve_occurrence

    # Lockout por IP (escalada) + rate-limit por minuto. Superfície pública
    # não-autenticada; sem freio um atacante poderia tentar enumerar os hashes
    # curtos. Aplicados ANTES de resolver para travar tentativas inválidas.
    # IP pela fonte única endurecida (core.audit.get_client_ip): só confia no
    # X-Forwarded-For atrás de proxy confiável — um XFF forjado não contorna
    # nem envenena o lockout (auditoria D7).
    ip = get_client_ip(request)
    if _verify_is_locked(ip):
        return HttpResponse(
            'Demasiadas tentativas. Tente novamente mais tarde.',
            status=429,
            content_type='text/plain; charset=utf-8',
        )
    if not _throttle_public_verify(request):
        return HttpResponse(
            'Demasiados pedidos. Tente novamente mais tarde.',
            status=429,
            content_type='text/plain; charset=utf-8',
        )

    occurrence = resolve_occurrence(short_hash)
    if occurrence is None:
        # Hash desconhecido — não distinguimos "não existe" de
        # "secret rotacionado" para não vazar informação. Conta para o lockout.
        _verify_register_fail(ip)
        return render(request, 'public_verify_notfound.html', status=404)
    _verify_clear_fails(ip)

    # Auth OPCIONAL via cookie JWT (fonte única _user_from_jwt_cookie — D12).
    # "Ver tudo" = poder aceder à ocorrência pelo mesmo critério da vista
    # autenticada (access.can_access_occurrence: titular / leitura total —
    # staff/NACIONAL/perito forense — / autoridade do caso). Quem não pode
    # aceder cai na vista pública mínima.
    user = _user_from_jwt_cookie(request)
    user_can_see_full = bool(
        user and user.is_authenticated and access.can_access_occurrence(user, occurrence)
    )

    if user_can_see_full:
        return HttpResponseRedirect(f'/occurrences/{occurrence.id}/')

    # Vista pública: dados mínimos, lista de hashes de integridade
    # (verificáveis externamente por SHA-256). Sem descrições.
    evidences = list(occurrence.evidences.only('code', 'integrity_hash', 'type').order_by('code'))
    return render(
        request,
        'public_verify.html',
        {
            'occurrence_code': occurrence.code or f'#{occurrence.id}',
            'occurrence_number': occurrence.number,
            'evidence_count': len(evidences),
            'evidences': evidences,
        },
    )


@jwt_cookie_user
def verifications_view(request):
    """Centro de verificação / QR (operador EXPERT/staff).

    Resolve um ``short_hash`` de QR OU um código de ocorrência (OC-…) para o
    caso correspondente, mostra o URL canónico do QR (para reimpressão da guia)
    e documenta o fluxo guia-de-transporte e as suas mitigações. NÃO é entrada
    de dados por código nem pesquisa pública — é ferramenta interna de
    gestão/auditoria, pelo que respeita o ADR-0012 §6. Só resolve casos dentro
    do âmbito do operador (need-to-know)."""
    from core.qr_verify import resolve_occurrence, short_hash_for, verify_url_for

    user = request.user
    if not access.is_expert_or_staff(user):
        return HttpResponseForbidden('Acesso reservado a perito forense / staff.')

    query = (request.GET.get('q') or '').strip()
    result = None
    not_found = False
    if query:
        occ = None
        if query.upper().startswith('OC-'):
            occ = _scope_occurrences(user).filter(code__iexact=query).first()
        else:
            cand = resolve_occurrence(query.lower())
            if cand is not None and _scope_occurrences(user).filter(pk=cand.id).exists():
                occ = cand
        if occ is not None:
            result = {
                'id': occ.id,
                'code': occ.code or f'#{occ.id}',
                'number': occ.number,
                'short_hash': short_hash_for(occ.id),
                # Composição do URL público na fonte única (qr_verify — D43).
                'verify_url': verify_url_for(occ.id),
            }
        else:
            not_found = True

    return render(
        request,
        'verifications.html',
        {'q': query, 'result': result, 'not_found': not_found},
    )


_HERO_BOUNDS = {
    'continental': [[36.95, -9.55], [42.15, -6.18]],
    # Madeira inclui Porto Santo (33.02-33.12, -16.42…-16.29) — os bounds
    # antigos cortavam-no; as Selvagens ficam de fora conscientemente.
    'madeira': [[32.35, -17.45], [33.15, -16.25]],
    'acores': [[36.85, -31.40], [39.85, -24.70]],
}


def _occ_pri_code(o):
    """Código numérico de prioridade para o mapa (1=P1 lei, 2=P2 manual, 0=normal)."""
    if o.priority == Occurrence.Priority.PRIORITARIA:
        return 1 if o.priority_source == Occurrence.PrioritySource.LEI else 2
    return 0


def _activity_feed(user, limit=20):
    """Últimos eventos do AuditLog (append-only) visíveis ao utilizador.

    Só leitura nacional (staff ou credencial NACIONAL) vê TODO o registo de
    auditoria; qualquer outro perfil (FIRST_RESPONDER, FORENSIC_EXPERT NORMAL,
    CASE_AUTHORITY, EVIDENCE_CUSTODIAN…) vê APENAS os eventos que praticou —
    *need-to-know* (ADR-0017; âmbito numa fonte única, ``access.scope_audit_logs``,
    partilhada com :class:`core.views.ActivityFeedView`). É a fonte de verdade do
    "que aconteceu": criação de prova (com hash), eventos de custódia,
    exportações de PDF, alertas.

    A EXIBIÇÃO ordena por momento do evento (timestamp, com a sequência como
    desempate): por ``-sequence`` puro o feed mostrava timestamps baralhados
    quando a ordem de inserção divergia do tempo (registos diferidos) — num
    registo probatório, datas fora de ordem leem-se como corrupção. A ordem de
    append continua VISÍVEL (nº de sequência em cada linha) e auditável.
    """
    qs = access.scope_audit_logs(user).select_related('user').order_by('-timestamp', '-sequence')
    logs = list(qs[:limit])

    # Código real e rota de cada alvo, em lote por tipo — "Evidência #7" não
    # identifica nada; o código hierárquico identifica e o link deixa agir.
    # (Os destinos impõem as suas próprias permissões; o link não alarga nada.)
    RT = AuditLog.ResourceType
    ids_by_type = {}
    for r in logs:
        ids_by_type.setdefault(r.resource_type, set()).add(r.resource_id)
    target = {}
    if RT.OCCURRENCE in ids_by_type:
        for o in Occurrence.objects.filter(id__in=ids_by_type[RT.OCCURRENCE]).only(
            'id', 'code', 'number'
        ):
            target[(RT.OCCURRENCE, o.id)] = (o.code or o.number, f'/occurrences/{o.id}/')
    # DEVICE: o alvo é o registo de EVIDÊNCIA do dispositivo (mesmo id) —
    # resolve-se pelo mesmo caminho para o feed ser clicável.
    ev_ids = ids_by_type.get(RT.EVIDENCE, set()) | ids_by_type.get(RT.DEVICE, set())
    if ev_ids:
        for e in Evidence.objects.filter(id__in=ev_ids).only('id', 'code'):
            target[(RT.EVIDENCE, e.id)] = (e.code, f'/evidences/{e.id}/')
            target[(RT.DEVICE, e.id)] = (e.code, f'/evidences/{e.id}/')
    if RT.CUSTODY in ids_by_type:
        for c in ChainOfCustody.objects.filter(id__in=ids_by_type[RT.CUSTODY]).only(
            'id', 'code', 'evidence_id'
        ):
            target[(RT.CUSTODY, c.id)] = (c.code, f'/evidences/{c.evidence_id}/custody/')

    for r in logs:
        r.action_label = r.get_action_display()
        # Rótulo curto + tom semântico numa fonte única (labels — D97); o
        # template emite a variante, o CSS não conhece o enum.
        r.action_short = ACTION_SHORT.get(r.action, r.action_label)
        r.action_css = ACTION_CSS.get(r.action, '')
        r.resource_label = r.get_resource_type_display()
        r.user_label = get_user_display_name(r.user)
        code, url = target.get((r.resource_type, r.resource_id), (None, None))
        if r.resource_type == RT.SYSTEM:
            # Meta-auditoria: o id numérico não identifica nada navegável.
            r.target_label, r.target_url = r.resource_label, None
        elif code:
            r.target_label, r.target_url = f'{r.resource_label} {code}', url
        else:
            # Alvo sem código ou já não existente — honesto, sem link.
            r.target_label, r.target_url = f'{r.resource_label} #{r.resource_id}', None
        d = r.details or {}
        if r.resource_type == RT.EVIDENCE and d.get('hash'):
            r.extra = d['hash'][:16] + '…'
        elif r.resource_type == RT.CUSTODY and d.get('event_type'):
            # Label PT do enum (fonte única em policy); valor cru só se o
            # código já não existir no enum.
            try:
                r.extra = EventType(d['event_type']).label
            except ValueError:
                r.extra = d['event_type']
        else:
            r.extra = ''
    return logs


def _state_filter(states_getter, fk='id'):
    """Filtro computado do grid por estado legal DERIVADO (uma closure única
    para evidências e custódias — só muda a FK contra o dict de estados).

    ``states_getter`` devolve o ``{evidence_id: estado}`` da fonte única
    (:func:`core.analytics.legal_states_by_evidence`), avaliado só quando o
    filtro é mesmo aplicado (e memoizável pelo chamador).
    """

    def _apply(filtered_qs, _request, value):
        matching = [ev_id for ev_id, st in states_getter().items() if st == value]
        return filtered_qs.filter(**{f'{fk}__in': matching})

    return _apply


# ---------------------------------------------------------------------------
# Dispatch por ZONA de consola (duas zonas) — ver core.access.Lens.
# A consola é case-axis (de processo, nunca por item): MINE = o âmbito de caso
# pessoal (scope_occurrences); INSTITUTION = o processo INTEIRO das ocorrências da
# instituição (scope_occurrences_institutional) — ampliação de leitura por modo,
# deliberada. access.console_mode resolve a zona (param/sessão) contra o
# utilizador (fallback silencioso); access.remember_console_mode memoriza-a.
# ---------------------------------------------------------------------------


def _lens_occurrences(user, lens):
    """Ocorrências para a zona ativa: ``MINE`` = âmbito de caso pessoal;
    ``INSTITUTION`` = ocorrências da instituição (processo inteiro, sem item)."""
    if lens == access.Lens.INSTITUTION:
        return access.scope_occurrences_institutional(user, base_qs=_occurrence_base_qs())
    return _scope_occurrences(user)


def _lens_evidences(user, lens):
    """Itens para a zona ativa (case-axis, nunca por item).

    ``INSTITUTION`` mostra TODOS os itens das ocorrências da instituição (processo
    inteiro — a instituição é dona do processo). ``MINE`` mostra os itens legíveis
    (item-level, ADR-0017) das ocorrências do utilizador.
    """
    qs = _evidence_base_qs()
    if lens == access.Lens.INSTITUTION:
        return qs.filter(
            occurrence__in=access.scope_occurrences_institutional(user).values('pk')
        )
    return access.scope_evidences(user, base_qs=qs).filter(
        occurrence__in=access.scope_occurrences(user).values('pk')
    )


def _lens_custody(user, lens):
    """Eventos de custódia para a zona ativa (mesma lógica case-axis)."""
    qs = _custody_base_qs()
    if lens == access.Lens.INSTITUTION:
        return qs.filter(
            evidence__occurrence__in=access.scope_occurrences_institutional(user).values('pk')
        )
    return access.scope_custody(user, base_qs=qs).filter(
        evidence__occurrence__in=access.scope_occurrences(user).values('pk')
    )


# ---------------------------------------------------------------------------
# Arquivo — ocorrências CONCLUÍDAS (todos os itens em estado legal terminal).
# Derivado do ledger (sem coluna nova), mesmo padrão WI-E do Painel: uma só
# passagem sobre os estados legais por item. Listas ativas EXCLUEM os arquivados;
# a vista /arquivo/ mostra-os.
# ---------------------------------------------------------------------------


def _archived_occurrence_ids(user, occ_qs):
    """``set`` de IDs ARQUIVADOS no âmbito ``occ_qs``: ocorrências com ≥1 item e
    TODOS os itens em estado legal terminal (restituída/perdida a favor do
    Estado/destruída). Itens SEM eventos (estado por abrir) impedem o arquivo — o
    processo ainda está vivo.

    Eficiência (não varre tudo a cada página): só se DERIVA o estado das
    ocorrências CANDIDATAS — as que têm no ledger ≥1 evento de disposição final
    (restituição / destruição / perda a favor do Estado). Uma ocorrência sem
    nenhum desses eventos não pode estar concluída e é descartada em SQL, sem custo
    de derivação. A derivação usa a cadeia COMPLETA do candidato (não o âmbito da
    lente): "processo concluído" é uma propriedade OBJETIVA do ledger, independente
    de quem vê que eventos — para o titular/membro o âmbito já é a cadeia inteira,
    pelo que coincide com os tiles do Painel. ``derive_legal_state`` é a fonte de
    verdade (sem tradução para SQL), aplicada só ao subconjunto candidato."""
    candidate_ids = list(
        occ_qs.filter(
            evidences__custody_chain__event_type__in=(
                EventType.RESTITUICAO,
                EventType.DESTRUICAO,
                EventType.PERDA_FAVOR_ESTADO,
            )
        )
        .values_list('pk', flat=True)
        .distinct()
    )
    if not candidate_ids:
        return set()
    states = analytics.legal_states_by_evidence(
        ChainOfCustody.objects.filter(evidence__occurrence_id__in=candidate_ids)
    )
    by_occ = {}
    for ev_id, occ_id in Evidence.objects.filter(
        occurrence_id__in=candidate_ids
    ).values_list('id', 'occurrence_id'):
        by_occ.setdefault(occ_id, []).append(states.get(ev_id))
    return {
        occ_id
        for occ_id, sts in by_occ.items()
        if sts and all(s in TERMINAL_LEGAL_STATES for s in sts)
    }


@jwt_cookie_user
def dashboard_view(request):
    """Painel — hero geo + últimas ocorrências + registo de atividade, TUDO
    server-rendered (Fase 3). Sem o JS antigo do hero (drift eliminado)."""
    user = request.user
    lens = access.active_console_mode(request, user)
    # O hero segue a zona ativa da consola: "as minhas" (âmbito de caso pessoal)
    # ou "Instituição" (processo inteiro das ocorrências da instituição).
    occ_qs = _lens_occurrences(user, lens)
    occ_total = occ_qs.count()

    # Tiles do estado da cadeia — contagem por estado legal DERIVADO (ledger),
    # agrupamento e contagem na fonte única (core.analytics).
    cus_qs = _lens_custody(user, lens)
    tile_counts = analytics.state_counts(analytics.legal_states_by_evidence(cus_qs))
    tiles = [
        {'key': k, 'label': LEGAL_STATE_LABELS[k], 'n': tile_counts[k]} for k in LEGAL_STATE_LABELS
    ]
    # "A aguardar validação" — EIXO próprio (a validação é ato jurídico, não um
    # estado de custódia): tile de ATENÇÃO à parte; o clique filtra a própria
    # tabela (?attn=pending), como os prazos — o número é re-derivável.
    val_statuses = analytics.validation_statuses_by_evidence(cus_qs)
    pending_ids = {
        ev for ev, vs in val_statuses.items() if vs in VALIDATION_PENDING_STATUSES
    }
    tiles.append({
        'key': 'val_pendente', 'label': 'A aguardar validação',
        'n': len(pending_ids), 'href': '?attn=pending', 'attn': True,
    })

    # Métricas de FLUXO (não só stock) — mesma fonte única que alimenta /stats/:
    # prazos a estourar (CPP 178.º/6), trânsito por receber e paragem mais longa
    # respondem a "o que está em risco HOJE?"; mov/24h dá pulso aos tiles.
    sla = analytics.aging_sla(_lens_evidences(user, lens), cus_qs)
    dwell = analytics.custody_dwell(cus_qs)
    moves_24h = cus_qs.filter(timestamp__gte=timezone.now() - timedelta(hours=24)).count()

    # Pontos georreferenciados por região (mapa do hero). O `id` permite o
    # drill-down (popup com link) no mapa interativo.
    pts = [
        {'id': o.id, 'lat': float(o.gps_lat), 'lng': float(o.gps_lng),
         'label': o.code or o.number, 'pri': _occ_pri_code(o)}
        for o in occ_qs.exclude(gps_lat=None).exclude(gps_lng=None)
    ]

    def _within(b, p):
        return b[0][0] <= p['lat'] <= b[1][0] and b[0][1] <= p['lng'] <= b[1][1]

    regions = {name: [p for p in pts if _within(b, p)] for name, b in _HERO_BOUNDS.items()}
    # Pontos fora das 3 caixas NUNCA desaparecem em silêncio (princípio de
    # re-verificabilidade): contam-se e o template expõe-os na legenda.
    n_fora_mapa = sum(1 for p in pts if not any(_within(b, p) for b in _HERO_BOUNDS.values()))

    def _pri_counts(points):
        return {
            'p1': sum(1 for p in points if p['pri'] == 1),
            'p2': sum(1 for p in points if p['pri'] == 2),
            'normal': sum(1 for p in points if p['pri'] == 0),
        }

    # Filtro local "Prazos & atenção" (?attn=): clicar num prazo mostra na
    # PRÓPRIA tabela as ocorrências cujos itens o contam — o número do painel
    # é re-derivável no clique (antes ligava a uma lista mais lata, N≠número).
    _ATTN = {
        'overdue': ('validações em atraso', sla['overdue_ids']),
        'transit': ('em trânsito por receber', sla['transit_ids']),
        'pending': ('a aguardar validação', pending_ids),
    }
    attn_key = (request.GET.get('attn') or '').strip()
    attn_filter = None
    recent_qs = occ_qs
    if attn_key in _ATTN:
        label, ev_ids = _ATTN[attn_key]
        recent_qs = occ_qs.filter(evidences__id__in=ev_ids).distinct()
        attn_filter = {
            'key': attn_key,
            'label': label,
            'n_items': len(ev_ids),
            'n_occ': recent_qs.count(),
        }

    recent = list(
        # distinct=True: a lente institucional filtra por evidences__custody_chain__…,
        # e o join multi-valor multiplicava a contagem (1 por EVENTO de custódia).
        # 30 linhas: a lista do painel tem altura fixa com scroll interno.
        recent_qs.annotate(n_items=Count('evidences', distinct=True)).order_by('-date_time')[:30]
    )
    _decorate_occurrences_page(recent)
    for o in recent:
        o.detail_url = f'/occurrences/{o.id}/'

    # Colunas da grelha "Últimas ocorrências" — gerador único (core.grid), como
    # todas as listas; um painel read-only só dispensa filtros/paginação.
    # Larguras dimensionadas para a coluna ESQUERDA da dash-grid (~700px a
    # 1440): código e data nunca truncam; o tipo de crime é o que cede.
    recent_columns = serialize_columns([
        GridColumn('pri', 'Pri.', cell='pri', css='col-reduce-hide', width=8),
        GridColumn('code', 'Código', cell='code', width=18, link_key='detail_url', val_flag=True),
        GridColumn('number', 'NUIPC', css='mono', width=18),
        GridColumn('crime_label', 'Tipo de crime', css='grid__ellipsis col-reduce-hide', width=24),
        GridColumn('n_items', 'Itens', cell='num', css='col-hide-sm', width=8),
        GridColumn('date_time', 'Data / hora', cell='date', time=True, width=24),
    ])

    return render(
        request,
        'dashboard.html',
        {
            'u': user,
            'occ_total': occ_total,
            # Carimbo de âmbito da linha de regie (fonte única do rótulo da zona).
            'lens_zone_label': access.lens_label(user, lens),
            'recent': recent,
            'recent_columns': recent_columns,
            'attn_filter': attn_filter,
            'logs': _activity_feed(user, limit=20),
            'feed_is_national': access.has_national_read(user),
            'tiles': tiles,
            # Total de itens COM custódia (inclui terminais) — era 'total_active',
            # nome enganador (auditoria D45); o template mostra "N itens".
            'custody_total': sum(tile_counts.values()),
            'sla': sla,
            'dwell': dwell,
            'moves_24h': moves_24h,
            # O mapa principal leva TODOS os pontos geolocalizados: o foco
            # regional (insets) re-enquadra ESTE mapa nos arquipélagos, e sem
            # os pontos das ilhas a Madeira focada lia-se como "zero
            # ocorrências". No enquadramento continental os pontos insulares
            # ficam fora do viewport — sem efeito visual.
            'points_main': json.dumps(pts),
            'points_madeira': json.dumps(regions['madeira']),
            'points_acores': json.dumps(regions['acores']),
            'bounds_continental': json.dumps(_HERO_BOUNDS['continental']),
            'bounds_madeira': json.dumps(_HERO_BOUNDS['madeira']),
            'bounds_acores': json.dumps(_HERO_BOUNDS['acores']),
            # Contagens que batem certo com os pontos DESENHADOS em cada mapa
            # (occ_total inclui sem-GPS — não serve para o cabeçalho do mapa).
            'n_geo': len(pts),
            'n_madeira': len(regions['madeira']),
            'n_acores': len(regions['acores']),
            'n_fora_mapa': n_fora_mapa,
            'pri_points': _pri_counts(pts),
        },
    )


def _occurrences_list_response(request, archived=False):
    """Corpo PARTILHADO das listas de ocorrências ativas (``/occurrences/``) e do
    Arquivo (``/arquivo/``): mesmo dispatch por zona de consola, colunas, filtros,
    ordenação e paginação — só diferem na divisão arquivado/ativo e no template.
    O drawer (``?drawer=``) é comum (o detalhe de um processo é o mesmo). Toda a
    plumbing (filtros por coluna, busca, paginação, vista mobile) vem do gerador
    único :func:`core.grid.grid_list_response`; aqui declara-se só a spec."""
    user = request.user

    drawer = _drawer_dispatch(request, user, _occurrence_drawer)
    if drawer is not None:
        return drawer

    lens = access.active_console_mode(request, user)
    qs = _lens_occurrences(user, lens)

    cat_choices = _crime_cat_choices()
    # Ordem = colunas: Pri · Código · NUIPC · Crime · Data · Local · Agente.
    columns = [
        GridColumn('pri', 'Pri.', cell='pri', css='col-reduce-hide', width=6,
                   filter=ColFilter('pri', 'Prioridade', kind='select', field='priority',
                                    choices=((Occurrence.Priority.PRIORITARIA, 'Prioritárias'),
                                             (Occurrence.Priority.NORMAL, 'Normais')))),
        GridColumn('code', 'Código', cell='code', width=13, dot=True, val_flag=True,
                   filter=ColFilter('q_code', 'Código', kind='text', field='code', placeholder='Código')),
        GridColumn('number', 'NUIPC', css='mono', width=16,
                   filter=ColFilter('q_number', 'NUIPC', kind='text', field='number', placeholder='NUIPC')),
        GridColumn('crime_label', 'Tipo de crime', css='grid__ellipsis col-reduce-hide', width=21,
                   filter=ColFilter('cat', 'Tipo de crime', kind='select',
                                    field='crime_type__subcategoria__categoria_id', choices=cat_choices)),
        GridColumn('date_time', 'Data', cell='date', time=True, width=12,
                   filter=ColFilter('date', 'Data', kind='date_range', field='date_time')),
        GridColumn('address', 'Local', css='grid__ellipsis grid__muted col-reduce-hide', width=20, geo=True,
                   filter=ColFilter('q_address', 'Local', kind='text', field='address', placeholder='Local')),
        GridColumn('agent_label', 'Agente', css='grid__muted col-hide-sm', width=12,
                   filter=ColFilter('q_agent', 'Agente', kind='text', placeholder='Agente',
                                    fields=('agent__first_name', 'agent__last_name', 'agent__username'))),
    ]

    def archived_split(filtered_qs, _request):
        # Processo CONCLUÍDO = todos os itens em estado legal terminal. Deriva-se
        # sobre o âmbito já filtrado e divide-se (sem coluna nova).
        archived_ids = _archived_occurrence_ids(user, filtered_qs)
        return (filtered_qs.filter(pk__in=archived_ids) if archived
                else filtered_qs.exclude(pk__in=archived_ids))

    lens_qs = f'?lens={lens}' if lens else ''
    if archived:
        empty_hint = ('Ainda não há processos concluídos — todos os itens em estado '
                      'terminal (restituídos, perdidos a favor do Estado ou destruídos).')
        empty_filtered = 'Nenhum processo arquivado para os filtros aplicados.'
    else:
        empty_hint = format_html(
            'Ainda não há ocorrências ativas que possa ver. Os processos concluídos '
            'estão no <a href="/arquivo/{}">Arquivo</a>.', lens_qs
        )
        empty_filtered = 'Nenhum resultado para os filtros aplicados.'

    return grid_list_response(
        request,
        queryset=qs,
        columns=columns,
        grid_key='occ',
        endpoint='/arquivo/' if archived else '/occurrences/',
        page_template='arquivo.html' if archived else 'occurrences.html',
        table_label='Processos arquivados' if archived else 'Lista de ocorrências',
        count_noun='processo' if archived else 'registo',
        sorts=_OCC_SORTS,
        default_sort='recent',
        sorts_ui=(('recent', 'Mais recentes'), ('oldest', 'Mais antigas'),
                  ('number', 'NUIPC'), ('created', 'Data de registo')),
        search_fields=('code', 'number', 'address',
                       'agent__first_name', 'agent__last_name', 'agent__username',
                       'crime_type__descritivo', 'crime_type__subcategoria__nome',
                       'crime_type__subcategoria__categoria__nome'),
        search_placeholder='Procurar código, NUIPC, crime, local, agente…',
        decorate=_decorate_occurrences_page,
        legend=URGENCY_LEGEND_OCCURRENCE,
        page_size=25,
        lens=lens,
        empty_hint=empty_hint,
        empty_filtered=empty_filtered,
        post_filter=archived_split,
    )


@jwt_cookie_user
def occurrences_view(request):
    """Lista de ocorrências ATIVAS — server-rendered (Fase 3, Django + HTMX).

    Lê o ORM com o working-set da zona de consola ativa. Os processos CONCLUÍDOS
    (todos os itens em estado terminal) saem para o Arquivo (:func:`arquivo_view`).
    Em pedidos HTMX devolve só o fragmento da grelha; com ``?drawer=<id>`` o
    painel de detalhe.
    """
    return _occurrences_list_response(request, archived=False)


@jwt_cookie_user
def arquivo_view(request):
    """Arquivo de processos CONCLUÍDOS — ocorrências cujos itens estão TODOS em
    estado legal terminal (restituído/perdido a favor do Estado/destruído). Mesma
    grelha e zona de consola da lista ativa, restrita aos arquivados."""
    return _occurrences_list_response(request, archived=True)


@jwt_cookie_user
def occurrence_detail_view(request, occurrence_id):
    """Detalhe de uma ocorrência — hub do caso, server-rendered (Fase 3)."""
    user = request.user
    occ = _readable_occurrence(user, occurrence_id)
    if occ is None:
        return HttpResponseNotFound('Ocorrência não encontrada.')
    _decorate_occurrences([occ])
    # Processo INTEIRO: quem ACEDE à ocorrência vê TODOS os seus itens, sem filtro
    # por item (a instituição é dona do processo). O object-level já foi imposto
    # por _readable_occurrence; a lista cross-ocorrência (Evidências) é que mantém
    # o need-to-know item-level.
    evidences = list(_occurrence_items_qs(occ))
    _decorate_evidences(evidences)
    occ.evidence_count = len(evidences)
    # Encaminhar/validar são ações de escrita: escondidas a perfis só-leitura (a
    # porta real é o can_append_custody por item, no serializer). O botão de
    # validar só aparece havendo apreensões por validar (badge já derivado).
    can_handoff = not access.is_read_only_profile(user)
    can_validate = can_handoff and any(
        e.validation_status in VALIDATION_PENDING_STATUSES for e in evidences
    )
    # Restituir: aparece havendo itens que as guardas aceitam restituir JÁ
    # (génese feita, ledger aberto, não em trânsito) — mesma fonte única do
    # modal (policy.next_events; _restituiveis faz a seleção real no POST).
    can_restitute = can_handoff and any(
        EventType.RESTITUICAO.value in {
            v
            for v, _ in _valid_next_events(sort_custody_chain(e.custody_chain.all()), e)
        }
        for e in evidences
    )
    return render(
        request,
        'occurrence_detail.html',
        {
            'occ': occ,
            'evidences': evidences,
            'can_handoff': can_handoff,
            'can_validate': can_validate,
            'can_restitute': can_restitute,
        },
    )


def _itens_com_proximo_evento(user, occ, event_type):
    """Itens da ocorrência para os quais ``event_type`` é um PRÓXIMO evento
    válido (guardas da policy via ``_valid_next_events``) E o utilizador tem
    escrita no ledger (``can_append_custody``). Esqueleto único da seleção das
    ações em lote da ocorrência (encaminhar, validar). Lista decorada."""
    itens = []
    for ev in _occurrence_items_qs(occ):
        events = sort_custody_chain(ev.custody_chain.all())
        valid = {v for v, _ in _valid_next_events(events, ev)}
        if event_type.value in valid and access.can_append_custody(user, ev, event_type):
            itens.append(ev)
    _decorate_evidences(itens)
    return itens


def _encaminhaveis(user, occ):
    """Itens da ocorrência que o utilizador pode ENCAMINHAR agora: génese feita,
    não terminais nem já em trânsito (ENCAMINHAMENTO é próximo evento válido).
    Anota-se ``ev.checked`` na view (omissão: todos — encaminha-se a prova junta)."""
    return _itens_com_proximo_evento(user, occ, EventType.ENCAMINHAMENTO_CUSTODIA)


def _validaveis(user, occ):
    """Itens da ocorrência com apreensão POR VALIDAR (dentro ou fora do prazo):
    VALIDACAO_APREENSAO é próximo evento válido segundo as guardas (há génese de
    apreensão, ainda não validada, ledger aberto, não em trânsito)."""
    return _itens_com_proximo_evento(user, occ, EventType.VALIDACAO_APREENSAO)


def _restituiveis(user, occ):
    """Itens da ocorrência que podem ser RESTITUÍDOS agora (CPP art. 186.º):
    RESTITUICAO é próximo evento válido segundo as guardas (génese feita,
    ledger aberto, não em trânsito)."""
    return _itens_com_proximo_evento(user, occ, EventType.RESTITUICAO)


def _bearer_fields_from_post(request):
    """Lê do POST a identificação do portador (fonte única encaminhar/timeline):
    portador REGISTADO (``bearer``, FK — o save() copia o snapshot da ficha) OU
    PONTUAL (``bearer_nome``/``bearer_apelido``/``bearer_matricula``[+``bearer_posto``],
    snapshot direto — a lei exige identificar quem transporta, não que esteja
    pré-registado). Devolve ``(payload, erro)``: payload com os campos a juntar
    ao evento, ou erro accionável (ambos/nenhum/pontual incompleto)."""
    bearer_id = (request.POST.get('bearer') or '').strip()
    adhoc = {
        k: (request.POST.get(f'bearer_{k}') or '').strip()
        for k in ('nome', 'apelido', 'matricula', 'posto')
    }
    given = [k for k in ('nome', 'apelido', 'matricula') if adhoc[k]]
    if bearer_id and given:
        return None, (
            'Escolha o portador registado OU identifique o portador pontual — '
            'não ambos.'
        )
    if bearer_id:
        return {'bearer': bearer_id}, None
    if len(given) == 3:
        payload = {f'bearer_{k}': v for k, v in adhoc.items() if v}
        return payload, None
    if given:
        return None, (
            'Portador pontual incompleto: indique nome, apelido e '
            'matrícula/identificador (CC, passaporte ou outro).'
        )
    return None, (
        'Indique o portador que conduz a prova: escolha um registado ou '
        'identifique o portador pontual.'
    )


def _receiver_fields_from_post(request):
    """Lê do POST a identidade de quem RECEBE a prova (fonte única do termo de
    entrega — CPP art. 186.º): ``receiver_nome`` + ``receiver_doc_tipo`` +
    ``receiver_doc_numero``, snapshot direto sem ficha (a pessoa não é
    utilizador nem entidade registada); os três entram na cadeia de hash (hv3).
    Devolve ``(payload, erro)``: payload com os campos do evento, ou erro
    accionável (incompleto/tipo de documento inválido)."""
    fields = {
        f'receiver_{k}': (request.POST.get(f'receiver_{k}') or '').strip()
        for k in ('nome', 'doc_tipo', 'doc_numero')
    }
    if not all(fields.values()):
        return None, (
            'Identifique quem recebeu a prova: nome completo, tipo e número '
            'do documento (entra na cadeia de hash).'
        )
    if fields['receiver_doc_tipo'] not in ReceiverDocType.values:
        return None, 'Tipo de documento do recetor inválido.'
    return fields, None


def _register_handoff(request, evidences, bearer_fields, destino):
    """Regista ENCAMINHAMENTO_CUSTODIA em cada item (1 evento/item), numa transação
    atómica: portador + destino, custódio promovido pelo tipo do destino, SEM GPS (a
    coordenada regista-se na receção). Reusa o ``ChainOfCustodySerializer`` (guardas
    do ledger, ownership, gate de laboratório, hash, criação da ProvaEmTransito).
    ``bearer_fields``: payload de :func:`_bearer_fields_from_post` (portador
    registado ou pontual — em ambos os casos o snapshot entra na cadeia hv2).
    Devolve lista de erros (vazia = sucesso); qualquer falha reverte tudo."""
    base = {
        'event_type': EventType.ENCAMINHAMENTO_CUSTODIA.value,
        'custodian_institution': destino.id,
        'observations': (request.POST.get('observations') or '').strip(),
        **bearer_fields,
    }
    ctype = custody_transitions.CUSTODIAN_TYPE_BY_INSTITUTION.get(destino.type)
    if ctype:
        base['custodian_type'] = ctype
    return _append_custody_events(
        request, base, evidences, extra_details={'destino': destino.id}
    )


@jwt_cookie_user
def occurrence_encaminhar_view(request, occurrence_id):
    """Encaminhar prova da ocorrência (handoff em LOTE, ADR-0016 v2): entregar
    vários itens a um portador, com destino a uma instituição — 1 evento
    ENCAMINHAMENTO_CUSTODIA por item, SEM GPS (a prova fica em trânsito; a
    coordenada regista-se na receção). Ação in-place (modal) a partir da página da
    ocorrência: o agente regista tudo e depois encaminha a prova junta ("a prova
    não fica no local"). Em sucesso no modal devolve 204 + HX-Redirect.
    """
    user = request.user
    occ = _readable_occurrence(user, occurrence_id)
    if occ is None:
        return HttpResponseNotFound('Ocorrência não encontrada.')

    modal = _wants_modal(request)
    template = _modal_template(modal, 'partials/_encaminhar_form.html', 'occurrence_encaminhar.html')
    itens = _encaminhaveis(user, occ)
    destinos = _active_institutions()
    portadores = _active_portadores()

    submitted = set(request.POST.getlist('evidence_ids')) if request.method == 'POST' else None
    for ev in itens:
        # GET: tudo selecionado; re-render por erro: mantém a escolha do utilizador.
        ev.checked = submitted is None or str(ev.id) in submitted

    def _ctx(errors, data):
        return {
            'occ': occ,
            'itens': itens,
            'destinos': destinos,
            'portadores': portadores,
            'errors': errors,
            'data': data or {},
            'modal': modal,
            'action': f'/occurrences/{occ.id}/encaminhar/',
            'cancel_url': f'/occurrences/{occ.id}/',
        }

    if request.method == 'POST':
        sel = [ev for ev in itens if str(ev.id) in submitted]
        bearer_fields, bearer_err = _bearer_fields_from_post(request)
        dest_id = (request.POST.get('custodian_institution') or '').strip()
        destino = destinos.filter(pk=dest_id).first() if dest_id.isdigit() else None
        errs = []
        if not sel:
            errs.append('Selecione pelo menos um item para encaminhar.')
        if bearer_err:
            errs.append(bearer_err)
        if destino is None:
            errs.append('Indique uma instituição de destino válida.')
        if not errs:
            errs = _register_handoff(request, sel, bearer_fields, destino)
        if not errs:
            messages.success(
                request,
                f'{len(sel)} item(ns) encaminhado(s) para {destino.sigla or destino.name}.',
            )
            return _form_success_response(modal, f'/occurrences/{occ.id}/')
        return render(request, template, _ctx({'geral': errs}, request.POST), status=400)

    return render(request, template, _ctx({}, {}))


def _register_validation(request, evidences, autoridade, justificacao, ts):
    """Regista VALIDACAO_APREENSAO em cada item (ato jurídico — CPP art. 178.º/6):
    sem GPS nem local (a prova não se desloca) e custódio HERDADO do último
    evento do ledger (a validação não muda quem detém a prova).

    O ``timestamp`` do evento é SEMPRE o do servidor (invariante anti-adulteração
    do ledger): a data/hora do DESPACHO declarada pela autoridade entra no texto
    de ``observations`` — que faz parte da fórmula do hash, ficando selada na
    cadeia. Devolve lista de erros (vazia = sucesso); qualquer falha reverte tudo."""
    quando = timezone.localtime(ts).strftime('%d/%m/%Y %H:%M')
    obs = f'Apreensão validada por {autoridade} em {quando}.'
    if justificacao:
        obs = f'{obs} {justificacao}'

    def _payload(ev):
        last = sort_custody_chain(ev.custody_chain.all())[-1]
        p = {
            'evidence': ev.id,
            'event_type': EventType.VALIDACAO_APREENSAO.value,
            'observations': obs,
        }
        if last.custodian_type:
            p['custodian_type'] = last.custodian_type
        if last.custodian_institution_id:
            p['custodian_institution'] = last.custodian_institution_id
        if last.custodian_user_id:
            p['custodian_user'] = last.custodian_user_id
        return p

    return _append_custody_events(
        request, _payload, evidences,
        extra_details={'validated_by': autoridade},
    )


@jwt_cookie_user
def occurrence_validar_view(request, occurrence_id):
    """Validar a apreensão em LOTE (CPP art. 178.º/6) — ação in-place (modal).

    A validação é um ATO JURÍDICO, não uma deslocação: regista QUEM validou,
    QUANDO e a justificação — sem GPS, morada ou mudança de custódio (eixo
    ortogonal ao estado de custódia; ver ``validation_status`` na policy). Um
    evento VALIDACAO_APREENSAO por item selecionado; todos os itens por validar
    vêm pré-selecionados e são desmarcáveis (a autoridade pode validar só
    alguns). Em sucesso no modal devolve 204 + HX-Redirect.
    """
    user = request.user
    occ = _readable_occurrence(user, occurrence_id)
    if occ is None:
        return HttpResponseNotFound('Ocorrência não encontrada.')

    modal = _wants_modal(request)
    template = _modal_template(modal, 'partials/_validar_form.html', 'occurrence_validar.html')
    itens = _validaveis(user, occ)

    submitted = set(request.POST.getlist('evidence_ids')) if request.method == 'POST' else None
    for ev in itens:
        # GET: tudo selecionado; re-render por erro: mantém a escolha do utilizador.
        ev.checked = submitted is None or str(ev.id) in submitted

    def _ctx(errors, data):
        return {
            'occ': occ,
            'itens': itens,
            'errors': errors,
            'data': data if data is not None else {
                'validated_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            },
            'modal': modal,
            'action': f'/occurrences/{occ.id}/validar/',
            'cancel_url': f'/occurrences/{occ.id}/',
        }

    if request.method == 'POST':
        sel = [ev for ev in itens if str(ev.id) in submitted]
        autoridade = (request.POST.get('validated_by') or '').strip()
        justificacao = (request.POST.get('justification') or '').strip()
        raw_ts = (request.POST.get('validated_at') or '').strip()
        ts = parse_datetime(raw_ts) if raw_ts else None
        if ts is not None and timezone.is_naive(ts):
            ts = timezone.make_aware(ts)
        errs = []
        if not sel:
            errs.append('Selecione pelo menos um item para validar.')
        if not autoridade:
            errs.append('Indique quem validou a apreensão (autoridade judiciária).')
        if ts is None:
            errs.append('Indique a data e hora da validação.')
        elif ts > timezone.now():
            errs.append('A data da validação não pode estar no futuro.')
        else:
            # A validação nunca antecede a apreensão que valida. O input só tem
            # granularidade de MINUTO: arredonda-se a apreensão ao minuto para
            # não recusar um despacho no próprio minuto da apreensão.
            for ev in sel:
                seizure = next(
                    (r for r in sort_custody_chain(ev.custody_chain.all())
                     if r.event_type in SEIZURE_GENESIS_EVENTS), None,
                )
                if seizure and ts < seizure.timestamp.replace(second=0, microsecond=0):
                    local = timezone.localtime(seizure.timestamp)
                    errs.append(
                        f'A validação de {ev.code} não pode anteceder a apreensão '
                        f'({local:%d/%m/%Y %H:%M}).'
                    )
        if not errs:
            errs = _register_validation(request, sel, autoridade, justificacao, ts)
        if not errs:
            messages.success(request, f'Apreensão validada: {len(sel)} item(ns).')
            return _form_success_response(modal, f'/occurrences/{occ.id}/')
        return render(request, template, _ctx({'geral': errs}, request.POST), status=400)

    return render(request, template, _ctx({}, None))


def _register_restituicao(request, evidences, receiver_fields, fundamento):
    """Regista RESTITUICAO em cada item (terminal — CPP art. 186.º, termo de
    entrega): custódio passa a PROPRIETARIO e a identidade do recetor entra
    estruturada no evento (e na cadeia de hash, hv3). Sem GPS — a entrega
    formaliza-se no posto, não é uma deslocação rastreada. O ``timestamp`` é
    SEMPRE o do servidor (invariante anti-adulteração); o fundamento/despacho
    fica em ``observations``. Devolve lista de erros (vazia = sucesso);
    qualquer falha reverte tudo."""
    base = {
        'event_type': EventType.RESTITUICAO.value,
        'custodian_type': CustodianType.PROPRIETARIO.value,
        'observations': fundamento,
        **receiver_fields,
    }
    return _append_custody_events(
        request, base, evidences,
        extra_details={'receiver': receiver_fields['receiver_nome']},
    )


@jwt_cookie_user
def occurrence_restituir_view(request, occurrence_id):
    """Restituir prova em LOTE (CPP art. 186.º — termo de entrega) — ação
    in-place (modal).

    A restituição EXTINGUE a cadeia, pelo que o ato exige identificar QUEM
    recebeu: nome completo + tipo e n.º de documento, campos estruturados que
    entram na cadeia de hash (hv3) — pesquisáveis ("tudo o que X recebeu"),
    ao contrário do texto de despacho da validação. Um evento RESTITUICAO por
    item selecionado; os itens elegíveis vêm pré-selecionados e desmarcáveis
    (restitui-se ao mesmo recetor num só termo). Em sucesso no modal devolve
    204 + HX-Redirect.
    """
    user = request.user
    occ = _readable_occurrence(user, occurrence_id)
    if occ is None:
        return HttpResponseNotFound('Ocorrência não encontrada.')

    modal = _wants_modal(request)
    template = _modal_template(modal, 'partials/_restituir_form.html', 'occurrence_restituir.html')
    itens = _restituiveis(user, occ)

    submitted = set(request.POST.getlist('evidence_ids')) if request.method == 'POST' else None
    for ev in itens:
        # GET: tudo selecionado; re-render por erro: mantém a escolha do utilizador.
        ev.checked = submitted is None or str(ev.id) in submitted

    def _ctx(errors, data):
        return {
            'occ': occ,
            'itens': itens,
            'doc_tipos': ReceiverDocType.choices,
            'errors': errors,
            'data': data or {},
            'modal': modal,
            'action': f'/occurrences/{occ.id}/restituir/',
            'cancel_url': f'/occurrences/{occ.id}/',
        }

    if request.method == 'POST':
        sel = [ev for ev in itens if str(ev.id) in submitted]
        receiver_fields, receiver_err = _receiver_fields_from_post(request)
        fundamento = (request.POST.get('justification') or '').strip()
        errs = []
        if not sel:
            errs.append('Selecione pelo menos um item para restituir.')
        if receiver_err:
            errs.append(receiver_err)
        if not errs:
            errs = _register_restituicao(request, sel, receiver_fields, fundamento)
        if not errs:
            messages.success(
                request,
                f'{len(sel)} item(ns) restituído(s) a {receiver_fields["receiver_nome"]}.',
            )
            return _form_success_response(modal, f'/occurrences/{occ.id}/')
        return render(request, template, _ctx({'geral': errs}, request.POST), status=400)

    return render(request, template, _ctx({}, {}))


@jwt_cookie_user
def inbound_view(request):
    """Caixa "prova a chegar" — provas encaminhadas para a(s) instituição(ões) do
    utilizador, ainda por receber (ADR-0016 v2, 2.ª metade do handoff).

    Fecha o ciclo encaminhar→chegar→receber: lista os avisos ``ProvaEmTransito`` por
    reconhecer e cada um liga ao intake da sua ocorrência, onde se regista a RECEÇÃO.
    É surface de :func:`core.access.scope_inbound_transit` — institucional (chaveia no
    DESTINO, não no detentor atual; ``none()`` para quem não pertence a nenhuma
    instituição). O portador é lido do *snapshot* gravado no evento de encaminhamento.
    """
    user = request.user
    notices = list(
        access.scope_inbound_transit(user)
        .select_related(
            'evidence__occurrence',
            'evidence__agent',
            'destino_institution',
            'encaminhamento_event',
        )
        .prefetch_related('evidence__custody_chain')
        .order_by('-created_at', 'evidence__code')
    )
    _decorate_evidences([n.evidence for n in notices])
    for n in notices:
        evt = n.encaminhamento_event
        nome = ' '.join(p for p in (evt.bearer_nome, evt.bearer_apelido) if p).strip()
        n.bearer_label = nome or evt.bearer_matricula or '—'
        n.bearer_mat = evt.bearer_matricula
    return render(request, 'inbound.html', {'notices': notices, 'total': len(notices)})


@jwt_cookie_user
def occurrences_new_view(request):
    """Registo de nova ocorrência — server-rendered + POST via serializer (Fase 3).

    A escrita reusa o ``OccurrenceSerializer`` (validação + derivação de
    prioridade + imutabilidade do modelo) e regista auditoria, tal como a API.
    """
    from core.serializers import OccurrenceSerializer

    user = request.user
    if not access.can_register_records(user):
        return HttpResponseForbidden('Apenas agentes podem registar ocorrências.')

    crime_categories = _crime_categories()
    # Página completa (navegação directa pelo atalho da barra lateral). Sucesso
    # → redireciona para a ocorrência criada; erro → re-render com os erros.
    template = 'occurrences_new.html'

    def _ctx(errors, data):
        """Contexto da página, com a ascendência N1/N2 do crime escolhido
        pré-resolvida para a cascata se re-renderizar após erro."""
        sel_type = (data.get('crime_type') or '') if data else ''
        sel_cat = sel_sub = ''
        if sel_type:
            ct = (
                CrimeTipo.objects.select_related('subcategoria')
                .filter(pk=sel_type)
                .first()
            )
            if ct is not None:
                sel_sub = str(ct.subcategoria_id)
                sel_cat = str(ct.subcategoria.categoria_id)
        return {
            'crime_categories': crime_categories,
            'errors': errors,
            'data': data or {},
            'sel_cat': sel_cat,
            'sel_sub': sel_sub,
            'sel_type': sel_type,
            'action': '/occurrences/new/',
        }

    if request.method == 'POST':
        data = {k: v for k, v in request.POST.items() if v != '' and k != 'csrfmiddlewaretoken'}
        serializer = OccurrenceSerializer(data=data)
        if serializer.is_valid():
            try:
                occ = serializer.save(agent=user)
            except DjangoValidationError as exc:
                return render(
                    request, template, _ctx({'geral': exc.messages}, request.POST), status=400
                )
            log_access(
                request=request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.OCCURRENCE,
                resource_id=occ.pk,
            )
            messages.success(request, f'Ocorrência {occ.code or occ.number} registada.')
            return HttpResponseRedirect(f'/occurrences/{occ.pk}/')
        return render(
            request, template, _ctx(serializer.errors, request.POST), status=400
        )

    # GET: data/hora pré-preenchida com o agora local (ajustável; o input
    # datetime-local usa o formato YYYY-MM-DDTHH:MM). A localização é
    # auto-capturada no cliente (geo-field.js).
    from django.utils import timezone
    initial = {'date_time': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}
    return render(request, template, _ctx({}, initial))


def _wants_modal(request):
    """Pedido em modo modal (ação-in-place)? GET ``?modal=1`` (abrir) ou o
    campo escondido ``modal`` no POST (submeter)."""
    return request.GET.get('modal') == '1' or request.POST.get('modal') == '1'


def _modal_template(modal, partial, page):
    """Template do contrato modal (F7): fragmento para a ação-in-place, página
    completa para o fallback sem-JS/navegação direta (auditoria D5)."""
    return partial if modal else page


def _form_success_response(modal, redirect_url):
    """Sucesso de um formulário com contrato modal (F7): ``204 + HX-Redirect``
    (o HTMX navega e fecha o modal) ou redirect clássico (auditoria D5)."""
    if modal:
        resp = HttpResponse(status=204)
        resp['HX-Redirect'] = redirect_url
        return resp
    return HttpResponseRedirect(redirect_url)


@jwt_cookie_user
def institutions_view(request):
    """Lista de instituições (pontos de controlo fixos) — gestão (staff/NACIONAL).

    As instituições são dados de referência da custódia (não são prova). Esta é a
    casa do gatilho de criação ação-in-place (modal). Passa a usar o gerador único
    (filtros por coluna + HTMX), mantendo o gate de gestão; as linhas NÃO são
    clicáveis (não há gaveta de detalhe). O ``<form method=get>`` é o fallback
    sem-JS; o botão "Nova instituição" e os scripts do mapa vivem na casca.
    """
    user = request.user
    if not access.can_manage_institutions(user):
        return HttpResponseForbidden('Sem permissão para gerir instituições.')

    def apply_inst_state(filtered_qs, _request, value):
        return filtered_qs.filter(is_active=(value == 'active'))

    def decorate_inst(items):
        for inst in items:
            inst.type_label = inst.get_type_display()
            if inst.gps_lat is not None and inst.gps_lng is not None:
                inst.gps_label = f'{inst.gps_lat}, {inst.gps_lng}'   # str(Decimal) = ponto decimal
            else:
                inst.gps_label = '—'
            active = inst.is_active
            inst.state_badge = {'css': 'ok' if active else 'muted',
                                'label': 'Ativa' if active else 'Inativa'}
            inst.dot = {'cls': 'ok' if active else 'muted',
                        'title': 'Ativa' if active else 'Inativa'}

    state_choices = (('active', 'Ativa'), ('inactive', 'Inativa'))
    columns = [
        GridColumn('name', 'Nome', width=24, dot=True,
                   filter=ColFilter('name', 'Nome', kind='text', field='name', placeholder='Nome')),
        GridColumn('type_label', 'Tipo', css='grid__ellipsis', width=18,
                   filter=ColFilter('type', 'Tipo', kind='select', field='type',
                                    choices=tuple(InstitutionType.choices))),
        GridColumn('sigla', 'Sigla', css='mono', width=11,
                   filter=ColFilter('sigla', 'Sigla', kind='text', field='sigla', placeholder='Sigla')),
        GridColumn('address', 'Morada', css='grid__muted col-hide-sm', width=23,
                   filter=ColFilter('address', 'Morada', kind='text', field='address', placeholder='Morada')),
        GridColumn('gps_label', 'GPS', css='mono col-hide-md', width=13),
        GridColumn('state_badge', 'Estado', cell='state', css='col-reduce-hide', width=11,
                   filter=ColFilter('state', 'Estado', kind='select', choices=state_choices)),
    ]

    return grid_list_response(
        request,
        queryset=Institution.objects.order_by('name'),
        columns=columns,
        grid_key='inst',
        endpoint='/institutions/',
        page_template='institutions.html',
        table_label='Instituições',
        count_noun='instituiç', count_plural='ão,ões',
        sorts={'name': 'name'},
        default_sort='name',
        search_fields=('name', 'sigla'),
        search_placeholder='Pesquisar nome ou sigla…',
        decorate=decorate_inst,
        legend=({'cls': 'ok', 'label': 'Ativa'}, {'cls': 'muted', 'label': 'Inativa'}),
        row_clickable=False,
        page_size=25,
        empty_title='Sem instituições',
        empty_hint='Crie o primeiro ponto de controlo com “Nova instituição”.',
        computed_filters={'state': apply_inst_state},
    )


@jwt_cookie_user
def institution_new_view(request):
    """Criação manual de instituição (ponto de controlo) — ADR-0016 Fase 1.

    Reusa o ``InstitutionSerializer`` (obrigatórios nome+tipo+morada+GPS, coerência
    e quantização a 7 casas via ``full_clean``). Serve duas superfícies da MESMA
    lógica: página completa (fallback no-JS / navegação direta) e fragmento modal
    (``?modal=1``, ação-in-place). Em sucesso no modal devolve 204 + ``HX-Redirect``
    (o HTMX navega); em erro devolve o fragmento com os erros e o modal mantém-se.
    """
    from core.serializers import InstitutionSerializer

    user = request.user
    if not access.can_manage_institutions(user):
        return HttpResponseForbidden('Sem permissão para criar instituições.')

    modal = _wants_modal(request)
    template = _modal_template(modal, 'partials/_institution_form.html', 'institution_new.html')

    def _ctx(errors, data):
        return {
            'errors': errors,
            'data': data or {},
            'institution_types': InstitutionType.choices,
            'modal': modal,
            'action': '/institutions/new/',
        }

    if request.method == 'POST':
        fields = ('name', 'type', 'sigla', 'address', 'gps_lat', 'gps_lng', 'email', 'phone')
        data = {k: request.POST[k].strip() for k in fields if request.POST.get(k, '').strip()}
        serializer = InstitutionSerializer(data=data)
        if serializer.is_valid():
            try:
                inst = serializer.save()
            except DjangoValidationError as exc:
                return render(request, template, _ctx({'geral': exc.messages}, request.POST), status=400)
            log_access(
                request=request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.SYSTEM,
                resource_id=inst.pk,
                details={'institution': inst.pk, 'name': inst.name, 'type': inst.type},
            )
            messages.success(request, f'Instituição {inst.sigla or inst.name} criada.')
            return _form_success_response(modal, '/institutions/')
        return render(request, template, _ctx(serializer.errors, request.POST), status=400)

    return render(request, template, _ctx({}, {}))


@jwt_cookie_user
def evidences_view(request):
    """Lista de evidências — server-rendered (Fase 3) via gerador único de grelhas.

    Ownership espelha o EvidenceViewSet (AGENTE vê as suas via occurrence;
    PERITO/staff todas). Estado legal derivado do ledger por linha (filtro
    DERIVADO via computed_filters; a bolinha/legenda refletem-no no telemóvel).
    """
    user = request.user

    drawer = _drawer_dispatch(request, user, _evidence_drawer)
    if drawer is not None:
        return drawer

    lens = access.active_console_mode(request, user)
    qs = _lens_evidences(user, lens)

    # Ordem = colunas: Ocorrência · Código · Data e Hora · Marca · Modelo · Nº série · Estado.
    # Mobile reduzido (col-reduce-hide) sobra Ocorrência · Código (bolinha) · Data; a
    # bolinha em Código carrega o estado legal no telemóvel. Marca/Modelo vivem em
    # type_specific_data (JSON), expostos no decorate; filtro JSON via key-transform (PG).
    columns = [
        GridColumn('occ_label', 'Ocorrência', css='mono', width=15,
                   filter=ColFilter('occ', 'Ocorrência', kind='text', field='occurrence__number', placeholder='NUIPC')),
        GridColumn('code', 'Código', cell='code', width=14, dot=True,
                   filter=ColFilter('code', 'Código', kind='text', field='code', placeholder='Código')),
        GridColumn('timestamp_seizure', 'Data e Hora', cell='date', time=True, width=15,
                   filter=ColFilter('date', 'Data e Hora', kind='date_range', field='timestamp_seizure')),
        GridColumn('marca', 'Marca', css='grid__ellipsis col-reduce-hide', width=14,
                   filter=ColFilter('marca', 'Marca', kind='text', field='type_specific_data__marca', placeholder='Marca')),
        GridColumn('modelo', 'Modelo', css='grid__ellipsis col-reduce-hide', width=14,
                   filter=ColFilter('modelo', 'Modelo', kind='text', field='type_specific_data__modelo', placeholder='Modelo')),
        GridColumn('serial_number', 'Nº série', css='mono grid__muted col-reduce-hide', width=16,
                   filter=ColFilter('serial', 'Nº série', kind='text', field='serial_number', placeholder='Nº série')),
        GridColumn('state_badge', 'Estado', cell='state', css='col-reduce-hide', width=12,
                   val_flag=True,
                   filter=ColFilter('state', 'Estado', kind='select', choices=list(LEGAL_STATE_LABELS.items()))),
    ]

    return grid_list_response(
        request,
        queryset=qs,
        columns=columns,
        grid_key='evd',
        endpoint='/evidences/',
        page_template='evidences.html',
        table_label='Itens de prova',
        count_noun='ite', count_plural='m,ns',
        sorts=_EVD_SORTS,
        default_sort='recent',
        sorts_ui=(('recent', 'Apreensão recente'), ('oldest', 'Apreensão antiga'),
                  ('code', 'Código'), ('occurrence', 'NUIPC')),
        search_fields=('code', 'description', 'serial_number', 'occurrence__number',
                       'type_specific_data__marca', 'type_specific_data__modelo'),
        search_placeholder='Pesquisar código, nº série, marca, NUIPC…',
        decorate=_decorate_evidences,
        legend=URGENCY_LEGEND_EVIDENCE,
        page_size=25,
        lens=lens,
        empty_title='Sem itens de prova',
        empty_hint='Ainda não há itens registados.',
        # Estado legal deriva da cadeia COMPLETA dos itens da zona ativa (WI-E).
        computed_filters={
            'state': _state_filter(
                lambda: analytics.legal_states_by_evidence(_lens_custody(user, lens))
            )
        },
    )


def _evd_field_ctx(post):
    """(transversais, por-tipo) para o formulário de evidência, cada campo com o
    valor atual (re-preenche após erro). A lista por-tipo é plana, marcada com o
    tipo para o JS mostrar/esconder; os transversais aparecem sempre."""
    def _v(field):
        return (post.get(field['key']) or '').strip() if hasattr(post, 'get') else ''

    transversal = [{**f, 'value': _v(f)} for f in evidence_field_config.transversal_fields()]
    # type_fields_flat() já marca cada campo com 'type' (para o JS mostrar/esconder).
    type_fields = [{**f, 'value': _v(f)} for f in evidence_field_config.type_fields_flat()]
    return transversal, type_fields


@jwt_cookie_user
def evidences_new_view(request):
    """Registo de nova evidência — server-rendered + POST via serializer (Fase 3).

    Reusa o ``EvidenceSerializer`` (validação por tipo, hash de integridade,
    imutabilidade) e regista auditoria com o hash, tal como a API.
    """
    from core.serializers import EvidenceSerializer

    user = request.user
    if not access.can_register_records(user):
        return HttpResponseForbidden('Apenas agentes podem registar evidências.')

    occurrences = _scope_occurrences(user).order_by('-date_time')
    parents = _scope_evidences(user).order_by('occurrence__number', 'code')
    transversal_fields, type_fields = _evd_field_ctx(
        request.POST if request.method == 'POST' else {}
    )
    # Página completa (navegação directa pelo atalho da barra lateral). Sucesso
    # → redireciona para o item criado; erro → re-render com os erros.
    template = 'evidences_new.html'

    def _ctx(errors, data, preselect):
        """Contexto único da página (antes copiado 3× — auditoria D4).

        ``data`` é o input cru (não validated_data), intencional: repopula o
        ``<select>`` com a PK em string (casa com o value da opção); é um
        serializer DRF, não um Form, e o re-render mostra o que foi submetido."""
        return {
            'occurrences': occurrences,
            'parents': parents,
            'evidence_types': evidence_type_config.active_choices(),
            'transversal_fields': transversal_fields,
            'type_fields': type_fields,
            'preselect': preselect,  # nosemgrep
            'errors': errors,
            'data': data,  # nosemgrep
            'action': '/evidences/new/',
        }

    if request.method == 'POST':
        tsd_keys = evidence_field_config.all_keys()
        data = {
            k: v
            for k, v in request.POST.items()
            if v != '' and k != 'csrfmiddlewaretoken' and k not in tsd_keys
        }
        tsd = {k: request.POST[k].strip() for k in tsd_keys if request.POST.get(k, '').strip()}
        if tsd:
            data['type_specific_data'] = tsd
        if request.FILES.get('photo'):
            data['photo'] = request.FILES['photo']

        serializer = EvidenceSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            from django.db import transaction
            try:
                # Registo = apreensão: o item e a sua génese de custódia nascem na
                # MESMA transação (se a génese falhar, o item não persiste).
                with transaction.atomic():
                    ev = serializer.save(agent=user)
                    _register_seizure_genesis(request, ev)
            except (DjangoValidationError, DRFValidationError) as exc:
                return render(
                    request,
                    template,
                    _ctx({'geral': _flatten_validation_error(exc)}, request.POST,
                         request.POST.get('occurrence', '')),
                    status=400,
                )
            log_access(
                request=request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.EVIDENCE,
                resource_id=ev.pk,
                details={'hash': ev.integrity_hash},
            )
            messages.success(request, f'Item de prova {ev.code} apreendido e registado.')
            return HttpResponseRedirect(f'/evidences/{ev.pk}/')
        return render(
            request,
            template,
            _ctx(serializer.errors, request.POST, request.POST.get('occurrence', '')),
            status=400,
        )

    return render(request, template, _ctx({}, {}, request.GET.get('occurrence', '')))


def _decorate_events(events):
    """Anota cada evento do ledger com rótulos PT e hash curto (apresentação)."""
    flag_m = settings.GPS_ACCURACY_FLAG_M
    for r in events:
        r.event_label = r.get_event_type_display()
        r.custodian_label = r.get_custodian_type_display() if r.custodian_type else '—'
        r.agent_label = get_user_display_name(r.agent)
        r.hash_short = (r.record_hash or '')[:16]
        r.aria_code = r.code or r.event_label   # rótulo da linha (fallback evento)
        # Precisão pior que o limiar único (settings.GPS_ACCURACY_FLAG_M) é
        # assinalada; o template testa só a flag (sem literais de limiar).
        r.acc_flagged = bool(r.gps_accuracy_m and r.gps_accuracy_m > flag_m)
        # Termo de entrega (hv3): quem recebeu a prova fora do sistema —
        # apresentado na timeline/gaveta junto do evento (restituição/depositário).
        r.receiver_label = (
            f'{r.receiver_nome} · {r.get_receiver_doc_tipo_display()} '
            f'n.º {r.receiver_doc_numero}'
            if r.receiver_nome else ''
        )


def _chain_points(events):
    """Pontos georreferenciados do ledger (para o mapa da cadeia, modo Cadeia).

    Coordenadas como float → json.dumps usa ponto decimal (nunca a vírgula
    PT-PT que partiria o parseFloat no cliente).
    """
    pts = []
    for r in events:
        if r.gps_lat is None or r.gps_lng is None:
            continue
        label = f'M{r.sequence:02d} · {r.get_event_type_display()} · {r.timestamp:%d/%m %H:%M}'
        if r.gps_accuracy_m:
            label += f' · ±{r.gps_accuracy_m}m'
        pts.append({'lat': float(r.gps_lat), 'lng': float(r.gps_lng), 'label': label})
    return pts


@jwt_cookie_user
def evidence_detail_view(request, evidence_id):
    """Detalhe de uma evidência — hub do item, server-rendered (Fase 3)."""
    user = request.user
    ev = _readable_evidence(user, evidence_id)
    if ev is None:
        return HttpResponseNotFound('Evidência não encontrada.')
    _decorate_evidences([ev])
    events = sort_custody_chain(ev.custody_chain.all())
    _decorate_events(events)
    sub_components = list(ev.sub_components.select_related('agent').order_by('id'))
    _decorate_evidences(sub_components)
    valid_next = _valid_next_events(events, ev)
    return render(
        request,
        'evidence_detail.html',
        {
            'ev': ev,
            'events': events,
            'sub_components': sub_components,
            'chain_json': json.dumps(_chain_points(events), ensure_ascii=False),
            # Mesma fonte única da página de custódia (policy.next_events): ledger
            # fechado ⇒ não se oferece «Registar evento» (auditoria D96).
            'ledger_closed': not valid_next,
            # Atos com modal dedicado na ocorrência (formulário único do ato),
            # aceitáveis já (não em trânsito/terminal): validação e restituição.
            'can_validate': any(
                v == EventType.VALIDACAO_APREENSAO.value for v, _ in valid_next
            ),
            'can_restitute': any(
                v == EventType.RESTITUICAO.value for v, _ in valid_next
            ),
        },
    )


def _genesis_event_for(evidence):
    """Evento de génese aplicável à evidência, por proveniência (ADR-0016 §2).

    Fina ponte para a fonte única ``custody_transitions.genesis_event_for``
    (ADR-0019): traduz a evidência (pode ser ``None``) nos dois sinais de
    proveniência e delega a regra.
    """
    has_parent = evidence is not None and evidence.parent_evidence_id is not None
    is_digital_file = (
        evidence is not None
        and evidence.type == Evidence.EvidenceType.DIGITAL_FILE
    )
    return custody_transitions.genesis_event_for(
        has_parent=has_parent, is_digital_file=is_digital_file
    )


def _register_seizure_genesis(request, ev):
    """Registar é apreender: o 1.º evento de génese da prova é
    criado no PRÓPRIO ato de registo do item — não há prova registada sem ficar
    sob custódia (ADR-0016 §2).

    Só para itens-RAIZ (APREENSAO_OBJETO / APREENSAO_DADOS, conforme a proveniência);
    um sub-componente (com evidência-pai) entra por DERIVACAO_ITEM, que é ato do
    perito e fica fora deste atalho. Custódio = OPC da instituição do agente (se
    tiver pertença); GPS herdado do local da apreensão do item (se captado). Reusa
    o ``ChainOfCustodySerializer`` — mesmas guardas, ownership (génese pelo agente)
    e hash encadeado. Corre dentro da mesma transação do registo da evidência.
    """
    if ev.parent_evidence_id is not None:
        return  # sub-componente: a génese por derivação é ato do perito (manual)
    genesis = _genesis_event_for(ev)  # APREENSAO_OBJETO ou APREENSAO_DADOS
    data = {
        'evidence': ev.id,
        'event_type': genesis.value,
        'custodian_type': CustodianType.OPC,
    }
    inst_id = (
        request.user.institution_memberships.filter(is_active=True)
        .values_list('institution_id', flat=True)
        .first()
    )
    if inst_id:
        data['custodian_institution'] = inst_id
    if ev.gps_lat is not None and ev.gps_lng is not None:
        data['gps_lat'] = ev.gps_lat
        data['gps_lng'] = ev.gps_lng
    # propagate=True: corre DENTRO da transação do registo do item e a exceção
    # sobe — se a génese falhar, o item não persiste (auditoria D1).
    _append_custody_events(
        request, data, [ev], extra_details={'genesis': True}, propagate=True
    )


def _valid_next_events(events, evidence=None):
    """(value, label) dos ``EventType`` que as guardas de ``ChainOfCustody.clean()``
    aceitariam como PRÓXIMO evento, dado o ledger atual e (na génese) a
    proveniência da evidência — ADR-0016 §2.

    Espelha apenas as regras BLOQUEANTES (não as advisory de 72h): 1.º evento =
    génese (objeto/dados/derivação conforme a evidência); a génese só pode ser o
    1.º; nenhum evento após terminal; VALIDAÇÃO_APREENSÃO exige apreensão prévia
    e só uma vez; INÍCIO_PERÍCIA exige DESPACHO_PERÍCIA prévio. Movimentação em
    dois tempos (ADR-0016 v2): em trânsito (último = ENCAMINHAMENTO) só admite a
    RECEPCAO; a RECEPCAO só se oferece nesse caso. ``TRANSFERENCIA``/``ASSUNCAO``
    (LEGADO) já não são oferecidos. O backend (serializer + clean) continua a ser
    a fonte de verdade — isto é só para não oferecer transições impossíveis.
    """
    prior_types = [e.event_type for e in events]
    has_parent = evidence is not None and evidence.parent_evidence_id is not None
    is_digital_file = (
        evidence is not None
        and evidence.type == Evidence.EvidenceType.DIGITAL_FILE
    )
    return [
        (et.value, et.label)
        for et in custody_transitions.next_events(
            prior_types, has_parent=has_parent, is_digital_file=is_digital_file
        )
    ]


def _flatten_validation_error(exc):
    """Lista de mensagens legíveis a partir de um ValidationError (DRF ou Django)."""
    detail = getattr(exc, 'detail', None)
    msgs = []
    if isinstance(detail, dict):
        for value in detail.values():
            msgs.extend(str(v) for v in (value if isinstance(value, (list, tuple)) else [value]))
    elif isinstance(detail, (list, tuple)):
        msgs.extend(str(v) for v in detail)
    elif hasattr(exc, 'messages'):
        msgs.extend(exc.messages)
    else:
        msgs.append(str(exc))
    return msgs


def _append_custody_events(request, base_payload, targets, *, extra_details=None, propagate=False):
    """Regista UM evento de custódia por alvo via ``ChainOfCustodySerializer``,
    em transação atómica com auditoria por registo — esqueleto ÚNICO do registo
    em lote (handoff, formulário da timeline, génese no registo do item, receção
    no intake — auditoria D1). O serializer mantém as guardas do ledger, o
    ownership e o hash encadeado.

    ``base_payload``: dict comum (o ``evidence`` é injetado por alvo) OU uma
    função ``f(alvo) -> payload completo`` quando o payload varia por item (ex.:
    o ``location_name`` da receção vem do destino de cada encaminhamento).
    ``extra_details``: dict ou ``f(record) -> dict`` juntos aos detalhes base da
    auditoria (``evidence_id`` + ``event_type``).

    Devolve a lista de erros achatada (vazia = sucesso). Com ``propagate=True``
    NÃO abre transação própria nem captura: a exceção sobe para reverter a
    transação envolvente (caso da génese, que corre dentro da transação do
    registo do item).
    """
    from django.db import transaction

    from core.serializers import ChainOfCustodySerializer

    def _run():
        for tgt in targets:
            payload = (
                base_payload(tgt) if callable(base_payload)
                else dict(base_payload, evidence=tgt.id)
            )
            serializer = ChainOfCustodySerializer(data=payload, context={'request': request})
            serializer.is_valid(raise_exception=True)
            record = serializer.save(agent=request.user)
            details = {'evidence_id': record.evidence_id, 'event_type': record.event_type}
            if extra_details:
                details.update(
                    extra_details(record) if callable(extra_details) else extra_details
                )
            log_access(
                request=request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.CUSTODY,
                resource_id=record.pk,
                details=details,
            )

    if propagate:
        _run()
        return []
    try:
        with transaction.atomic():
            _run()
    except (DRFValidationError, DjangoValidationError) as exc:
        return _flatten_validation_error(exc)
    return []


def _register_custody_event(request, evidence, targets):
    """Regista um evento de custódia em ``targets`` (evidência + opcionalmente
    sub-componentes) via ``ChainOfCustodySerializer``, numa transação atómica.

    Reusa o serializer validado (guardas do ledger + ownership + imutabilidade +
    hash encadeado) e regista auditoria por registo. Devolve lista de erros
    (vazia = sucesso). Em qualquer falha, a transação reverte por completo.
    """
    event_type = (request.POST.get('event_type') or '').strip()
    if not event_type:
        return ['Selecione o tipo de evento.']

    base = {
        'event_type': event_type,
        'custodian_type': (request.POST.get('custodian_type') or '').strip(),
        'location_name': (request.POST.get('location_name') or '').strip(),
        'storage_location': (request.POST.get('storage_location') or '').strip(),
        'observations': (request.POST.get('observations') or '').strip(),
    }
    # Custódia institucional / pessoal (ADR-0017) + portador no encaminhamento
    # (ADR-0016 v2) — opcionais.
    for fk in ('custodian_institution', 'custodian_user', 'relinquished_by', 'bearer'):
        val = (request.POST.get(fk) or '').strip()
        if val:
            base[fk] = val
    # Portador PONTUAL (não registado): snapshot direto no evento — o clean()
    # exige nome+apelido+matrícula no encaminhamento; com FK, o save() sobrepõe.
    for fld in ('bearer_nome', 'bearer_apelido', 'bearer_matricula', 'bearer_posto'):
        val = (request.POST.get(fld) or '').strip()
        if val:
            base[fld] = val
    # Selagem por-evento (ADR-0016 §4) — opcionais.
    if request.POST.get('sealed'):
        base['sealed'] = True
    seal_cond = (request.POST.get('seal_condition_on_receipt') or '').strip()
    if seal_cond:
        base['seal_condition_on_receipt'] = seal_cond
    new_seal = (request.POST.get('new_seal_number') or '').strip()
    if new_seal:
        base['new_seal_number'] = new_seal
    gps_lat = (request.POST.get('gps_lat') or '').strip()
    gps_lng = (request.POST.get('gps_lng') or '').strip()
    if gps_lat and gps_lng:
        base['gps_lat'] = gps_lat
        base['gps_lng'] = gps_lng
        acc = (request.POST.get('gps_accuracy_m') or '').strip()
        if acc:
            base['gps_accuracy_m'] = acc

    return _append_custody_events(
        request, base, targets,
        extra_details=lambda r: {'custodian_type': r.custodian_type},
    )


@jwt_cookie_user
def custody_timeline_view(request, evidence_id):
    """Timeline geo-rastreável + registo de eventos de custódia (Fase 3, WI-A).

    GET renderiza o trajeto + ledger + formulário inline de registo (só com os
    eventos que as guardas aceitariam). POST regista o evento (e, opcionalmente,
    nos sub-componentes em cascata atómica) via ``ChainOfCustodySerializer`` e
    redireciona (PRG); em erro re-renderiza com o formulário aberto.
    """
    user = request.user
    # Leitura: item-level OU processo da instituição (consola). A ESCRITA (POST)
    # é governada à parte pelo ChainOfCustodySerializer (can_append_custody,
    # fail-closed) — abrir a timeline não concede direito de registar eventos.
    ev = _readable_evidence(user, evidence_id)
    if ev is None:
        return HttpResponseNotFound('Evidência não encontrada.')

    sub_components = list(ev.sub_components.order_by('id'))
    register_errors = []
    if request.method == 'POST':
        targets = [ev]
        if request.POST.get('apply_subcomponents'):
            targets += sub_components
        register_errors = _register_custody_event(request, ev, targets)
        if not register_errors:
            messages.success(request, 'Evento de custódia registado.')
            return HttpResponseRedirect(f'/evidences/{ev.id}/custody/')

    _decorate_evidences([ev])
    events = sort_custody_chain(ev.custody_chain.all())
    _decorate_events(events)
    valid_events = _valid_next_events(events, ev)
    # Atos com formulário PRÓPRIO (modal da ocorrência): a VALIDAÇÃO certifica
    # quem validou/data do despacho/justificação (CPP 178.º/6) e a RESTITUIÇÃO
    # exige a identidade de quem recebeu (CPP 186.º — termo de entrega). Saem
    # do select genérico para não existir um 2.º caminho sem esses campos. As
    # guardas do modelo não mudam; cada flag liga o botão dedicado.
    dedicated = {EventType.VALIDACAO_APREENSAO.value, EventType.RESTITUICAO.value}
    register_events = [(v, label) for v, label in valid_events if v not in dedicated]
    valid_values = {v for v, _ in valid_events}
    can_validate = EventType.VALIDACAO_APREENSAO.value in valid_values
    can_restitute = EventType.RESTITUICAO.value in valid_values
    return render(
        request,
        'custody_timeline.html',
        {
            'ev': ev,
            'events': events,
            'chain_json': json.dumps(_chain_points(events), ensure_ascii=False),
            'valid_events': register_events,
            'can_validate': can_validate,
            'can_restitute': can_restitute,
            'custodian_types': CustodianType.choices,
            'institutions': _active_institutions(),
            # Portadores ativos para o select do ENCAMINHAMENTO (ADR-0016 v2).
            'portadores': _active_portadores(),
            'seal_conditions': Evidence.SealCondition.choices,
            'sub_components': sub_components,
            'ledger_closed': not valid_events,
            'register_errors': register_errors,
            'register_data': request.POST if request.method == 'POST' else {},
        },
    )


_CUSTODY_SORTS = {
    'recent': '-timestamp',
    'oldest': 'timestamp',
    'evidence': 'evidence__code',
}


def _readable_custody(user, pk):
    """Evento de custódia por ``pk`` se o utilizador pode LER o seu item na consola
    (item-level ``can_view_evidence`` OU processo da instituição —
    :func:`_readable_evidence`); ``None`` caso contrário."""
    return _readable(
        _custody_base_qs(), pk,
        lambda rec: access.can_view_evidence(user, rec.evidence),
        lambda rec: access.is_occurrence_institutional(user, rec.evidence.occurrence),
    )


def _custody_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de um evento de custódia."""
    return _drawer_response(
        request, user, drawer_id,
        fetch=_readable_custody, decorate=_decorate_events,
        template='partials/_custody_drawer.html', ctx_key='r',
        not_found='Registo de custódia não encontrado.',
    )


@jwt_cookie_user
def custody_list_view(request):
    """Lista do ledger de custódia — server-rendered (Fase 3) via gerador único.

    Filtros por coluna iguais às ocorrências, INCLUSIVE Instituição titular e
    Estado legal DERIVADO do item (computed_filters). A bolinha/legenda mostram o
    estado legal no telemóvel (mesma fonte das evidências)."""
    user = request.user

    drawer = _drawer_dispatch(request, user, _custody_drawer)
    if drawer is not None:
        return drawer

    lens = access.active_console_mode(request, user)
    # evidence já vem de _lens_custody; redeclara-se aqui (com a instituição) para
    # tornar explícita a dependência do gerador (cellattr 'evidence.code' + estado).
    qs = _lens_custody(user, lens).select_related('custodian_institution', 'evidence')

    institutions = _active_institutions()
    inst_choices = tuple((i.id, i.sigla or i.name) for i in institutions)

    # Estados legais derivados da lente, calculados UMA vez por request e
    # partilhados entre o filtro computado e a decoração (auditoria D9).
    _states_memo = {}

    def _lens_states():
        if 'v' not in _states_memo:
            _states_memo['v'] = analytics.legal_states_by_evidence(
                _lens_custody(user, lens)
            )
        return _states_memo['v']

    def decorate_custody(events):
        _decorate_events(events)
        states = _lens_states()
        # Eixo da validação (marcador pendente por linha) — bulk, só na página.
        val_statuses = analytics.validation_statuses_by_evidence(
            ChainOfCustody.objects.filter(
                evidence_id__in={r.evidence_id for r in events}
            )
        )
        for r in events:
            st = states.get(r.evidence_id)
            label = LEGAL_STATE_LABELS.get(st, 'Sem custódia')
            css = LEGAL_STATE_CSS.get(st, 'muted')
            r.state_badge = {'css': css, 'label': label}
            r.dot = {'cls': css, 'title': label}          # bolinha mobile = estado legal
            vs = val_statuses.get(r.evidence_id)
            r.val_dot = (
                {'cls': VALIDATION_STATUS_CSS[vs], 'title': VALIDATION_STATUS_LABELS[vs]}
                if vs in VALIDATION_PENDING_STATUSES else None
            )
            inst = r.custodian_institution
            r.institution_label = (inst.sigla or inst.name) if inst else '—'

    columns = [
        GridColumn('code', 'Código', cell='code', width=11, dot=True,
                   filter=ColFilter('code', 'Código', kind='text', field='code', placeholder='Código')),
        GridColumn('evidence.code', 'Item', css='mono', width=11,
                   filter=ColFilter('item', 'Item', kind='text', field='evidence__code', placeholder='Item')),
        GridColumn('event_label', 'Evento', css='grid__ellipsis col-reduce-hide', width=15,
                   filter=ColFilter('event', 'Evento', kind='select', field='event_type',
                                    choices=tuple(EventType.choices))),
        GridColumn('custodian_label', 'Custódio', css='grid__muted col-hide-sm', width=13,
                   filter=ColFilter('custodian', 'Custódio', kind='select', field='custodian_type',
                                    choices=tuple(CustodianType.choices))),
        GridColumn('institution_label', 'Instituição', css='grid__muted col-reduce-hide', width=13,
                   filter=ColFilter('institution', 'Instituição', kind='select',
                                    field='custodian_institution_id', choices=inst_choices)),
        GridColumn('state_badge', 'Estado', cell='state', css='col-reduce-hide', width=11,
                   val_flag=True,
                   filter=ColFilter('state', 'Estado', kind='select', choices=list(LEGAL_STATE_LABELS.items()))),
        GridColumn('timestamp', 'Data / hora', cell='date', time=True, width=16,
                   filter=ColFilter('date', 'Data / hora', kind='date_range', field='timestamp')),
        GridColumn('hash_short', 'Hash', suffix='…', css='mono grid__muted col-hide-md', width=10),
    ]

    return grid_list_response(
        request,
        queryset=qs,
        columns=columns,
        grid_key='cc',
        endpoint='/custodies/',
        page_template='custody_list.html',
        table_label='Eventos de custódia',
        count_noun='evento',
        sorts=_CUSTODY_SORTS,
        default_sort='recent',
        sorts_ui=(('recent', 'Mais recentes'), ('oldest', 'Mais antigos'),
                  ('evidence', 'Por item')),
        search_fields=('code', 'evidence__code', 'evidence__occurrence__number'),
        search_placeholder='Pesquisar item, NUIPC, código…',
        decorate=decorate_custody,
        legend=URGENCY_LEGEND_EVIDENCE,
        page_size=30,
        lens=lens,
        empty_title='Sem eventos de custódia',
        empty_hint='Ainda não há eventos registados.',
        computed_filters={'state': _state_filter(_lens_states, fk='evidence_id')},
    )


@jwt_cookie_user
def audit_console_view(request):
    """Consola de Auditoria & Integridade (UX 2026-06) — substitui o placeholder
    legado ``investigation_report``.

    Três leituras, todas no universo visível ao perfil (need-to-know, lente ativa):

    1. **Integridade da cadeia de hash** — :func:`core.integrity.verify_chains`
       recalcula o ``record_hash`` encadeado de cada item e assinala quebras
       (adulteração de campo ou elo partido). É a prova técnica de não-adulteração.
    2. **Anomalias de custódia** — :func:`core.integrity.detect_anomalies` (génese
       ausente, prova encaminhada por receber, custódio em falta).
    3. **Trilho de auditoria** — feed do ``AuditLog`` (quem viu/criou/exportou),
       reaproveitando :func:`_activity_feed` (mesma regra de acesso da API).

    O cálculo de integridade vive na fonte única ``core.integrity``; a fórmula do
    hash não é duplicada (chama ``compute_record_hash``). CSP-safe, server-rendered.
    """
    user = request.user
    lens = access.active_console_mode(request, user)
    evidence_ids = list(_lens_evidences(user, lens).values_list('id', flat=True))
    return render(
        request,
        'audit_console.html',
        {
            'lens': lens,
            'chain': integrity.verify_chains(evidence_ids),
            'anomalies': integrity.detect_anomalies(evidence_ids),
            'logs': _activity_feed(user, limit=30),
            'feed_is_national': access.has_national_read(user),
        },
    )


@jwt_cookie_user
def reports_view(request):
    """Guias de transporte (PDF por ocorrência) — server-rendered (Fase 3) via
    gerador único. Linhas NÃO-clicáveis: o Código liga ao detalhe da ocorrência e
    a coluna Guia descarrega o PDF; filtros por coluna iguais às ocorrências."""
    user = request.user
    lens = access.active_console_mode(request, user)
    # distinct=True: o join multi-valor da lente institucional multiplicava a
    # contagem por evento de custódia (mesmo defeito corrigido no painel).
    qs = _lens_occurrences(user, lens).annotate(n_ev=Count('evidences', distinct=True))

    cat_choices = _crime_cat_choices()

    def decorate_reports(items):
        _decorate_occurrences(items)
        for o in items:
            o.detail_href = f'/occurrences/{o.id}/'
            # Caminho do PDF pela rota nomeada do router (fonte única — D103).
            o.guia = {'href': reverse('core:occurrence-export-pdf', args=[o.id]), 'label': 'PDF',
                      'aria': f'Descarregar guia PDF de {o.code}'}

    columns = [
        GridColumn('pri', 'Pri.', cell='pri', css='col-reduce-hide', width=6),
        GridColumn('code', 'Código', cell='code', width=15, dot=True, link_key='detail_href',
                   filter=ColFilter('code', 'Código', kind='text', field='code', placeholder='Código')),
        GridColumn('number', 'NUIPC', css='mono', width=18,
                   filter=ColFilter('number', 'NUIPC', kind='text', field='number', placeholder='NUIPC')),
        GridColumn('crime_label', 'Tipo de crime', css='grid__ellipsis col-hide-md', width=27,
                   filter=ColFilter('cat', 'Tipo de crime', kind='select',
                                    field='crime_type__subcategoria__categoria_id', choices=cat_choices)),
        GridColumn('n_ev', 'Itens', cell='num', css='col-hide-sm', width=9),
        GridColumn('date_time', 'Data', cell='date', time=False, css='col-hide-sm', width=13,
                   filter=ColFilter('date', 'Data', kind='date_range', field='date_time')),
        GridColumn('guia', 'Guia', cell='action', width=12),
    ]

    return grid_list_response(
        request,
        queryset=qs,
        columns=columns,
        grid_key='rpt',
        endpoint='/reports/',
        page_template='reports.html',
        table_label='Guias de transporte',
        count_noun='ocorrência',
        sorts={'recent': '-date_time'},
        default_sort='recent',
        search_fields=('number', 'code', 'address'),
        search_placeholder='Pesquisar código, NUIPC, morada…',
        decorate=decorate_reports,
        legend=URGENCY_LEGEND_OCCURRENCE,
        row_clickable=False,
        page_size=30,
        lens=lens,
        empty_title='Sem ocorrências',
        empty_hint='Ainda não há ocorrências para gerar guias.',
    )


@jwt_cookie_user
def occurrence_intake_view(request, occurrence_id):
    """Página de check-list de RECEÇÃO (2.ª metade do handoff, ADR-0016 v2).

    Recebe a prova em trânsito: regista um ``RECEPCAO_CUSTODIA`` por item marcado,
    em lote atómico, reusando o ``ChainOfCustodySerializer`` (herda destino/custódio
    do encaminhamento e, em instituição fixa, a coordenada do registo da instituição).

    Requisitos de auth (impostos no servidor antes do render):
    1. JWT válido em cookie `fq_access` (decorator canónico ``jwt_cookie_user``,
       que popula ``request.user`` — antes havia aqui uma reimplementação manual
       do decode, com um ``?next=`` que o login nem honrava; auditoria D12).
    2. Pode receber: EXPERT/staff (intake de laboratório) OU membro da instituição
       de destino de um encaminhamento pendente desta ocorrência (receção OPC→OPC —
       alinha com a caixa "prova a chegar"). A ESCRITA é, ainda assim, validada por
       ``can_append_custody`` no serializer.

    Quem não cumpra recebe HTTP 403.
    """
    user = request.user
    occurrence = Occurrence.objects.filter(pk=occurrence_id).first()
    # Quem pode RECEBER (abrir o intake): operador de laboratório (EXPERT) ou staff
    # — E TAMBÉM um membro da instituição de destino de um encaminhamento pendente
    # DESTA ocorrência. Sem este último ramo, a receção OPC→OPC fica num beco: a
    # caixa "prova a chegar" mostra o item ao membro do destino, mas o intake
    # recusava-o (403). A porta de ESCRITA real continua no serializer
    # (can_append_custody, fail-closed); aqui decide-se só quem vê/usa o formulário.
    can_receive = (
        user.is_superuser
        or access.is_expert_or_staff(user)
        or access.has_inbound_for_occurrence(user, occurrence)
    )
    if not can_receive:
        return render(request, '403_intake.html', status=403)
    if occurrence is None:
        return render(request, '404.html', status=404)

    # Para cada evidência: estado legal DERIVADO (ADR-0015) da sequência de
    # eventos. "Já recebida" = já encaminhada para laboratório ou além.
    from core.models import ChainOfCustody, EventType, Evidence

    evidences = list(Evidence.objects.filter(occurrence=occurrence).order_by('code', 'id'))
    # Agrupamento ledger→estado na fonte única (uma só query para TODOS os
    # eventos da ocorrência); with_events devolve também os registos agrupados,
    # de onde se lê o destino do último encaminhamento de cada item.
    states, eventos_por_ev = analytics.legal_states_by_evidence(
        ChainOfCustody.objects.filter(evidence__occurrence=occurrence),
        with_events=True,
        related=('custodian_institution',),
    )
    state_by_evidence = {ev.id: states.get(ev.id, '') for ev in evidences}

    # Instituição(ões) de DESTINO onde a prova é recebida — derivada do último
    # encaminhamento de cada item em trânsito. Em trânsito ⇒ o último evento É o
    # ENCAMINHAMENTO_CUSTODIA (derive_legal_state), logo o seu `custodian_institution`
    # é o destino. A coordenada e o local da receção vêm DESTE registo (não se pedem
    # ao operador): a instituição é fixa e já tem GPS/morada na ficha. Pré-selecionar
    # o destino aqui torna a receção um gesto de confirmação, não de captura.
    reception_institutions = []
    _seen_inst = set()
    for ev in evidences:
        if state_by_evidence[ev.id] != 'em_transito':
            continue
        destino = eventos_por_ev[ev.id][-1].custodian_institution
        if destino is not None and destino.id not in _seen_inst:
            _seen_inst.add(destino.id)
            reception_institutions.append(destino)

    # POST — registar a RECEÇÃO (fase 2 do handoff, ADR-0016 v2) dos itens em
    # trânsito marcados, em lote atómico, reusando o ChainOfCustodySerializer. O
    # destino/custódio e (em instituição fixa) a coordenada são herdados do
    # encaminhamento no clean() do modelo; aqui passa-se só o item + metadados.
    intake_errors = []
    if request.method == 'POST':
        selected = set(request.POST.getlist('evidence_ids'))
        storage = (request.POST.get('storage_location') or '').strip()
        observations = (request.POST.get('observations') or '').strip()
        # GPS e local NÃO se pedem na receção: a instituição de destino é fixa e o seu
        # registo (coordenada + morada) é a fonte. O clean() do modelo copia o GPS da
        # instituição herdada do encaminhamento; aqui só se deriva o `location_name`
        # (rótulo legível no ledger) do mesmo destino. Pedir captura de GPS num
        # laboratório com coordenada já conhecida seria ruído (ADR-0016 v2 — GPS só no
        # terreno).
        to_receive = [
            ev
            for ev in evidences
            if str(ev.id) in selected and state_by_evidence[ev.id] == 'em_transito'
        ]
        if not to_receive:
            intake_errors.append(
                'Selecione pelo menos um item em trânsito (encaminhado, ainda por receber).'
            )
        else:
            def _payload(ev):
                # Rótulo de local = nome da instituição de destino (herdado do
                # encaminhamento). O FK custodian_institution identifica o
                # destino com precisão; location_name é só a etiqueta legível.
                p = {'evidence': ev.id, 'event_type': EventType.RECEPCAO_CUSTODIA}
                destino = eventos_por_ev[ev.id][-1].custodian_institution
                if destino is not None:
                    p['location_name'] = destino.name
                if storage:
                    p['storage_location'] = storage
                if observations:
                    p['observations'] = observations
                return p

            try:
                # Esqueleto único do registo em lote (auditoria D1): loop atómico
                # + serializer + auditoria; os erros de validação (guardas do
                # ledger, GPS, permissão) voltam achatados — accionáveis e
                # seguros de mostrar ao operador.
                intake_errors = _append_custody_events(
                    request, _payload, to_receive,
                    extra_details=lambda r: {'custodian_type': r.custodian_type},
                )
            except Exception:  # noqa: BLE001 — falha inesperada → rollback (atomic) + msg genérica
                # NÃO interpolar a excepção crua na página (fuga de detalhe interno
                # + mascarava o erro real). Regista-se o stack trace e mostra-se
                # uma mensagem genérica.
                logger.exception('Falha inesperada no intake da ocorrência %s', occurrence.id)
                intake_errors.append(
                    'Falha no registo. A operação foi revertida; tente novamente '
                    'ou contacte o suporte se persistir.'
                )
            if not intake_errors:
                messages.success(
                    request,
                    f'Receção registada: {len(to_receive)} item(ns).',
                )
                return HttpResponseRedirect(f'/occurrences/{occurrence.id}/')

    rows = [
        {
            'evidence': ev,
            'current_state': state_by_evidence[ev.id],
            'current_state_display': LEGAL_STATE_LABELS.get(state_by_evidence[ev.id])
            or 'Sem custódia',
            'current_state_css': LEGAL_STATE_CSS.get(state_by_evidence[ev.id], 'muted'),
            # Recebível = em trânsito (encaminhado, ainda por receber — ADR-0016 v2).
            'in_transit': state_by_evidence[ev.id] == 'em_transito',
            # «Já recebida» = já está (ou passou) no destino — fonte única na
            # policy (STATES_AT_OR_PAST_LAB); não volta a oferecer-se para receção.
            'already_received': state_by_evidence[ev.id] in STATES_AT_OR_PAST_LAB,
        }
        for ev in evidences
    ]

    return render(
        request,
        'occurrence_intake.html',
        {
            'occurrence': occurrence,
            'rows': rows,
            'evidence_count': len(rows),
            'intake_errors': intake_errors,
            'cancel_url': f'/occurrences/{occurrence.id}/',
            # Intake = fase 2 do handoff (ADR-0016 v2): registar a RECEÇÃO dos
            # itens em trânsito. O destino/coordenada vêm do encaminhamento.
            'intake_action_label': 'Receção de prova encaminhada',
            'target_state': EventType.RECEPCAO_CUSTODIA,
            # Destino(s) de receção — coordenada/morada herdadas da ficha (read-only).
            'reception_institutions': reception_institutions,
        },
    )


@jwt_cookie_user
def stats_view(request):
    """Estatísticas orientadas a FLUXO (UX 2026-06): estado ATUAL derivado (stock),
    throughput por período, prazos/SLA e dwell time da custódia — em vez de
    contagens cumulativas point-in-time que não diziam quando/de quê/filtrado por
    quê. Cálculos na fonte única :mod:`core.analytics`; o estado legal vem de
    ``derive_legal_state`` (DRY com os tiles do Painel). Restrito à lente ativa."""
    from datetime import timedelta

    from django.utils import timezone

    user = request.user
    lens = access.active_console_mode(request, user)
    occ_qs = _lens_occurrences(user, lens)
    evd_qs = _lens_evidences(user, lens)
    cus_qs = _lens_custody(user, lens)

    days = analytics.resolve_window(request.GET.get('days'))
    since = timezone.now() - timedelta(days=days)

    states_by_ev = analytics.legal_states_by_evidence(cus_qs)
    return render(
        request,
        'stats.html',
        {
            'lens': lens,
            'days': days,
            'window_choices': analytics.WINDOW_CHOICES,
            'stock': analytics.state_distribution(states_by_ev),
            'flow': analytics.throughput(occ_qs, evd_qs, cus_qs, since),
            'sla': analytics.aging_sla(evd_qs, cus_qs),
            'dwell': analytics.custody_dwell(cus_qs),
        },
    )


@jwt_cookie_user
def settings_view(request):
    """Perfil/credencial do utilizador e preferências — server-rendered (Fase 3)."""
    return render(request, 'settings.html', {'u': request.user})


# ---------------------------------------------------------------------------
# Handlers de erro — 404 / 500
# ---------------------------------------------------------------------------


def not_found_view(request, exception=None):
    """Handler 404 — página amigável em vez do default do Django."""
    return render(request, '404.html', status=404)


def server_error_view(request):
    """Handler 500 — página amigável para erros inesperados."""
    return render(request, '500.html', status=500)


# ---------------------------------------------------------------------------
# Redirects 301 — retrocompatibilidade com nomes antigos (singular)
# ---------------------------------------------------------------------------


def occurrence_singular_redirect(_request):
    """/occurrence/ → /occurrences/"""
    return HttpResponsePermanentRedirect('/occurrences/')


def occurrence_detail_singular_redirect(_request, occurrence_id):
    """/occurrence/<id>/ → /occurrences/<id>/"""
    return HttpResponsePermanentRedirect(f'/occurrences/{occurrence_id}/')


def evidence_singular_redirect(_request):
    """/evidence/ → /evidences/"""
    return HttpResponsePermanentRedirect('/evidences/')


def custody_singular_redirect(_request):
    """/custody/ → /custodies/"""
    return HttpResponsePermanentRedirect('/custodies/')


def custody_evidence_redirect(_request, evidence_id):
    """/evidence/<id>/custody/ → /evidences/<id>/custody/"""
    return HttpResponsePermanentRedirect(f'/evidences/{evidence_id}/custody/')
