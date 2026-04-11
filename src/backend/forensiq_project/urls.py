"""
ForensiQ — Configuração de URLs raiz.

Inclui:
- /admin/ — Django Admin
- /api/ — API REST (core app)
- /api/auth/ — JWT authentication (login, refresh, verify)
- /api/schema/ — OpenAPI schema
- /api/docs/ — Swagger UI
- /login/, /dashboard/ — Frontend (templates HTML)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from core.frontend_views import (
    custody_timeline_view,
    dashboard_view,
    evidences_new_view,
    evidences_view,
    login_view,
    occurrences_new_view,
    occurrences_view,
)

urlpatterns = [
    # Django Admin
    path('admin/', admin.site.urls),

    # JWT Authentication
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # API REST (core)
    path('api/', include('core.urls')),

    # OpenAPI / Swagger
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # Frontend (templates HTML servidos pelo Django)
    path('', login_view, name='home'),
    path('login/', login_view, name='login'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('occurrences/', occurrences_view, name='occurrences'),
    path('occurrences/new/', occurrences_new_view, name='occurrences_new'),
    path('evidences/', evidences_view, name='evidences'),
    path('evidences/new/', evidences_new_view, name='evidences_new'),
    path('evidence/<int:evidence_id>/custody/', custody_timeline_view, name='custody_timeline'),
]

# Servir ficheiros media em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
