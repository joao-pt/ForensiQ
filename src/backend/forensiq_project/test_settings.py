"""
Configurações de teste para ForensiQ.

Sobrepõe as configurações de produção para executar testes
sem dependências externas (PostgreSQL Neon.tech, collectstatic, etc.).

Utilização:
    python manage.py test --settings=forensiq_project.test_settings
"""

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

# Suprimir warnings de diretórios estáticos inexistentes
STATICFILES_DIRS = []
STATIC_ROOT = '/tmp/forensiq_static_test'

# Desactivar throttling em testes (evita 429 em sequências rápidas)
REST_FRAMEWORK_THROTTLE_OVERRIDE = True
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_THROTTLE_CLASSES': [],
    'DEFAULT_THROTTLE_RATES': {},
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}
