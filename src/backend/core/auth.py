"""
ForensiQ — Autenticação JWT via HttpOnly cookies.

Substitui o fluxo `Authorization: Bearer` em localStorage por cookies
HttpOnly+Secure+SameSite=Strict, imunes a XSS. Mutações (POST/PATCH/DELETE)
passam a exigir CSRF token.
"""

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

ACCESS_COOKIE_NAME = 'fq_access'
REFRESH_COOKIE_NAME = 'fq_refresh'
REFRESH_COOKIE_PATH = '/api/auth/'


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return reason


def enforce_csrf(request):
    """Valida o CSRF token em pedidos autenticados via cookie."""
    check = _CSRFCheck(lambda req: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f'CSRF Failed: {reason}')


class JWTCookieAuthentication(JWTAuthentication):
    """
    Lê o access token do cookie `fq_access` (HttpOnly).

    Em pedidos de escrita (não-safe methods) valida CSRF para mitigar
    ataques cross-site que reutilizariam o cookie automaticamente.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            raw_token = request.COOKIES.get(ACCESS_COOKIE_NAME)
            if raw_token is None:
                return None
        else:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)

        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            enforce_csrf(request)

        return (user, validated_token)


def _cookie_kwargs(max_age, path='/'):
    return {
        'max_age': max_age,
        'httponly': True,
        'secure': not settings.DEBUG,
        'samesite': 'Strict',
        'path': path,
    }


def set_auth_cookies(response, access, refresh=None):
    access_lifetime = settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        str(access),
        **_cookie_kwargs(int(access_lifetime.total_seconds())),
    )
    if refresh is not None:
        refresh_lifetime = settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            str(refresh),
            **_cookie_kwargs(int(refresh_lifetime.total_seconds()), path=REFRESH_COOKIE_PATH),
        )


def delete_auth_cookies(response):
    response.delete_cookie(ACCESS_COOKIE_NAME, path='/')
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
