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


class IsOwnerOrReadOnly(BasePermission):
    """
    Permite edição apenas ao utilizador que criou o recurso (campo 'agent').
    Leitura permitida a qualquer utilizador autenticado.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return hasattr(obj, 'agent') and obj.agent == request.user
