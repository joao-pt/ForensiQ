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

# Autenticação e throttling alinhados com produção (ADR-0009): o REST_FRAMEWORK
# HERDA de settings.py — o bloco TESTING de lá já esvazia as classes de throttle
# e deriva os rates altos dos MESMOS scopes (auditoria D116); re-declarar aqui o
# dict completo era uma cópia byte-igual que tinha de ser mantida à mão. Testes
# dedicados ao throttling reactivam-no com @override_settings.
REST_FRAMEWORK_THROTTLE_OVERRIDE = True
