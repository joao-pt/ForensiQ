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

from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from rest_framework.throttling import ScopedRateThrottle

from core.auth_views import (
    CookieLoginView,
    CookieLogoutView,
    CookieRefreshView,
)
from core.frontend_views import (
    arquivo_view,
    audit_console_view,
    custody_evidence_redirect,
    custody_list_view,
    custody_singular_redirect,
    custody_timeline_view,
    dashboard_view,
    evidence_detail_view,
    evidence_singular_redirect,
    evidences_new_view,
    evidences_view,
    inbound_view,
    institution_new_view,
    institutions_view,
    login_view,
    occurrence_despachar_view,
    occurrence_detail_singular_redirect,
    occurrence_detail_view,
    occurrence_encaminhar_view,
    occurrence_intake_view,
    occurrence_restituir_view,
    occurrence_singular_redirect,
    occurrence_validar_view,
    occurrences_new_view,
    occurrences_view,
    public_verify_view,
    reports_view,
    settings_view,
    stats_view,
    verifications_view,
)
from core.views import MediaServeView


class ThrottledSchemaView(SpectacularAPIView):
    """Vista de schema OpenAPI com rate-limit (scope ``schema``).

    O ``SpectacularAPIView`` é público (sem auth) e gera o schema a partir
    da introspecção de todas as rotas — uma operação não trivial. Aplicamos
    o ``ScopedRateThrottle`` com o scope ``schema`` (30/min, definido em
    settings) para que a superfície pública tenha freio, em coerência com os
    restantes endpoints com throttle por scope.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'schema'


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
    path('api/schema/', ThrottledSchemaView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # -----------------------------------------------------------------
    # Frontend (templates HTML servidos pelo Django) — nomes canónicos
    # -----------------------------------------------------------------
    path('', login_view, name='home'),
    path('login/', login_view, name='login'),
    path('dashboard/', dashboard_view, name='dashboard'),

    # PWA — service worker (scope raiz) + manifest. Servidos por template para
    # que {% static %} resolva os caminhos com hashing (WhiteNoise) em produção.
    path(
        'sw.js',
        TemplateView.as_view(template_name='sw.js', content_type='application/javascript'),
        name='service_worker',
    ),
    path(
        'manifest.webmanifest',
        TemplateView.as_view(
            template_name='manifest.webmanifest', content_type='application/manifest+json'
        ),
        name='manifest',
    ),

    # Ocorrências
    path('occurrences/', occurrences_view, name='occurrences'),
    path('occurrences/new/', occurrences_new_view, name='occurrences_new'),
    # Arquivo — processos concluídos (itens todos em estado terminal)
    path('arquivo/', arquivo_view, name='arquivo'),
    path('occurrences/<int:occurrence_id>/', occurrence_detail_view, name='occurrence_detail'),
    path(
        'occurrences/<int:occurrence_id>/intake/',
        occurrence_intake_view,
        name='occurrence_intake',
    ),
    # Encaminhar prova em lote (handoff, ADR-0016 v2) — ação in-place (modal)
    path(
        'occurrences/<int:occurrence_id>/encaminhar/',
        occurrence_encaminhar_view,
        name='occurrence_encaminhar',
    ),
    # Validar a apreensão em lote (CPP art. 178.º/6) — ação in-place (modal)
    path(
        'occurrences/<int:occurrence_id>/validar/',
        occurrence_validar_view,
        name='occurrence_validar',
    ),
    # Despacho para perícia em lote (CPP art. 154.º) — ação in-place (modal)
    path(
        'occurrences/<int:occurrence_id>/despachar/',
        occurrence_despachar_view,
        name='occurrence_despachar',
    ),
    # Restituir prova em lote (CPP art. 186.º — termo de entrega) — ação in-place (modal)
    path(
        'occurrences/<int:occurrence_id>/restituir/',
        occurrence_restituir_view,
        name='occurrence_restituir',
    ),

    # Evidências
    path('evidences/', evidences_view, name='evidences'),
    path('evidences/new/', evidences_new_view, name='evidences_new'),
    path('evidences/<int:evidence_id>/', evidence_detail_view, name='evidence_detail'),
    path('evidences/<int:evidence_id>/custody/', custody_timeline_view, name='custody_timeline'),

    # Custódias
    path('custodies/', custody_list_view, name='custodies'),

    # Caixa "prova a chegar" — avisos de encaminhamento para a minha instituição,
    # por receber (2.ª metade do handoff, ADR-0016 v2). Liga ao intake/receber.
    path('inbound/', inbound_view, name='inbound'),

    # Instituições (pontos de controlo fixos) — gestão (staff/NACIONAL)
    path('institutions/', institutions_view, name='institutions'),
    path('institutions/new/', institution_new_view, name='institution_new'),

    # Relatórios PDF, estatísticas e definições
    path('reports/', reports_view, name='reports'),
    path('stats/', stats_view, name='stats'),
    path('settings/', settings_view, name='settings'),

    # Auditoria & Integridade — verificação da cadeia de hash + anomalias + trilho
    # (path/nome mantidos por compatibilidade com a navegação e bookmarks).
    path('audit/investigation/', audit_console_view, name='investigation_report'),

    # Centro de verificação / QR (operador EXPERT/staff) — gestão, não pesquisa
    # pública (ADR-0012 §6). Resolve hash/código → ocorrência.
    path('verificacoes/', verifications_view, name='verifications'),

    # Verificação pública via QR (ADR-0012 Vaga 1) — sem auth.
    # URL curta `/v/<hash>/` para QR codes denso (texto curto).
    path('v/<str:short_hash>/', public_verify_view, name='public_verify'),

    # Media (fotos de evidência) — view autenticada com ownership + audit log.
    # Substitui o `static(MEDIA_URL, ...)` para que funcione em produção
    # (sem nginx) e para que cada acesso fique registado (ISO/IEC 27037).
    path('media/<path:path>', MediaServeView.as_view(), name='media-serve'),

    # -----------------------------------------------------------------
    # Redirects 301 — nomes antigos (singular) para retrocompatibilidade
    # -----------------------------------------------------------------
    path('occurrence/', occurrence_singular_redirect),
    path('occurrence/<int:occurrence_id>/', occurrence_detail_singular_redirect),
    path('evidence/', evidence_singular_redirect),
    path('evidence/<int:evidence_id>/custody/', custody_evidence_redirect),
    path('custody/', custody_singular_redirect),
]


# ---------------------------------------------------------------------------
# Handlers de erro — registados no módulo raiz de URLs (Django convention)
# ---------------------------------------------------------------------------

handler404 = 'core.frontend_views.not_found_view'
handler500 = 'core.frontend_views.server_error_view'
