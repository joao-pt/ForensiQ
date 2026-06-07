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
from functools import wraps
from urllib.parse import urlencode

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
from django.utils.dateparse import parse_date
from rest_framework.exceptions import AuthenticationFailed, ValidationError as DRFValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from core import access, evidence_field_config, evidence_type_config
from core.audit import log_access
from core.auth import JWTCookieAuthentication
from core.labels import LEGAL_STATE_CSS, LEGAL_STATE_LABELS
from core.models import (
    LEGAL_STATES,
    TERMINAL_LEGAL_STATES,
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
    derive_legal_state,
)
from core.policy import custody_transitions
from core.utils import get_user_display_name, sort_custody_chain

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


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


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
        occ.agent_label = get_user_display_name(occ.agent)


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


def _readable_occurrence(user, pk):
    """Ocorrência por ``pk`` se o utilizador a pode LER na consola server-rendered;
    ``None`` se não existe ou está fora de acesso. É a porta de DETALHE/drawer:
    mais ampla que a LISTA pessoal (``scope_occurrences``) — abre por acesso global
    (titular / leitura total / autoridade do caso, :func:`can_access_occurrence`)
    OU por pertença institucional (a instituição é dona do processo, abre o
    processo inteiro — :func:`is_occurrence_institutional`). A API/PDF/verificação
    pública mantêm o need-to-know item-level (não passam por aqui)."""
    try:
        occ = Occurrence.objects.select_related('agent', 'crime_type').get(pk=pk)
    except (Occurrence.DoesNotExist, ValueError, TypeError):
        return None
    if access.can_access_occurrence(user, occ) or access.is_occurrence_institutional(user, occ):
        return occ
    return None


def _occurrence_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de uma ocorrência."""
    occ = _readable_occurrence(user, drawer_id)
    if occ is None:
        return HttpResponseNotFound('Ocorrência não encontrada.')
    _decorate_occurrences([occ])
    occ.evidence_count = occ.evidences.count()
    return render(request, 'partials/_occurrence_drawer.html', {'occ': occ})


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
    qs = Evidence.objects.select_related('occurrence', 'agent', 'parent_evidence').prefetch_related(
        'custody_chain'
    )
    return access.scope_evidences(user, base_qs=qs)


def _evidence_state(evidence):
    """(label, css) do estado legal derivado da cadeia de custódia."""
    eventos = sort_custody_chain(evidence.custody_chain.all())
    if not eventos:
        return ('Sem custódia', 'muted')
    st = derive_legal_state(eventos)
    return (LEGAL_STATE_LABELS.get(st, st), LEGAL_STATE_CSS.get(st, 'muted'))


def _decorate_evidences(evidences):
    # labels() uma vez (evita N+1 com o choices-callable de Evidence.type — ADR-0018).
    type_labels = evidence_type_config.labels()
    for e in evidences:
        e.type_label = type_labels.get(e.type, e.type)
        e.agent_label = get_user_display_name(e.agent)
        e.occ_label = e.occurrence.code or e.occurrence.number
        e.state_label, e.state_css = _evidence_state(e)


def _readable_evidence(user, pk):
    """Evidência por ``pk`` se o utilizador a pode LER na consola server-rendered;
    ``None`` caso contrário. Item-level need-to-know (``can_view_evidence``) OU o
    item pertence a uma ocorrência que o utilizador lê por pertença institucional
    (a instituição é dona do processo → vê o processo INTEIRO, incl. itens-irmãos
    que a sua instituição nunca custodiou — coerente com a zona "Instituição" da
    consola, que lista o processo todo). A ESCRITA continua governada pelo
    serializer (``can_append_custody``, fail-closed), independente desta porta."""
    try:
        ev = (
            Evidence.objects.select_related('occurrence', 'agent', 'parent_evidence')
            .prefetch_related('custody_chain')
            .get(pk=pk)
        )
    except (Evidence.DoesNotExist, ValueError, TypeError):
        return None
    if access.can_view_evidence(user, ev) or access.is_occurrence_institutional(
        user, ev.occurrence
    ):
        return ev
    return None


def _evidence_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de uma evidência."""
    ev = _readable_evidence(user, drawer_id)
    if ev is None:
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

    # Lockout por IP (escalada) + rate-limit por minuto. Superfície pública
    # não-autenticada; sem freio um atacante poderia tentar enumerar os hashes
    # curtos. Aplicados ANTES de resolver para travar tentativas inválidas.
    ip = _client_ip(request)
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

    # Tenta autenticar via cookie JWT.
    token = request.COOKIES.get('fq_access')
    user_can_see_full = False
    if token:
        try:
            # NB: variável local `decoded` (não `access`) — `access` é o módulo
            # core.access; reutilizar o nome aqui mascarava-o e rebentava a chamada.
            decoded = AccessToken(token)
            from django.contrib.auth import get_user_model

            user = get_user_model().objects.filter(pk=decoded['user_id']).first()
            # "Ver tudo" = poder aceder à ocorrência pelo mesmo critério da vista
            # autenticada (access.can_access_occurrence: titular / leitura total —
            # staff/NACIONAL/perito forense — / autoridade do caso). Antes concedia-se
            # a QUALQUER FORENSIC_EXPERT e redirecionava-se para /occurrences/<id>/,
            # que reaplica o âmbito e devolvia 404 a quem não tinha acesso; agora os
            # critérios coincidem. Quem não pode aceder cai na vista pública mínima.
            if user and user.is_authenticated and access.can_access_occurrence(user, occurrence):
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


@jwt_cookie_user
def verifications_view(request):
    """Centro de verificação / QR (operador EXPERT/staff).

    Resolve um ``short_hash`` de QR OU um código de ocorrência (OC-…) para o
    caso correspondente, mostra o URL canónico do QR (para reimpressão da guia)
    e documenta o fluxo guia-de-transporte e as suas mitigações. NÃO é entrada
    de dados por código nem pesquisa pública — é ferramenta interna de
    gestão/auditoria, pelo que respeita o ADR-0012 §6. Só resolve casos dentro
    do âmbito do operador (need-to-know)."""
    from django.conf import settings as dj_settings

    from core.qr_verify import resolve_occurrence, short_hash_for

    user = request.user
    if not (user.is_staff or getattr(user, 'profile', None) == 'FORENSIC_EXPERT'):
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
            site = (getattr(dj_settings, 'SITE_URL', '') or '').rstrip('/')
            sh = short_hash_for(occ.id)
            result = {
                'id': occ.id,
                'code': occ.code or f'#{occ.id}',
                'number': occ.number,
                'short_hash': sh,
                'verify_url': f'{site}/v/{sh}/',
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

    Só leitura nacional (staff ou credencial NACIONAL) vê TODO o registo de
    auditoria; qualquer outro perfil (FIRST_RESPONDER, FORENSIC_EXPERT NORMAL,
    CASE_AUTHORITY, EVIDENCE_CUSTODIAN…) vê APENAS os eventos que praticou —
    *need-to-know* (ADR-0017). Espelha :class:`core.views.ActivityFeedView`. É a
    fonte de verdade do "que aconteceu": criação de prova (com hash), eventos
    de custódia, exportações de PDF, alertas.
    """
    qs = AuditLog.objects.select_related('user').order_by('-sequence')
    if not access.has_national_read(user):
        qs = qs.filter(user_id=user.id)
    logs = list(qs[:limit])
    for r in logs:
        r.action_label = r.get_action_display()
        r.resource_label = r.get_resource_type_display()
        r.user_label = get_user_display_name(r.user)
        d = r.details or {}
        if r.resource_type == AuditLog.ResourceType.EVIDENCE and d.get('hash'):
            r.extra = d['hash'][:16] + '…'
        elif r.resource_type == AuditLog.ResourceType.CUSTODY and d.get('event_type'):
            r.extra = d['event_type']
        else:
            r.extra = ''
    return logs


def _legal_states_by_evidence(user, custody_qs=None):
    """``{evidence_id: estado_legal_derivado}`` numa ÚNICA query (WI-E).

    Substitui a iteração O(n) que instanciava todas as evidências e ordenava o
    ``custody_chain`` em Python por evidência. Agrupa os eventos do ledger
    (já com o ownership aplicado) por ``evidence_id`` — uma só passagem,
    suportada pelo índice ``coc_ev_seq_idx`` — e deriva o estado uma vez por
    item com a função pura :func:`derive_legal_state` (fonte de verdade única,
    sem tradução para SQL). É o mesmo padrão usado nos endpoints da API.
    """
    # Âmbito *need-to-know* item-level (ADR-0017), fonte única em core.access — NÃO
    # o antigo filtro só-titular. Antes: ChainOfCustody.objects.all() para todos
    # menos FIRST_RESPONDER, o que (a) vazava contagens de TODOS os casos aos
    # restantes perfis no dashboard e (b) sub-contava o FIRST_RESPONDER que detém
    # itens de ocorrências de outrem. scope_custody devolve todos os eventos das
    # evidências visíveis, pelo que derive_legal_state recebe a cadeia completa.
    # ``custody_qs`` permite restringir à lente ativa (ex.: tiles do Painel em
    # "À guarda") — tem de ser já um âmbito imposto (subconjunto de scope_custody).
    qs = access.scope_custody(user) if custody_qs is None else custody_qs
    eventos = {}
    # select_related(None) limpa quaisquer joins (ex.: a lente traz
    # select_related('agent')) que entrariam em conflito com o .only() abaixo.
    for rec in qs.select_related(None).order_by('evidence_id', 'sequence').only(
        'evidence_id', 'event_type', 'custodian_type', 'sequence'
    ):
        eventos.setdefault(rec.evidence_id, []).append(rec)
    return {ev_id: derive_legal_state(evs) for ev_id, evs in eventos.items()}


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
        qs = Occurrence.objects.select_related('agent', 'crime_type')
        return access.scope_occurrences_institutional(user, base_qs=qs)
    return _scope_occurrences(user)


def _lens_evidences(user, lens):
    """Itens para a zona ativa (case-axis, nunca por item).

    ``INSTITUTION`` mostra TODOS os itens das ocorrências da instituição (processo
    inteiro — a instituição é dona do processo). ``MINE`` mostra os itens legíveis
    (item-level, ADR-0017) das ocorrências do utilizador.
    """
    qs = Evidence.objects.select_related('occurrence', 'agent', 'parent_evidence').prefetch_related(
        'custody_chain'
    )
    if lens == access.Lens.INSTITUTION:
        return qs.filter(
            occurrence__in=access.scope_occurrences_institutional(user).values('pk')
        )
    return access.scope_evidences(user, base_qs=qs).filter(
        occurrence__in=access.scope_occurrences(user).values('pk')
    )


def _lens_custody(user, lens):
    """Eventos de custódia para a zona ativa (mesma lógica case-axis)."""
    qs = ChainOfCustody.objects.select_related('evidence', 'evidence__occurrence', 'agent')
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
    states = _legal_states_by_evidence(
        user,
        custody_qs=ChainOfCustody.objects.filter(evidence__occurrence_id__in=candidate_ids),
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
    lens = access.console_mode(request, user)
    access.remember_console_mode(request, lens)
    # O hero segue a zona ativa da consola: "as minhas" (âmbito de caso pessoal)
    # ou "Instituição" (processo inteiro das ocorrências da instituição).
    occ_qs = _lens_occurrences(user, lens)
    occ_total = occ_qs.count()

    # Tiles do estado da cadeia — contagem por estado legal DERIVADO (ledger).
    # WI-E: uma só query agrupada (sem instanciar todas as evidências).
    tile_counts = {k: 0 for k in LEGAL_STATE_LABELS}
    for st in _legal_states_by_evidence(user, custody_qs=_lens_custody(user, lens)).values():
        if st in tile_counts:
            tile_counts[st] += 1
    tiles = [
        {'key': k, 'label': LEGAL_STATE_LABELS[k], 'n': tile_counts[k]} for k in LEGAL_STATE_LABELS
    ]

    # Pontos georreferenciados por região (mapa do hero).
    pts = [
        {'lat': float(o.gps_lat), 'lng': float(o.gps_lng), 'label': o.code or o.number, 'pri': _occ_pri_code(o)}
        for o in occ_qs.exclude(gps_lat=None).exclude(gps_lng=None)
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
            'feed_is_national': access.has_national_read(user),
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


def _occurrences_list_response(request, archived=False):
    """Corpo PARTILHADO das listas de ocorrências ativas (``/occurrences/``) e do
    Arquivo (``/arquivo/``): mesmo dispatch por zona de consola, filtros,
    ordenação e paginação — só diferem na divisão arquivado/ativo e no template.
    O drawer (``?drawer=``) é comum (o detalhe de um processo é o mesmo)."""
    user = request.user

    drawer_id = request.GET.get('drawer')
    if drawer_id:
        return _occurrence_drawer(request, user, drawer_id)

    lens = access.console_mode(request, user)
    access.remember_console_mode(request, lens)
    qs = _lens_occurrences(user, lens)

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

    # Filtro por categoria de crime (N1). Um dropdown dos N3 (centenas de tipos)
    # seria mau de UX; filtra-se pela categoria de topo via a cascata N3→N2→N1.
    cat = (request.GET.get('cat') or '').strip()
    if cat.isdigit():
        qs = qs.filter(crime_type__subcategoria__categoria_id=int(cat))

    date_after = (request.GET.get('date_after') or '').strip()
    date_before = (request.GET.get('date_before') or '').strip()
    d_after, d_before = parse_date(date_after), parse_date(date_before)
    if d_after:
        qs = qs.filter(date_time__date__gte=d_after)
    if d_before:
        qs = qs.filter(date_time__date__lte=d_before)

    # Arquivo vs ativo: processo CONCLUÍDO = todos os itens em estado legal
    # terminal. Deriva-se sobre o âmbito já filtrado (sem coluna nova) e divide-se.
    archived_ids = _archived_occurrence_ids(user, qs)
    qs = qs.filter(pk__in=archived_ids) if archived else qs.exclude(pk__in=archived_ids)

    sort_key = (request.GET.get('sort') or 'recent').strip()
    qs = qs.order_by(_OCC_SORTS.get(sort_key, '-date_time'))

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_occurrences(page_obj.object_list)

    list_endpoint = '/arquivo/' if archived else '/occurrences/'
    # Querystring base (sem 'page') para a paginação propagar TODOS os filtros.
    qs_base = urlencode({k: v for k, v in (
        ('lens', lens), ('q', query), ('pri', priority), ('cat', cat),
        ('date_after', date_after), ('date_before', date_before), ('sort', sort_key),
    ) if v})

    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'pri': priority,
        'cat': cat,
        'date_after': date_after,
        'date_before': date_before,
        'sort': sort_key,
        'qs_base': qs_base,
        'lens': lens,
        'is_archive': archived,
        'list_endpoint': list_endpoint,
        'crime_categories': CrimeCategoria.objects.order_by('codigo'),
        'selected_id': request.GET.get('selected') or '',
        'is_htmx': bool(request.headers.get('HX-Request')),
    }

    if ctx['is_htmx']:
        return render(request, 'partials/_occurrences_grid.html', ctx)
    return render(request, 'arquivo.html' if archived else 'occurrences.html', ctx)


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
    evidences = list(
        Evidence.objects.filter(occurrence=occ)
        .select_related('occurrence', 'agent', 'parent_evidence')
        .prefetch_related('custody_chain')
        .order_by('parent_evidence_id', 'id')
    )
    _decorate_evidences(evidences)
    occ.evidence_count = len(evidences)
    # Encaminhar é ação de escrita: escondida a perfis só-leitura (a porta real é
    # o can_append_custody por item, no serializer).
    can_handoff = getattr(user, 'profile', None) not in ('CHEFE_SERVICO', 'AUDITOR')
    return render(
        request,
        'occurrence_detail.html',
        {'occ': occ, 'evidences': evidences, 'can_handoff': can_handoff},
    )


def _encaminhaveis(user, occ):
    """Itens da ocorrência que o utilizador pode ENCAMINHAR agora: génese feita,
    não terminais nem já em trânsito (ENCAMINHAMENTO é próximo evento válido) E com
    permissão de escrita (``can_append_custody``). Lista decorada para o template.
    Anota ``ev.checked`` (omissão: todos selecionados — encaminha-se a prova junta)."""
    itens = []
    qs = (
        Evidence.objects.filter(occurrence=occ)
        .select_related('occurrence', 'agent', 'parent_evidence')
        .prefetch_related('custody_chain')
        .order_by('parent_evidence_id', 'id')
    )
    for ev in qs:
        events = sort_custody_chain(ev.custody_chain.all())
        valid = {v for v, _ in _valid_next_events(events, ev)}
        if EventType.ENCAMINHAMENTO_CUSTODIA.value in valid and access.can_append_custody(
            user, ev, EventType.ENCAMINHAMENTO_CUSTODIA
        ):
            itens.append(ev)
    _decorate_evidences(itens)
    return itens


def _register_handoff(request, evidences, bearer_id, destino):
    """Regista ENCAMINHAMENTO_CUSTODIA em cada item (1 evento/item), numa transação
    atómica: portador + destino, custódio promovido pelo tipo do destino, SEM GPS (a
    coordenada regista-se na receção). Reusa o ``ChainOfCustodySerializer`` (guardas
    do ledger, ownership, gate de laboratório, hash, criação da ProvaEmTransito).
    Devolve lista de erros (vazia = sucesso); qualquer falha reverte tudo."""
    from django.db import transaction

    from core.serializers import ChainOfCustodySerializer

    base = {
        'event_type': EventType.ENCAMINHAMENTO_CUSTODIA.value,
        'bearer': bearer_id,
        'custodian_institution': destino.id,
        'observations': (request.POST.get('observations') or '').strip(),
    }
    ctype = custody_transitions.CUSTODIAN_TYPE_BY_INSTITUTION.get(destino.type)
    if ctype:
        base['custodian_type'] = ctype
    errors = []
    try:
        with transaction.atomic():
            for ev in evidences:
                serializer = ChainOfCustodySerializer(
                    data=dict(base, evidence=ev.id), context={'request': request}
                )
                serializer.is_valid(raise_exception=True)
                record = serializer.save(agent=request.user)
                log_access(
                    request=request,
                    action=AuditLog.Action.CREATE,
                    resource_type=AuditLog.ResourceType.CUSTODY,
                    resource_id=record.pk,
                    details={
                        'evidence_id': record.evidence_id,
                        'event_type': record.event_type,
                        'destino': destino.id,
                    },
                )
    except (DRFValidationError, DjangoValidationError) as exc:
        errors = _flatten_validation_error(exc)
    return errors


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
    template = 'partials/_encaminhar_form.html' if modal else 'occurrence_encaminhar.html'
    itens = _encaminhaveis(user, occ)
    destinos = Institution.objects.filter(is_active=True).order_by('name')
    portadores = Portador.objects.filter(is_active=True).order_by('apelido', 'nome')

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
        bearer_id = (request.POST.get('bearer') or '').strip()
        dest_id = (request.POST.get('custodian_institution') or '').strip()
        destino = destinos.filter(pk=dest_id).first() if dest_id.isdigit() else None
        errs = []
        if not sel:
            errs.append('Selecione pelo menos um item para encaminhar.')
        if not bearer_id:
            errs.append('Indique o portador que conduz a prova.')
        if destino is None:
            errs.append('Indique uma instituição de destino válida.')
        if not errs:
            errs = _register_handoff(request, sel, bearer_id, destino)
        if not errs:
            messages.success(
                request,
                f'{len(sel)} item(ns) encaminhado(s) para {destino.sigla or destino.name}.',
            )
            if modal:
                resp = HttpResponse(status=204)
                resp['HX-Redirect'] = f'/occurrences/{occ.id}/'
                return resp
            return HttpResponseRedirect(f'/occurrences/{occ.id}/')
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
    if not (user.is_staff or getattr(user, 'profile', None) == 'FIRST_RESPONDER'):
        return HttpResponseForbidden('Apenas agentes podem registar ocorrências.')

    crime_categories = CrimeCategoria.objects.order_by('codigo')
    # Duas superfícies da MESMA lógica: página completa (fallback no-JS) e
    # fragmento modal (ação-in-place, ?modal=1). O sucesso no modal devolve
    # 204 + HX-Redirect (o HTMX navega); o erro devolve o fragmento.
    modal = _wants_modal(request)
    template = 'partials/_occurrence_form.html' if modal else 'occurrences_new.html'

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
            'modal': modal,
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
            if modal:
                resp = HttpResponse(status=204)
                resp['HX-Redirect'] = f'/occurrences/{occ.pk}/'
                return resp
            return HttpResponseRedirect(f'/occurrences/{occ.pk}/')
        return render(
            request, template, _ctx(serializer.errors, request.POST), status=400
        )

    return render(request, template, _ctx({}, {}))


def _can_manage_institutions(user):
    """Gerir instituições (pontos de controlo) é ato de administração: ``staff``
    ou credencial NACIONAL. Lista e criação partilham o mesmo portão."""
    return bool(user.is_staff or getattr(user, 'has_national_clearance', False))


def _wants_modal(request):
    """Pedido em modo modal (ação-in-place)? GET ``?modal=1`` (abrir) ou o
    campo escondido ``modal`` no POST (submeter)."""
    return request.GET.get('modal') == '1' or request.POST.get('modal') == '1'


@jwt_cookie_user
def institutions_view(request):
    """Lista de instituições (pontos de controlo fixos) — gestão (staff/NACIONAL).

    As instituições são dados de referência da custódia (não são prova). Esta é a
    casa do gatilho de criação ação-in-place (modal). Filtra por texto e por tipo.
    """
    user = request.user
    if not _can_manage_institutions(user):
        return HttpResponseForbidden('Sem permissão para gerir instituições.')

    qs = Institution.objects.order_by('name')
    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(sigla__icontains=query))
    itype = (request.GET.get('type') or '').strip()
    if itype in InstitutionType.values:
        qs = qs.filter(type=itype)

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    qs_base = urlencode({k: v for k, v in (('q', query), ('type', itype)) if v})
    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'type': itype,
        'institution_types': InstitutionType.choices,
        'qs_base': qs_base,
    }
    return render(request, 'institutions.html', ctx)


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
    if not _can_manage_institutions(user):
        return HttpResponseForbidden('Sem permissão para criar instituições.')

    modal = _wants_modal(request)
    template = 'partials/_institution_form.html' if modal else 'institution_new.html'

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
            if modal:
                resp = HttpResponse(status=204)
                resp['HX-Redirect'] = '/institutions/'
                return resp
            return HttpResponseRedirect('/institutions/')
        return render(request, template, _ctx(serializer.errors, request.POST), status=400)

    return render(request, template, _ctx({}, {}))


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

    lens = access.console_mode(request, user)
    access.remember_console_mode(request, lens)
    qs = _lens_evidences(user, lens)

    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(
            Q(code__icontains=query)
            | Q(description__icontains=query)
            | Q(serial_number__icontains=query)
            | Q(occurrence__number__icontains=query)
        )

    etype = (request.GET.get('type') or '').strip()
    if etype in evidence_type_config.active_codes():
        qs = qs.filter(type=etype)

    # Filtro por estado legal DERIVADO (entrada a partir dos tiles do Painel).
    # WI-E: uma só query agrupada em vez de iterar todas as evidências 2x. O estado
    # deriva da cadeia COMPLETA dos itens da zona ativa (_lens_custody devolve
    # cadeias inteiras, não eventos isolados).
    state = (request.GET.get('state') or '').strip()
    if state in LEGAL_STATES:
        states = _legal_states_by_evidence(user, custody_qs=_lens_custody(user, lens))
        matching = [ev_id for ev_id, st in states.items() if st == state]
        qs = qs.filter(id__in=matching)

    date_after = (request.GET.get('date_after') or '').strip()
    date_before = (request.GET.get('date_before') or '').strip()
    d_after, d_before = parse_date(date_after), parse_date(date_before)
    if d_after:
        qs = qs.filter(timestamp_seizure__date__gte=d_after)
    if d_before:
        qs = qs.filter(timestamp_seizure__date__lte=d_before)

    sort_key = (request.GET.get('sort') or 'recent').strip()
    qs = qs.order_by(_EVD_SORTS.get(sort_key, '-timestamp_seizure'))

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_evidences(page_obj.object_list)

    qs_base = urlencode({k: v for k, v in (
        ('lens', lens), ('q', query), ('type', etype), ('state', state),
        ('date_after', date_after), ('date_before', date_before), ('sort', sort_key),
    ) if v})

    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'type': etype,
        'state': state,
        'state_label': LEGAL_STATE_LABELS.get(state, ''),
        'date_after': date_after,
        'date_before': date_before,
        'sort': sort_key,
        'qs_base': qs_base,
        'evidence_types': evidence_type_config.active_choices(),
        'legal_state_choices': list(LEGAL_STATE_LABELS.items()),
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if ctx['is_htmx']:
        return render(request, 'partials/_evidences_grid.html', ctx)
    return render(request, 'evidences.html', ctx)


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
    if not (user.is_staff or getattr(user, 'profile', None) == 'FIRST_RESPONDER'):
        return HttpResponseForbidden('Apenas agentes podem registar evidências.')

    occurrences = _scope_occurrences(user).order_by('-date_time')
    parents = _scope_evidences(user).order_by('occurrence__number', 'code')
    transversal_fields, type_fields = _evd_field_ctx(
        request.POST if request.method == 'POST' else {}
    )
    # Duas superfícies da MESMA lógica: página completa (fallback no-JS) e
    # fragmento modal (ação-in-place, ?modal=1). Sucesso no modal → 204 +
    # HX-Redirect; erro → fragmento com os erros.
    modal = _wants_modal(request)
    template = 'partials/_evidence_form.html' if modal else 'evidences_new.html'

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
                    {
                        'occurrences': occurrences,
                        'parents': parents,
                        'evidence_types': evidence_type_config.active_choices(),
                        'transversal_fields': transversal_fields,
                        'type_fields': type_fields,
                        # Input cru (não validated_data) é intencional: repopula
                        # o <select> com a PK em string (casa com o value da opção);
                        # é um serializer DRF, não um Form, e o re-render mostra o
                        # que o utilizador submeteu.
                        'preselect': request.POST.get('occurrence', ''),  # nosemgrep
                        'errors': {'geral': _flatten_validation_error(exc)},
                        'data': request.POST,  # nosemgrep
                        'modal': modal,
                        'action': '/evidences/new/',
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
            messages.success(request, f'Item de prova {ev.code} apreendido e registado.')
            if modal:
                resp = HttpResponse(status=204)
                resp['HX-Redirect'] = f'/evidences/{ev.pk}/'
                return resp
            return HttpResponseRedirect(f'/evidences/{ev.pk}/')
        return render(
            request,
            template,
            {
                'occurrences': occurrences,
                'parents': parents,
                'evidence_types': evidence_type_config.active_choices(),
                'transversal_fields': transversal_fields,
                'type_fields': type_fields,
                'preselect': request.POST.get('occurrence', ''),
                'errors': serializer.errors,
                'data': request.POST,
                'modal': modal,
                'action': '/evidences/new/',
            },
            status=400,
        )

    return render(
        request,
        template,
        {
            'occurrences': occurrences,
            'parents': parents,
            'evidence_types': evidence_type_config.active_choices(),
            'transversal_fields': transversal_fields,
            'type_fields': type_fields,
            'preselect': request.GET.get('occurrence', ''),
            'errors': {},
            'data': {},
            'modal': modal,
            'action': '/evidences/new/',
        },
    )


def _decorate_events(events):
    """Anota cada evento do ledger com rótulos PT e hash curto (apresentação)."""
    for r in events:
        r.event_label = r.get_event_type_display()
        r.custodian_label = r.get_custodian_type_display() if r.custodian_type else '—'
        r.agent_label = get_user_display_name(r.agent)
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
    ev = _readable_evidence(user, evidence_id)
    if ev is None:
        return HttpResponseNotFound('Evidência não encontrada.')
    _decorate_evidences([ev])
    events = sort_custody_chain(ev.custody_chain.all())
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
    from core.serializers import ChainOfCustodySerializer

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
    serializer = ChainOfCustodySerializer(data=data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    record = serializer.save(agent=request.user)
    log_access(
        request=request,
        action=AuditLog.Action.CREATE,
        resource_type=AuditLog.ResourceType.CUSTODY,
        resource_id=record.pk,
        details={
            'evidence_id': record.evidence_id,
            'event_type': record.event_type,
            'genesis': True,
        },
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
    # Custódia institucional / pessoal (ADR-0017) + portador no encaminhamento
    # (ADR-0016 v2) — opcionais.
    for fk in ('custodian_institution', 'custodian_user', 'relinquished_by', 'bearer'):
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
            # Portadores ativos para o select do ENCAMINHAMENTO (ADR-0016 v2).
            'portadores': Portador.objects.filter(is_active=True).order_by('apelido', 'nome'),
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


def _readable_custody(user, pk):
    """Evento de custódia por ``pk`` se o utilizador pode LER o seu item na consola
    (item-level ``can_view_evidence`` OU processo da instituição —
    :func:`_readable_evidence`); ``None`` caso contrário."""
    try:
        rec = ChainOfCustody.objects.select_related(
            'evidence', 'evidence__occurrence', 'agent'
        ).get(pk=pk)
    except (ChainOfCustody.DoesNotExist, ValueError, TypeError):
        return None
    if access.can_view_evidence(user, rec.evidence) or access.is_occurrence_institutional(
        user, rec.evidence.occurrence
    ):
        return rec
    return None


def _custody_drawer(request, user, drawer_id):
    """Fragmento HTMX do painel direito (detalhe Local) de um evento de custódia."""
    rec = _readable_custody(user, drawer_id)
    if rec is None:
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

    lens = access.console_mode(request, user)
    access.remember_console_mode(request, lens)
    qs = _lens_custody(user, lens)

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

    # Custódio (coluna visível, antes não filtrável) e instituição titular.
    custodian = (request.GET.get('custodian') or '').strip()
    if custodian in CustodianType.values:
        qs = qs.filter(custodian_type=custodian)

    institution = (request.GET.get('institution') or '').strip()
    if institution.isdigit():
        qs = qs.filter(custodian_institution_id=int(institution))

    # Estado legal DERIVADO do item a que o evento pertence (mesmo padrão WI-E),
    # restrito à lente ativa (cadeias completas dos itens da lente).
    state = (request.GET.get('state') or '').strip()
    if state in LEGAL_STATES:
        states = _legal_states_by_evidence(user, custody_qs=_lens_custody(user, lens))
        matching = [ev_id for ev_id, st in states.items() if st == state]
        qs = qs.filter(evidence_id__in=matching)

    date_after = (request.GET.get('date_after') or '').strip()
    date_before = (request.GET.get('date_before') or '').strip()
    d_after, d_before = parse_date(date_after), parse_date(date_before)
    if d_after:
        qs = qs.filter(timestamp__date__gte=d_after)
    if d_before:
        qs = qs.filter(timestamp__date__lte=d_before)

    sort_key = (request.GET.get('sort') or 'recent').strip()
    qs = qs.order_by(_CUSTODY_SORTS.get(sort_key, '-timestamp'))

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_events(page_obj.object_list)

    qs_base = urlencode({k: v for k, v in (
        ('lens', lens), ('q', query), ('event', event), ('custodian', custodian),
        ('institution', institution), ('state', state),
        ('date_after', date_after), ('date_before', date_before), ('sort', sort_key),
    ) if v})

    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'event': event,
        'custodian': custodian,
        'institution': institution,
        'state': state,
        'date_after': date_after,
        'date_before': date_before,
        'sort': sort_key,
        'qs_base': qs_base,
        'event_types': EventType.choices,
        'custodian_types': CustodianType.choices,
        'institutions': Institution.objects.filter(is_active=True).order_by('name'),
        'legal_state_choices': list(LEGAL_STATE_LABELS.items()),
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
    lens = access.console_mode(request, user)
    access.remember_console_mode(request, lens)
    qs = _lens_occurrences(user, lens).annotate(n_ev=Count('evidences'))
    query = (request.GET.get('q') or '').strip()
    if query:
        qs = qs.filter(
            Q(number__icontains=query) | Q(code__icontains=query) | Q(address__icontains=query)
        )
    qs = qs.order_by('-date_time')
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    _decorate_occurrences(page_obj.object_list)
    qs_base = urlencode({k: v for k, v in (('lens', lens), ('q', query)) if v})
    ctx = {
        'page_obj': page_obj,
        'total': paginator.count,
        'q': query,
        'qs_base': qs_base,
        'is_htmx': bool(request.headers.get('HX-Request')),
    }
    if ctx['is_htmx']:
        return render(request, 'partials/_reports_grid.html', ctx)
    return render(request, 'reports.html', ctx)


def occurrence_intake_view(request, occurrence_id):
    """Página de check-list de RECEÇÃO (2.ª metade do handoff, ADR-0016 v2).

    Recebe a prova em trânsito: regista um ``RECEPCAO_CUSTODIA`` por item marcado,
    em lote atómico, reusando o ``ChainOfCustodySerializer`` (herda destino/custódio
    do encaminhamento e, em instituição fixa, a coordenada do registo da instituição).

    Requisitos de auth (impostos no servidor antes do render):
    1. JWT válido em cookie `fq_access`.
    2. Pode receber: EXPERT/staff (intake de laboratório) OU membro da instituição
       de destino de um encaminhamento pendente desta ocorrência (receção OPC→OPC —
       alinha com a caixa "prova a chegar"). A ESCRITA é, ainda assim, validada por
       ``can_append_custody`` no serializer.

    Quem não cumpra recebe HTTP 403.
    """
    from django.contrib.auth import get_user_model

    from core.models import Occurrence

    token = request.COOKIES.get('fq_access')
    if not token:
        return HttpResponseRedirect('/login/?next=' + request.path)
    try:
        # `decoded` (não `access`): `access` é o módulo core.access — reutilizar o
        # nome mascará-lo-ia e rebentaria qualquer chamada access.* nesta função.
        decoded = AccessToken(token)
    except TokenError:
        return HttpResponseRedirect('/login/?next=' + request.path)

    user = get_user_model().objects.filter(pk=decoded['user_id']).first()
    if user is None:
        return HttpResponseRedirect('/login/?next=' + request.path)

    # Esta view descodifica o JWT à mão (não passa pela auth do DRF), por isso
    # request.user ficaria anónimo. Fixamo-lo para que o gate de escrita do
    # ChainOfCustodySerializer (access.can_append_custody, agora fail-closed)
    # autorize com base no utilizador real do intake.
    request.user = user

    occurrence = Occurrence.objects.filter(pk=occurrence_id).first()
    # Quem pode RECEBER (abrir o intake): operador de laboratório (EXPERT) ou staff
    # — E TAMBÉM um membro da instituição de destino de um encaminhamento pendente
    # DESTA ocorrência. Sem este último ramo, a receção OPC→OPC fica num beco: a
    # caixa "prova a chegar" mostra o item ao membro do destino, mas o intake
    # recusava-o (403). A porta de ESCRITA real continua no serializer
    # (can_append_custody, fail-closed); aqui decide-se só quem vê/usa o formulário.
    is_expert = getattr(user, 'profile', None) == 'FORENSIC_EXPERT'
    can_receive = (
        user.is_staff
        or user.is_superuser
        or is_expert
        or access.has_inbound_for_occurrence(user, occurrence)
    )
    if not can_receive:
        return render(request, '403_intake.html', status=403)
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
    # Uma só query para TODOS os eventos da ocorrência (antes: uma query por
    # evidência — N+1 a cada carregamento da página de intake). Agrupa por
    # evidência e deriva o estado uma vez por item.
    eventos_por_ev = {}
    for rec in (
        ChainOfCustody.objects.filter(evidence__occurrence=occurrence)
        .select_related('custodian_institution')
        .order_by('evidence_id', 'sequence')
    ):
        eventos_por_ev.setdefault(rec.evidence_id, []).append(rec)
    state_by_evidence = {
        ev.id: (derive_legal_state(eventos_por_ev[ev.id]) if ev.id in eventos_por_ev else '')
        for ev in evidences
    }

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
        from django.db import transaction

        from core.serializers import ChainOfCustodySerializer

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
            try:
                with transaction.atomic():
                    for ev in to_receive:
                        payload = {
                            'evidence': ev.id,
                            'event_type': EventType.RECEPCAO_CUSTODIA,
                        }
                        # Rótulo de local = nome da instituição de destino (herdado do
                        # encaminhamento). O FK custodian_institution identifica o
                        # destino com precisão; location_name é só a etiqueta legível.
                        destino = eventos_por_ev[ev.id][-1].custodian_institution
                        if destino is not None:
                            payload['location_name'] = destino.name
                        if storage:
                            payload['storage_location'] = storage
                        if observations:
                            payload['observations'] = observations
                        s = ChainOfCustodySerializer(
                            data=payload, context={'request': request}
                        )
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
                    f'Receção registada: {len(to_receive)} item(ns).',
                )
                return HttpResponseRedirect(f'/occurrences/{occurrence.id}/')
            except (DjangoValidationError, DRFValidationError) as exc:
                # Erros de validação (guardas do ledger, GPS, permissão) são
                # accionáveis e seguros de mostrar ao operador.
                messages_list = getattr(exc, 'messages', None)
                if messages_list:
                    intake_errors.extend(messages_list)
                else:
                    intake_errors.append(str(getattr(exc, 'detail', exc)))
            except Exception:  # noqa: BLE001 — falha inesperada → rollback (atomic) + msg genérica
                # NÃO interpolar a excepção crua na página (fuga de detalhe interno
                # + mascarava o erro real). Regista-se o stack trace e mostra-se
                # uma mensagem genérica.
                logger.exception('Falha inesperada no intake da ocorrência %s', occurrence.id)
                intake_errors.append(
                    'Falha no registo. A operação foi revertida; tente novamente '
                    'ou contacte o suporte se persistir.'
                )

    rows = [
        {
            'evidence': ev,
            'current_state': state_by_evidence[ev.id],
            'current_state_display': LEGAL_STATE_LABELS.get(state_by_evidence[ev.id])
            or 'Sem custódia',
            'current_state_css': LEGAL_STATE_CSS.get(state_by_evidence[ev.id], 'muted'),
            # Recebível = em trânsito (encaminhado, ainda por receber — ADR-0016 v2).
            'in_transit': state_by_evidence[ev.id] == 'em_transito',
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
    """Estatísticas agregadas — server-rendered (Fase 3). Agregados baratos
    (não deriva estado legal por linha; isso fica para uma vista dedicada)."""
    user = request.user
    lens = access.console_mode(request, user)
    access.remember_console_mode(request, lens)
    occ_qs = _lens_occurrences(user, lens)
    evd_qs = _lens_evidences(user, lens)
    cus_qs = _lens_custody(user, lens)
    kpis = {
        'occurrences': occ_qs.count(),
        'evidences': evd_qs.count(),
        'custody_events': cus_qs.count(),
        'prioritarias': occ_qs.filter(priority=Occurrence.Priority.PRIORITARIA).count(),
    }
    # Lookup tolerante: EnumValue(x) levantaria ValueError (→ 500) se a BD tivesse
    # um valor fora dos choices actuais (ex.: dado anterior a um rename de tipo/
    # evento). dict(choices).get cai no valor cru em vez de rebentar.
    type_labels = evidence_type_config.labels()
    event_labels = dict(EventType.choices)
    by_type = [
        {'label': type_labels.get(r['type'], r['type']), 'n': r['n']}
        for r in evd_qs.values('type').annotate(n=Count('id')).order_by('-n')
    ]
    by_event = [
        {'label': event_labels.get(r['event_type'], r['event_type']), 'n': r['n']}
        for r in cus_qs.values('event_type').annotate(n=Count('id')).order_by('-n')
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
