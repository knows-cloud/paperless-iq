# Paperless IQ — single-container build

# Stage 1: Build frontend
FROM node:24-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.12-slim
WORKDIR /app

# System deps: build tools for chromadb; libgomp1 for onnxruntime (fastembed).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Install Python dependencies (layer cached until pyproject.toml changes).
# Optional extras are controlled by the PIQ_EXTRAS build arg (comma-separated):
#   qdrant-hybrid  — fastembed sparse encoder for Qdrant hybrid search
#   rerank-local   — sentence-transformers + CPU torch cross-encoder reranker
# docker-compose.yml defaults to both; set PIQ_EXTRAS= for the leanest image.
COPY pyproject.toml ./
ARG PIQ_EXTRAS="qdrant-hybrid"

# When the local reranker is bundled, pre-install the CPU-only torch wheel so
# sentence-transformers reuses it instead of pulling the default ~3 GB CUDA
# build. Must run BEFORE the main install so the CPU build wins resolution.
RUN if echo ",$PIQ_EXTRAS," | grep -q ',rerank-local,'; then \
        uv pip install --system --no-cache \
            --index-url https://download.pytorch.org/whl/cpu torch; \
    fi

RUN uv pip install --system --no-cache -r pyproject.toml \
    $(for e in $(echo "$PIQ_EXTRAS" | tr ',' ' '); do printf -- '--extra %s ' "$e"; done)

# Copy source and register the package so importlib.metadata.version() works.
COPY backend/ ./backend/
COPY main.py alembic.ini ./
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN uv pip install --system --no-cache --no-deps .

RUN mkdir -p /data

ENV DATABASE_URL=sqlite+aiosqlite:////data/paperless_iq.db
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/data/hf-cache

EXPOSE 8080
VOLUME ["/data"]

# Schema migrations run at app startup (backend/db_migrate.py self-heals
# pre-Alembic and stale-revision DBs). Exec form so uvicorn is PID 1.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
