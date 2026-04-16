"""
ForensiQ — URLs da app core (API REST).

Router DRF com os seguintes endpoints:
- /api/users/              — utilizadores
- /api/users/me/           — perfil do utilizador autenticado
- /api/occurrences/        — ocorrências
- /api/evidences/          — evidências
- /api/devices/            — dispositivos digitais
- /api/custody/            — cadeia de custódia
- /api/custody/evidence/<id>/timeline/ — timeline de custódia
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ChainOfCustodyViewSet,
    DigitalDeviceViewSet,
    EvidenceViewSet,
    OccurrenceViewSet,
    StatsView,
    UserViewSet,
)

app_name = 'core'

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'occurrences', OccurrenceViewSet, basename='occurrence')
router.register(r'evidences', EvidenceViewSet, basename='evidence')
router.register(r'devices', DigitalDeviceViewSet, basename='device')
router.register(r'custody', ChainOfCustodyViewSet, basename='custody')

urlpatterns = router.urls + [
    path('stats/', StatsView.as_view(), name='stats'),
]
