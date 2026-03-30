# Paperless IQ — single-container build
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.12-slim
WORKDIR /app

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Copy backend dependencies and install
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy backend source
COPY backend/ ./backend/
COPY main.py ./
COPY alembic.ini ./

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directory
RUN mkdir -p /data

# Environment defaults
ENV DATABASE_URL=sqlite+aiosqlite:///./data/paperless_iq.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
VOLUME ["/data"]

# Startup: run migrations, then start uvicorn
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn backend.main:app --host 0.0.0.0 --port 8080"]
