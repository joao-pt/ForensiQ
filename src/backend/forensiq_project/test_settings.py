"""
Configurações de teste para ForensiQ.

Sobrepõe as configurações de produção para executar testes
sem dependências externas (PostgreSQL Neon.tech, collectstatic, etc.).

Utilização:
    python manage.py test --settings=forensiq_project.test_settings
"""

import tempfile as _tempfile
from pathlib import Path as _Path

from .settings import *  # noqa: F401, F403

# Remover whitenoise do middleware (não necessário em testes e não instalado neste ambiente)
MIDDLEWARE = [m for m in MIDDLEWARE if 'whitenoise' not in m.lower()]

# Base de dados SQLite em memória (sem necessidade de Neon.tech)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Ficheiros estáticos sem manifesto (evita erro 'Missing staticfiles manifest')
# Django 4.2+ usa STORAGES em vez de STATICFILES_STORAGE
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# Debug activo — desactiva comportamentos de produção
DEBUG = True

# Desactivar redirecionamento HTTPS (desnecessário em testes)
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Suprimir warnings de diretórios estáticos inexistentes.
# Usamos ``tempfile.gettempdir()`` para o directório de testes (cross-OS:
# resolve para ``/tmp`` em Linux/macOS e ``%TEMP%`` em Windows).
STATICFILES_DIRS = []
STATIC_ROOT = str(_Path(_tempfile.gettempdir()) / 'forensiq_static_test')

# Autenticação e throttling alinhados com produção (ADR-0009).
# Mantemos JWTCookieAuthentication como default — os testes usam
# `force_authenticate` em APIClient, que ignora a classe de autenticação,
# mas o alinhamento assegura que testes que *não* forcem auth (p.ex.
# IDOR / CSRF) reflectem o comportamento real.
REST_FRAMEWORK_THROTTLE_OVERRIDE = True
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'core.auth.JWTCookieAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.BoundedPageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    # Throttling desactivado em testes — 429 em sequências rápidas é
    # artefacto do runner, não comportamento que queiramos validar aqui.
    # Testes dedicados ao throttling reactivam-no com @override_settings.
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10000/minute',
        'user': '10000/minute',
        'auth': '10000/minute',
        'evidence_upload': '10000/minute',
        'pdf_export': '10000/minute',
        'csv_export': '10000/minute',
        'schema': '10000/minute',
    },
    'EXCEPTION_HANDLER': 'core.exceptions.forensiq_exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}
