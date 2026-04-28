# Paperless IQ

AI-powered metadata suggestions for [Paperless NGX](https://docs.paperless-ngx.com/). Analyzes document content via LLMs and suggests title, tags, correspondent, document type, storage path, and custom fields — with a human-in-the-loop approval workflow.

## Features

- **AI metadata suggestions** — OCR text or full document content is sent to an LLM which returns structured metadata (title, tags, correspondent, document type, storage path, custom fields)
- **Smart entity selection** — uses vector similarity (ChromaDB) to find similar processed documents and sends only relevant tags/correspondents/types to the LLM instead of the full set, dramatically reducing prompt size and improving accuracy
- **Editable suggestions** — review, edit, add/remove tags, and approve or reject each suggestion before it's applied
- **Keep existing tags** — merge suggested tags with the document's current tags instead of replacing them
- **New value detection** — values that don't exist in Paperless NGX are highlighted in red; optionally create them on approve
- **Batch analysis** — select multiple documents and analyze them in one go
- **Approval queue** — suggestions are staged for review; auto-apply is opt-in
- **Automation** — polls an inbox tag for new documents and processes them on a schedule
- **Per-field instructions** — tell the LLM how to populate each metadata field
- **Advanced prompt templates** — per-field and per-document-type prompt overrides
- **Connection test** — verify Paperless NGX connectivity from the settings page
- **Audit log** — every metadata change is recorded with field-level detail
- **Settings persistence** — all settings saved to database, survive container restarts
- **Environment variable seeding** — pre-configure via `PIQ_*` env vars on first run

## LLM Providers

Amazon Bedrock · Anthropic · Ollama (local) · OpenAI

## Quick Start

Add to your Paperless NGX `docker-compose.yml`:

```yaml
  paperless-iq:
    build:
      context: /path/to/paperless-iq
      dockerfile: docker/Dockerfile
    restart: unless-stopped
    depends_on:
      - webserver
    ports:
      - "8082:8080"
    volumes:
      - paperless-iq-data:/data
    environment:
      PAPERLESS_URL: http://webserver:8000
      PAPERLESS_TOKEN: <your-paperless-api-token>
      SECRET_KEY: <random-secret-for-encryption>
      # Optional: pre-configure LLM provider
      PIQ_LLM_PROVIDER: ollama
      PIQ_LLM_MODEL: mistral-nemo:12b-instruct-2407-q4_K_M
      PIQ_OLLAMA_URL: http://192.168.1.100:11434
```

Add to the `volumes:` section:

```yaml
volumes:
  paperless-iq-data:
```

Then:

```bash
docker compose up -d --build paperless-iq
```

Access the UI at `http://localhost:8082`.

## Configuration

All settings are configurable via the web UI. On first startup, settings can be seeded from environment variables (prefixed `PIQ_`). After the first UI save, database values take precedence.

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `PAPERLESS_URL` | Base URL of the Paperless NGX instance (e.g. `http://webserver:8000`) |
| `PAPERLESS_TOKEN` | API token for Paperless NGX |
| `SECRET_KEY` | Master key for Fernet encryption of credentials at rest |

### Optional Environment Variables (PIQ_* — initial seed only)

| Variable | Default | Purpose |
|---|---|---|
| `PIQ_LLM_PROVIDER` | `ollama` | LLM provider: `ollama`, `anthropic`, `openai`, `bedrock` |
| `PIQ_LLM_MODEL` | `llama3` | Model name |
| `PIQ_LLM_CREDENTIALS` | — | API key (Anthropic/OpenAI) or JSON credentials (Bedrock) |
| `PIQ_OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `PIQ_DEFAULT_ANALYSIS_MODE` | `ocr` | `ocr` or `full_document` |
| `PIQ_CONTEXT_WINDOW_CHARS` | `128000` | Max characters sent to LLM |
| `PIQ_SMART_ENTITY_SELECTION` | `true` | Use vector similarity for entity selection |
| `PIQ_SIMILAR_DOCS_COUNT` | `10` | Number of similar docs to consider |
| `PIQ_FREQUENCY_FALLBACK_COUNT` | `20` | Top-N frequent entities as fallback |
| `PIQ_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama model for embeddings |
| `PIQ_TAG_CREATION_POLICY` | `existing_only` | `existing_only` or `allow_new` |
| `PIQ_CORRESPONDENT_CREATION_POLICY` | `existing_only` | `existing_only` or `allow_new` |
| `PIQ_DOCTYPE_CREATION_POLICY` | `existing_only` | `existing_only` or `allow_new` |
| `PIQ_INBOX_TAG_ID` | — | Paperless NGX tag ID for inbox documents |
| `PIQ_AUTO_APPLY` | `false` | Auto-apply suggestions (skip approval queue) |
| `PIQ_AUTOMATION_ENABLED` | `false` | Enable inbox polling and scheduled runs |
| `PIQ_POLL_INTERVAL_SECONDS` | `10` | Inbox poll interval |
| `PIQ_BATCH_SIZE` | `10` | Documents per scheduled batch |
| `PIQ_SCHEDULE_CRON` | — | Cron expression for scheduled batch runs |
| `PIQ_AUDIT_RETENTION_DAYS` | `90` | Minimum audit log retention |
| `PIQ_TARGET_LANGUAGE` | — | Target language for translations |
| `PIQ_VECTOR_STORE_BACKEND` | `local` | `local` (ChromaDB) or `bedrock_kb` |
| `PIQ_BEDROCK_KB_ID` | — | Bedrock Knowledge Base ID |

### Rebuilding

After code changes:

```bash
docker compose build --no-cache paperless-iq
docker compose up -d paperless-iq
```

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run dev server (manual — do not use in Docker)
uv run uvicorn backend.main:app --reload

# Database migrations
uv run alembic upgrade head
```

## Architecture

- **Backend**: Python 3.12+ / FastAPI / SQLAlchemy 2.x / SQLite
- **Frontend**: React 18 / TypeScript / Vite / TanStack Query
- **Vector Store**: ChromaDB (local) or Amazon Bedrock Knowledge Base
- **Testing**: pytest + Hypothesis (property-based testing)
- **Package Management**: uv

## License

Private — all rights reserved.
