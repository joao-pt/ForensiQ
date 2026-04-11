"""
ForensiQ — Views do frontend (server-side rendering de templates).

Estas views servem os templates HTML do frontend.
A autenticação e lógica de negócio são tratadas no frontend via JWT + API REST.

SEGURANÇA: as páginas protegidas verificam a presença de um token JWT válido
num cookie (definido pelo frontend após login). Isto impede que o HTML da
aplicação seja servido a utilizadores não autenticados, mesmo que os dados
sensíveis só sejam carregados via API.
"""

from functools import wraps

from django.http import HttpResponseRedirect
from django.shortcuts import render
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


def jwt_cookie_required(view_func):
    """
    Decorator que verifica a presença de um token JWT válido no cookie
    'forensiq_access'. Redireciona para /login/ se ausente ou inválido.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token = request.COOKIES.get('forensiq_access')
        if not token:
            return HttpResponseRedirect('/login/')
        try:
            AccessToken(token)
        except TokenError:
            return HttpResponseRedirect('/login/')
        return view_func(request, *args, **kwargs)
    return wrapper


def login_view(request):
    """Página de login (pública)."""
    return render(request, 'login.html')


@jwt_cookie_required
def dashboard_view(request):
    """Painel principal — requer token JWT válido."""
    return render(request, 'dashboard.html')


@jwt_cookie_required
def occurrences_view(request):
    """Lista de ocorrências — requer token JWT válido."""
    return render(request, 'occurrences.html')


@jwt_cookie_required
def occurrences_new_view(request):
    """Formulário de nova ocorrência — requer token JWT válido."""
    return render(request, 'occurrences_new.html')


@jwt_cookie_required
def evidences_view(request):
    """Lista de evidências — requer token JWT válido."""
    return render(request, 'evidences.html')


@jwt_cookie_required
def evidences_new_view(request):
    """Formulário de nova evidência — requer token JWT válido."""
    return render(request, 'evidences_new.html')


@jwt_cookie_required
def custody_timeline_view(request, evidence_id):
    """Timeline visual da cadeia de custódia de uma evidência — requer token JWT válido."""
    return render(request, 'custody_timeline.html', {'evidence_id': evidence_id})
