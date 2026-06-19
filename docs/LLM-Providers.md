# LLM Providers

Paperless IQ supports four LLM providers for chat completions, and three for embeddings. You can use a different provider for embeddings than for chat — embedding models are small and fast, so a local Ollama embedding model pairs well with a cloud chat LLM.

All credentials are **Fernet-encrypted** before storage. Plaintext credentials never appear in logs or API responses.

---

## Ollama

**Use case:** fully local, air-gapped operation. No API keys, no usage costs.

### Prerequisites

- [Ollama](https://ollama.com/) running on the host or on a reachable server
- At least one chat model pulled: `ollama pull llama3` (or any other model)
- At least one embedding model pulled: `ollama pull nomic-embed-text`

### Configuration

| Setting | Value |
|---------|-------|
| **LLM provider** | `ollama` |
| **Ollama URL** | `http://localhost:11434` (or your remote Ollama address) |
| **LLM model** | Any model you've pulled, e.g. `llama3`, `mistral`, `qwen2.5` |
| **Embedding provider** | `ollama` |
| **Embedding model** | `nomic-embed-text` (recommended) |

### Docker networking note

If Paperless IQ runs in Docker and Ollama runs on the host machine, use `http://host.docker.internal:11434` as the Ollama URL. On Linux, `host.docker.internal` may not resolve automatically — add it to `extra_hosts` in your compose file:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### Model selection

Any model Ollama supports can be used for chat. For metadata analysis (structured JSON output), models with good instruction following perform best: `llama3`, `mistral`, `command-r`, `qwen2.5`, `phi4`.

For vision analysis, use a multimodal model: `llava`, `llava-llama3`, `moondream`.

### Embedding concurrency

With a local Ollama on a single GPU or CPU, keep `embed_concurrency = 1`. If Ollama runs on a remote GPU server, raise it to 4–8 to speed up batch indexing.

---

## Anthropic

**Use case:** cloud-hosted, strong analysis quality, especially for multi-lingual archives.

### Prerequisites

An [Anthropic API key](https://console.anthropic.com/). Usage is billed per token.

### Configuration

| Setting | Value |
|---------|-------|
| **LLM provider** | `anthropic` |
| **API key** | `sk-ant-...` |
| **LLM model** | See model list below |
| **Embedding provider** | `ollama` or `openai` (Anthropic has no embedding API) |

### Model selection

| Model | Notes |
|-------|-------|
| `claude-haiku-4-5-20251001` | Fast, cheap, good for routine analysis |
| `claude-sonnet-4-5` | Balanced quality and cost |
| `claude-opus-4-5` | Highest quality, highest cost |

For vision analysis, all Claude 3+ models support vision.

### Seed via environment

```yaml
PIQ_LLM_PROVIDER: anthropic
PIQ_LLM_CREDENTIALS: sk-ant-...
PIQ_LLM_MODEL: claude-haiku-4-5-20251001
```

---

## OpenAI

**Use case:** cloud-hosted; supports both chat and embeddings from a single provider.

### Prerequisites

An [OpenAI API key](https://platform.openai.com/). Usage is billed per token.

### Configuration

| Setting | Value |
|---------|-------|
| **LLM provider** | `openai` |
| **API key** | `sk-...` |
| **LLM model** | See model list below |
| **Embedding provider** | `openai` |
| **Embedding model** | `text-embedding-3-small` |

### Model selection

| Model | Notes |
|-------|-------|
| `gpt-4o-mini` | Fast, cost-effective, good for routine analysis |
| `gpt-4o` | Higher quality, higher cost |

For vision analysis, both `gpt-4o` and `gpt-4o-mini` support vision.

### Seed via environment

```yaml
PIQ_LLM_PROVIDER: openai
PIQ_LLM_CREDENTIALS: sk-...
PIQ_LLM_MODEL: gpt-4o-mini
PIQ_EMBED_PROVIDER: openai
PIQ_EMBEDDING_MODEL: text-embedding-3-small
```

---

## Amazon Bedrock

**Use case:** enterprise, AWS-native deployments; access to multiple model families from a single AWS account; embedding and reranking from the same provider.

### Prerequisites

- AWS account with Amazon Bedrock enabled in your region
- IAM permissions for `bedrock:InvokeModel` and (if using embeddings) `bedrock:InvokeModel` on the embedding model ARN
- Model access enabled in the Bedrock console for the specific models you want to use

### Configuration

Credentials are provided as a JSON object with AWS credentials:

```json
{
  "aws_access_key_id": "AKIA...",
  "aws_secret_access_key": "...",
  "region_name": "eu-central-1"
}
```

Alternatively, if Paperless IQ runs on an EC2 instance or ECS task with an IAM role, you can omit the key/secret and pass only `{"region_name": "eu-central-1"}` — the SDK will use the instance role.

| Setting | Value |
|---------|-------|
| **LLM provider** | `bedrock` |
| **Credentials** | JSON as above |
| **LLM model** | Model ID or inference profile ID (see below) |
| **Embedding provider** | `bedrock` |
| **Embedding model** | `amazon.titan-embed-text-v1`, `amazon.titan-embed-text-v2:0`, or a Cohere model |

### Model selection

Bedrock uses different model IDs depending on region and whether you use cross-region inference profiles:

| Model | Base ID | Inference profile (eu) |
|-------|---------|------------------------|
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | `eu.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Claude Sonnet 4.5 | `anthropic.claude-sonnet-4-5-20250929-v1:0` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Nova Micro | `amazon.nova-micro-v1:0` | `eu.amazon.nova-micro-v1:0` |
| Nova Lite | `amazon.nova-lite-v1:0` | `eu.amazon.nova-lite-v1:0` |
| Llama 3.3 70B | `meta.llama3-3-70b-instruct-v1:0` | `eu.meta.llama3-3-70b-instruct-v1:0` |

**Embedding models:**

| Model | ID | Dimension |
|-------|-----|-----------|
| Titan Embed v1 | `amazon.titan-embed-text-v1` | 1536 |
| Titan Embed v2 | `amazon.titan-embed-text-v2:0` | 1024 |
| Cohere Embed v3 | `cohere.embed-multilingual-v3` | 1024 |

For cross-region inference profiles, use the full profile ID (e.g. `eu.cohere.embed-multilingual-v3`). Paperless IQ detects the model family from the ID substring, so embedding provider selection works correctly with both base IDs and profile IDs.

### Bedrock Rerank (optional)

With Bedrock as the LLM provider, you can use the Bedrock Rerank API instead of the local cross-encoder:

| Setting | Value |
|---------|-------|
| **Enable re-ranking** | on |
| **Reranker** | `api` |
| **Model** | `amazon.rerank-v1:0` or `cohere.rerank-v3-5:0` |

### Seed via environment

```yaml
PIQ_LLM_PROVIDER: bedrock
PIQ_LLM_MODEL: eu.anthropic.claude-haiku-4-5-20251001-v1:0
PIQ_LLM_CREDENTIALS: '{"aws_access_key_id":"AKIA...","aws_secret_access_key":"...","region_name":"eu-central-1"}'
PIQ_EMBED_PROVIDER: bedrock
PIQ_EMBEDDING_MODEL: eu.cohere.embed-multilingual-v3
```

---

## Switching providers

You can switch the LLM provider live in Settings — the change takes effect immediately for new analysis requests. No restart is required.

**Switching the embedding provider** is different: changing it makes existing vectors incompatible with queries from the new model (dimension mismatch). After saving a new embedding provider or model, go to **Settings → Access Control** and click **Re-index Vector Store** to rebuild the index with the new model.

If you want to switch LLM providers without re-indexing (because you're only changing the chat model, not the embedding model), that is safe to do at any time.

---

## Provider capabilities

| | Ollama | Anthropic | OpenAI | Bedrock |
|--|--------|-----------|--------|---------|
| Chat completions | ✓ | ✓ | ✓ | ✓ |
| Embeddings | ✓ | — | ✓ | ✓ |
| Vision analysis | ✓ (multimodal models) | ✓ | ✓ | ✓ |
| Reranking | — | — | — | ✓ (Bedrock Rerank) |
| Air-gapped | ✓ | — | — | — |
