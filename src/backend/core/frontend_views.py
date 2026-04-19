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

from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import render
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


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
def occurrence_detail_view(request, occurrence_id):
    """Detalhe de uma ocorrência — hub central do caso. Requer token JWT válido."""
    return render(request, 'occurrence_detail.html', {'occurrence_id': occurrence_id})


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
def evidence_detail_view(request, evidence_id):
    """Detalhe de uma evidência — requer token JWT válido."""
    return render(request, 'evidence_detail.html', {'evidence_id': evidence_id})


@jwt_cookie_required
def custody_timeline_view(request, evidence_id):
    """Timeline visual da cadeia de custódia de uma evidência — requer token JWT válido."""
    return render(request, 'custody_timeline.html', {'evidence_id': evidence_id})


@jwt_cookie_required
def custody_list_view(request):
    """
    Lista de transições de cadeia de custódia visíveis ao utilizador.

    A filtragem concreta (agente vê as suas; coordenador vê as da equipa;
    perito vê as em que é custodiante actual) é aplicada no endpoint REST
    `/api/custody/` via permissões do backend. Esta view apenas serve o
    template; o JS popula-o via API.
    """
    return render(request, 'custody_list.html')


@jwt_cookie_required
def investigation_report_view(request):
    """
    Relatório de investigação estática da aplicação (auditoria).

    Página editorial que lista achados de revisão de código organizados por
    severidade (Crítico / Alto / Médio / Baixo / Notas). O conteúdo é estático
    — serve como referência de arquitectura e registo do estado conhecido da
    base de código à data do relatório. Requer token JWT válido.
    """
    return render(request, 'investigation_report.html')


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
