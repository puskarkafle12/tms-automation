# syntax=docker/dockerfile:1.7

# --- Frontend (cached when package-lock unchanged) ---
FROM node:20-bookworm AS frontend-build

ENV NPM_CONFIG_UPDATE_NOTIFIER=false

WORKDIR /frontend
COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm ci \
    && npx --yes update-browserslist-db@latest
COPY frontend/ ./
RUN npm run build

# --- Python deps (cached when requirements-* unchanged; no Postgres/apt noise) ---
FROM python:3.11-bookworm AS python-deps

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0

RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --upgrade pip setuptools wheel

WORKDIR /deps
COPY requirements-heavy.txt requirements.txt ./

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements-heavy.txt -r requirements.txt

ARG DEPS_VERSION=unknown
LABEL org.opencontainers.image.deps-version=$DEPS_VERSION

# --- Final all-in-one image ---
FROM postgres:16-bookworm

ENV PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PGDATA=/var/lib/postgresql/data \
    DB_USER=pk \
    DB_PASSWORD=pk \
    DB_HOST=127.0.0.1 \
    DB_NAME=stock \
    FRONTEND_SEED_USER=admin \
    FRONTEND_SEED_PASSWORD=admin \
    TUNNEL_PROVIDER=ngrok \
    NGROK_AUTHTOKEN=REDACTED_CREDENTIAL \
    NGROK_DOMAIN=untrained-pleading-unmarked.ngrok-free.dev \
    ZROK_ENV_TOKEN=

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        libglib2.0-0 \
        libgl1 \
        libpq5 \
        nginx \
        python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /opt/venv /opt/venv

# Venv was created on python:3.11-bookworm; point its interpreter at this image's Python.
RUN mkdir -p /usr/local/bin \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3.11

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) ngrok_arch=amd64 ;; \
      arm64) ngrok_arch=arm64 ;; \
      *) echo "Unsupported architecture for ngrok: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${ngrok_arch}.tgz" \
      | tar xz -C /usr/local/bin ngrok; \
    chmod +x /usr/local/bin/ngrok; \
    ngrok version

RUN set -eux; \
    curl -fsSL https://get.openziti.io/tun/package-repos.gpg \
      | gpg --dearmor --yes --output /usr/share/keyrings/openziti.gpg; \
    chmod a+r /usr/share/keyrings/openziti.gpg; \
    printf '%s\n' \
      'deb [signed-by=/usr/share/keyrings/openziti.gpg] https://packages.openziti.org/zitipax-openziti-deb-stable debian main' \
      > /etc/apt/sources.list.d/openziti-release.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends zrok zrok2; \
    ln -sf /usr/bin/zrok /usr/local/bin/zrok; \
    ln -sf /usr/bin/zrok2 /usr/local/bin/zrok2; \
    zrok version; \
    zrok2 version

WORKDIR /app

COPY . /app
COPY --from=frontend-build /frontend/build /app/frontend/build
COPY nginx-tms-automation.conf /etc/nginx/conf.d/tms-automation.conf
RUN chmod +x /app/docker-entrypoint-all-in-one.sh /app/scripts/show-public-url.sh \
    && sed -i 's/\r$//' /app/docker-entrypoint-all-in-one.sh /app/scripts/show-public-url.sh
RUN rm -f /etc/nginx/sites-enabled/default \
    && nginx -t

ARG GIT_COMMIT=unknown
ARG SOURCE_VERSION=unknown
ARG BUILD_DATE=unknown
ARG DEPS_VERSION=unknown

LABEL org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.source-version=$SOURCE_VERSION \
      org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.deps-version=$DEPS_VERSION

ENV APP_GIT_COMMIT=$GIT_COMMIT \
    APP_SOURCE_VERSION=$SOURCE_VERSION \
    APP_BUILD_DATE=$BUILD_DATE

RUN if [ "$BUILD_DATE" != "unknown" ]; then echo "$BUILD_DATE" > /app/.deployed_at; fi

EXPOSE 80

ENTRYPOINT ["/app/docker-entrypoint-all-in-one.sh"]
