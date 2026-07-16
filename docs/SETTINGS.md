# Paperless IQ — Settings Reference

This page documents every configurable setting, its default, and — most importantly —
its **caveats**: the non-obvious behaviours that surprise people (scores that aren't
what they look like, changes that silently do nothing until you re-index, knobs that
trade recall for latency, and options with hidden dependencies or cost).

It is organised to mirror the **Settings** page in the app. Each setting lists its
config key (as stored in the database `settings` row) so you can cross-reference logs
and API payloads.

> **Source of truth:** the authoritative schema is
> [`backend/models.py` → `PaperlessIQConfig`](../backend/models.py). If this page and
> the code ever disagree, the code wins — please open a PR to fix the doc.

---

## Read this first — two cross-cutting caveats

### 1. "Re-index required" vs "applied live"

Some settings change how documents are **embedded and stored**. Changing them does
**not** retroactively rewrite the existing index — your old vectors stay as they were,
and only newly-indexed documents use the new value, until you rebuild. Until then you
get an inconsistent or silently-degraded index.

After changing any setting marked 🔁 **Requires re-index**, go to
**Processing → Re-index Vector Store**.

Settings that require a re-index: `chunk_size`, `chunk_overlap`, `chunk_strategy`,
the **embedding model/provider**, `qdrant_hybrid_search`, `qdrant_quantization`,
HNSW build params (`*_hnsw_m`, `*_construction_ef`). Query-time params
(`*_hnsw_ef` / `*_search_ef`, `search_min_score`, `search_overfetch_multiplier`,
rerank settings) apply **live**.

### 2. The "score" is not a cosine similarity — and its meaning changes

This is the single most misunderstood setting. `search_min_score` (UI: **Min Score**)
filters results by a score in `[0, 1]`, but **what that number represents depends on
the active mode**:

| Mode | What the score is | Practical meaning |
|------|-------------------|-------------------|
| **Dense only** (no hybrid, no rerank) | `(cosine + 1) / 2` | Inflated: unrelated (cos 0) → **0.5**, so even loose matches score ~0.6–0.8. A 0.45 threshold is very permissive. |
| **Hybrid on, no rerank** (a common default) | RRF fusion score, **min-max normalised across that one query's results** | **Relative, not absolute.** The best hit in each search is always **1.0**, the worst **0.0**. `0.45` means "≈45% of the way from the weakest to the strongest candidate *in this batch*" — **not** "45% relevant." |
| **Reranker on** (any fusion) | The reranker's own score (overrides the above) | LLM reranker → rating `0–10 ÷ 10`, i.e. quantised to `{0.0, 0.1 … 1.0}` (a 0.45 cutoff ≈ "keep ≥ 5/10"). Local cross-encoder → calibrated `sigmoid(logit)`. |

**Consequences to know:**

- In **hybrid, no-rerank** mode the top result is *always* ~1.0 even when nothing in the
  archive is actually relevant — so `min_score` **cannot** gate out a "best of a bad
  bunch." The number gives false confidence about absolute relevance.
- Raising `min_score` in hybrid mode does **not** demand "better" matches; it just trims
  more of the lower-ranked candidates *relative to that query's result set*.
- The thing that judges **absolute** relevance is the **reranker** (see
  [Re-ranking](#re-ranking)). If results feel insufficiently relevant, enable reranking
  rather than chasing a higher `min_score`.
- Implementation: [`vector_store.py` → `_point_scores`](../backend/vector_store.py).

> The in-app tooltip currently calls this a "normalised cosine score," which is only
> accurate in the dense-only case. Treat the table above as the real behaviour.

---

## Connection

Paperless NGX connectivity and callback URLs. The credentials live in the **environment**,
not the settings database (see [Environment variables](#environment-variables-not-in-the-ui)).

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Webhook secret | `webhook_secret` | `""` (auto-generated on first run) | Stored **encrypted**. Authenticates the Paperless NGX webhook callback. Empty = no auth required (not recommended if reachable beyond localhost). |
| Public Paperless URL | `paperless_public_url` | `""` | The URL your **browser** can reach Paperless at. `PAPERLESS_URL` (env) is the internal Docker address; deep-links in Discovery are rewritten from internal → public using this. Set it if internal and public hostnames differ. |
| Paperless IQ internal URL | `paperless_iq_internal_url` | `""` | URL of Paperless IQ **as reachable from Paperless NGX** (used when registering the webhook). Leave empty to derive it from the incoming request. |

---

## AI Provider

### LLM

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Provider | `llm_provider` | — (required) | One of `ollama`, `bedrock`, `anthropic`, `openai`. |
| Model | `llm_model` | provider-specific | Per-provider defaults: ollama `llama3`, bedrock `claude-3-haiku`, anthropic `claude-3-5-haiku`, openai `gpt-4o-mini`. |
| Credentials | `llm_credentials` | — | **Fernet-encrypted**, never returned to the UI. The `__KEEP__` sentinel means "keep the stored value." |
| Ollama URL | `ollama_url` | `http://localhost:11434` | Only used when provider is `ollama`. |
| LLM timeout (s) | `llm_timeout_seconds` | `120` | Max seconds to wait for an LLM response. `0` = no limit. Applies to analysis, discovery answers, and the LLM reranker. |

### Vector store

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Backend | `vector_store_backend` | `local` | `local` = ChromaDB (in-container, zero setup). `qdrant` = external Qdrant service (better at scale, supports hybrid search + quantization). `bedrock_kb` = AWS Bedrock Knowledge Base (managed; AWS does its own retrieval). |
| Bedrock KB ID | `bedrock_kb_id` | `null` | Required when backend is `bedrock_kb`. |

**Switching backends** does not move your vectors. Use **Processing → Migrate
embeddings** (or `POST /api/vector/migrate`) to copy existing vectors across **without
re-embedding** — but only if the embedding model is unchanged. If the model changed, a
full re-index is required.

#### Qdrant backend

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Mode | `qdrant_mode` | `local` | `local` = self-hosted (compose service). `cloud` = Qdrant Cloud (set URL + API key). |
| URL | `qdrant_url` | `http://qdrant:6333` | Default is the compose service DNS name. |
| API key | `qdrant_api_key` | `""` | **Fernet-encrypted**, never returned to the UI. Needed for Qdrant Cloud. |
| Collection | `qdrant_collection` | `paperless_iq_chunks` | Document-chunk collection name. |
| Memory collection | `qdrant_memory_collection` | `piq_memories` | Long-term memory collection name. |

> These next three groups live in the **Vector Store** section of the page (they
> describe how the index is built and stored). Query-time relevance knobs are under
> [Similarity Search Tuning](#similarity-search-tuning).

#### Chunking (all backends)

How documents are split before embedding. 🔁 **Changing any of these requires a re-index.**

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Chunk size (chars) | `chunk_size` | `1000` | Max characters per embedded chunk. Smaller = more precise retrieval; larger = more context per chunk. |
| Chunk overlap (chars) | `chunk_overlap` | `200` | Characters shared between consecutive chunks, so answers straddling a boundary are still retrieved. |
| Chunk strategy | `chunk_strategy` | `char` | `char` = fixed-width windows (fast). `sentence` = packs whole sentences up to `chunk_size`, avoiding mid-sentence cuts. |

#### ChromaDB index — HNSW (when backend = `local`)

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Search ef | `chroma_hnsw_search_ef` | `100` | Query candidate-list size. Higher = better recall, more latency. **Must be ≥ `similar_docs_count × search_overfetch_multiplier`** or recall silently caps (validator-enforced). Applied **live**. |
| M (graph connectivity) | `chroma_hnsw_m` | `16` | Links per node. Higher = better recall, more memory. 🔁 **Build-time — requires re-index.** |
| Construction ef | `chroma_hnsw_construction_ef` | `100` | Index build quality. Higher = better recall, slower indexing. 🔁 **Build-time — requires re-index.** |

#### Qdrant index — HNSW & quantization (when backend = `qdrant`)

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| HNSW ef | `qdrant_hnsw_ef` | `128` | Query-time candidate list. Higher = better recall, more latency. **Must be ≥ `similar_docs_count × search_overfetch_multiplier`** (validator-enforced). Applied **live**. |
| M | `qdrant_hnsw_m` | `16` | Graph connectivity. 🔁 **Build-time — requires re-index.** |
| Quantization | `qdrant_quantization` | `none` | `none` = full precision. `scalar` = INT8, ~4× smaller, minimal quality loss. `binary` = ~32× smaller, noticeable quality loss. 🔁 **Requires re-index.** |

### Embeddings

Used for semantic search and smart entity selection. **Can use a different provider than
the chat LLM** — embedding models are small and fast.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Embedding provider | `embed_provider` | `ollama` | `ollama`, `bedrock`, or `openai`. |
| Embedding model | `embedding_model` | `nomic-embed-text` | Per-provider defaults: ollama `nomic-embed-text`, bedrock `amazon.titan-embed-text-v1`, openai `text-embedding-3-small`. 🔁 **Changing the model requires re-indexing** — the vector dimension must match the index, or search fails with a dimension-mismatch error. |
| Parallel embeddings | `embed_concurrency` | `1` | Embedding API calls in flight at once. For Ollama this is chunks-per-document; for cloud providers it now also overlaps **whole documents** during indexing. `1` is safe for a local Ollama. Raise to **4–8** for a remote/GPU Ollama, and to **~8** for Bedrock (the Bedrock embeddings panel defaults this to 8). The vector store's embed semaphore caps total concurrent calls, so raising it never exceeds this number regardless of how many documents are being indexed. |
| Embedding batch size | `embed_batch_size` | `32` | Texts sent per embedding API call. **Only Cohere Embed models on Bedrock** batch multiple texts in one call (up to 96) — this cuts request count and cost during indexing. Titan and all non-Bedrock providers ignore it and always send one text per call. |

### Embedding refresh

Controls **when metadata changes re-embed a document**. A re-embed happens after an
approval writes new metadata, after a webhook edit, and after a grooming merge —
because chunk embeddings carry a metadata prefix (tags/correspondent/type), so changing
those should refresh the vector. First-time indexing always embeds immediately and is
unaffected. The chokepoint is `schedule_reembed()`; only *re*-embeds of already-indexed
documents are deferred.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Refresh mode | `embed_refresh_mode` | `immediate` | `immediate` = re-embed the moment metadata changes (vectors always fresh; default, zero behaviour change). `daily` = stamp the document dirty and re-embed all dirty docs once per day. `manual` = stamp dirty and wait for the user to flush. Daily/manual **debounce** repeated same-day edits (one re-embed, not N) and spread embedding cost — useful on metered embedding APIs or after a large grooming merge. The dirty document re-fetches its current content + metadata from Paperless at flush time, so the deferred vector reflects the latest state, not the state when it was stamped. |
| Daily flush hour (UTC) | `embed_refresh_hour` | `3` | `0–23`. Only used when mode = `daily`. The flush loop checks every minute and runs when the UTC hour matches. |
| Content-drift reindex (days) | `content_drift_reindex_days` | `7` | Safety net for **content/OCR edits** that didn't fire the webhook. Every N days, documents whose Paperless `modified` is newer than our last embed are re-embedded. `0` disables it. The **webhook remains the primary, real-time path** — this only catches drift it missed. First run is one interval after startup. Compares against the per-document `last_embedded_at`, so it never re-embeds an unchanged document. |

When dirty re-embeds are pending (`daily`/`manual`), the count is exposed at
`GET /api/embeddings/pending`; `POST /api/embeddings/refresh` flushes them now (the UI
surfaces a banner). See **D-22** for why merges defer rather than re-embed inline.

> **Embed visibility.** Every document embed writes an `embedded` event to the audit
> log (with the document title and a `change_source` naming the trigger:
> `system:index`, `approval`, `webhook`, `system:flush`, `drift`). This makes
> double-embeds visible — e.g. a freshly *added* document fires the webhook *and* gets
> picked up for analysis → embedded on approval. Filter the Audit page by the `embedded`
> action (and by source) to see the history; old rows are pruned by `audit_retention_days`.

### Similarity Search Tuning

Query-time relevance knobs — all applied **live** (no re-index). Index-build settings
(chunking, HNSW) live in the [Vector store](#vector-store) section instead.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Overfetch multiplier | `search_overfetch_multiplier` | `5` | Candidates fetched = `top_n × this`. Higher = better recall, more post-processing. Also feeds the HNSW `ef` validation. |
| Min Score | `search_min_score` | `0.0` (off) | Drop results below this `[0,1]` score. **⚠️ Meaning is mode-dependent — see [the score caveat](#2-the-score-is-not-a-cosine-similarity--and-its-meaning-changes).** `0` disables the filter. |
| Hybrid search | `qdrant_hybrid_search` | `false` | *(Qdrant only.)* Combines dense (semantic) + sparse (BM25 keyword) vectors via **RRF fusion** — improves recall for precise/rare-term queries (names, IDs, exact phrases). It's a query strategy, so it lives here rather than with the index settings. **Caveats:** ① needs the `fastembed` sparse encoder (`paperless-iq[qdrant-hybrid]` extra). ② 🔁 **Requires re-index** to build the sparse vectors. ③ **changes the meaning of the score** to relative min-max — see [the score caveat](#2-the-score-is-not-a-cosine-similarity--and-its-meaning-changes). |

### Re-ranking

After vector search, re-score `(query, passage)` pairs to **significantly improve
precision**. This is the real lever for relevance quality (more so than `min_score`).
Ships **OFF**. Adds latency proportional to `rerank_top_k × passage length`.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Enable re-ranking | `rerank_enabled` | `false` | Master switch. When on, the reranker's score **overrides** the vector/fusion score everywhere. |
| Reranker | `rerank_method` | `llm` | See method comparison below. |
| Re-rank top K | `rerank_top_k` | `20` | Candidates passed to the reranker. Higher = better recall before reranking, more reranker latency. |
| Model | `rerank_model` | `BAAI/bge-reranker-v2-m3` | HuggingFace ID (for `local`) or Bedrock model ID/ARN (for `api`). The default is multilingual (~560 MB, downloaded on first use). |

**Method comparison:**

| Method | Dependencies | Cost / latency profile | Caveats |
|--------|--------------|------------------------|---------|
| `llm` (your chat LLM, listwise) | None — reuses LLM creds | One extra LLM call per query | Scores are quantised to `rating/10`. Cheapest to operate; recommended default. **If automation is on**, every suggestion also reranks → extra LLM load. |
| `local` (in-process cross-encoder) | `paperless-iq[rerank-local]` (sentence-transformers + torch) | **CPU-bound and heavy** | ⚠️ The model is **CPU-only here** and saturates all cores. A single shared instance is used by Discovery *and* the automation loop; inference is now **serialised** and the model is **loaded once** ([`rerankers.py`](../backend/rerankers.py)), but on a busy box it still adds seconds per query. The image bundles a **CPU-only torch** build (`PIQ_EXTRAS` includes `rerank-local`) — see [Environment variables](#environment-variables-not-in-the-ui). First use downloads the weights into `HF_HOME` (persisted). |
| `api` (Amazon Bedrock Rerank) | Bedrock as the LLM provider | Per-call AWS cost | Requires `llm_provider = bedrock`. Enter a Bedrock rerank model ID/ARN (e.g. `amazon.rerank-v1:0`, `cohere.rerank-v3-5:0`). |

---

## Metadata Rules

### Analysis defaults

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Default analysis mode | `default_analysis_mode` | `ocr` | `ocr` = send the existing OCR text (fast, cheap). `full_document` = send the rendered document (vision models; higher quality, higher cost). |
| Per-doctype analysis mode | `per_doctype_analysis_mode` | `{}` | Override the mode per document type (id → `ocr`/`full_document`). |
| Context window (chars) | `context_window_chars` | `128000` | Max characters sent to the LLM; content beyond this is **truncated**. Keep ≤ your model's context window. |
| Vision page warning | `vision_max_pages_warning` | `5` | When `full_document` is used and a doc exceeds this page count, the UI warns (Keep / Limit / Cancel) before incurring vision cost. |

### Smart entity selection

Hybrid strategy for suggesting tags/correspondents/types: vector similarity to past
documents, with a frequency-based fallback.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Smart entity selection | `smart_entity_selection` | `true` | When off, falls back to frequency only. |
| Similar documents to consider | `similar_docs_count` | `10` | How many similar docs feed entity suggestions. Also one factor in the HNSW `ef` validation. |
| Frequency fallback count | `frequency_fallback_count` | `20` | Top-N most frequent entities offered when similarity yields little. |

### Creation policies

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Tag policy | `tag_creation_policy` | `existing_only` | `existing_only` = LLM may only pick from existing tags. `allow_new` = LLM may propose new ones. |
| Correspondent policy | `correspondent_creation_policy` | `existing_only` | As above, for correspondents. |
| Document-type policy | `doctype_creation_policy` | `existing_only` | As above, for document types. |
| Storage-path policy | `storage_path_creation_policy` | `existing_only` | As above, for storage paths. |

---

## Prompts & Fields

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Global prompt template | `global_prompt_template` | built-in classifier prompt | The base instruction sent for metadata analysis. |
| Per-field prompt templates | `per_field_prompt_templates` | `{}` | Override the prompt for a specific field. |
| Per-doctype prompt templates | `per_doctype_prompt_templates` | `{}` | Override the prompt per document type. |
| Discovery system prompt | `discovery_system_prompt` | `null` (built-in default) | The system prompt body for the Discovery (RAG) answer. |
| Field descriptions | `field_descriptions` | `{}` | Per-field instructions telling the LLM how to populate each metadata field. |

---

## Automation

The background loop that analyses (and optionally applies metadata to) incoming
documents.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Automation enabled | `automation_enabled` | `false` | Master switch for the background loop. **Caveat:** when on, it continuously runs analysis *and* embedding/entity search — which means it also exercises the reranker continuously. With `rerank_method = local` this keeps the CPU busy and can starve interactive Discovery. |
| Inbox tag | `inbox_tag_id` | `null` | The tag that marks "needs processing." Documents with it are picked up; suggestions exclude already-tagged (reviewed) docs. |
| Auto-apply | `auto_apply` | `false` | When on, every suggestion the poller/scheduler produces is **approved automatically and immediately** — nothing waits for a human, and entities allowed by the creation policies are created in Paperless at that moment (audited as `change_source=automation`). Off = suggestions wait in the queue for human approval, and nothing is created until you approve. |
| Poll interval (s) | `poll_interval_seconds` | `10` | How often the **inbox poller** checks for new documents. **Minimum 1** (validator-enforced). |
| Batch size | `batch_size` | `10` | Documents processed per **scheduled** batch run. **Minimum 1** (validator-enforced). |
| Schedule (cron) | `schedule_cron` | `null` | Cron expression for **scheduled batch analysis** (separate from the always-on inbox poller). A real cron schedule (croniter) — e.g. `0 2 * * *` = 2 AM daily. Empty/null disables it. **Invalid expressions are rejected on save** (422). Edits apply within ~30s, no restart. |

---

## Library & Grooming

Vocabulary maintenance — entity descriptions, duplicate detection, and a similarity
**mismatch scan** that suggests tag/correspondent/type corrections. The whole feature
is **off by default** and gated behind a dedicated `can_groom` permission. The Library
page is hidden for everyone (admins included) until `grooming_enabled` is on. The scan
is **zero-LLM / zero-embed** (it reuses stored entity vectors); the only LLM spend is
description generation. See **D-21/D-22/D-23** for the design decisions.

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Enable grooming | `grooming_enabled` | `false` | Master switch. Off = Library page hidden, scheduled scans idle. |
| Entity types | `grooming_entity_types` | `["tag","correspondent","document_type"]` | Which entity kinds the Library manages. |
| Dedup — name threshold | `grooming_dedup_name_threshold` | `0.85` | `[0,1]` fuzzy-name similarity to flag a name-duplicate pair (LLM-free). |
| Dedup — embedding threshold | `grooming_dedup_embed_threshold` | `0.90` | `[0,1]` cosine between **entity** vectors to flag a semantic-duplicate pair. Only fires for entities that have a generated description (hence an embedding). |
| Description — sample docs | `grooming_desc_sample_docs` | `5` | How many representative documents are sampled to generate an entity's description. |
| Description — snippet chars | `grooming_desc_snippet_chars` | `300` | Characters of content per sampled doc included in the generation prompt. |
| Scan — add threshold | `grooming_add_threshold` | `0.80` | Doc similarity at/above which the scan suggests **adding** the entity. **Must be > remove threshold** (validator-enforced — the dead band between them is the hysteresis that prevents flip-flopping). |
| Scan — remove threshold | `grooming_remove_threshold` | `0.35` | Doc similarity below which an applied tag is suggested for **removal**. |
| Scan — remove percentile | `grooming_remove_percentile` | `10` | Cohort-relative rule: a doc in the bottom N% of its entity's cohort can be flagged even if it clears the absolute remove threshold. Counters the D-18 prefix inflation on removals. **Cohort scoring needs a filterable backend** — Qdrant for tags; both backends for correspondent/document_type. On Chroma, tag cohorts fall back to the absolute rule only. Needs a cohort of ≥10 docs to engage. |
| Scan — min supporting chunks | `grooming_min_supporting_chunks` | `2` | An **add** needs at least this many chunks above the add threshold — one lucky chunk isn't enough. |
| Scan — top-K | `grooming_scan_top_k` | `100` | Chunks retrieved per entity vector query. Also gates the "absence is evidence" remove rule (only when `top_k ≥ 3 × entity_doc_count`). |
| Scan — max suggestions / run | `grooming_max_suggestions_per_scan` | `50` | Hard cap on documents enqueued per scan, highest `|score − threshold|` first — protects the queue from flooding on the first scan of a large corpus. |
| Scan schedule (cron) | `grooming_scan_cron` | `null` | Cron for **scheduled** scans (croniter; e.g. `0 3 * * *`). Empty/null = manual-only (Library → Scan → *Scan now*). Invalid expressions rejected on save. **Scheduled scans are incremental** — only entities that are new, whose description changed, or whose documents were re-embedded since their last scan (content drift) are re-examined; the manual *Scan now* is always a full scan. The scan is **hard-disabled on the `bedrock_kb` backend** (no vector queries) and skips while the embed circuit breaker is open. |
| Re-suggest after (days) | `grooming_resuggest_after_days` | `0` | `0` = a rejected suggestion is **never** re-suggested (rejection = permanent answer, D-23). `>0` = a dismissal expires after N days and may resurface. |

> **Dry run first.** Embedding-model and corpus differences make universal thresholds
> impossible. Use **Library → Scan → Dry run** to preview scored candidates without
> enqueueing, and tune `grooming_add_threshold` / `grooming_remove_threshold` against
> your actual data before turning on a scheduled scan.

---

## Access Control

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Sync NGX admins | `sync_ng_admins` | `true` | Paperless NGX superusers/staff automatically get full Paperless IQ access. Per-user permissions (`can_access`, `can_view_queue`, `can_approve`, `can_analyze`, `can_discover`, `can_settings`, `can_groom`) are managed in this tab's user list, not in this config blob. `can_groom` is additionally gated by `grooming_enabled` — even an admin can't see the Library when grooming is off. |

> Authentication is **required**: Paperless IQ refuses to start unless `PAPERLESS_URL`
> (env) is set, because login validates against Paperless (there is no open mode — see
> **D-24**). The `PAPERLESS_TOKEN` lives **only** in the environment and never in the
> settings DB.

---

## Long-term Memory

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Memory enabled | `memory_enabled` | `true` | When on, relevant stored memories are retrieved and injected into Discovery answers (only those above a relevance threshold). Memory CRUD lives in the Memories tab. |

---

## Audit

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Audit retention (days) | `audit_retention_days` | `180` | How long change-history rows are kept. **Minimum 30** (validator-enforced). |

---

## Localization

| Setting | Key | Default | Notes & caveats |
|---------|-----|---------|-----------------|
| Target language | `target_language` | `null` | Forces the language of LLM-generated output (titles, Discovery answers). Empty = match the user's input language. |

---

## Appearance

Theme settings (Appearance tab). These are purely cosmetic and apply live.

| Key | Default | Notes |
|-----|---------|-------|
| `mantine_color` | `teal` | Mantine primary palette name. |
| `color_scheme` | `dark` | `light` / `dark` / `auto`. |
| `theme_primary_color` | `#1a7288` | Primary accent. |
| `theme_sidebar_from` / `theme_sidebar_to` | `#0a3344` / `#0e4458` | Sidebar gradient. |
| `theme_font` / `theme_font_size` | `Roboto` / `14px` | Base typography. |
| `theme_text_color` / `theme_bg_color` / `theme_card_color` | `#2d3239` / `#f8f9fb` / `#ffffff` | Core colours. |
| `theme_card_alt_hex` / `theme_card_alt_opacity` | `#1a7288` / `12` | Alternate card tint. |
| `theme_chip_color` | `""` | Empty = derive from `theme_primary_color`. |
| `theme_nav_icons` | `{}` | Per-nav-item icon overrides. |

---

## Environment variables (not in the UI)

These are set in `docker-compose.yml` / the container environment, **not** the settings
database. Several are deliberately kept out of the DB for security.

| Variable | Purpose | Caveats |
|----------|---------|---------|
| `PAPERLESS_URL` | Internal Paperless NGX address (Docker network). | **Required — the app refuses to start without it** (login validates against Paperless; there is no open mode, see D-24). |
| `PAPERLESS_TOKEN` | Paperless NGX API token. | **Environment only — never stored in the settings DB.** Required for Paperless operations; if absent the app still starts (auth enforced) but warns loudly that search/writes/indexing will fail. |
| `SECRET_KEY` | Fernet key for encrypting credentials. | Auto-generated on first run into `/data/.secret_key`. Set explicitly if you need to restore an encrypted DB backup after a volume loss. |
| `DATABASE_URL` | SQLite path. | Defaults to `/data/paperless_iq.db` in the volume. |
| `PIQ_VECTOR_STORE_BACKEND` | Overrides the vector backend at boot. | Optional; the UI setting normally governs this. |
| `PIQ_QDRANT_URL` | Qdrant URL override. | Defaults to the compose service DNS. |
| `PIQ_EXTRAS` | **Build arg** selecting optional dependency extras baked into the image. | Default `qdrant-hybrid,rerank-local`. Controls whether hybrid search (`fastembed`) and the local reranker (`sentence-transformers` + **CPU-only torch**) are installed. Set to `qdrant-hybrid` (or empty) for a leaner image. Changing it requires a rebuild. |
| `HF_HOME` | HuggingFace cache dir. | Set to `/data/hf-cache` so reranker/sparse-encoder weights are downloaded **once** and survive restarts. |

---

## Quick caveat index

- **"I raised Min Score but bad results still show / good ones disappeared."** → In
  hybrid mode the score is *relative per query*; in dense mode it's an inflated
  `(cos+1)/2`. See [the score caveat](#2-the-score-is-not-a-cosine-similarity--and-its-meaning-changes). Use a **reranker** for real relevance gating.
- **"I changed chunk size / embedding model / hybrid / quantization and nothing changed."**
  → Those need a **re-index** (Processing → Re-index Vector Store).
- **"Discovery hangs / is very slow."** → Likely `rerank_method = local` on a CPU box,
  especially with automation also running. Switch to `llm` rerank, or accept the latency.
- **"My image is huge (~6 GB)."** → A CUDA torch build. Ensure the CPU-only torch path is
  used (`PIQ_EXTRAS` + the Dockerfile CPU-wheel install); a correct build is ~1.7 GB.
- **"Search errors with a dimension mismatch."** → The embedding model changed after
  indexing. Re-index.
