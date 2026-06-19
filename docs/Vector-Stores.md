# Vector Stores

Paperless IQ uses a vector store to embed your document archive and power semantic search in Discovery. Three backends are supported. The default is ChromaDB — it requires no extra setup. Qdrant adds hybrid search and better performance at scale.

---

## Backends at a glance

| Backend | Setup | Highlights | Best for |
|---------|-------|-----------|----------|
| **ChromaDB** (`local`) | Zero — embedded in the container | Default; no network dep; data on disk | Small to medium archives, getting started |
| **Qdrant** (`qdrant`) | One extra compose service | Hybrid search; scalar/binary quantization; HNSW tuning | Larger archives, exact-term queries (names, IDs, dates) |
| **Bedrock KB** (`bedrock_kb`) | AWS console setup required | Managed by AWS; no self-hosted infra | AWS-native deployments, Bedrock-only stacks |

---

## ChromaDB (default)

ChromaDB is embedded directly in the Paperless IQ container. No extra services, no configuration required. Document chunks are stored on disk at `/data/chroma/` inside the persistent volume.

**Switch to ChromaDB:** in Settings → AI Provider → Vector Store, set the backend to `Local (ChromaDB)`. This is the default.

### HNSW tuning

ChromaDB's HNSW index parameters are configurable in Settings:

| Setting | Default | Effect |
|---------|---------|--------|
| `chroma_hnsw_search_ef` | 100 | Candidate list size at query time. Higher = better recall, more latency. Applied **live**. |
| `chroma_hnsw_m` | 16 | Graph connectivity per node. Higher = better recall, more memory. 🔁 Requires re-index. |
| `chroma_hnsw_construction_ef` | 100 | Index build quality. Higher = better index, slower indexing. 🔁 Requires re-index. |

`search_ef` must be ≥ `similar_docs_count × overfetch_multiplier` — the settings page enforces this.

---

## Qdrant

Qdrant is a dedicated vector database that runs as a separate service alongside Paperless IQ. It enables:
- **Hybrid search** — combines dense semantic vectors with sparse BM25 keyword vectors via Reciprocal Rank Fusion (RRF). Better recall for exact terms like invoice numbers, account numbers, names, and dates.
- **Quantization** — reduce memory footprint with scalar (INT8, ~4× smaller) or binary (~32× smaller, some quality loss) compression.
- **HNSW tuning** — same knobs as ChromaDB.

### Setup

The Qdrant service is defined in `docker-compose.yml` under the `qdrant` profile. Start it with:

```bash
docker compose --profile qdrant up -d
```

Enable it in Paperless IQ by setting:
```yaml
PIQ_VECTOR_STORE_BACKEND: qdrant
PIQ_QDRANT_URL: http://qdrant:6333
```

Or switch the backend in **Settings → AI Provider → Vector Store → Backend → Qdrant**.

### Qdrant Cloud

For cloud-hosted Qdrant, set mode to `cloud`, provide the Qdrant Cloud cluster URL and API key in Settings. The API key is Fernet-encrypted at rest.

### Hybrid search

Enable hybrid search in Settings → AI Provider → Similarity Search → Hybrid search. This adds sparse BM25 vectors to your index alongside the dense semantic vectors.

**Important:** hybrid search requires a re-index to build the sparse vectors. After enabling it, go to **Settings → Access Control → Re-index Vector Store**.

> Hybrid search requires the `fastembed` package. This is included in the default image build (`PIQ_EXTRAS: qdrant-hybrid,rerank-local`). If you built with `PIQ_EXTRAS=` (empty), you need to rebuild with `qdrant-hybrid` included.

### HNSW tuning

| Setting | Default | Effect |
|---------|---------|--------|
| `qdrant_hnsw_ef` | 128 | Query-time candidate list size. Higher = better recall, more latency. Applied **live**. |
| `qdrant_hnsw_m` | 16 | Graph connectivity. 🔁 Requires re-index. |
| `qdrant_quantization` | `none` | `scalar` = INT8, ~4× smaller, minimal quality loss. `binary` = ~32× smaller, noticeable quality loss. 🔁 Requires re-index. |

---

## Amazon Bedrock Knowledge Base

Bedrock KB delegates all embedding storage and retrieval to AWS managed infrastructure. Paperless IQ sends documents to the Knowledge Base; queries go through the Bedrock Retrieve API.

**Setup:**
1. Create a Knowledge Base in the AWS Bedrock console
2. Set the KB ID in Settings → AI Provider → Vector Store → Bedrock KB ID
3. Set the backend to `bedrock_kb`

**Limitations:**
- Read-only query mode — Paperless IQ queries the KB but relies on AWS for ingestion (documents must be synced to S3 and re-synced through the KB pipeline)
- The grooming mismatch scan is disabled on this backend (no filterable vector queries)
- Migration from/to Bedrock KB re-embedding is always required

---

## Migrating between backends

When you switch vector store backends, your existing embeddings need to move. Paperless IQ can migrate them **without re-embedding** — as long as the embedding model hasn't changed:

1. Switch the backend in Settings and save
2. Go to **Settings → Access Control**
3. Click **Migrate embeddings**

The migration copies stored vectors from the old backend to the new one. Progress is visible on the Processing page.

**If the embedding model also changed:** migration without re-embedding is not possible (the vector dimensions differ, or the space is not comparable). In this case you need a full re-index:

1. Change the backend and embedding model in Settings and save
2. Go to **Settings → Access Control**
3. Click **Re-index Vector Store**

This re-fetches and re-embeds every document from scratch.

---

## Re-indexing

**Re-index Vector Store** (Settings → Access Control) rebuilds the entire vector index from scratch. Use it when:

- You changed the embedding model
- You changed chunk size or overlap
- You enabled hybrid search for the first time
- You changed quantization settings
- The index seems corrupted or shows dimension mismatch errors

Indexing progress is visible on the **Processing** page. For large archives, it may take a while depending on your `embed_concurrency` setting and embedding provider speed.

---

## Which backend to choose?

**Start with ChromaDB.** It requires nothing beyond the initial setup and works well for thousands of documents. You can always migrate to Qdrant later without re-embedding.

**Switch to Qdrant when:**
- Discovery results for exact terms (account numbers, names, dates) are poor
- Your archive has tens of thousands of documents and you want better performance
- You want quantization to reduce memory usage
- You want HNSW ef to be independently tunable per query vs. index build

**Use Bedrock KB when:**
- Your entire stack is AWS-native and you prefer managed infrastructure
- You already have a Bedrock Knowledge Base set up

---

## Score semantics

The similarity score returned by each backend has different meaning depending on the active configuration. See the [Min Score section in Discovery](Discovery#understanding-min-score) and [[Settings#similarity-search-tuning]] for the full explanation.
