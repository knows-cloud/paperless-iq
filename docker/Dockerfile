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

# Install system deps for chromadb (needs build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/
COPY main.py ./
COPY alembic.ini ./
COPY pyproject.toml ./

# Copy Alembic config
COPY backend/alembic/ ./backend/alembic/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directory
RUN mkdir -p /data

# Environment defaults
ENV DATABASE_URL=sqlite+aiosqlite:///./data/paperless_iq.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
VOLUME ["/data"]

CMD ["sh", "-c", "python -m alembic upgrade head 2>/dev/null; uvicorn backend.main:app --host 0.0.0.0 --port 8080"]
