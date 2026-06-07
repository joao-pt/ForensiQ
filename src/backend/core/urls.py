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
- /api/custody/                        — cadeia de custódia
- /api/custody/evidence/<id>/timeline/ — timeline de custódia
- /api/activity-feed/                  — feed read-only de actividade (AuditLog)
- /api/stats/                          — stats agregadas (legacy)
- /api/stats/dashboard/                — payload estável do dashboard (Wave 2d)
- /api/health/                         — healthcheck (liveness + DB)
- /api/reverse-geocode/                — geocodificação inversa (proxy Nominatim)
- /api/nearby-pois/                    — POIs OSM próximos (proxy Overpass)
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ActivityFeedView,
    ChainOfCustodyViewSet,
    CrimeCategoryListView,
    CrimeSubcategoryListView,
    CrimeTypeListView,
    DashboardStatsView,
    EvidenceIMEILookupView,
    EvidenceViewSet,
    EvidenceVINLookupView,
    NearbyPOIsView,
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
    path('nearby-pois/', NearbyPOIsView.as_view(), name='nearby-pois'),
    # Taxonomia de crimes — seletor em cascata N1>N2>N3 (occurrences_new)
    path('crime-categories/', CrimeCategoryListView.as_view(), name='crime-categories'),
    path('crime-subcategories/', CrimeSubcategoryListView.as_view(), name='crime-subcategories'),
    path('crime-types/', CrimeTypeListView.as_view(), name='crime-types'),
    path('activity-feed/', ActivityFeedView.as_view(), name='activity-feed'),
    path('stats/', StatsView.as_view(), name='stats'),
    path('stats/dashboard/', DashboardStatsView.as_view(), name='stats-dashboard'),
    path('health/', healthcheck, name='healthcheck'),
] + router.urls
