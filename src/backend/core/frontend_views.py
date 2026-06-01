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
from functools import wraps

from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.shortcuts import render
from rest_framework.exceptions import AuthenticationFailed, ValidationError as DRFValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from core import access
from core.audit import log_access
from core.auth import JWTCookieAuthentication
from core.models import (
    GENESIS_EVENTS,
    LEGAL_STATES,
    SEIZURE_GENESIS_EVENTS,
    AuditLog,
    ChainOfCustody,
    CrimeCategoria,
    CrimeTipo,
    CustodianType,
    EventType,
    Evidence,
    Institution,
    Occurrence,
    derive_legal_state,
)


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


def jwt_cookie_required(view_func):
    """
    Decorator que verifica a presença de um token JWT válido no cookie
    'fq_access'. Redireciona para /login/ se ausente ou inválido.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token = request.COOKIES.get('fq_access')
        if not token:
            return HttpResponseRedirect('/login/')
        try:
            AccessToken(token)
        except TokenError:
            return HttpResponseRedirect('/login/')
        return view_func(request, *args, **kwargs)

    return wrapper


def jwt_cookie_user(view_func):
    """Resolve ``request.user`` a partir do cookie JWT, para páginas
    server-rendered (Fase 3 — Django + HTMX).

    Ao contrário de :func:`jwt_cookie_required` (que só verifica a presença do
    token), reusa :class:`core.auth.JWTCookieAuthentication` para popular
    ``request.user`` — permitindo às views ler o ORM com a identidade e o
    ownership corretos. Redireciona para ``/login/`` se ausente ou inválido.
    O login mantém-se intacto (continua a emitir o cookie ``fq_access``).
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            result = JWTCookieAuthentication().authenticate(request)
        except (TokenError, AuthenticationFailed):
            result = None
        if result is None:
            return HttpResponseRedirect('/login/')
        request.user = result[0]
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


def _decorate_occurrences(occurrences):
    """Anota cada ocorrência com campos de apresentação (sem tocar no modelo)."""
    for occ in occurrences:
        occ.pri = _priority_badge(occ)
        ct = occ.crime_type
        occ.crime_label = f'{ct.codigo} — {ct.descritivo}' if ct else '—'
        occ.agent_label = occ.agent.get_full_name() or occ.agent.username


# Ordenações expostas na UI → expressão de ORM (lista branca: impede injeção
# de campos arbitrários de ordenação via query param).
_OCC_SORTS = {
    'recent': '-date_time',
    'oldest': 'date_time',
    'number': 'number',
    'created': '-created_at',
}


def _scope_occurrences(user):
    """Ocorrências legíveis pelo utilizador — *need-to-know* derivado do ledger
    (ADR-0017; fonte única em :mod:`core.access`)."""
    qs = Occurrence.objects.select_related('agent', 'crime_type')
    return access.scope_occurrences(user, base_qs=qs)


def _occurrence_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de uma ocorrência."""
    try:
        occ = _scope_occurrences(user).get(pk=drawer_id)
    except (Occurrence.DoesNotExist, ValueError, TypeError):
        return HttpResponseNotFound('Ocorrência não encontrada.')
    _decorate_occurrences([occ])
    occ.evidence_count = occ.evidences.count()
    return render(request, 'partials/_occurrence_drawer.html', {'occ': occ})


# ---------------------------------------------------------------------------
# Evidências (lista server-rendered)
# ---------------------------------------------------------------------------

# Rótulos PT do estado legal derivado (ADR-0015) — espelho de
# pdf_export._LEGAL_STATE_LABELS, para render server-side.
LEGAL_STATE_LABELS = {
    'a_guarda_opc': 'À guarda do OPC',
    'validada': 'Validada',
    'em_pericia': 'Em perícia',
    'pericia_concluida': 'Perícia concluída',
    'encaminhada': 'Encaminhada',
    'restituida': 'Restituída',
    'perdida_favor_estado': 'Perdida a favor do Estado',
    'destruida': 'Destruída',
}
# Variante semântica do ponto do badge .state (cor classifica o estado).
LEGAL_STATE_CSS = {
    'a_guarda_opc': 'info',
    'validada': 'info',
    'em_pericia': 'warn',
    'pericia_concluida': 'ok',
    'encaminhada': 'warn',
    'restituida': 'muted',
    'perdida_favor_estado': 'danger',
    'destruida': 'muted',
}

_EVD_SORTS = {
    'recent': '-timestamp_seizure',
    'oldest': 'timestamp_seizure',
    'code': 'code',
    'occurrence': 'occurrence__number',
}


def _scope_evidences(user):
    """Evidências legíveis pelo utilizador — *need-to-know* item-level
    (ADR-0017; fonte única em :mod:`core.access`)."""
    qs = Evidence.objects.select_related('occurrence', 'agent', 'parent_evidence').prefetch_related(
        'custody_chain'
    )
    return access.scope_evidences(user, base_qs=qs)


def _evidence_state(evidence):
    """(label, css) do estado legal derivado da cadeia de custódia."""
    eventos = sorted(evidence.custody_chain.all(), key=lambda r: r.sequence)
    if not eventos:
        return ('Sem custódia', 'muted')
    st = derive_legal_state(eventos)
    return (LEGAL_STATE_LABELS.get(st, st), LEGAL_STATE_CSS.get(st, 'muted'))


def _decorate_evidences(evidences):
    for e in evidences:
        e.type_label = e.get_type_display()
        e.agent_label = e.agent.get_full_name() or e.agent.username
        e.occ_label = e.occurrence.code or e.occurrence.number
        e.state_label, e.state_css = _evidence_state(e)


def _evidence_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de uma evidência."""
    try:
        ev = _scope_evidences(user).get(pk=drawer_id)
    except (Evidence.DoesNotExist, ValueError, TypeError):
        return HttpResponseNotFound('Evidência não encontrada.')
    _decorate_evidences([ev])
    return render(request, 'partials/_evidence_drawer.html', {'ev': ev})


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

    # Rate-limit por IP (scope `verify_public`, ADR-0012): superfície pública
    # não-autenticada; sem freio um atacante poderia tentar enumerar hashes
    # curtos. Aplicado ANTES de resolver para travar tentativas inválidas.
    if not _throttle_public_verify(request):
        return HttpResponse(
            'Demasiados pedidos. Tente novamente mais tarde.',
            status=429,
            content_type='text/plain; charset=utf-8',
        )

    occurrence = resolve_occurrence(short_hash)
    if occurrence is None:
        # Hash desconhecido — não distinguimos "não existe" de
        # "secret rotacionado" para não vazar informação.
        return render(request, 'public_verify_notfound.html', status=404)

    # Tenta autenticar via cookie JWT.
    token = request.COOKIES.get('fq_access')
    user_can_see_full = False
    if token:
        try:
            access = AccessToken(token)
            from django.contrib.auth import get_user_model

            user_id = access['user_id']
            user = get_user_model().objects.filter(pk=user_id).first()
            if user and user.is_authenticated:
                # FORENSIC_EXPERT vê tudo; FIRST_RESPONDER só se for o dono.
                profile = getattr(user, 'profile', None)
                if (
                    getattr(user, 'is_staff', False)
                    or profile == 'FORENSIC_EXPERT'
                    or profile == 'FIRST_RESPONDER'
                    and occurrence.agent_id == user.id
                ):
                    user_can_see_full = True
        except TokenError:
            pass

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


_HERO_BOUNDS = {
    'continental': [[36.95, -9.55], [42.15, -6.18]],
    'madeira': [[32.40, -17.40], [33.10, -16.50]],
    'acores': [[36.85, -31.40], [39.85, -24.70]],
}


def _occ_pri_code(o):
    """Código numérico de prioridade para o mapa (1=P1 lei, 2=P2 manual, 0=normal)."""
    if o.priority == Occurrence.Priority.PRIORITARIA:
        return 1 if o.priority_source == Occurrence.PrioritySource.LEI else 2
    return 0


def _activity_feed(user, limit=20):
    """Últimos eventos do AuditLog (append-only) visíveis ao utilizador.

    AGENTE vê os seus; PERITO/staff veem tudo (espelha ActivityFeedView). É a
    fonte de verdade do "que aconteceu": criação de prova (com hash), eventos
    de custódia, exportações de PDF, alertas.
    """
    qs = AuditLog.objects.select_related('user').order_by('-sequence')
    if not user.is_staff and getattr(user, 'profile', None) == 'FIRST_RESPONDER':
        qs = qs.filter(user_id=user.id)
    logs = list(qs[:limit])
    for r in logs:
        r.action_label = r.get_action_display()
        r.resource_label = r.get_resource_type_display()
        r.user_label = (r.user.get_full_name() or r.user.username) if r.user else 'sistema'
        d = r.details or {}
        if r.resource_type == AuditLog.ResourceType.EVIDENCE and d.get('hash'):
            r.extra = d['hash'][:16] + '…'
        elif r.resource_type == AuditLog.ResourceType.CUSTODY and d.get('event_type'):
            r.extra = d['event_type']
        else:
            r.extra = ''
    return logs


def _legal_states_by_evidence(user):
    """``{evidence_id: estado_legal_derivado}`` numa ÚNICA query (WI-E).

    Substitui a iteração O(n) que instanciava todas as evidências e ordenava o
    ``custody_chain`` em Python por evidência. Agrupa os eventos do ledger
    (já com o ownership aplicado) por ``evidence_id`` — uma só passagem,
    suportada pelo índice ``coc_ev_seq_idx`` — e deriva o estado uma vez por
    item com a função pura :func:`derive_legal_state` (fonte de verdade única,
    sem tradução para SQL). É o mesmo padrão usado nos endpoints da API.
    """
    qs = ChainOfCustody.objects.all()
    if not user.is_staff and getattr(user, 'profile', None) == 'FIRST_RESPONDER':
        qs = qs.filter(evidence__occurrence__agent=user)
    eventos = {}
    for rec in qs.order_by('evidence_id', 'sequence').only(
        'evidence_id', 'event_type', 'custodian_type', 'sequence'
    ):
        eventos.setdefault(rec.evidence_id, []).append(rec)
    return {ev_id: derive_legal_state(evs) for ev_id, evs in eventos.items()}


@jwt_cookie_user
def dashboard_view(request):
    """Painel — hero geo + últimas ocorrências + registo de atividade, TUDO
    server-rendered (Fase 3). Sem o JS antigo do hero (drift eliminado)."""
    user = request.user
    occ_qs = _scope_occurrences(user)
    occ_total = occ_qs.count()

    # Tiles do estado da cadeia — contagem por estado legal DERIVADO (ledger).
    # WI-E: uma só query agrupada (sem instanciar todas as evidências).
    tile_counts = {k: 0 for k in LEGAL_STATE_LABELS}
    for st in _legal_states_by_evidence(user).values():
        if st in tile_counts:
            tile_counts[st] += 1
    tiles = [
        {'key': k, 'label': LEGAL_STATE_LABELS[k], 'n': tile_counts[k]} for k in LEGAL_STATE_LABELS
    ]

    # Pontos georreferenciados por região (mapa do hero).
    pts = [
        {'lat': float(o.gps_lat), 'lng': float(o.gps_lng), 'label': o.code or o.number, 'pri': _occ_pri_code(o)}
        for o in occ_qs.exclude(gps_lat=None)
    ]

    def _within(b, p):
        return b[0][0] <= p['lat'] <= b[1][0] and b[0][1] <= p['lng'] <= b[1][1]

    regions = {name: [p for p in pts if _within(b, p)] for name, b in _HERO_BOUNDS.items()}

    recent = list(occ_qs.order_by('-date_time')[:8])
    _decorate_occurrences(recent)

    return render(
        request,
        'dashboard.html',
        {
            'u': user,
            'occ_total': occ_total,
            'recent': recent,
            'logs': _activity_feed(user, limit=20),
            'tiles': tiles,
            'total_active': sum(tile_counts.values()),
            'points_continental': json.dumps(regions['continental']),
            'points_madeira': json.dumps(regions['madeira']),
            'points_acores': json.dumps(regions['acores']),
            'bounds_continental': json.dumps(_HERO_BOUNDS['continental']),
            'bounds_madeira': json.dumps(_HERO_BOUNDS['madeira']),
            'bounds_acores': json.dumps(_HERO_BOUNDS['acores']),
        },
    )


@jwt_cookie_user
def occurrences_view(request):
    """Lista de ocorrências — server-rendered (Fase 3, Django + HTMX).

    Lê o ORM diretamente com o ownership do utilizador. Filtros, pesquisa,
    ordenação e paginação por query params. Em pedidos HTMX devolve só o
    fragmento da grelha; com ``?drawer=<id>`` devolve o painel de detalhe.
    """
    user = request.user

    drawer_id = request.GET.get('drawer')
    if drawer_id:
        return _occurrence_drawer(request, user, drawer_id)

    qs = _scope_occurrences(user)

    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(
            Q(number__icontains=query)
            | Q(code__icontains=query)
            | Q(description__icontains=query)
            | Q(address__icontains=query)
        )

    priority = (request.GET.get('pri') or '').strip()
    if priority in (Occurrence.Priority.PRIORITARIA, Occurrence.Priority.NORMAL):
        qs = qs.filter(priority=priority)

    sort_key = (request.GET.get('sort') or 'recent').strip()
    qs = qs.order_by(_OCC_SORTS.get(sort_key, '-date_time'))

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_occurrences(page_obj.object_list)

    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'pri': priority,
        'sort': sort_key,
        'selected_id': request.GET.get('selected') or '',
        'is_htmx': bool(request.headers.get('HX-Request')),
    }

    if ctx['is_htmx']:
        return render(request, 'partials/_occurrences_grid.html', ctx)
    return render(request, 'occurrences.html', ctx)


@jwt_cookie_user
def occurrence_detail_view(request, occurrence_id):
    """Detalhe de uma ocorrência — hub do caso, server-rendered (Fase 3)."""
    user = request.user
    try:
        occ = _scope_occurrences(user).get(pk=occurrence_id)
    except (Occurrence.DoesNotExist, ValueError, TypeError):
        return HttpResponseNotFound('Ocorrência não encontrada.')
    _decorate_occurrences([occ])
    evidences = list(
        _scope_evidences(user).filter(occurrence=occ).order_by('parent_evidence_id', 'id')
    )
    _decorate_evidences(evidences)
    occ.evidence_count = len(evidences)
    return render(request, 'occurrence_detail.html', {'occ': occ, 'evidences': evidences})


@jwt_cookie_user
def occurrences_new_view(request):
    """Registo de nova ocorrência — server-rendered + POST via serializer (Fase 3).

    A escrita reusa o ``OccurrenceSerializer`` (validação + derivação de
    prioridade + imutabilidade do modelo) e regista auditoria, tal como a API.
    """
    from core.serializers import OccurrenceSerializer

    user = request.user
    if not (user.is_staff or getattr(user, 'profile', None) == 'FIRST_RESPONDER'):
        return HttpResponseForbidden('Apenas agentes podem registar ocorrências.')

    crime_categories = CrimeCategoria.objects.order_by('codigo')

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
        }

    if request.method == 'POST':
        data = {k: v for k, v in request.POST.items() if v != '' and k != 'csrfmiddlewaretoken'}
        serializer = OccurrenceSerializer(data=data)
        if serializer.is_valid():
            try:
                occ = serializer.save(agent=user)
            except DjangoValidationError as exc:
                return render(
                    request, 'occurrences_new.html', _ctx({'geral': exc.messages}, request.POST), status=400
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
            request, 'occurrences_new.html', _ctx(serializer.errors, request.POST), status=400
        )

    return render(request, 'occurrences_new.html', _ctx({}, {}))


@jwt_cookie_user
def evidences_view(request):
    """Lista de evidências — server-rendered (Fase 3, Django + HTMX).

    Ownership espelha o EvidenceViewSet (AGENTE vê as suas via occurrence;
    PERITO/staff todas). Estado legal derivado do ledger por linha.
    """
    user = request.user

    drawer_id = request.GET.get('drawer')
    if drawer_id:
        return _evidence_drawer(request, user, drawer_id)

    qs = _scope_evidences(user)

    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(
            Q(code__icontains=query)
            | Q(description__icontains=query)
            | Q(serial_number__icontains=query)
            | Q(occurrence__number__icontains=query)
        )

    etype = (request.GET.get('type') or '').strip()
    if etype in Evidence.EvidenceType.values:
        qs = qs.filter(type=etype)

    # Filtro por estado legal DERIVADO (entrada a partir dos tiles do Painel).
    # WI-E: uma só query agrupada em vez de iterar todas as evidências 2x.
    state = (request.GET.get('state') or '').strip()
    if state in LEGAL_STATES:
        matching = [ev_id for ev_id, st in _legal_states_by_evidence(user).items() if st == state]
        qs = qs.filter(id__in=matching)

    sort_key = (request.GET.get('sort') or 'recent').strip()
    qs = qs.order_by(_EVD_SORTS.get(sort_key, '-timestamp_seizure'))

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_evidences(page_obj.object_list)

    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'type': etype,
        'state': state,
        'state_label': LEGAL_STATE_LABELS.get(state, ''),
        'sort': sort_key,
        'evidence_types': Evidence.EvidenceType.choices,
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if ctx['is_htmx']:
        return render(request, 'partials/_evidences_grid.html', ctx)
    return render(request, 'evidences.html', ctx)


# Identificadores específicos do tipo recolhidos no formulário e empacotados
# em type_specific_data (os validadores de formato correm no serializer).
_TSD_KEYS = ['imei', 'imsi', 'iccid', 'vin', 'mac']


@jwt_cookie_user
def evidences_new_view(request):
    """Registo de nova evidência — server-rendered + POST via serializer (Fase 3).

    Reusa o ``EvidenceSerializer`` (validação por tipo, hash de integridade,
    imutabilidade) e regista auditoria com o hash, tal como a API.
    """
    from core.serializers import EvidenceSerializer

    user = request.user
    if not (user.is_staff or getattr(user, 'profile', None) == 'FIRST_RESPONDER'):
        return HttpResponseForbidden('Apenas agentes podem registar evidências.')

    occurrences = _scope_occurrences(user).order_by('-date_time')
    parents = _scope_evidences(user).order_by('occurrence__number', 'code')

    if request.method == 'POST':
        data = {
            k: v
            for k, v in request.POST.items()
            if v != '' and k != 'csrfmiddlewaretoken' and k not in _TSD_KEYS
        }
        tsd = {k: request.POST[k].strip() for k in _TSD_KEYS if request.POST.get(k, '').strip()}
        if tsd:
            data['type_specific_data'] = tsd
        if request.FILES.get('photo'):
            data['photo'] = request.FILES['photo']

        serializer = EvidenceSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            try:
                ev = serializer.save(agent=user)
            except DjangoValidationError as exc:
                return render(
                    request,
                    'evidences_new.html',
                    {
                        'occurrences': occurrences,
                        'parents': parents,
                        'evidence_types': Evidence.EvidenceType.choices,
                        'preselect': request.POST.get('occurrence', ''),
                        'errors': {'geral': exc.messages},
                        'data': request.POST,
                    },
                    status=400,
                )
            log_access(
                request=request,
                action=AuditLog.Action.CREATE,
                resource_type=AuditLog.ResourceType.EVIDENCE,
                resource_id=ev.pk,
                details={'hash': ev.integrity_hash},
            )
            messages.success(request, f'Item de prova {ev.code} registado.')
            return HttpResponseRedirect(f'/evidences/{ev.pk}/')
        return render(
            request,
            'evidences_new.html',
            {
                'occurrences': occurrences,
                'parents': parents,
                'evidence_types': Evidence.EvidenceType.choices,
                'preselect': request.POST.get('occurrence', ''),
                'errors': serializer.errors,
                'data': request.POST,
            },
            status=400,
        )

    return render(
        request,
        'evidences_new.html',
        {
            'occurrences': occurrences,
            'parents': parents,
            'evidence_types': Evidence.EvidenceType.choices,
            'preselect': request.GET.get('occurrence', ''),
            'errors': {},
            'data': {},
        },
    )


def _decorate_events(events):
    """Anota cada evento do ledger com rótulos PT e hash curto (apresentação)."""
    for r in events:
        r.event_label = r.get_event_type_display()
        r.custodian_label = r.get_custodian_type_display() if r.custodian_type else '—'
        r.agent_label = r.agent.get_full_name() or r.agent.username
        r.hash_short = (r.record_hash or '')[:16]


def _chain_points(events):
    """Pontos georreferenciados do ledger (para o mapa da cadeia, modo Cadeia).

    Coordenadas como float → json.dumps usa ponto decimal (nunca a vírgula
    PT-PT que partiria o parseFloat no cliente).
    """
    pts = []
    for r in events:
        if r.gps_lat is None or r.gps_lng is None:
            continue
        label = f'{r.sequence}. {r.get_event_type_display()} · {r.timestamp:%H:%M}'
        if r.gps_accuracy_m:
            label += f' · ±{r.gps_accuracy_m}m'
        pts.append({'lat': float(r.gps_lat), 'lng': float(r.gps_lng), 'label': label})
    return pts


@jwt_cookie_user
def evidence_detail_view(request, evidence_id):
    """Detalhe de uma evidência — hub do item, server-rendered (Fase 3)."""
    user = request.user
    try:
        ev = _scope_evidences(user).get(pk=evidence_id)
    except (Evidence.DoesNotExist, ValueError, TypeError):
        return HttpResponseNotFound('Evidência não encontrada.')
    _decorate_evidences([ev])
    events = sorted(ev.custody_chain.all(), key=lambda r: r.sequence)
    _decorate_events(events)
    sub_components = list(ev.sub_components.select_related('agent').order_by('id'))
    _decorate_evidences(sub_components)
    return render(
        request,
        'evidence_detail.html',
        {
            'ev': ev,
            'events': events,
            'sub_components': sub_components,
            'chain_json': json.dumps(_chain_points(events), ensure_ascii=False),
        },
    )


_TERMINAL_EVENT_VALUES = {EventType.RESTITUICAO, EventType.DESTRUICAO}


def _genesis_event_for(evidence):
    """Evento de génese aplicável à evidência, por proveniência (ADR-0016 §2)."""
    if evidence is not None and evidence.parent_evidence_id is not None:
        return EventType.DERIVACAO_ITEM
    if evidence is not None and evidence.type == Evidence.EvidenceType.DIGITAL_FILE:
        return EventType.APREENSAO_DADOS
    return EventType.APREENSAO_OBJETO


def _valid_next_events(events, evidence=None):
    """(value, label) dos ``EventType`` que as guardas de ``ChainOfCustody.clean()``
    aceitariam como PRÓXIMO evento, dado o ledger atual e (na génese) a
    proveniência da evidência — ADR-0016 §2.

    Espelha apenas as regras BLOQUEANTES (não as advisory de 72h): 1.º evento =
    génese (objeto/dados/derivação conforme a evidência); a génese só pode ser o
    1.º; nenhum evento após terminal; VALIDAÇÃO_APREENSÃO exige apreensão prévia
    e só uma vez; INÍCIO_PERÍCIA exige DESPACHO_PERÍCIA prévio. O backend
    (serializer + clean) continua a ser a fonte de verdade — isto é só para não
    oferecer transições impossíveis.
    """
    types = {e.event_type for e in events}
    if not events:
        genesis = _genesis_event_for(evidence)
        return [(genesis.value, genesis.label)]
    if types & _TERMINAL_EVENT_VALUES:
        return []
    seizure_done = bool(types & SEIZURE_GENESIS_EVENTS)
    out = []
    for et in EventType:
        if et in GENESIS_EVENTS:
            continue  # génese só na posição 1
        if et == EventType.VALIDACAO_APREENSAO and (
            not seizure_done or EventType.VALIDACAO_APREENSAO in types
        ):
            continue
        if et == EventType.INICIO_PERICIA and EventType.DESPACHO_PERICIA not in types:
            continue
        out.append((et.value, et.label))
    return out


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


def _register_custody_event(request, evidence, targets):
    """Regista um evento de custódia em ``targets`` (evidência + opcionalmente
    sub-componentes) via ``ChainOfCustodySerializer``, numa transação atómica.

    Reusa o serializer validado (guardas do ledger + ownership + imutabilidade +
    hash encadeado) e regista auditoria por registo. Devolve lista de erros
    (vazia = sucesso). Em qualquer falha, a transação reverte por completo.
    """
    from django.db import transaction

    from core.serializers import ChainOfCustodySerializer

    user = request.user
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
    # Custódia institucional / pessoal (ADR-0017) — opcionais.
    for fk in ('custodian_institution', 'custodian_user', 'relinquished_by'):
        val = (request.POST.get(fk) or '').strip()
        if val:
            base[fk] = val
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

    errors = []
    try:
        with transaction.atomic():
            for tgt in targets:
                serializer = ChainOfCustodySerializer(
                    data=dict(base, evidence=tgt.id), context={'request': request}
                )
                serializer.is_valid(raise_exception=True)
                record = serializer.save(agent=user)
                log_access(
                    request=request,
                    action=AuditLog.Action.CREATE,
                    resource_type=AuditLog.ResourceType.CUSTODY,
                    resource_id=record.pk,
                    details={
                        'evidence_id': record.evidence_id,
                        'event_type': record.event_type,
                        'custodian_type': record.custodian_type,
                    },
                )
    except (DRFValidationError, DjangoValidationError) as exc:
        errors = _flatten_validation_error(exc)
    return errors


@jwt_cookie_user
def custody_timeline_view(request, evidence_id):
    """Timeline geo-rastreável + registo de eventos de custódia (Fase 3, WI-A).

    GET renderiza o trajeto + ledger + formulário inline de registo (só com os
    eventos que as guardas aceitariam). POST regista o evento (e, opcionalmente,
    nos sub-componentes em cascata atómica) via ``ChainOfCustodySerializer`` e
    redireciona (PRG); em erro re-renderiza com o formulário aberto.
    """
    user = request.user
    try:
        ev = _scope_evidences(user).get(pk=evidence_id)
    except (Evidence.DoesNotExist, ValueError, TypeError):
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
    events = sorted(ev.custody_chain.all(), key=lambda r: r.sequence)
    _decorate_events(events)
    valid_events = _valid_next_events(events, ev)
    return render(
        request,
        'custody_timeline.html',
        {
            'ev': ev,
            'events': events,
            'chain_json': json.dumps(_chain_points(events), ensure_ascii=False),
            'valid_events': valid_events,
            'custodian_types': CustodianType.choices,
            'institutions': Institution.objects.filter(is_active=True).order_by('name'),
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


def _scope_custody(user):
    """Eventos de custódia dos itens legíveis pelo utilizador (ADR-0017;
    fonte única em :mod:`core.access`)."""
    qs = ChainOfCustody.objects.select_related('evidence', 'evidence__occurrence', 'agent')
    return access.scope_custody(user, base_qs=qs)


def _custody_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de um evento de custódia."""
    try:
        rec = _scope_custody(user).get(pk=drawer_id)
    except (ChainOfCustody.DoesNotExist, ValueError, TypeError):
        return HttpResponseNotFound('Registo de custódia não encontrado.')
    _decorate_events([rec])
    return render(request, 'partials/_custody_drawer.html', {'r': rec})


@jwt_cookie_user
def custody_list_view(request):
    """Lista do ledger de custódia — server-rendered (Fase 3, Django + HTMX)."""
    user = request.user

    drawer_id = request.GET.get('drawer')
    if drawer_id:
        return _custody_drawer(request, user, drawer_id)

    qs = _scope_custody(user)

    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(
            Q(code__icontains=query)
            | Q(evidence__code__icontains=query)
            | Q(evidence__occurrence__number__icontains=query)
        )

    event = (request.GET.get('event') or '').strip()
    if event in EventType.values:
        qs = qs.filter(event_type=event)

    sort_key = (request.GET.get('sort') or 'recent').strip()
    qs = qs.order_by(_CUSTODY_SORTS.get(sort_key, '-timestamp'))

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_events(page_obj.object_list)

    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'event': event,
        'sort': sort_key,
        'event_types': EventType.choices,
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if ctx['is_htmx']:
        return render(request, 'partials/_custody_grid.html', ctx)
    return render(request, 'custody_list.html', ctx)


@jwt_cookie_required
def investigation_report_view(request):
    """
    Relatório de investigação estática da aplicação (LEGACY v1, congelado).

    **v2 (T11):** página editorial estática (achados de revisão por
    severidade), fora da arquitectura de informação da v2. Fronteira
    congelada — a reinvenção do frontend (Fase 3) remove-a ou reescreve-a;
    não construir em cima. Mantida por ora; requer token JWT válido.
    """
    return render(request, 'investigation_report.html')


@jwt_cookie_user
def reports_view(request):
    """Guias de transporte (PDF por ocorrência) — server-rendered (Fase 3)."""
    user = request.user
    qs = _scope_occurrences(user).annotate(n_ev=Count('evidences'))
    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(
            Q(number__icontains=query) | Q(code__icontains=query) | Q(address__icontains=query)
        )
    qs = qs.order_by('-date_time')
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_occurrences(page_obj.object_list)
    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if ctx['is_htmx']:
        return render(request, 'partials/_reports_grid.html', ctx)
    return render(request, 'reports.html', ctx)


def occurrence_intake_view(request, occurrence_id):
    """Página de check-list de intake no laboratório (ADR-0012 Vaga 2).

    Acessível só a EXPERT (ou staff). AGENT em campo entrega; não faz
    intake. O template renderiza checklist das evidências esperadas;
    o submit é feito via JS para o endpoint `/api/custody/cascade/`
    existente, registando em todos os itens marcados um evento
    ``TRANSFERENCIA`` para ``LAB_PUBLICO`` numa só operação atómica
    (ledger de eventos, ADR-0015).

    Requisitos de auth (impostos no servidor antes do render):
    1. JWT válido em cookie `fq_access`.
    2. Perfil EXPERT, staff, ou superuser.

    Qualquer outro perfil recebe HTTP 403.
    """
    from django.contrib.auth import get_user_model

    from core.models import Occurrence

    token = request.COOKIES.get('fq_access')
    if not token:
        return HttpResponseRedirect('/login/?next=' + request.path)
    try:
        access = AccessToken(token)
    except TokenError:
        return HttpResponseRedirect('/login/?next=' + request.path)

    user = get_user_model().objects.filter(pk=access['user_id']).first()
    if user is None:
        return HttpResponseRedirect('/login/?next=' + request.path)

    is_expert = getattr(user, 'profile', None) == 'FORENSIC_EXPERT'
    if not (user.is_staff or user.is_superuser or is_expert):
        return render(request, '403_intake.html', status=403)

    occurrence = Occurrence.objects.filter(pk=occurrence_id).first()
    if occurrence is None:
        return render(request, '404.html', status=404)

    # Para cada evidência: estado legal DERIVADO (ADR-0015) da sequência de
    # eventos. "Já recebida" = já encaminhada para laboratório ou além.
    from core.models import ChainOfCustody, EventType, Evidence, derive_legal_state

    # Estados legais a partir dos quais a prova já está (ou passou) no
    # laboratório — não faz sentido voltar a "receber" no intake.
    received_states = {
        'encaminhada',
        'em_pericia',
        'pericia_concluida',
        'restituida',
        'perdida_favor_estado',
        'destruida',
    }

    evidences = list(Evidence.objects.filter(occurrence=occurrence).order_by('code', 'id'))
    state_by_evidence = {}
    for ev in evidences:
        eventos = list(ChainOfCustody.objects.filter(evidence=ev).order_by('sequence'))
        state_by_evidence[ev.id] = derive_legal_state(eventos) if eventos else ''

    # POST — registar TRANSFERENCIA → LAB_PUBLICO nos itens marcados (lote atómico,
    # ledger de eventos ADR-0015), reusando o ChainOfCustodySerializer validado.
    intake_errors = []
    if request.method == 'POST':
        from django.db import transaction

        from core.serializers import ChainOfCustodySerializer

        selected = set(request.POST.getlist('evidence_ids'))
        location = (request.POST.get('location_name') or '').strip()
        storage = (request.POST.get('storage_location') or '').strip()
        observations = (request.POST.get('observations') or '').strip()
        gps_lat = (request.POST.get('gps_lat') or '').strip()
        gps_lng = (request.POST.get('gps_lng') or '').strip()
        gps_accuracy = (request.POST.get('gps_accuracy_m') or '').strip()
        to_receive = [
            ev
            for ev in evidences
            if str(ev.id) in selected and state_by_evidence[ev.id] not in received_states
        ]
        if not to_receive:
            intake_errors.append('Selecione pelo menos um item ainda não recebido.')
        else:
            try:
                with transaction.atomic():
                    for ev in to_receive:
                        payload = {
                            'evidence': ev.id,
                            'event_type': EventType.TRANSFERENCIA_CUSTODIA,
                            'custodian_type': ChainOfCustody.CustodianType.LAB_PUBLICO,
                        }
                        if location:
                            payload['location_name'] = location
                        if storage:
                            payload['storage_location'] = storage
                        if observations:
                            payload['observations'] = observations
                        if gps_lat and gps_lng:
                            payload['gps_lat'] = gps_lat
                            payload['gps_lng'] = gps_lng
                            if gps_accuracy:
                                payload['gps_accuracy_m'] = gps_accuracy
                        s = ChainOfCustodySerializer(data=payload)
                        s.is_valid(raise_exception=True)
                        rec = s.save(agent=user)
                        log_access(
                            request=request,
                            action=AuditLog.Action.CREATE,
                            resource_type=AuditLog.ResourceType.CUSTODY,
                            resource_id=rec.pk,
                            details={
                                'evidence_id': rec.evidence_id,
                                'event_type': rec.event_type,
                                'custodian_type': rec.custodian_type,
                            },
                        )
                messages.success(
                    request,
                    f'Receção registada: {len(to_receive)} item(ns) no laboratório.',
                )
                return HttpResponseRedirect(f'/occurrences/{occurrence.id}/')
            except Exception as exc:  # noqa: BLE001 — qualquer falha → rollback + mostra erro
                intake_errors.append(f'Falha no registo: {exc}')

    rows = [
        {
            'evidence': ev,
            'current_state': state_by_evidence[ev.id],
            'current_state_display': LEGAL_STATE_LABELS.get(state_by_evidence[ev.id])
            or 'Sem custódia',
            'current_state_css': LEGAL_STATE_CSS.get(state_by_evidence[ev.id], 'muted'),
            'already_received': state_by_evidence[ev.id] in received_states,
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
            # Intake = registar TRANSFERENCIA → LAB_PUBLICO em lote (ADR-0015).
            # ``target_state``/``target_custodian`` são consumidos pelo JS de
            # intake para compor o POST a /api/custody/cascade/ (event_type +
            # custodian_type). O template do intake será reformulado na fase
            # frontend; o backend já entrega a semântica nova.
            'target_state': EventType.TRANSFERENCIA_CUSTODIA,
            'target_custodian': ChainOfCustody.CustodianType.LAB_PUBLICO,
        },
    )


@jwt_cookie_user
def stats_view(request):
    """Estatísticas agregadas — server-rendered (Fase 3). Agregados baratos
    (não deriva estado legal por linha; isso fica para uma vista dedicada)."""
    user = request.user
    occ_qs = _scope_occurrences(user)
    kpis = {
        'occurrences': occ_qs.count(),
        'evidences': _scope_evidences(user).count(),
        'custody_events': _scope_custody(user).count(),
        'prioritarias': occ_qs.filter(priority=Occurrence.Priority.PRIORITARIA).count(),
    }
    by_type = [
        {'label': Evidence.EvidenceType(r['type']).label, 'n': r['n']}
        for r in _scope_evidences(user).values('type').annotate(n=Count('id')).order_by('-n')
    ]
    by_event = [
        {'label': EventType(r['event_type']).label, 'n': r['n']}
        for r in _scope_custody(user).values('event_type').annotate(n=Count('id')).order_by('-n')
    ]
    return render(request, 'stats.html', {'kpis': kpis, 'by_type': by_type, 'by_event': by_event})


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


def _redirect_permanent(path):
    """Factory para redirects 301 simples (sem kwargs)."""

    def view(_request):
        return HttpResponsePermanentRedirect(path)

    return view


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
