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
| `docs/SETTINGS.md` | User-facing reference for every setting + its caveats (score semantics, re-index triggers, reranker cost). Mirrored to the GitHub Wiki by `.github/workflows/wiki-sync.yml`. |


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
  main.py            — all HTTP routes + inbox poller + cron loops + background tasks
  analyzer.py        — DocumentAnalyzer pipeline (fetch → prompt → LLM → persist)
  grooming.py        — GroomingService: dedup, descriptions, entity embedding, mismatch scan
  providers/         — 4 LLM adapters (ollama, bedrock, anthropic, openai)
  protocols.py       — LLMProvider + VectorStore + Reranker as typing.Protocol
  orm_models.py      — SQLAlchemy 2 ORM (9 tables; + entity_descriptions, grooming_dismissals)
  models.py          — Pydantic v2 API models (separate from ORM)
  vector_store.py    — ChromaDB + Qdrant + Bedrock KB implementations (+ shared helpers)
  vector_factory.py  — make_vector_store() — single construction point (see D-20)
  vector_migrate.py  — migrate_embeddings/memories without re-embedding
  db_migrate.py      — run_migrations() at startup: Alembic upgrade + auto-adopt pre-Alembic DBs (see D-21)
  rerankers.py       — LLMReranker + LocalCrossEncoderReranker + BedrockReranker (off by default)
  memory_store.py    — ChromaMemoryStore + QdrantMemoryStore + make_memory_store() factory
  alembic/           — schema migrations (env.py + versions/); run at startup (D-02 sibling)

frontend/src/
  pages/SettingsPage.tsx          — ~510-line orchestrator (all state + handleSubmit)
  pages/settings/constants.ts     — METADATA_FIELDS, LLM_MODEL_DEFAULTS, EMBED_MODEL_DEFAULTS, VECTOR_STORE_BACKENDS, CHUNK_STRATEGIES, RERANK_METHODS, QDRANT_MODES, QDRANT_QUANTIZATIONS
  pages/settings/*.tsx            — 8 tab components (pure display; exceptions: MemoriesTab + AccessControlTab own their CRUD)
  components/MarkdownText.tsx     — markdown + citation renderer (used by DiscoveryPage)
  components/InfoLabel.tsx        — label + Tooltip info icon (§9.5 pattern); use for every settings field that has a tip
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
| Drive scheduled work off `poll_interval` / a `batch_size` flag | Cron job via `_cron_loop(name, get_expr, run_job)` (see D-02) |
| Re-embed inline in a route/merge | `schedule_reembed()` chokepoint (D-22) |
| Put grooming entity vectors in a vector collection | JSON on `EntityDescriptionORM`; `query_chunks_by_vector` for entity→doc (D-21) |
| Duplicate pagination loop for Paperless NGX lists | `_paperless_list(entity, extra_fields=None)` |
| `get_document_ocr_text()` inside `analyze()` | `doc_meta.get("content", "")` |
| Inherit from `LLMProvider` in a provider adapter | Implement the `typing.Protocol` structurally |
| Construct `ChromaVectorStore` / `QdrantVectorStore` in `main.py` | `make_vector_store(config, provider, concurrency, providers)` |
| `vs._collection`, `vs._llm`, `vs._embed_sem` from outside `vector_store.py` | Use Protocol methods: `vs.count()`, `vs.set_embed_provider()`, `vs.embed_health_check()`, `vs.get_indexed_chunk_counts()` |

---

## Before You Commit / Push

Run the lint, typecheck, and test gates locally **before pushing to GitHub** and
fix anything they surface — do not rely on CI to catch it. Note that CI's backend
job historically ran only pip-audit + pytest, so a green CI does **not** prove the
backend is ruff-clean; always run ruff yourself.

1. `npx tsc --noEmit` from `frontend/` — zero errors required
2. `npm run lint` from `frontend/` — eslint (`eslint src`); catches React-hooks/code-quality issues `tsc` misses. Zero errors required (warnings are tolerated but should trend down)
3. `ruff check backend` — zero errors required (config in `pyproject.toml`); use `--fix` for autofixable lints
4. `uv run bandit -rq backend --severity-level medium` — security linter; finds smells ruff's default rules don't (hardcoded secrets, `shell=True`, weak crypto). Zero medium/high findings required. (Plain `bandit -rq backend` also flags 12 intentional Low `try/except/pass` (B110) — those are accepted, hence the `medium` gate.)
5. `uv run pytest` — must not introduce new failures (note: the property suite is currently flaky from cross-test state pollution — a different test may fail per run but each passes in isolation)
6. `npm run check:i18n` from `frontend/` — all 5 locale files must have identical key sets
7. If you changed the DB schema, generate an Alembic migration (`alembic revision --autogenerate`) — never inline `ALTER`/`create_all` (see D-21)
8. If you changed a design decision, update `docs/DECISIONS.md`
9. If you changed the module structure, update `docs/ARCHITECTURE.md`

---

## Release Process

Releases produce a versioned Docker image published to `ghcr.io/knows-cloud/paperless-iq`.
The GitHub Actions workflow (`.github/workflows/release.yml`) fires automatically on a
`vX.Y.Z` tag and pushes three image tags: the full semver, the minor-pinned alias, and `latest`.

### Steps to cut a release

1. **Bump the version** — update `version` in **both** files to the same value:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `frontend/package.json` → `"version": "X.Y.Z"`

2. **Run all pre-commit gates** (see above) and fix anything they surface.

3. **Commit and push to main:**
   ```bash
   git add pyproject.toml frontend/package.json
   git commit -m "chore: bump version to X.Y.Z"
   git push origin main
   ```

4. **Tag and push the tag** — this triggers the release workflow:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

5. **Verify** — the Actions tab on GitHub will show the `Release` workflow building
   the multi-arch image. Once green, `ghcr.io/knows-cloud/paperless-iq:X.Y.Z`
   and `:latest` are live. The version banner in the UI will show "Update available"
   to anyone running an older image within an hour of the release.

### Version source of truth

`pyproject.toml` is the canonical version. `importlib.metadata.version("paperless-iq")`
reads it at runtime via the installed package dist-info. `frontend/package.json` must
be kept in sync manually — never bump one without the other.
CI mirrors the lint/test gates (`.github/workflows/test.yml`): the backend job runs
`ruff check backend`, `bandit -rq backend --severity-level medium`, then pytest; the
frontend job runs `tsc`, `eslint`, `npm run check:i18n`, and `npm audit`.
