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
    FRONTEND_SEED_PASSWORD=admin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libglib2.0-0 \
        libgl1 \
        libpq-dev \
        python3 \
        python3-dev \
        python3-venv \
    && python3 -m venv "$VIRTUAL_ENV" \
    && mkdir -p /root/.EasyOCR/model /root/.EasyOCR/user_network \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app
COPY --from=frontend-build /frontend/build /app/frontend/build
COPY docker-entrypoint-all-in-one.sh /app/docker-entrypoint-all-in-one.sh
RUN chmod +x /app/docker-entrypoint-all-in-one.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint-all-in-one.sh"]
