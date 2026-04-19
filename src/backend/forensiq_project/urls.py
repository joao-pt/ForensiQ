"""
ForensiQ — Configuração de URLs raiz.

Inclui:
- /admin/ — Django Admin
- /api/ — API REST (core app)
- /api/auth/ — JWT authentication (login, refresh, verify)
- /api/schema/ — OpenAPI schema
- /api/docs/ — Swagger UI
- /login/, /dashboard/ — Frontend (templates HTML)

Convenção de nomes (Wave 2d):
- Colecções: plural (/occurrences/, /evidences/, /custodies/)
- Instância: plural + id (/occurrences/<id>/)
- Sub-recursos: /evidences/<id>/custody/

Nomes antigos no singular (/occurrence/, /evidence/, /custody/) são
redireccionados com 301 permanente para retrocompatibilidade.
"""

import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from core.auth_views import (
    CookieLoginView,
    CookieLogoutView,
    CookieRefreshView,
)
from core.frontend_views import (
    custody_evidence_redirect,
    custody_list_view,
    custody_singular_redirect,
    custody_timeline_view,
    dashboard_view,
    evidence_detail_view,
    evidence_singular_redirect,
    evidences_new_view,
    evidences_view,
    login_view,
    occurrence_detail_singular_redirect,
    occurrence_detail_view,
    occurrence_singular_redirect,
    occurrences_new_view,
    occurrences_view,
)

urlpatterns = [
    # Django Admin (hidden behind environment variable prefix)
    path(os.environ.get('ADMIN_URL_PREFIX', 'admin') + '/', admin.site.urls),

    # JWT Authentication via HttpOnly cookies (rate-limited)
    path('api/auth/login/', CookieLoginView.as_view(), name='auth_login'),
    path('api/auth/refresh/', CookieRefreshView.as_view(), name='auth_refresh'),
    path('api/auth/logout/', CookieLogoutView.as_view(), name='auth_logout'),

    # API REST (core)
    path('api/', include('core.urls')),

    # OpenAPI / Swagger
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # -----------------------------------------------------------------
    # Frontend (templates HTML servidos pelo Django) — nomes canónicos
    # -----------------------------------------------------------------
    path('', login_view, name='home'),
    path('login/', login_view, name='login'),
    path('dashboard/', dashboard_view, name='dashboard'),

    # Ocorrências
    path('occurrences/', occurrences_view, name='occurrences'),
    path('occurrences/new/', occurrences_new_view, name='occurrences_new'),
    path('occurrences/<int:occurrence_id>/', occurrence_detail_view, name='occurrence_detail'),

    # Evidências
    path('evidences/', evidences_view, name='evidences'),
    path('evidences/new/', evidences_new_view, name='evidences_new'),
    path('evidences/<int:evidence_id>/', evidence_detail_view, name='evidence_detail'),
    path('evidences/<int:evidence_id>/custody/', custody_timeline_view, name='custody_timeline'),

    # Custódias
    path('custodies/', custody_list_view, name='custodies'),

    # -----------------------------------------------------------------
    # Redirects 301 — nomes antigos (singular) para retrocompatibilidade
    # -----------------------------------------------------------------
    path('occurrence/', occurrence_singular_redirect),
    path('occurrence/<int:occurrence_id>/', occurrence_detail_singular_redirect),
    path('evidence/', evidence_singular_redirect),
    path('evidence/<int:evidence_id>/custody/', custody_evidence_redirect),
    path('custody/', custody_singular_redirect),
]

# Servir ficheiros media em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
