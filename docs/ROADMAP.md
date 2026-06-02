# Paperless IQ — Roadmap

Forward-looking items to evaluate. Not committed work — these are candidates to scope and
prioritise. Add a short problem statement and any constraints so a future evaluation has context.

---

## Frontend / DX

### Evaluate a proper i18n library (e.g. react-i18next) to replace the custom map
- **Today:** translations live in a hand-maintained `frontend/src/i18n.ts` — a single
  `Record<Lang, Record<string, string>>` covering 5 languages (en/de/fr/es/it), consumed via a
  custom `t(key, params)`. Some components (e.g. `AIProviderTab.tsx`) still hardcode English
  strings, so the map is partial and easy to drift.
- **Problem:** every new string must be added by hand to all 5 blocks; no tooling for missing-key
  detection, pluralisation, interpolation safety, namespacing, or lazy-loading per route.
  Complexity grows with each feature.
- **Evaluate:** `react-i18next` (or `lingui`/`formatjs`) — migrate the existing map to JSON
  resource files, add a typed `t()` with key autocompletion, missing-key linting in CI, and
  namespace splitting. Weigh migration cost (touch every `t()` call site + extract hardcoded
  strings) against the ongoing maintenance savings.
- **Why now-ish:** the Qdrant/vector-tuning work (see local `docs/QDRANT_PLAN.md`) adds a large
  batch of new settings + info-tooltip strings across all 5 languages — a good forcing function
  to decide before the map grows further.

### Improve the mobile experience
- **Problem:** the UI is built for desktop (settings tabs, audit log tables, approval queue,
  discovery). Evaluate how it degrades on small screens and what a good mobile flow looks like.
- **Evaluate:** responsive review of the main pages (Analysis, Queue, Discovery, Settings, Audit);
  Mantine breakpoints / responsive props; touch targets and tooltip behaviour on touch (the new
  `InfoLabel` tooltips must work on tap, not just hover); navigation pattern on narrow viewports;
  possibly a condensed/stacked layout for tables. Decide whether to target responsive-web first or
  consider a PWA install path.

---

## Search / retrieval (in progress)

See the local working doc `docs/QDRANT_PLAN.md` (git-ignored) for the active plan: Qdrant as a
third interchangeable vector backend, Chroma search-quality improvements (HNSW tuning,
configurable overfetch, sentence-aware chunking, optional reranking), and per-backend
similarity-search tuning settings.
