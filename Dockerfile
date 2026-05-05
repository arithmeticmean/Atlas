# syntax=docker/dockerfile:1

# --- stage 1: build the React UI -> /web/dist ---
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

# --- stage 2: the FastAPI service (also serves the built UI) ---
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH

# libmagic1: required by python-magic (mime sniffing in the loader registry)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, locked dependency installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Install deps first (cached until pyproject/lock change). --no-install-project
# installs only the locked dependencies, not the app itself (it's not a package).
COPY service/pyproject.toml service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App source, then the built UI where FastAPI expects it: settings.frontend_dir
# defaults to ../web/dist relative to the service root (/app) -> /web/dist.
COPY service/ /app/
COPY --from=web /web/dist /web/dist

EXPOSE 8000

# Config comes from the environment (docker-compose env_file: .env, generated
# by configure.py). Apply migrations, then serve. Runtime state (sqlite/lance/
# blobs) lives under /data.
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.app:app --host 0.0.0.0 --port 8000"]
