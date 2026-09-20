# syntax=docker/dockerfile:1.7

FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# frontend/src/i18n imports the repository-level shared locale registry.
COPY locales/ /app/locales/
RUN npm run build


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_DEBUG=false

WORKDIR /app

# OASIS/unstructured need a few native runtime libraries. Build tools are
# removed after Python dependencies are installed to keep the final image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2 \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt

# Installing a CPU PyTorch wheel first prevents pip from pulling the multi-GB
# CUDA dependency tree that the generic torch wheel can bring in on Linux.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r backend/requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /root/.cache/pip

COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/backend/uploads/simulations

EXPOSE 5001

# One web worker is intentional for the demo: SimulationRunner owns subprocesses
# and live state in-process. Threads provide HTTP concurrency without splitting
# that ownership across workers.
CMD ["sh", "-c", "gunicorn --chdir backend --workers 1 --threads ${GUNICORN_THREADS:-8} --timeout ${GUNICORN_TIMEOUT:-600} --graceful-timeout 60 --bind 0.0.0.0:${PORT:-5001} wsgi:app"]
