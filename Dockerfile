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
    && rm -rf /var/lib/apt/lists/*

# Utilizador não-root por segurança
RUN useradd --create-home forensiq

# Pre-criar /data/media com ownership `forensiq` antes do USER switch.
# Fly.io copia o conteúdo deste path para o volume na primeira
# inicialização, preservando ownership. Para volumes JÁ existentes é
# preciso correr uma vez:
#   fly ssh console -C 'chown -R forensiq:forensiq /data/media'
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
# Durante o `collectstatic` o Django importa o settings.py, que exige
# SECRET_KEY e DATABASE_URL. Os valores abaixo são efémeros, usados
# apenas pelo build — nunca aterram no filesystem da imagem final nem
# são válidos para autenticação/acesso a recursos.
WORKDIR /home/forensiq/app/backend
RUN DATABASE_URL="sqlite:///tmp/build-dummy.db" \
    SECRET_KEY="build-time-only-not-a-real-secret-$(date +%s)" \
    DEBUG="False" \
    ALLOWED_HOSTS="localhost" \
    python manage.py collectstatic --noinput

# Expor porta
EXPOSE 8000

# Gunicorn — 2 workers para VM pequena
CMD ["gunicorn", "forensiq_project.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
