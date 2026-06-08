# Paperless IQ — single-container build

# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.12-slim
WORKDIR /app

# System deps: build tools for chromadb; libgomp1 for onnxruntime (fastembed).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies from pyproject.toml (single source of truth) via uv.
# Hybrid search (fastembed) is included by default. Add more optional extras with
# the PIQ_EXTRAS build arg (comma-separated), e.g. to also bundle the local torch
# reranker:  --build-arg PIQ_EXTRAS=qdrant-hybrid,rerank-local
# Set PIQ_EXTRAS= (empty) for the leanest image (no hybrid).
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
ARG PIQ_EXTRAS="qdrant-hybrid"
# When the local reranker is bundled, pre-install the CPU-only torch wheel so
# sentence-transformers reuses it instead of pulling the default ~3 GB CUDA build
# (this container runs CPU-only — no GPU is passed in). Must run BEFORE the main
# install so the CPU build is already-satisfied and wins resolution.
RUN if echo ",$PIQ_EXTRAS," | grep -q ',rerank-local,'; then \
        uv pip install --system --no-cache \
            --index-url https://download.pytorch.org/whl/cpu torch; \
    fi
RUN uv pip install --system --no-cache -r pyproject.toml \
    $(for e in $(echo "$PIQ_EXTRAS" | tr ',' ' '); do printf -- '--extra %s ' "$e"; done)

# Copy backend source
COPY backend/ ./backend/
COPY main.py ./
COPY alembic.ini ./

# Copy Alembic config
COPY backend/alembic/ ./backend/alembic/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directory
RUN mkdir -p /data

# Environment defaults
ENV DATABASE_URL=sqlite+aiosqlite:////data/paperless_iq.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
VOLUME ["/data"]

# Schema migrations (incl. auto-adopting pre-Alembic databases) run at app
# startup in the FastAPI lifespan — see backend/db_migrate.py.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
