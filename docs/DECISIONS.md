# Paperless IQ — Design Decisions

> Decisions are recorded here so future contributors (and future Claude sessions) understand *why* the code looks the way it does. When you change a decision, update the entry — don't delete it.

---

## D-01 · Protocol-based provider abstraction

**Decision:** `LLMProvider` and `VectorStore` are `typing.Protocol` (structural subtyping), not abstract base classes.

**Rationale:** Provider adapters are thin wrappers around external SDKs. Requiring them to inherit from a base class would couple the SDK-facing class hierarchy to our own. Protocols let the adapters look like idiomatic SDK wrappers while still being statically type-checkable as conforming to our interface. New providers need zero extra boilerplate.

**Rule:** New providers must implement all methods of `protocols.LLMProvider`. Do not add convenience helpers to the protocol — put them in the concrete class or a shared utility.

---

## D-02 · Automation = continuous inbox poller + cron-driven jobs

**Decision:** `_automation_loop(app, poll_interval)` is the **inbox poller only** (process every inbox-tagged document each poll). *Scheduled* work is cron-driven, not poll-driven: a generic `_cron_loop(name, get_expr, run_job)` fires a one-shot job when a cron expression comes due. Two jobs ride it today — `_run_scheduler_batch` (batch analysis, `schedule_cron`) and `_run_scheduled_grooming_scan` (`grooming_scan_cron`). The shared per-document analysis closures live in `_make_analysis_callbacks`, so the poller and the batch job stay identical without sharing a loop body.

**Rationale:** The original design folded scheduling into `_automation_loop` via a `batch_size` flag, but timing was still `poll_interval` — so `schedule_cron` was a truthy flag that never actually honoured its cron value. Real cron scheduling (croniter, D-21) needs a different cadence than inbox polling, and two unrelated schedules (batch, grooming scan) now need it. `_cron_loop` re-reads the expression every tick, so a settings change applies within one check interval with no task restart — which is why the settings-update handler no longer starts/stops the scheduler task.

**Rule:** Don't reintroduce `batch_size` into `_automation_loop` or drive scheduled work off `poll_interval`. New periodic jobs go through `_cron_loop` with their own cron setting. Cron strings are validated at save time by the `validate_cron` field validator in `models.py` (invalid → 422); the loop also tolerates an invalid/None expression by idling.

---

## D-03 · `_fetch_entity_context` returns a 4-tuple

**Decision:** `DocumentAnalyzer._fetch_entity_context()` returns `tuple[str, list[str], list[str], list[str]]` — the formatted prompt string plus the three raw entity lists.

**Rationale:** The caller (`analyze()`) needs to pass the entity lists to `_apply_creation_policy` to check whether suggested values already exist. Without the tuple, `_apply_creation_policy` would need to re-fetch the same data from Paperless NGX that `_fetch_entity_context` just retrieved, doubling the API calls per document.

**Rule:** `_apply_creation_policy` accepts `all_tags`, `all_correspondents`, `all_document_types` as keyword-only arguments. When called from `analyze()` these are always passed. The fallback to fetching individually is a safety net for callers outside the normal pipeline (e.g. tests) and should not be relied on in production paths.

---

## D-04 · OCR text sourced from metadata response

**Decision:** In `ocr` analysis mode, `analyze()` reads `doc_meta.get("content", "")` instead of making a separate `GET /api/documents/{id}/content/` request.

**Rationale:** Paperless NGX includes the full OCR text in the standard metadata endpoint (`GET /api/documents/{id}/`). A second request is redundant. `full_document` mode still uses the content endpoint because it retrieves the original file content, not just the OCR text.

**Rule:** Do not re-introduce `get_document_ocr_text()` calls in `analyze()`. If Paperless NGX changes this behaviour in a future version, update the `content` field extraction here.

---

## D-05 · Session management — `Depends(get_session)` vs `AsyncSessionLocal()`

**Decision:**
- HTTP route handlers always use `session: AsyncSession = Depends(get_session)`
- Background tasks and lifespan code always use `async with AsyncSessionLocal() as db`

**Rationale:** `Depends(get_session)` ties the session lifetime to the HTTP request (auto-commit on success, auto-rollback on exception, auto-close after response). Background tasks and lifespan run outside a request context so they must manage their own session lifecycle explicitly.

**Rule:** Never mix the two patterns. A function that is both a route handler and called from a background task should be refactored into a shared helper that accepts a `session` argument.

---

## D-06 · `asyncio.get_running_loop()` not `get_event_loop()`

**Decision:** All `run_in_executor` calls use `asyncio.get_running_loop()`.

**Rationale:** `asyncio.get_event_loop()` is deprecated in Python 3.10+ and raises a `DeprecationWarning` in many contexts. In async code there is always a running loop available; `get_running_loop()` is both correct and raises immediately if accidentally called outside an async context (useful for catching bugs).

**Rule:** Never use `asyncio.get_event_loop()` anywhere in the codebase.

---

## D-07 · Bedrock boto3 client caching and token refresh

**Decision:** `BedrockProvider` caches the boto3 runtime client in `self._cached_runtime`. On `ExpiredTokenException`, it calls `_invalidate_runtime_client()` and retries exactly once. If the second attempt also fails, the exception propagates.

**Rationale:** Creating a boto3 client is cheap but not free. More importantly, STS temporary credentials can expire mid-session. One automatic retry covers the common case (token just expired, new client picks up fresh credentials from the environment or IAM role).

**Rule:** The retry count is fixed at 1. Do not turn this into a general-purpose retry loop — for genuine API errors (throttling, service errors) use exponential back-off at a higher level.

---

## D-08 · Ollama singleton `AsyncClient`

**Decision:** `OllamaProvider` creates its `AsyncClient` once (`_client_instance`) and reuses it across all calls.

**Rationale:** The Ollama Python SDK's `AsyncClient` manages its own `httpx.AsyncClient` connection pool. Creating a new instance per request would open and close connections on every call, negating the benefit of connection pooling and adding latency.

**Rule:** Never instantiate `ollama.AsyncClient` per-request. The single instance is sufficient for concurrent requests because the SDK handles multiplexing internally.

---

## D-09 · Memory deduplication via cosine similarity

**Decision:** Before inserting a new memory fact, `MemoryStore.find_similar()` queries the `piq_memories` ChromaDB collection for the nearest existing fact. If the cosine distance is ≤ 0.08 (i.e. similarity ≥ 0.92), the fact is considered a duplicate and the existing entry is updated instead.

**Rationale:** Without deduplication, the same fact extracted from multiple conversations would accumulate as separate rows, growing unboundedly and injecting redundant context. Semantic similarity catches paraphrases ("Telekom contract €30/mo ends Aug 2025" ≈ "Monthly Telekom plan expires 2025-08, costs 30 EUR") that exact-string matching would miss.

**Rule:** The threshold (0.08 distance) is intentionally conservative. If users report that distinct facts are being merged, raise the threshold — don't disable the check.

---

## D-10 · Settings: orchestrator + pure tab components

**Decision:** `SettingsPage.tsx` is the single owner of all settings state. The seven tab components (`settings/*.tsx`) are pure display — they receive values and setters as props and emit no events directly to the server.

**Rationale:** Settings is a single form (one `<form>` element, one `onSubmit`). The form must capture values from all tabs in a single submit, which requires all state to live in one place. Co-locating state with the component that owns the submit also prevents the tab-switch footgun: with a multi-form approach, switching tabs before saving would silently lose data.

**Exceptions:** `MemoriesTab` makes its own API calls (`updateMemory`, `deleteMemory`, `clearMemories`) because these are fire-and-forget CRUD mutations that don't feed back into the main `handleSubmit` path. Lifting them to the orchestrator would require 4+ extra callback props for no architectural gain.

**Rule:**
- Tab components must not import `useQuery` or `useMutation`
- Tab components must not call `api.*` directly (except `MemoriesTab` for its memory CRUD)
- Do not add `settingsTab`-awareness to tab components — the orchestrator controls which tab is visible
- Any constant needed by both a tab component and `SettingsPage.tsx` belongs in `settings/constants.ts`

---

## D-11 · Shared constants in `settings/constants.ts`

**Decision:** `METADATA_FIELDS`, `LLM_MODEL_DEFAULTS`, and `EMBED_MODEL_DEFAULTS` are defined once in `frontend/src/pages/settings/constants.ts` and imported wherever needed.

**Rationale:** `METADATA_FIELDS` is used in `PromptsFieldsTab` (rendering) and `SettingsPage` (assembling `field_descriptions` in `handleSubmit`). `LLM_MODEL_DEFAULTS` / `EMBED_MODEL_DEFAULTS` are used in `AIProviderTab` (provider-switch handler) and `SettingsPage` (useEffect initialisation). Defining them in two places guarantees they will diverge.

**Rule:** Never copy these definitions into a component file. Add new shared lookup tables here.

---

## D-12 · `MarkdownText` is a standalone component

**Decision:** `MarkdownText` (including `renderInline`, the `Source` type, and the citation badge logic) lives in `frontend/src/components/MarkdownText.tsx`, not inline in `DiscoveryPage`.

**Rationale:** The markdown renderer is ~200 lines of logic that is conceptually independent of the Discovery page. Inlining it made `DiscoveryPage.tsx` unwieldy and prevented the renderer from being reused elsewhere (e.g. future audit log formatting).

**Rule:** Changes to markdown rendering go in `components/MarkdownText.tsx`. Do not duplicate the renderer logic in any other page.

---

## D-13 · Full-replacement settings saves (not PATCH)

**Decision:** `PUT /api/settings` always receives and stores the complete configuration. The frontend's `handleSubmit` assembles the full config by merging: existing server state → DOM form fields → React-state-owned fields.

**Rationale:** A partial-update (PATCH) approach requires the frontend to track which fields have changed, which introduces complex dirty-state logic. Full replacement is simpler and more predictable: what you see in the UI is exactly what gets saved. The merge strategy (start from server state, overlay active tab's form fields) ensures values from inactive tabs are never silently dropped.

**Rule:** The merge order in `handleSubmit` is intentional:
1. Spread `{...s}` (current server state as baseline)
2. `fd.forEach((v, k) => { values[k] = v; })` — overlay active tab DOM fields
3. Explicit React-state assignments at the bottom — these always win

Do not reorder steps 2 and 3. React-state fields (theme colours, prompt text, Bedrock credentials) must overwrite FormData in case the DOM and React state diverge.

---

## D-14 · Two-layer model approach (Pydantic + ORM)

**Decision:** Data in the DB is represented by `orm_models.py` (SQLAlchemy); data crossing the API boundary is represented by `models.py` (Pydantic). Mapping between them is explicit.

**Rationale:** ORM models are optimised for persistence (indexes, relationships, lazy loading). Pydantic models are optimised for serialisation and validation. Merging them (e.g. via SQLModel) couples the two concerns and makes it harder to evolve the API schema independently from the DB schema.

**Rule:** API route handlers return Pydantic models (or plain dicts for settings). DB writes use ORM models. There should be no `from_orm()` magic — mappings are explicit field assignments.

---

## D-16 · Bedrock uses the Converse API, not model-specific InvokeModel

**Decision:** `BedrockProvider.chat()` calls the Bedrock `converse()` API (unified request shape) rather than `invoke_model()` with a model-specific JSON body.

**Rationale:** The original implementation used `invoke_model()` with a Claude-specific body (`anthropic_version`, `messages`, `system`). This worked only for Claude models — switching to Nova, Llama, or Mistral would have required branching logic per model family. The Converse API accepts a single unified shape for all model families; Bedrock handles per-model translation internally.

**Rule:** Do not introduce `invoke_model()` calls or model-family branching in `BedrockProvider.chat()`. If a model is not supported by the Converse API, use a different provider adapter.

---

## D-17 · Permission system: middleware for base access, `Depends` for per-route checks

**Decision:** The `can_access` check runs in `auth_middleware` using `AsyncSessionLocal()`. All other per-route permission checks use `require_perm(*perms)` as a FastAPI `Depends`.

**Rationale:** FastAPI middleware cannot participate in the dependency injection graph (`Depends` is not available there). The base access check must be in middleware because it needs to run before any route handler sees the request. Per-route checks that need richer context (which specific permission, e.g. `can_approve` vs `can_settings`) use `Depends(require_perm(...))` so they get the request-scoped session from `Depends(get_session)` and don't need a separate session open.

The bootstrap problem (first admin has no permissions yet) is solved by `sync_ng_admins=True` (default): Paperless NGX superusers/staff automatically receive full PIQ access on first login, with no manual setup required.

**Rule:**
- Middleware uses `async with AsyncSessionLocal()` — never `Depends`.
- Route handlers use `dependencies=[Depends(require_perm("can_X"))]` — never `AsyncSessionLocal()`.
- Do not add a second base-access check inside route handlers; middleware already enforces it.
- `sync_ng_admins` must default to `True` so fresh installs are not locked out.

---

## D-18 · Metadata prefix prepended to chunks before embedding

**Decision:** `ChromaVectorStore.upsert()` prepends a structured metadata header (title, document type, correspondent, tags, custom fields) to each text chunk before computing its embedding.

**Rationale:** Without the prefix, a chunk of body text that merely *mentions* a topic (e.g. a salary slip mentioning "Lebensversicherung" in passing) can outscore a document that *is* about that topic, because the chunk's semantic content reflects its surrounding text rather than the document's identity. Prepending the metadata makes the embedding capture both the document's classification and its content, dramatically improving recall for queries like "show me my life insurance documents".

**Rule:** The prefix is prepended at embed time only — it is not stored in the `documents` column of ChromaDB (which still holds the raw chunk). Do not store the prefix as part of the passage returned in search results.

---

## D-19 · Session expiry via background loop, not startup hard-delete

**Decision:** Expired conversation sessions (older than 24 hours) are processed by a persistent `_session_expiry_loop` background task, not by a hard-delete in `lifespan()`. The loop runs immediately at startup and then every hour.

**Rationale:** The original startup prune ran before providers and the memory store were initialized, so it could only hard-delete sessions — memories were silently lost. The background loop runs after all providers are ready, so it calls `_extract_memories_from_session()` for each expired session before deleting it. Sessions that expire while the app is down are caught on the first loop iteration after restart.

**Rule:**
- Do not re-introduce a startup hard-delete of sessions in `lifespan()`.
- Memory extraction is always attempted before deletion; failures are logged but do not block deletion.
- The loop is always started (regardless of automation settings) and cancelled on shutdown alongside the automation tasks.

---

## D-20 · Vector backend selection via factory; embeddings are app-side and portable

**Decision:** The active vector store is built by `backend/vector_factory.make_vector_store(config, embed_provider, concurrency, providers)`. Embeddings are computed **inside the app** (not delegated to the store) and are therefore backend-portable. Switching backends auto-migrates existing vectors without re-embedding when the embedding model is unchanged; if the model changed the app sets `needs_reindex=True` in the save response and the user must trigger a full re-index.

**Rationale:** Before this, `main.py` hardcoded `ChromaVectorStore` and reached into its private attributes (`_collection`, `_llm`, `_embed_sem`). `BedrockKnowledgeBaseStore` was in the Protocol but never wired. The factory:
- enforces the `VectorStore` Protocol as the only interface the rest of the app touches
- centralises construction so every caller (lifespan, settings reload) gets identical configuration
- makes backend switches testable via the `:memory:` Qdrant client
- fixes the pre-existing bug that `bedrock_kb` was silently ignored at startup

**Rule:**
- Never construct `ChromaVectorStore`, `QdrantVectorStore`, or `BedrockKnowledgeBaseStore` directly in `main.py`. Always go through `make_vector_store`.
- Never access `vs._collection`, `vs._llm`, `vs._embed_sem`, or `vs._embed_concurrency` from outside `vector_store.py`. Use the Protocol methods (`vs.count()`, `vs.set_embed_provider()`, `vs.embed_health_check()`, etc.).
- `migrate_embeddings(src, dst)` in `backend/vector_migrate.py` is the only code that reads raw vectors out of a store (via `dump_points`/`load_points`). No other code should enumerate raw vectors.

---

## D-21 · Schema changes go through Alembic; existing databases auto-adopt

**Decision:** The database schema is managed exclusively by Alembic migrations under `backend/alembic/versions/`. At startup the FastAPI lifespan calls `backend/db_migrate.run_migrations()`, which brings the schema to `head`. Databases created before Alembic was adopted (built by the former `create_all` + inline `ALTER TABLE` approach, so they have no `alembic_version` table) are detected and **stamped** at the baseline revision before upgrading — they adopt Alembic without re-creating tables or losing data. Migrations run off the event loop in a worker thread because Alembic's env uses `asyncio.run` internally (see D-06).

**Rationale:** Previously the lifespan ran `Base.metadata.create_all` plus a hand-maintained list of `ALTER TABLE` statements wrapped in `try/except pass`, while the Dockerfile separately ran `alembic upgrade head` against an empty `versions/` (a no-op). That meant: schema drift between fresh and upgraded DBs, silent failures, and no migration history. Consolidating on Alembic gives one source of truth, real up/down migrations, and a safe adoption path for existing deployments.

**Rule:**
- Never add `Base.metadata.create_all` or inline `ALTER TABLE` to runtime code. Generate a migration: `alembic revision --autogenerate -m "..."`, review it, commit it.
- Tests create their own schema via `Base.metadata.create_all` in fixtures — that is the **only** sanctioned use of `create_all`, and tests must not call `run_migrations()`.
- `backend/alembic/env.py` must `import backend.orm_models` so every model registers on `Base.metadata` before autogenerate runs.

---

## D-15 · `_paperless_list` handles all entity pagination

**Decision:** The private helper `_paperless_list(entity, extra_fields=None)` in `main.py` handles all pagination for Paperless NGX list endpoints. Functions like `list_tags`, `list_custom_fields`, `list_storage_paths` are one-liners that call this helper.

**Rationale:** Paperless NGX paginates list responses. Before this helper existed, the pagination loop was copy-pasted across three functions. Copy-paste pagination is a common source of subtle bugs (off-by-one page numbers, wrong `next` URL extraction).

**Rule:** Do not write a new pagination loop elsewhere in `main.py`. If a new list endpoint has non-standard response shape, extend `_paperless_list` with an `extra_fields` parameter or add a specific override — do not duplicate the loop.

---

## D-21 · Grooming entity vectors live in SQLite, not a vector collection

**Decision:** Entity descriptions and their embedding vectors are stored as rows on `EntityDescriptionORM` (vector = JSON float list in `embedding_json`), not in a Chroma/Qdrant collection. Dedup similarity is computed app-side (numpy/pure-python cosine over a few hundred vectors); the scan reads an entity's vector straight from SQL and passes it to `VectorStore.query_chunks_by_vector`.

**Rationale:** A vector DB earns its keep through ANN top-k over large, growing sets. The entity set is bounded (hundreds) and dedup needs *all-pairs* similarity — you'd pull every vector into numpy anyway. SQL storage avoids a third per-backend collection (no Chroma/Qdrant/Bedrock variants, no `vector_migrate` wiring, no reset-on-model-switch plumbing), keeps the vector transactionally glued to its description row, and — decisively — keeps embedding-based dedup working on `bedrock_kb`, where there is no app-managed collection to put entity vectors in.

**Rule:** Do not move entity vectors into a vector-store collection. Entity↔document similarity uses `query_chunks_by_vector` (takes a precomputed vector, no embed); entity↔entity similarity stays app-side. Each row records `embed_model`/`embed_dim` so a model switch invalidates entity vectors alongside document vectors (lazy re-embed on next scan/page load). Revisit only if entities ever need ANN search (they won't at library scale).

---

## D-22 · Grooming merges queue re-embeds; chunk-payload staleness is bounded, not silent

**Decision:** Chunk embeddings carry a metadata prefix (D-18), so a document's vector reflects the entities it carried *at embed time*. After a grooming merge reassigns documents, those chunk payloads are stale until re-embedded. We do not re-embed synchronously inside the merge; instead the global `embed_refresh_mode` (immediate / daily / manual, `schedule_reembed()` chokepoint) governs when affected documents are re-embedded. The scan reads an entity's *current* document assignments from Paperless as ground truth (not from chunk payloads), so classification is correct even when payloads lag.

**Rationale:** Re-embedding every reassigned document inline would make a merge of a high-volume entity block for minutes. Deferring via the existing refresh mechanism lets the user pick the cost/freshness trade-off, and daily batching debounces repeated same-day edits. Grounding the scan in live Paperless assignments removes the correctness dependency on payload freshness — staleness costs a little recall, never correctness.

**Rule:** Don't re-embed inline in `merge_entities`. Route post-merge/post-approval re-embeds through `schedule_reembed()`, never a direct `vs.upsert`. Treat chunk-payload entity fields as a *hint* for cohort scoring, never as the authority on what a document currently carries — fetch current assignments for ground truth.

**Embed bookkeeping (extends D-22):** every successful document embed is recorded once, centrally, via `_record_document_embed(doc_id, title, source)` — it (a) stamps `document_tracking.last_embedded_at` (a persistent "vector last refreshed at", distinct from the *transient* `reembed_dirty_since`, which marks a *pending* deferred re-embed and is cleared on flush), and (b) writes an `embedded` audit event with the document title and a `source` label (`system:index` / `approval` / `webhook` / `system:flush` / `drift`). `last_embedded_at` powers the weekly **content-drift reindex** (`content_drift_reindex_days`, default 7, `0`=off): a safety net that re-embeds documents whose Paperless `modified` is newer than `last_embedded_at`, catching content/OCR edits the webhook missed. The webhook stays the primary, real-time path; the comparison against `last_embedded_at` guarantees the drift loop never re-embeds an unchanged document. `last_embedded_at` also feeds **incremental grooming scans**: `_entity_needs_rescan` re-examines an entity when the newest `last_embedded_at` across the corpus (a single global watermark, since each entity is queried against the whole document set) is later than that entity's `last_scanned_at` — so a re-embedded (content-drifted) document re-triggers the entities whose mismatch scores could have shifted, not just entities whose own description changed. Rule: stamp `last_embedded_at` and emit the audit event at **every** `vs.upsert` of a document — call `_record_document_embed` rather than upserting bare; never reuse the transient `reembed_dirty_since` as an "embedded at" timestamp.

---

## D-23 · A rejected grooming suggestion is a permanent answer

**Decision:** Rejecting a grooming suggestion writes one `GroomingDismissalORM` row per action in its `evidence_json`; the scan then skips that (entity, document, action) forever — unless `grooming_resuggest_after_days > 0` (default 0 = never). A rejected `replace` also blocks a future `review` for the same (entity, document) and vice-versa (both mean "keep the incumbent, stop asking"). Clutter-clearing paths that aren't a judgment — Empty Queue and re-analyze swaps — pass `record_dismissals=False` and write no memory.

**Rationale:** Without rejection memory the scan re-suggests the same correction every run and nags forever. With it, reject = "I disagree, don't ask again." Distinguishing deliberate rejection from bulk clutter-clearing prevents an Empty Queue from silently suppressing every pending suggestion for good.

**Rule:** Every new grooming rejection path must decide explicitly whether it records dismissals. Deliberate per-suggestion rejects record; bulk/swap operations pass `record_dismissals=False`. Dedup-pair dismissals use `action="dedup"` with `document_id=0` and are kept separate from scan-action dismissals.

---

## D-24 · Fail closed — refuse to start without `PAPERLESS_URL`

**Decision:** Authentication is enforced only when `PAPERLESS_URL` is set (login validates credentials against Paperless). The app **refuses to start** when it is unset: the lifespan logs a `CRITICAL` message and raises, so uvicorn aborts startup and the process exits. There is no OPEN mode in a running deployment.

**Rationale:** Previously an unset `PAPERLESS_URL` silently put the app in open mode — no login, every page reachable — which is indistinguishable from an auth bypass and is a classic "fails open" footgun. `PAPERLESS_TOKEN` missing is different: auth still works (login uses user credentials), but Paperless operations can't run, so that case starts with a loud warning rather than a hard stop.

**Rule:** Keep the startup guard. `_is_auth_required()` may still return False when `PAPERLESS_URL` is unset (route tests rely on it via ASGITransport, which doesn't run the lifespan) — security in production comes from the lifespan guard, which those tests bypass. Don't reintroduce a silent open mode; if a dev escape hatch is ever needed, gate it behind an explicit opt-in env var, never the absence of config.

---

## D-25 · Entity creation is gated per entity type, at approval time only

**Decision:** Creating a tag / correspondent / document type / storage path in Paperless happens in exactly one place — `_resolve_or_create_entity_ids`, reached only from `ApprovalQueueService.approve()`. Nothing creates entities at analyze time; `_apply_creation_policy` only *filters* an `existing_only` suggestion down to what already exists. The `create_missing` argument threaded into `approve()` / `_patch_paperless()` is either a `bool` (one answer for every type — the human-approve routes, where an explicit edit is authority enough) or a `Mapping[str, bool]` keyed by Paperless endpoint name (`tags`, `correspondents`, `document_types`, `storage_paths`, `custom_fields`). Unattended runs (`auto_apply`) always pass the mapping built by `creation_policy_map(config)`, so each type is gated on its own policy. Custom fields have no policy and are never created unattended. Auto-applied approvals are audited as `change_source="automation"`, not `"human"`.

**Rationale:** `create_missing` used to be a single bool OR-ed across the three policies, so `allow_new` on tags alone silently granted permission to create correspondents, document types *and* storage paths — defeating an explicit `existing_only` on each. Storage paths were worse: they had no policy at all, so they were created unconditionally whenever any other type allowed it. Separately, `bulk_approve` omitted `create_missing` entirely and so silently dropped new entities that single-approve would have created — the same click producing different results depending on which button you used. Auto-apply logging itself as `"human"` made unattended writes indistinguishable from reviewed ones in the audit log, which is precisely the confusion that surfaced this bug.

**Rule:** Never widen `create_missing` to a bare truthy check — resolve it through `_may_create(create_missing, entity_type)` so an absent key means "don't create". Every new entity type that `_patch_paperless` learns to resolve needs its own key in `creation_policy_map` and its own `*_creation_policy` field on `PaperlessIQConfig`; a type with no policy defaults to False, never True. Any new approve() caller must decide explicitly between the bool (human authority) and the mapping (policy authority) — the default is `False`, which creates nothing.
