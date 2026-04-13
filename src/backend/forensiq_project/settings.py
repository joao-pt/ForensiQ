"""
Django settings for forensiq_project.

ForensiQ — Plataforma Modular de Gestão de Prova Digital para First Responders
UC 21184 — Projeto de Engenharia Informática · Universidade Aberta
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# Carregar variáveis de ambiente do ficheiro .env na raiz do projecto
# O .env está em ForensiQ/.env (dois níveis acima de src/backend/)
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent.parent  # ForensiQ/
load_dotenv(PROJECT_ROOT / '.env')

# --- Segurança ---
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError(
        'A variável de ambiente SECRET_KEY tem de estar definida. '
        'Gere uma com: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
    )
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

# --- Aplicações ---
INSTALLED_APPS = [
    # Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Terceiros
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'drf_spectacular',
    # ForensiQ
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Servir estáticos em produção
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.CorrelationIDMiddleware',  # Gera UUID correlation_id
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'forensiq_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR.parent / 'frontend' / 'templates',  # src/frontend/templates/
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'forensiq_project.wsgi.application'

# --- Base de Dados (PostgreSQL via Neon.tech) ---
DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# --- Modelo de utilizador personalizado ---
AUTH_USER_MODEL = 'core.User'

# --- Validação de passwords ---
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Django REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10/minute',
        'user': '60/minute',
    },
}

# --- SimpleJWT ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', 60))
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        days=int(os.environ.get('JWT_REFRESH_TOKEN_LIFETIME_DAYS', 7))
    ),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# --- drf-spectacular (Swagger / OpenAPI) ---
SPECTACULAR_SETTINGS = {
    'TITLE': 'ForensiQ API',
    'DESCRIPTION': (
        'API REST para gestão de prova digital — '
        'registo de ocorrências, evidências, dispositivos digitais '
        'e cadeia de custódia (ISO/IEC 27037).'
    ),
    'VERSION': '0.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# --- CORS ---
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://forensiq.pt',
    'https://www.forensiq.pt',
]
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Só em desenvolvimento

# --- CSRF ---
CSRF_TRUSTED_ORIGINS = [
    'https://forensiq.pt',
    'https://www.forensiq.pt',
]

# --- Internacionalização ---
LANGUAGE_CODE = 'pt-pt'
TIME_ZONE = 'Europe/Lisbon'
USE_I18N = True
USE_TZ = True

# --- Ficheiros estáticos e media ---
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR.parent / 'frontend' / 'static',  # src/frontend/static/
]
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- Chave primária por defeito ---
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Segurança em produção ---
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # 1 ano
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    SESSION_COOKIE_SAMESITE = 'Strict'
    CSRF_COOKIE_SAMESITE = 'Strict'

# --- Logging e auditoria ---
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'correlation_id': {
            '()': 'core.logging_utils.CorrelationIDFilter',
        },
    },
    'formatters': {
        'verbose': {
            'format': '[{asctime}] [{correlation_id}] {levelname} {name} {module}.{funcName}:{lineno} — {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['correlation_id'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'core': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
