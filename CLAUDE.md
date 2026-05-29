# Paperless IQ — Claude Context

This file is read automatically by Claude Code at the start of every session.
It provides orientation, points to the full documentation, and lists the rules
that keep the codebase consistent.

---

## Documentation

| File | What it covers |
|------|---------------|
| `docs/ARCHITECTURE.md` | System diagram, all backend modules, frontend tree, three key data flows, async patterns, security |
| `docs/DECISIONS.md` | 19 design decisions (D-01–D-19) — each has Decision, Rationale, and an explicit Rule |


**Always read `docs/DECISIONS.md` before starting a refactor.** The decisions there are not optional style preferences — they reflect real bugs that were fixed by establishing the rule.

---

## Non-negotiable Rules

These are the highest-risk rules; violating them causes data loss, security issues, or silent breakage.

### Session management (D-05)
- Route handlers: `session: AsyncSession = Depends(get_session)` — always
- Background tasks / lifespan: `async with AsyncSessionLocal() as db` — always
- Never mix the two. Never use `AsyncSessionLocal()` in a route handler.

### Async event loop (D-06)
- Use `asyncio.get_running_loop()` for `run_in_executor` calls
- `asyncio.get_event_loop()` is banned — it is deprecated and raises in Python 3.12+

### Credentials
- Credentials are Fernet-encrypted via `backend/providers/encryption.py`. Never log or return plaintext.
- The `__KEEP__` sentinel in Bedrock payloads means "don't overwrite the stored value" — the backend must honour it.
- `PAPERLESS_TOKEN` lives in the environment only; it must never appear in the settings DB.

### Settings save (D-13)
The `handleSubmit` merge order in `SettingsPage.tsx` is intentional:
1. `{...s}` — baseline from server
2. `fd.forEach` — active tab DOM fields
3. Explicit React-state assignments — always win

Do not reorder steps 2 and 3.

---

## Architecture Quick-Reference

```
backend/
  main.py            — all HTTP routes + _automation_loop + background tasks
  analyzer.py        — DocumentAnalyzer pipeline (fetch → prompt → LLM → persist)
  providers/         — 4 LLM adapters (ollama, bedrock, anthropic, openai)
  protocols.py       — LLMProvider + VectorStore as typing.Protocol
  orm_models.py      — SQLAlchemy 2 ORM (7 tables)
  models.py          — Pydantic v2 API models (separate from ORM)
  vector_store.py    — ChromaDB + Bedrock KB implementations
  memory_store.py    — piq_memories ChromaDB collection (long-term memory)

frontend/src/
  pages/SettingsPage.tsx          — ~510-line orchestrator (all state + handleSubmit)
  pages/settings/constants.ts     — METADATA_FIELDS, LLM_MODEL_DEFAULTS, EMBED_MODEL_DEFAULTS
  pages/settings/*.tsx            — 8 tab components (pure display; exceptions: MemoriesTab + AccessControlTab own their CRUD)
  components/MarkdownText.tsx     — markdown + citation renderer (used by DiscoveryPage)
  PermissionsContext.tsx          — React context + usePermissions() hook; populated from /api/piq-users/me
  locales/{en,de,fr,es,it}/translation.json — i18n strings (react-i18next)
```

### Key invariants
- `_fetch_entity_context(document_content="", doc_meta=None)` returns `tuple[str, list[str], list[str], list[str]]` — the prompt string plus the three raw entity lists. Always pass `doc_meta` so the LLM sees current state. Pass the raw lists to `_apply_creation_policy` to avoid double API calls.
- `list_entities_with_map(entity_type)` returns `(list[str], dict[int, str])` — names plus `id→name` map for resolving document metadata integer IDs. Use this instead of `list_entities()` when you need ID resolution.
- OCR text comes from `doc_meta["content"]` (already in the metadata response). Do not call `get_document_ocr_text()` from `analyze()`.
- The Ollama `AsyncClient` is a singleton per `OllamaProvider` instance. Never create one per request.
- The Bedrock boto3 runtime client is cached and auto-invalidated on `ExpiredTokenException` with one retry.
- Any constant shared between `SettingsPage.tsx` and a tab component must live in `settings/constants.ts`, never duplicated.

---

## What NOT to Do

| Don't | Do instead |
|-------|-----------|
| `asyncio.get_event_loop()` | `asyncio.get_running_loop()` |
| `AsyncSessionLocal()` in a route handler | `Depends(get_session)` |
| Define `METADATA_FIELDS` in a tab component | Import from `settings/constants.ts` |
| `useQuery` / `useMutation` in a tab component | Lift to `SettingsPage.tsx` (except MemoriesTab and AccessControlTab CRUD) |
| `import { t } from "../i18n"` | `const { t } = useTranslation()` (react-i18next hook) |
| Add a new UI string in one language | Add to **all 5** `locales/<lang>/translation.json` files; run `npm run check:i18n` |
| Two separate automation loops | `_automation_loop(batch_size=None|N)` |
| Duplicate pagination loop for Paperless NGX lists | `_paperless_list(entity, extra_fields=None)` |
| `get_document_ocr_text()` inside `analyze()` | `doc_meta.get("content", "")` |
| Inherit from `LLMProvider` in a provider adapter | Implement the `typing.Protocol` structurally |

---

## Before You Commit

1. `npx tsc --noEmit` from `frontend/` — zero errors required
2. `uv run pytest` — must not introduce new failures
3. `npm run check:i18n` from `frontend/` — all 5 locale files must have identical key sets
4. If you changed a design decision, update `docs/DECISIONS.md`
5. If you changed the module structure, update `docs/ARCHITECTURE.md`
