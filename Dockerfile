# ForensiQ — Dockerfile para produção (Fly.io)
# Imagem multi-stage para manter o tamanho reduzido

# --- Stage 1: Build ---
FROM python:3.12-slim AS builder

WORKDIR /build

# Instalar dependências de compilação (psycopg2, Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY src/backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.12-slim

# Dependências runtime (libpq para PostgreSQL, libjpeg para Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Utilizador não-root por segurança
RUN useradd --create-home forensiq

# Pre-criar /data/media com ownership `forensiq`. Em volume NOVO o Fly preserva
# este ownership; em volume JÁ existente o mount sobrepõe-no com root:root — por
# isso o docker-entrypoint.sh volta a fazer o chown no arranque (runtime), o que
# resolve de forma durável o upload de fotos (PermissionError em /data/media).
RUN mkdir -p /data/media && chown -R forensiq:forensiq /data

USER forensiq
WORKDIR /home/forensiq/app

# Copiar dependências Python do builder
COPY --from=builder /install /usr/local

# Copiar código-fonte
COPY --chown=forensiq:forensiq src/backend/ ./backend/
COPY --chown=forensiq:forensiq src/frontend/ ./frontend/

# Variáveis de ambiente não-sensíveis.
# NOTA: SECRET_KEY, DATABASE_URL, JWT_SIGNING_KEY, IMEIDB_API_TOKEN e outros
# segredos NUNCA são definidos no Dockerfile. Em produção são injectados
# pelo Fly.io via `fly secrets set KEY=VALUE` e surgem no contentor como
# variáveis de ambiente em runtime. Conformidade com o princípio de
# minimização de exposição de segredos (ISO/IEC 27002 8.24).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=forensiq_project.settings

# Recolher ficheiros estáticos (executado no build, não no runtime).
# Durante o `collectstatic` o Django importa o settings.py, que com
# DEBUG=False exige SECRET_KEY, DATABASE_URL e JWT_SIGNING_KEY (este
# último por causa do guard fail-closed da assinatura de tokens). Os
# valores abaixo são efémeros, usados apenas pelo build — nunca aterram
# no filesystem da imagem final nem são válidos para
# autenticação/assinatura; os reais são injectados em runtime via
# `fly secrets set`.
WORKDIR /home/forensiq/app/backend
RUN DATABASE_URL="sqlite:///tmp/build-dummy.db" \
    SECRET_KEY="build-time-only-not-a-real-secret-$(date +%s)" \
    JWT_SIGNING_KEY="build-time-only-not-a-real-jwt-$(date +%s)" \
    DEBUG="False" \
    ALLOWED_HOSTS="localhost" \
    python manage.py collectstatic --noinput

# O contentor arranca como root apenas para o entrypoint poder fazer chown do
# volume montado em runtime; o entrypoint larga logo privilégios para `forensiq`
# (gosu) antes de executar a aplicação.
USER root
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expor porta
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Gunicorn — 2 workers para VM pequena (corre como forensiq via gosu)
CMD ["gunicorn", "forensiq_project.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
