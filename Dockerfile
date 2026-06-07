FROM node:20-bookworm AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

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
    NGROK_AUTHTOKEN=3EombR7pM5BtIVDJ2s3RVHeqxYY_5DFGGW87479PWxts3xSsX \
    NGROK_DOMAIN=untrained-pleading-unmarked.ngrok-free.dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libglib2.0-0 \
        libgl1 \
        libpq-dev \
        nginx \
        python3 \
        python3-dev \
        python3-venv \
    && python3 -m venv "$VIRTUAL_ENV" \
    && mkdir -p /root/.EasyOCR/model /root/.EasyOCR/user_network \
    && rm -rf /var/lib/apt/lists/*

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

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app
COPY --from=frontend-build /frontend/build /app/frontend/build
COPY docker-entrypoint-all-in-one.sh /app/docker-entrypoint-all-in-one.sh
COPY scripts/show-public-url.sh /app/scripts/show-public-url.sh
COPY nginx-tms-automation.conf /etc/nginx/conf.d/tms-automation.conf
RUN chmod +x /app/docker-entrypoint-all-in-one.sh /app/scripts/show-public-url.sh
RUN rm -f /etc/nginx/sites-enabled/default \
    && nginx -t

EXPOSE 80

ENTRYPOINT ["/app/docker-entrypoint-all-in-one.sh"]
