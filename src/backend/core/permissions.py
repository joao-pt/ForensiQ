"""
ForensiQ — Permissões personalizadas para a API REST.

Perfis operacionais base:
- FIRST_RESPONDER (primeiro interveniente): cria ocorrências, evidências,
  dispositivos, abre a cadeia de custódia.
- FORENSIC_EXPERT (perito forense): recebe evidências no laboratório, avança
  a custódia, conclui a perícia.

Ambos podem consultar (GET) todos os recursos.

NOTA DE SEGURANÇA: O ForensiQ gere dados potencialmente sob segredo de
justiça. Todas as permissões devem validar explicitamente o perfil do
utilizador — nunca confiar apenas em IsAuthenticated. O controlo de acesso
*need-to-know* derivado da cadeia de custódia é definido no ADR-0017.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAgent(BasePermission):
    """
    Permite escrita apenas a utilizadores com perfil FIRST_RESPONDER.
    Leitura (GET, HEAD, OPTIONS) é permitida a qualquer utilizador autenticado.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.profile == 'FIRST_RESPONDER'


class IsExpert(BasePermission):
    """
    Permite escrita apenas a utilizadores com perfil FORENSIC_EXPERT.
    Leitura (GET, HEAD, OPTIONS) é permitida a qualquer utilizador autenticado.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.profile == 'FORENSIC_EXPERT'


class IsAgentOrExpert(BasePermission):
    """
    Permite escrita apenas a FIRST_RESPONDER ou FORENSIC_EXPERT autenticados.
    Leitura é permitida a qualquer utilizador autenticado com perfil válido.

    Rejeita utilizadores autenticados sem perfil operacional
    (ex.: superusers criados apenas para admin).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Validar que o utilizador tem um perfil operacional
        return request.user.profile in ('FIRST_RESPONDER', 'FORENSIC_EXPERT')


class CanAccessCustodyApi(BasePermission):
    """Gate de acesso à API de custódia (ChainOfCustodyViewSet).

    - LEITURA (GET/HEAD/OPTIONS): qualquer utilizador autenticado com perfil
      operacional — o ``get_queryset`` aplica o âmbito *need-to-know* (ADR-0017).
    - ESCRITA: qualquer perfil que NÃO seja só-leitura
      (CHEFE_SERVICO/AUDITOR nunca escrevem) ou staff. A autorização item-level
      (detém / override de perito / despacho da autoridade do caso) é decidida
      em ``access.can_append_custody`` dentro de ``perform_create``/``cascade``.

    Substitui ``IsAgentOrExpert`` no ChainOfCustodyViewSet, que bloqueava
    indevidamente CASE_AUTHORITY e EVIDENCE_CUSTODIAN — perfis que o modelo de
    acesso autoriza a escrever (despacho do MP, custódio que detém o item).
    ``IsAgentOrExpert`` mantém-se nos proxies geo (consulta de APIs externas),
    onde a restrição a FIRST_RESPONDER/FORENSIC_EXPERT é intencional.
    """

    def has_permission(self, request, view):
        from core import access

        user = request.user
        if not user or not user.is_authenticated:
            return False
        profile = getattr(user, 'profile', None)
        # Utilizador sem perfil operacional (ex.: superuser só-admin) só passa se
        # for staff.
        if not profile and not user.is_staff:
            return False
        if request.method in SAFE_METHODS:
            return True
        # ESCRITA: perfis só-leitura (CHEFE_SERVICO/AUDITOR) NUNCA escrevem — nem
        # com is_staff (sem `is_staff or`, senão um auditor/chefe a quem se desse
        # acesso de staff conseguiria escrever). Os restantes (perfil operacional
        # ou staff sem perfil só-leitura) podem TENTAR; a autorização item-level
        # fica para access.can_append_custody em perform_create/cascade.
        return profile not in access.READ_ONLY_PROFILES


class IsOwnerOrReadOnly(BasePermission):
    """
    Permite edição apenas ao utilizador que criou o recurso (campo 'agent').
    Leitura permitida a qualquer utilizador autenticado.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return hasattr(obj, 'agent') and obj.agent == request.user
