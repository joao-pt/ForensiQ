"""
ForensiQ — Permissões personalizadas para a API REST.

Dois perfis de acesso:
- AGENT (first responder): cria ocorrências, evidências, dispositivos, inicia custódia.
- EXPERT (perito forense): recebe evidências no laboratório, avança custódia, conclui perícia.

Ambos os perfis podem consultar (GET) todos os recursos.

NOTA DE SEGURANÇA: O ForensiQ gere dados potencialmente sob segredo de
justiça. Todas as permissões devem validar explicitamente o perfil do
utilizador — nunca confiar apenas em IsAuthenticated.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAgent(BasePermission):
    """
    Permite escrita apenas a utilizadores com perfil AGENT.
    Leitura (GET, HEAD, OPTIONS) é permitida a qualquer utilizador autenticado.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.profile == 'AGENT'


class IsExpert(BasePermission):
    """
    Permite escrita apenas a utilizadores com perfil EXPERT.
    Leitura (GET, HEAD, OPTIONS) é permitida a qualquer utilizador autenticado.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.profile == 'EXPERT'


class IsAgentOrExpert(BasePermission):
    """
    Permite escrita apenas a AGENT ou EXPERT autenticados.
    Leitura é permitida a qualquer utilizador autenticado com perfil válido.

    Rejeita utilizadores autenticados sem perfil AGENT/EXPERT
    (ex.: superusers criados apenas para admin).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Validar que o utilizador tem um perfil operacional
        return request.user.profile in ('AGENT', 'EXPERT')


class IsOwnerOrReadOnly(BasePermission):
    """
    Permite edição apenas ao utilizador que criou o recurso (campo 'agent').
    Leitura permitida a qualquer utilizador autenticado.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return hasattr(obj, 'agent') and obj.agent == request.user
