# Paperless IQ — Design Decisions

> Decisions are recorded here so future contributors (and future Claude sessions) understand *why* the code looks the way it does. When you change a decision, update the entry — don't delete it.

---

## D-01 · Protocol-based provider abstraction

**Decision:** `LLMProvider` and `VectorStore` are `typing.Protocol` (structural subtyping), not abstract base classes.

**Rationale:** Provider adapters are thin wrappers around external SDKs. Requiring them to inherit from a base class would couple the SDK-facing class hierarchy to our own. Protocols let the adapters look like idiomatic SDK wrappers while still being statically type-checkable as conforming to our interface. New providers need zero extra boilerplate.

**Rule:** New providers must implement all methods of `protocols.LLMProvider`. Do not add convenience helpers to the protocol — put them in the concrete class or a shared utility.

---

## D-02 · Single `_automation_loop` for inbox polling and scheduling

**Decision:** One parameterized `_automation_loop(app, poll_interval, batch_size=None)` replaces two separate loop functions. `batch_size=None` means inbox mode; `batch_size=N` means scheduler mode.

**Rationale:** The two loops were 90% identical — same error handling, same sleep, same session lifecycle. The only difference was which processing strategy they invoked. Merging eliminates the risk of fixing a bug in one loop but not the other.

**Rule:** Do not split this back into separate functions. If the modes diverge significantly in future, introduce a strategy object, not a second loop.

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

## D-15 · `_paperless_list` handles all entity pagination

**Decision:** The private helper `_paperless_list(entity, extra_fields=None)` in `main.py` handles all pagination for Paperless NGX list endpoints. Functions like `list_tags`, `list_custom_fields`, `list_storage_paths` are one-liners that call this helper.

**Rationale:** Paperless NGX paginates list responses. Before this helper existed, the pagination loop was copy-pasted across three functions. Copy-paste pagination is a common source of subtle bugs (off-by-one page numbers, wrong `next` URL extraction).

**Rule:** Do not write a new pagination loop elsewhere in `main.py`. If a new list endpoint has non-standard response shape, extend `_paperless_list` with an `extra_fields` parameter or add a specific override — do not duplicate the loop.
