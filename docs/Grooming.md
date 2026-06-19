# Library Grooming

The Library page provides vocabulary maintenance for your Paperless-NGX metadata — finding and merging duplicate tags, correspondents, and document types; generating consistent descriptions; and scanning for documents that are mis-tagged or missing a tag they should have.

Grooming is **off by default** and gated behind a dedicated `can_groom` permission flag.

---

## Enabling grooming

1. Go to **Settings → Library & Grooming**
2. Turn on **Enable grooming**
3. Save

The Library page appears in the navigation for users with the `can_groom` permission. Paperless-NGX admins are automatically granted `can_groom` when `sync_ng_admins` is on.

---

## Descriptions

Every entity (tag, correspondent, document type) can have a plain-language description that defines what it means — for example:

> **Tag: Steuer / Tax**  
> "Documents related to German income tax returns, VAT filings, tax assessments, and correspondence with the Finanzamt."

Descriptions serve two purposes:
1. They give humans a consistent, searchable definition of what the entity covers.
2. They're embedded as vectors and used by the **mismatch scan** to find documents that should (or shouldn't) carry the entity.

### Generating descriptions

In **Library → Descriptions**, select one or more entities and click **Generate descriptions**. Paperless IQ samples a few representative documents (controlled by `grooming_desc_sample_docs`, default 5) and asks the LLM to write a description based on their content.

Generated descriptions are always editable — you can refine the output before saving. Edited descriptions trigger a re-embed of the entity vector automatically.

**LLM cost:** description generation is the **only LLM call in the grooming pipeline**. Everything else (dedup, mismatch scan) is pure vector math using data that already exists.

---

## Deduplication

The **Dedup** tab in Library finds entities that are likely to be duplicates of each other:

- **Name-based duplicates** — fuzzy string similarity above `grooming_dedup_name_threshold` (default 0.85). Catches "Invoice" / "Invoices", "Rechnung" / "Rechnungen".
- **Embedding-based duplicates** — cosine similarity between entity vectors above `grooming_dedup_embed_threshold` (default 0.90). Catches semantically equivalent entities with different names, like "Deutsche Telekom AG" / "Telekom AG", or "Health Insurance" / "Krankenversicherung".

Embedding-based dedup only works for entities that have a generated description (and thus a vector). Name-based dedup is always available.

### Merging duplicates

Select a cluster of duplicates, choose the **canonical** entity (the one to keep), and click **Merge**. Paperless IQ:

1. Calls the Paperless-NGX bulk edit API to replace every occurrence of the "loser" entities with the canonical one
2. Records audit entries for every affected document
3. Schedules the affected documents for re-embedding (respecting your embedding refresh mode)
4. Deletes the loser entities from Paperless

Merges cannot be undone automatically, but the audit log records every changed document so you can identify what was affected.

---

## Mismatch scan

The mismatch scan checks your document archive for:
- Documents that **should** carry a tag/correspondent/type but don't (**add** suggestions)
- Documents that carry a tag/correspondent/type that doesn't match their content (**remove** suggestions)

**Key property: zero LLM, zero new embeddings.** The scan works by taking each entity's stored description vector and querying the document chunk vectors that already exist in your index. No additional API calls are made.

### How the scan decides

For each entity, its description vector is used to find the most similar document chunks (`grooming_scan_top_k`, default 100). Documents are scored by how closely their content matches the entity's description.

**Add suggestion:** a document scores above `grooming_add_threshold` (default 0.80) and is supported by at least `grooming_min_supporting_chunks` chunks (default 2), but doesn't already have the entity.

**Remove suggestion:** a document currently has the entity but scores below `grooming_remove_threshold` (default 0.35), or falls in the bottom `grooming_remove_percentile`% of its entity's cohort.

**Hysteresis:** the add and remove thresholds must be separated (the validator enforces `add > remove`). The gap between them is a "don't touch" zone that prevents the same document from flip-flopping between add and remove suggestions.

### Dry run

Before running a real scan, use **Library → Scan → Dry run** to preview scored candidates without creating any queue suggestions. This lets you tune the thresholds against your actual data and corpus before committing.

### Running the scan

Click **Scan now** for an immediate full scan. Results land in the approval **Queue** page as normal suggestions — approve or reject them like any other suggestion.

**Max suggestions per run** (`grooming_max_suggestions_per_scan`, default 50) caps how many suggestions are created per scan, prioritising the candidates with the highest confidence (largest delta from threshold). This prevents flooding the queue on a first scan of a large archive.

### Scheduled scans

Set a cron expression for `grooming_scan_cron` to run scans automatically. Scheduled scans are **incremental** — only entities that are new, or whose description changed, or whose associated documents were re-embedded since the last scan are re-examined. Manual *Scan now* is always a full scan.

### Dismissals

When you reject a grooming suggestion, the dismissal is recorded permanently — the same suggestion won't resurface on future scans. Set `grooming_resuggest_after_days` to a non-zero value if you want dismissed suggestions to be reconsidered after a period of time.

---

## Backend compatibility

The mismatch scan requires vector similarity queries:

- **Qdrant backend:** full support, including cohort-percentile scoring for tag removal
- **ChromaDB backend:** full support for correspondent and document type cohort scoring; tag cohort scoring falls back to the absolute-threshold rule only
- **Bedrock KB backend:** the scan is disabled on Bedrock KB (no filterable vector queries)

For the most complete scan results, use the Qdrant backend.

---

## Recommended workflow

1. **Start with descriptions** — generate descriptions for your most important entities (high-volume tags, frequently used correspondents)
2. **Run a dry scan** — preview what the scan would suggest and tune `grooming_add_threshold` / `grooming_remove_threshold` to fit your corpus
3. **Run a full scan** — review and process the first batch of suggestions in the Queue
4. **Check dedup** — look for name-based duplicates; merge any found
5. **Iterate** — generate descriptions for more entities, re-scan, adjust thresholds if needed
6. **Set a schedule** — once calibrated, set `grooming_scan_cron` for ongoing maintenance
