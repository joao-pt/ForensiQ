"""
ForensiQ — Endpoints de autenticação via cookies HttpOnly.

- POST /api/auth/login/   → valida credenciais, emite access+refresh em cookies.
- POST /api/auth/refresh/ → rotaciona tokens lendo o refresh do cookie.
- POST /api/auth/logout/  → blacklist do refresh e remoção dos cookies.
"""

from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from core.auth import (
    REFRESH_COOKIE_NAME,
    delete_auth_cookies,
    set_auth_cookies,
)
from core.serializers import UserDetailSerializer
from core.throttles import AuthRateThrottle


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CookieLoginView(APIView):
    """Emite tokens JWT em cookies HttpOnly + CSRF cookie."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        data = serializer.validated_data
        user = serializer.user
        response = Response(
            {'user': UserDetailSerializer(user).data},
            status=status.HTTP_200_OK,
        )
        set_auth_cookies(response, access=data['access'], refresh=data['refresh'])
        get_token(request)
        return response


class CookieRefreshView(APIView):
    """Lê o refresh do cookie, valida e rotaciona."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        refresh = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not refresh:
            return Response(
                {'detail': 'Refresh token em falta.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = TokenRefreshSerializer(data={'refresh': refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        data = serializer.validated_data
        response = Response({'detail': 'Token renovado.'}, status=status.HTTP_200_OK)
        set_auth_cookies(
            response,
            access=data['access'],
            refresh=data.get('refresh'),
        )
        return response


class CookieLogoutView(APIView):
    """Blacklist do refresh e remoção dos cookies."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        refresh = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass

        response = Response(status=status.HTTP_204_NO_CONTENT)
        delete_auth_cookies(response)
        return response
