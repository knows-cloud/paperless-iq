# Paperless IQ — Technical Architecture

> This document is the authoritative reference for the system structure, module responsibilities, and key data flows. Update it when you add, remove, or significantly alter a subsystem.

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        Browser (SPA)                              │
│   React 18 · TypeScript · Vite · TanStack Query · Inline CSS     │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP/REST + Server-Sent Events (SSE)
┌────────────────────────────▼─────────────────────────────────────┐
│                      FastAPI backend                               │
│            Python 3.12 · SQLAlchemy 2 async · SQLite              │
│                                                                    │
│  ┌───────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │  DocumentAnalyzer│  │ Discovery / RAG  │  │  Automation Engine │  │
│  │  (analyzer.py) │  │  (main.py routes)│  │  (_automation_loop)│  │
│  └───────┬───────┘  └────────┬────────┘  └──────────┬─────────┘  │
│          │                   │                        │             │
│  ┌───────▼───────────────────▼────────────────────────▼─────────┐ │
│  │                   LLM Provider Layer                           │ │
│  │    protocols.LLMProvider · provider_registry · 4 adapters     │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                  Storage Layer                               │  │
│  │  SQLite (ORM)  ·  ChromaDB (persistent on disk)             │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                     Paperless NGX                                  │
│              REST API (token-authenticated)                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend Modules

### `backend/main.py` (~2 200 lines)
The FastAPI application entry-point. Contains:
- All HTTP route handlers (`@app.get/post/put/delete`)
- `lifespan()` — startup/shutdown: DB init, background task launch, settings seed
- `_automation_loop(batch_size=None|N)` — unified background loop (inbox monitor or scheduler)
- `_background_index(doc_id)` — background task to embed a document after it is processed
- `_extract_memories_from_session(session_id)` — extracts and deduplicates memories on session close
- Helper utilities: `_paperless_list()`, `_apply_settings()`, auth middleware

**Session management rule:**
- HTTP route handlers receive `session: AsyncSession = Depends(get_session)` — the session lifecycle is managed by FastAPI's dependency injection.
- Background tasks and lifespan code use `async with AsyncSessionLocal() as db` — they run outside a request context.
- Never use `AsyncSessionLocal()` inside a route handler and never use `Depends(get_session)` in a background task.

### `backend/analyzer.py` (~590 lines)
`DocumentAnalyzer` — the core intelligence pipeline.

Key responsibilities:
- `analyze(document_id)` — full pipeline: fetch metadata, build prompt, call LLM, parse JSON, apply creation policy, persist suggestion
- `_fetch_entity_context()` → `tuple[str, list[str], list[str], list[str]]` — fetches all tags / correspondents / document types from Paperless NGX in parallel, returns both the formatted prompt string and the raw lists (to avoid duplicate API calls in `_apply_creation_policy`)
- `_build_field_instructions()` — assembles per-field instruction text from `config.field_descriptions`
- `_apply_creation_policy(suggestion, …, all_tags, all_correspondents, all_document_types)` — accepts pre-fetched entity lists as keyword args to skip redundant API calls; falls back to fetching individually if not provided

**OCR vs full-document mode:**
OCR text is already included in the Paperless NGX `GET /api/documents/{id}/` metadata response (`content` field). The analyzer reuses `doc_meta["content"]` directly — it does **not** make a second `GET /api/documents/{id}/content/` call.

### `backend/providers/`
Four provider adapters that all implement `protocols.LLMProvider`:

| Module | Provider | Notes |
|--------|----------|-------|
| `ollama_provider.py` | Ollama | Single `AsyncClient` instance (singleton per provider object); request queue via `ollama_queue.py` |
| `bedrock.py` | Amazon Bedrock | Lazy boto3 runtime client; cached until `ExpiredTokenException`, then invalidated + retried once |
| `anthropic_provider.py` | Anthropic | Thin wrapper around `anthropic.AsyncAnthropic` |
| `openai_provider.py` | OpenAI | Thin wrapper around `openai.AsyncOpenAI` |

All blocking (boto3) calls use `loop.run_in_executor(None, fn)` with `asyncio.get_running_loop()`.

### `backend/protocols.py`
`LLMProvider` and `VectorStore` as `typing.Protocol` (structural subtyping). Implementations are not required to inherit from these — they just need to match the method signatures. This keeps the adapters decoupled.

### `backend/vector_store.py` (~420 lines)
`ChromaVectorStore` and `BedrockKBVectorStore` both implement `VectorStore`. ChromaDB runs locally on disk (`/data/chroma`). Two collections:
- `paperless_iq_chunks` — document passages with `doc_id`, `title`, `url` metadata
- `piq_memories` — long-term memory facts with `memory_id` metadata

### `backend/memory_store.py`
Manages the `piq_memories` ChromaDB collection. Key method: `find_similar(fact) → str | None` — returns the ID of an existing memory with cosine similarity ≥ 0.92 (deduplication threshold), or `None` if the fact is new.

### `backend/orm_models.py`
SQLAlchemy 2 ORM declarations. Six tables:

| Table | Purpose |
|-------|---------|
| `suggestions` | Pending / approved / rejected metadata suggestions |
| `audit_log` | Field-level change history |
| `document_tracking` | Documents seen by the inbox monitor (first seen, last analyzed, embedding status) |
| `settings` | Single-row JSON blob for `PaperlessIQConfig` |
| `conversation_sessions` | Discovery chat sessions (verbatim turns + rolling summary) |
| `user_memories` | Long-term memory facts |

### `backend/models.py`
Pydantic v2 models. Separate from ORM models — the API serialises Pydantic, persistence uses ORM. Mapping is explicit (`from_attributes=True`).

### `backend/settings_service.py`
Loads `PaperlessIQConfig` from the database; falls back to `PIQ_*` env vars on first run. After the first UI save the database value is canonical. Credentials are Fernet-encrypted before storage (via `providers/encryption.py` + `SECRET_KEY`).

### `backend/approval_queue.py` / `backend/inbox_monitor.py`
`ApprovalQueue` — methods to list, approve, reject, and bulk-action suggestions, handling entity creation when `allow_new` policies are active.
`InboxMonitor` — fetches documents tagged with the inbox tag that haven't been seen before.

---

## 3. Frontend Structure

```
frontend/src/
├── api.ts                   # All API calls (single module, typed return values)
├── i18n.ts                  # Translation lookup (t("key"))
├── App.tsx                  # Router, layout, nav sidebar
├── ThemeProvider.tsx         # Injects CSS variables from settings into :root
├── main.tsx                 # React root
│
├── components/
│   └── MarkdownText.tsx      # renderInline + MarkdownText component + Source type
│                             # Used by DiscoveryPage for LLM answer rendering
│
├── pages/
│   ├── LoginPage.tsx
│   ├── ManualPage.tsx        # On-demand document analysis
│   ├── QueuePage.tsx         # Approval queue
│   ├── ProcessingPage.tsx    # Re-index / status panel
│   ├── AuditPage.tsx
│   ├── DiscoveryPage.tsx     # RAG chat interface
│   ├── SettingsPage.tsx      # ~470-line orchestrator — all state + handleSubmit
│   └── settings/
│       ├── constants.ts      # METADATA_FIELDS · LLM_MODEL_DEFAULTS · EMBED_MODEL_DEFAULTS
│       ├── ConnectionTab.tsx
│       ├── AIProviderTab.tsx
│       ├── PromptsFieldsTab.tsx
│       ├── MetadataRulesTab.tsx
│       ├── AutomationTab.tsx
│       ├── AppearanceTab.tsx
│       └── MemoriesTab.tsx
│
├── AutocompleteInput.tsx     # Reusable tag autocomplete
├── CfNameEditor.tsx          # Custom field name inline editor
├── StatusPanel.tsx           # Background task status widget
└── TagInput.tsx              # Tag chip input
```

### SettingsPage pattern (orchestrator + tab components)

`SettingsPage.tsx` owns **all** state, effects, mutations, and the `handleSubmit` form handler. It renders the active tab component as a pure display tree, passing values and setters as props.

Tab components (`settings/*.tsx`):
- Are **pure display** — no `useQuery`, no `useMutation`, no API calls (exception: `MemoriesTab` owns its fire-and-forget CRUD mutations because lifting them would require 4+ extra props for trivial state)
- Receive props via explicit TypeScript `interface Props`
- **Never** define constants that are also needed by `SettingsPage` — put shared constants in `constants.ts`

### State management
- TanStack Query for server state (settings, tags, custom fields, logos)
- `useState` for all form/UI state that needs to survive tab switches (the form is a single `<form>` element wrapping all 7 tab views; switching tabs shows/hides — not unmounts — the content)
- No Redux or Zustand — the query cache + local component state is sufficient

---

## 4. Data Flows

### 4.1 Metadata analysis pipeline
```
InboxMonitor.poll()
  └─► DocumentAnalyzer.analyze(doc_id)
        ├── GET /api/documents/{id}/          # metadata + content (single call)
        ├── _fetch_entity_context()           # parallel: tags, correspondents, types
        │     └── returns (ctx_str, tags[], correspondents[], doc_types[])
        ├── _build_field_instructions()
        ├── LLMProvider.complete(prompt)
        ├── parse JSON → MetadataSuggestion
        ├── _apply_creation_policy(…, all_tags=tags, …)   # no extra API calls
        └── INSERT suggestions row
              └─► shown in QueuePage
```

On approval:
```
ApprovalQueue.approve(suggestion_id)
  ├── PATCH /api/documents/{id}/   # write metadata to Paperless NGX
  ├── INSERT audit_log rows (one per changed field)
  └── UPDATE suggestions.status = "approved"
```

### 4.2 Discovery conversation
```
POST /api/discovery/chat  {question, session_id?}
  ├── get_or_create ConversationSession
  ├── if history: LLM reformulates question → standalone search query
  ├── MemoryStore.find_relevant(query) → injected into system prompt
  ├── VectorStore.query(query, top_n=8) → source chunks
  ├── LLMProvider.chat([system, …history_turns, user])
  ├── append new turn to session.turns
  ├── if len(turns) > 8: compress oldest turns → session.summary
  └── return {answer, sources[]}

POST /api/discovery/close  {session_id}
  ├── LLM extracts facts from full conversation
  └── for each fact:
        ├── MemoryStore.find_similar(fact) → existing_id or None
        ├── if duplicate: UPDATE user_memories + chroma upsert
        └── if new: INSERT user_memories + chroma upsert
```

### 4.3 Settings save (frontend → backend)
The form collects state from all 7 tabs into a single `values` dict:
1. Starts from the current full server settings (`{...s}`) so hidden-tab values are not lost
2. Overlays `FormData` fields present in the active tab's DOM
3. Merges React-state-owned values (theme, prompt text, field descriptions, Bedrock fields) explicitly
4. Sends `PUT /api/settings` with the merged dict

This means every save is a full replacement — the backend receives the complete config, not a patch.

---

## 5. Async Patterns

- All `asyncio.get_event_loop()` calls have been replaced with `asyncio.get_running_loop()`. Do not re-introduce `get_event_loop()`.
- Blocking calls (boto3, heavy crypto) use `await loop.run_in_executor(None, fn)`.
- The Ollama `AsyncClient` is a singleton per `OllamaProvider` instance — never create a new client per request.
- The Bedrock boto3 runtime client is cached on the provider instance and invalidated on `ExpiredTokenException` (with one automatic retry).

---

## 6. Security

- Credentials (API keys, Bedrock secret) are Fernet-encrypted with `SECRET_KEY` before being stored in SQLite. The plaintext never appears in logs.
- Bedrock `__KEEP__` sentinel: the frontend sends `"__KEEP__"` for secret sub-fields that weren't changed; the backend recognises this and retains the existing encrypted value.
- Optional HTTP basic auth (`AUTH_USER` / `AUTH_PASSWORD` env vars). When disabled (default), all routes are open — intended for single-user LAN deployments.
- `PAPERLESS_TOKEN` is stored in the environment only (not in the settings DB) and is injected at request time.
