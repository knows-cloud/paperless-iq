# Getting Started

## Prerequisites

- A running **Paperless-NGX** instance (any recent version)
- **Docker** and Docker Compose
- An **LLM provider** — one of:
  - [Ollama](https://ollama.com/) running locally (fully air-gapped, no API key needed)
  - An Anthropic API key
  - An OpenAI API key
  - AWS credentials with Amazon Bedrock access

A **Paperless-NGX API token** is also required. Generate one under **Paperless → Settings → API Auth Tokens**.

---

## Installation

### Step 1 — Add Paperless IQ to your compose file

Paperless IQ runs as a sidecar alongside your existing Paperless-NGX containers. Add it to the same `docker-compose.yml`:

```yaml
services:
  paperless-iq:
    build:
      context: /path/to/paperless-iq   # clone this repo first
      dockerfile: docker/Dockerfile
    restart: unless-stopped
    depends_on:
      - webserver                        # your Paperless-NGX webserver service
    ports:
      - "8082:8080"
    volumes:
      - paperless-iq-data:/data
    networks:
      - paperless_default                # must share the Paperless network
    environment:
      PAPERLESS_URL: http://webserver:8000   # internal Docker address
      PAPERLESS_TOKEN: <your-paperless-api-token>
```

```yaml
volumes:
  paperless-iq-data:
```

> **Network:** `paperless_default` is the typical network name when Paperless-NGX is started from the official `docker-compose.yml`. Check with `docker network ls` if yours differs.

### Step 2 — Configure an LLM provider

Add environment variables for your chosen provider:

**Ollama (local — recommended for air-gapped setups)**
```yaml
environment:
  PIQ_LLM_PROVIDER: ollama
  PIQ_EMBED_PROVIDER: ollama
  PIQ_OLLAMA_URL: http://host.docker.internal:11434   # adjust if Ollama runs elsewhere
  PIQ_LLM_MODEL: llama3                               # any model you've pulled
  PIQ_EMBEDDING_MODEL: nomic-embed-text               # pull this in Ollama first
```

**Anthropic**
```yaml
environment:
  PIQ_LLM_PROVIDER: anthropic
  PIQ_LLM_CREDENTIALS: sk-ant-...
  PIQ_LLM_MODEL: claude-haiku-4-5-20251001
  PIQ_EMBED_PROVIDER: ollama   # Anthropic has no embedding API; pair with Ollama or OpenAI
```

**OpenAI**
```yaml
environment:
  PIQ_LLM_PROVIDER: openai
  PIQ_LLM_CREDENTIALS: sk-...
  PIQ_LLM_MODEL: gpt-4o-mini
  PIQ_EMBED_PROVIDER: openai
  PIQ_EMBEDDING_MODEL: text-embedding-3-small
```

**Amazon Bedrock**
```yaml
environment:
  PIQ_LLM_PROVIDER: bedrock
  PIQ_LLM_MODEL: us.anthropic.claude-haiku-4-5-20251001-v1:0
  PIQ_LLM_CREDENTIALS: '{"aws_access_key_id":"...","aws_secret_access_key":"...","region_name":"us-east-1"}'
  PIQ_EMBED_PROVIDER: bedrock
  PIQ_EMBEDDING_MODEL: amazon.titan-embed-text-v2:0
```

See [[LLM-Providers]] for full per-provider setup details.

### Step 3 — Build and start

```bash
docker compose up -d --build paperless-iq
```

The first build takes a few minutes (Python deps + optional torch for the local reranker). Subsequent starts are fast.

### Step 4 — Open the UI

Navigate to `http://localhost:8082`. Log in with your **Paperless-NGX username and password** — Paperless IQ validates credentials against Paperless (there is no separate user database).

---

## First-run checklist

### 1. Verify the connection

Go to **Settings → Connection** and click **Test connection**. A green checkmark confirms Paperless IQ can reach your Paperless-NGX instance and authenticate.

### 2. Set the inbox tag

In **Settings → Connection**, set **Inbox Tag** to the tag Paperless-NGX applies to newly uploaded documents (commonly named `Inbox`). This is the tag the automation poller watches.

If you don't have an inbox tag workflow set up in Paperless, you can skip automation and use **Manual Analysis** instead (trigger analysis per-document from the Manual page).

### 3. Configure AI in the UI

Settings seeded from `PIQ_*` environment variables are overwritten the first time you save Settings from the UI. To confirm everything is wired up:

1. Go to **Settings → AI Provider**
2. Check that your LLM provider and model are correct
3. Click **Test LLM** — a short round-trip call confirms the provider is reachable
4. Check the embedding provider and model
5. Click **Test embeddings** — confirms the embedding API is working

### 4. Index your documents (vector store)

Before Discovery can answer questions, your documents need to be embedded into the vector store.

Go to **Settings → Access Control** and click **Re-index Vector Store**. This queues all documents in your archive for embedding. Progress is visible on the **Processing** page.

For large archives (thousands of documents), indexing may take a while depending on your embedding provider's speed and your `embed_concurrency` setting.

### 5. (Optional) Enable automation

If you want Paperless IQ to analyse new documents automatically as they arrive:

1. Go to **Settings → Automation**
2. Turn on **Automation enabled**
3. Verify the inbox tag is set
4. Save

With automation on, documents tagged with your inbox tag will be picked up, analysed, and a suggestion will appear in the **Queue** page. If you also enable **Auto-apply**, suggestions are written directly back to Paperless without manual review — only enable this once you've verified the analysis quality for your archive.

---

## Using Qdrant (optional)

Qdrant is an optional vector backend that adds hybrid dense+sparse search (better recall for exact terms like names, dates, and invoice numbers). See [[Vector-Stores]] for the full setup guide.

The short version — add the `--profile qdrant` flag when starting:

```bash
docker compose --profile qdrant up -d --build
```

And set `PIQ_VECTOR_STORE_BACKEND: qdrant` in your compose environment.

---

## Data storage

All Paperless IQ data lives in the `paperless-iq-data` Docker volume, mounted at `/data` inside the container:

| Path | Contents |
|------|----------|
| `/data/paperless_iq.db` | SQLite database (settings, queue, audit log, sessions, memories) |
| `/data/chroma/` | ChromaDB vector store (if using the default local backend) |
| `/data/.secret_key` | Auto-generated Fernet encryption key (protects stored API credentials) |
| `/data/hf-cache/` | HuggingFace model cache (local reranker / sparse encoder weights) |

Back up the volume to preserve your index and settings. The `.secret_key` file is especially important — without it, stored LLM credentials cannot be decrypted after a volume restore.

---

## Updating

```bash
git pull
docker compose build paperless-iq
docker compose up -d paperless-iq
```

Database migrations run automatically at startup. There is no manual migration step.
