"""
ForensiQ — URLs da app core (API REST).

Router DRF com os seguintes endpoints:
- /api/users/                          — utilizadores
- /api/users/me/                       — perfil do utilizador autenticado
- /api/occurrences/                    — ocorrências
- /api/evidences/                      — evidências
- /api/evidences/<id>/pdf/             — exportação PDF (ISO/IEC 27037)
- /api/evidences/lookup/imei/<imei>/   — enriquecimento IMEI (imeidb.xyz)
- /api/evidences/lookup/vin/<vin>/     — redirect para vindecoder.eu
- /api/devices/                        — dispositivos digitais
- /api/custody/                        — cadeia de custódia
- /api/custody/evidence/<id>/timeline/ — timeline de custódia
- /api/stats/                          — stats agregadas (legacy)
- /api/stats/dashboard/                — payload estável do dashboard (Wave 2d)
- /api/health/                         — healthcheck (liveness + DB)
- /api/reverse-geocode/                — geocodificação inversa (proxy Nominatim)
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ChainOfCustodyViewSet,
    DashboardStatsView,
    DigitalDeviceViewSet,
    EvidenceIMEILookupView,
    EvidenceViewSet,
    EvidenceVINLookupView,
    OccurrenceViewSet,
    ReverseGeocodeView,
    StatsView,
    UserViewSet,
    healthcheck,
)

app_name = 'core'

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'occurrences', OccurrenceViewSet, basename='occurrence')
router.register(r'evidences', EvidenceViewSet, basename='evidence')
router.register(r'devices', DigitalDeviceViewSet, basename='device')
router.register(r'custody', ChainOfCustodyViewSet, basename='custody')

# Endpoints customizados — registados antes do router para não colidirem
# com as rotas auto-geradas.
urlpatterns = [
    path(
        'evidences/lookup/imei/<str:imei>/',
        EvidenceIMEILookupView.as_view(),
        name='evidence-lookup-imei',
    ),
    path(
        'evidences/lookup/vin/<str:vin>/',
        EvidenceVINLookupView.as_view(),
        name='evidence-lookup-vin',
    ),
    path('reverse-geocode/', ReverseGeocodeView.as_view(), name='reverse-geocode'),
    path('stats/', StatsView.as_view(), name='stats'),
    path('stats/dashboard/', DashboardStatsView.as_view(), name='stats-dashboard'),
    path('health/', healthcheck, name='healthcheck'),
] + router.urls
