# Troubleshooting

---

## Container won't start

**Symptom:** `docker compose up` exits immediately with a CRITICAL log line.

**Cause:** `PAPERLESS_URL` is not set, or Paperless-NGX is not reachable at that address.

Paperless IQ refuses to start without `PAPERLESS_URL` — there is no open/unauthenticated mode. Login is validated against Paperless-NGX, so the app needs the URL at startup.

**Fix:**
- Verify `PAPERLESS_URL` is in your compose environment (e.g. `http://webserver:8000`)
- Check that the Paperless-NGX container is on the same Docker network as Paperless IQ
- Run `docker compose logs paperless-iq` to see the exact error

---

## Can't log in

**Symptom:** login fails with "Invalid credentials" or times out.

**Checks:**
1. Verify `PAPERLESS_URL` points to the internal Paperless-NGX address (the Docker service hostname, not the public URL)
2. Verify `PAPERLESS_TOKEN` is set and valid — check it against `http://<paperless-url>/api/token/` directly
3. The app rate-limits login to 10 attempts per IP per 5 minutes. Wait 5 minutes and try again if you've hit that limit.
4. Check `docker compose logs paperless-iq` for auth errors

---

## Discovery results are poor / irrelevant

### "I raised Min Score but bad results still show"

In **hybrid mode**, the score is relative per query — the top result is always ~1.0 even when nothing in the archive is relevant. Raising `min_score` trims lower-ranked candidates but cannot filter out a "best of a bad bunch."

In **dense-only mode**, the score is `(cosine + 1) / 2`, which inflates scores — an unrelated document scores ~0.5, loose matches ~0.6–0.8. A threshold of `0.45` is already very permissive.

**Fix:** Enable re-ranking. A reranker judges absolute relevance and is the right lever for quality. `llm` rerank is the easiest (no extra deps, reuses your chat LLM). Set it in **Settings → AI Provider → Re-ranking**.

### "Search errors with dimension mismatch"

The embedding model was changed after documents were indexed. Old vectors have the wrong dimension for the new model.

**Fix:** go to **Settings → Access Control → Re-index Vector Store**. This rebuilds the entire index with the current embedding model.

### Documents don't appear in Discovery

The documents haven't been indexed yet.

**Fix:** go to **Settings → Access Control → Re-index Vector Store** to index all documents. New documents are indexed automatically after each approval (or via the webhook). Check the **Processing** page for indexing status.

---

## Discovery is very slow / hangs

**Cause:** almost always the local cross-encoder reranker (`rerank_method = local`) running on CPU, especially when automation is also active.

The local reranker is CPU-bound and serialised — one inference at a time. If the automation loop is continuously analysing documents and also reranking, and you send a Discovery query, both contend for the same CPU.

**Fix (choose one):**
- Switch to `llm` rerank (Settings → AI Provider → Re-ranking → Reranker = LLM). No extra dependencies, one LLM call per query.
- Disable reranking temporarily while the initial indexing batch runs.
- Accept the latency — on a fast CPU it's seconds, not minutes.

---

## Settings change doesn't take effect

### Changed chunk size / embedding model / quantization and nothing changed in search results

These settings change how documents are **built and stored in the index**. Existing vectors are not retroactively updated.

**Fix:** after changing any of these, go to **Settings → Access Control → Re-index Vector Store**:
- `chunk_size`, `chunk_overlap`, `chunk_strategy`
- Embedding model or provider
- `qdrant_hybrid_search` (first enable)
- `qdrant_quantization`
- HNSW build parameters (`*_hnsw_m`, `*_construction_ef`)

Query-time settings (`search_min_score`, `search_overfetch_multiplier`, HNSW `ef` / `search_ef`, rerank settings) apply **live** — no re-index needed.

### Schedule change isn't picked up

Cron schedule changes (batch schedule, grooming scan schedule) take effect within ~30 seconds without a restart.

---

## Image is very large (~6 GB)

**Cause:** the image contains a CUDA-enabled PyTorch build, which is ~6 GB. The correct build uses the CPU-only torch wheel.

**Fix:** check your build args. The `docker-compose.yml` sets `PIQ_EXTRAS: qdrant-hybrid,rerank-local` by default, which installs sentence-transformers + the CPU-only torch wheel. The Dockerfile installs a CPU-only wheel regardless of `PIQ_EXTRAS` when `rerank-local` is included. If you've customised the Dockerfile or build args and ended up with the CUDA build, restore the CPU torch install line.

A correct build with `rerank-local` is approximately **1.7 GB**.

---

## Pending re-embeds aren't flushing (daily / manual mode)

**Symptom:** the Processing page shows a count of pending re-embeds that isn't decreasing.

**Checks:**
- If mode is `daily`, check that `embed_refresh_hour` (UTC) matches the expected flush time
- If mode is `manual`, re-embeds won't flush until you click **Flush pending** in Processing, or call `POST /api/embeddings/refresh`
- If the embed circuit breaker is open (visible on the Processing page), the embedding provider is returning errors — check the provider connection

---

## Ollama not reachable from Docker

**Symptom:** LLM/embedding tests fail with connection refused or name resolution errors for `localhost:11434`.

**Cause:** inside a Docker container, `localhost` is the container itself, not the host machine.

**Fix:** use `http://host.docker.internal:11434` as the Ollama URL. On Linux, you may also need:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

in your `paperless-iq` service definition.

---

## Bedrock embedding fails with "Malformed request"

**Cause:** the embedding model ID or inference profile ID doesn't match what the Bedrock endpoint expects.

Common issues:
- Using a base model ID when the endpoint expects a cross-region inference profile (or vice versa)
- A model that isn't enabled in your Bedrock region / account

**Fix:**
- Check that the model is enabled in the Bedrock console under "Model access"
- For cross-region inference profiles, use the full profile ID with the region prefix (e.g. `eu.cohere.embed-multilingual-v3`)
- Check the Paperless IQ logs — the raw Bedrock error is logged at WARNING level

---

## Grooming scan produces too many / too few suggestions

**Too many:**
- Lower `grooming_add_threshold` (default 0.80) — require higher similarity before suggesting an addition
- Lower `grooming_scan_top_k` (default 100) — fewer candidates per entity
- Lower `grooming_max_suggestions_per_scan` (default 50) — hard cap per run
- Use **Dry run** first to preview scores before running a real scan

**Too few:**
- Raise `grooming_remove_threshold` (default 0.35) — suggest removals for more documents
- Make sure entities have generated **descriptions** — entities without a description vector are skipped
- Check that your vector backend supports the scan (Bedrock KB doesn't; Chroma tag cohorts fall back to absolute threshold only)

---

## Encrypted credentials unreadable after volume restore

**Cause:** the `SECRET_KEY` used to encrypt stored credentials is stored at `/data/.secret_key`. If the volume was lost and a fresh key was auto-generated, old encrypted credentials from a backup database can't be decrypted.

**Fix:** before restoring a backup, set `SECRET_KEY` in your compose environment to the original key value. The key is a base64-encoded Fernet key — check if you backed it up separately.

If the key is lost, you'll need to re-enter all provider credentials in Settings after restoring the database.

---

## Getting more debug information

Check container logs:
```bash
docker compose logs paperless-iq --tail=100
```

The app logs at INFO level by default. Errors from provider calls (Bedrock, Ollama, etc.) appear at WARNING or ERROR level with the raw error message from the provider.

The **Processing** page shows the current state of all background tasks: automation status, indexing progress, pending re-embeds, and any active grooming scans.
