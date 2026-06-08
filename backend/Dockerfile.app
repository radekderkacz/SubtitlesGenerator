# Stage 1: build the React frontend
FROM node:26-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.14-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libpq-dev \
       curl \
    # Pull the latest security patches for OpenSSL + CA bundle on every
    # build. The base python:3.12-slim image lags Debian's apt repo, and
    # Dependency-Track was flagging us for CVE-2026-28387..31790 against
    # an openssl revision that already had patches available upstream.
    && apt-get install -y --no-install-recommends --only-upgrade \
       openssl \
       libssl3 \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements/base.txt requirements/base.txt
COPY backend/requirements/app.txt requirements/app.txt
RUN pip install --no-cache-dir -r requirements/app.txt

COPY backend/app/ app/
COPY backend/alembic/ alembic/
COPY backend/alembic.ini alembic.ini
COPY backend/entrypoint.app.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Embed the built SPA — served at / by FastAPI
COPY --from=frontend-builder /frontend/dist /app/static

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
