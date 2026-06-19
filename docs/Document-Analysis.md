# Document Analysis

Paperless IQ analyses documents from your Paperless-NGX archive and produces structured metadata suggestions: title, tags, correspondent, document type, storage path, and any custom fields. Nothing is written to Paperless automatically unless you enable auto-apply — every suggestion lands in the **approval queue** first.

---

## How the pipeline works

```
Document → Fetch OCR / render pages → Smart entity pre-selection
         → Assemble prompt → LLM → Parse JSON
         → Apply creation policy → Queue suggestion
```

1. **Fetch** — the backend fetches the document's metadata from Paperless NGX in a single API call. The OCR text is already included in the response (`content` field) — no separate content request is made.

2. **Smart entity pre-selection** — instead of sending your full list of tags, correspondents, and document types to the LLM (which can be hundreds of items), the vector store is queried for the most similar previously-indexed documents. Only the entities that appear on those similar documents are included in the prompt, keeping the LLM context tight and suggestions accurate. Controlled by `similar_docs_count` and `frequency_fallback_count` in Settings.

3. **Prompt assembly** — the OCR text (or vision transcript), the entity shortlist, per-field instructions, and any per-document-type prompt overrides are assembled into a single prompt.

4. **LLM call** — the prompt is sent to your configured LLM provider. The LLM returns structured JSON with suggested values for each metadata field.

5. **Creation policy check** — if the LLM suggests a value that doesn't exist in Paperless (a new tag, a new correspondent), the configured creation policy decides whether it's allowed (`allow_new`) or silently dropped (`existing_only`). Suggested-but-not-allowed values are flagged visually in the queue.

6. **Queue** — the suggestion is stored in SQLite and appears in the **Queue** page. If auto-apply is on, it is applied immediately to Paperless and no manual review is needed.

---

## OCR mode vs. Vision mode

### OCR mode (default)

The document's existing OCR text from Paperless NGX is sent to the LLM. This is fast and cheap — no additional API calls for document rendering.

OCR mode works well when Paperless has already produced good text for the document. It fails (or produces poor suggestions) on:
- Image-only PDFs (scanned documents where Tesseract produced empty or garbled text)
- Handwritten documents
- Documents where the embedded text is corrupted

### Vision mode

For documents where OCR text is unreliable, Paperless IQ can render each page as an image and send it to a vision-capable LLM. The pipeline has two phases:

1. **Transcription** — the vision LLM reads the rendered pages and produces clean plain text
2. **Analysis** — that text is fed through the standard analysis pipeline (smart entity selection, prompt assembly, LLM call)

Vision mode requires a vision-capable model: multimodal Ollama models, Claude 3/4 via Anthropic or Bedrock, GPT-4o via OpenAI.

**Trigger:** In the **Manual** page, every document has an option to force vision analysis regardless of the default mode. The default mode (OCR or vision) can be set globally, or overridden per document type in Settings → Metadata Rules.

**Cost warning:** when a document exceeds `vision_max_pages_warning` pages (default 5), the UI shows a confirmation dialog before proceeding, because multi-page vision calls can be expensive.

**Tuning:** rendering DPI and pages per LLM call are configurable in Settings.

---

## The approval queue

The **Queue** page lists every pending suggestion. For each document you can:

- **See the suggested values** side-by-side with the current values in Paperless
- **Edit any field inline** before approving (title, tags, correspondent, document type, storage path, custom fields)
- **Keep existing tags** — merge the suggested tags with the document's current tags rather than replacing them
- **Approve** — writes the suggestion back to Paperless NGX via its API and records an audit entry
- **Reject** — dismisses the suggestion without touching Paperless

**Suggestion stacking:** if the same document is analysed more than once, all suggestions are shown as tabs ordered chronologically (newest first and active). Changed fields are highlighted so you can see exactly what differs between runs. Approving one tab supersedes the others.

**Batch actions:** select multiple suggestions and approve or reject them in one click.

---

## Auto-apply

When **Auto-apply** is enabled (Settings → Automation), the approval queue is bypassed — suggestions are applied to Paperless immediately after analysis. The queue still records them for audit purposes but they arrive pre-approved.

Use auto-apply only after validating analysis quality on a sample of your documents. A mistake with auto-apply on can update metadata on many documents before you notice.

---

## Per-field instructions

In **Settings → Prompts & Fields**, you can give the LLM explicit instructions for each metadata field. For example:

- `Correspondent`: "Always use the full legal company name, not abbreviations. 'Deutsche Telekom AG' not 'Telekom'."
- `Storage Path`: "Use format `invoices/YYYY/MM-correspondent-title`"
- Custom field `Contract End Date`: "Extract the contract termination date, not the signing date. Format as YYYY-MM-DD."

These instructions are appended to the prompt for every analysis. Per-document-type prompt templates let you go further — different instructions for invoices vs. contracts vs. letters.

---

## Creation policies

Three policies control what happens when the LLM suggests a value that doesn't yet exist in Paperless:

| Policy | Behaviour |
|--------|-----------|
| `existing_only` (default) | The suggested value is discarded. The field is left blank in the suggestion. |
| `allow_new` | The value is kept in the suggestion. On approval, Paperless IQ creates the tag / correspondent / document type in Paperless before writing the metadata. |

Set per entity type in **Settings → Metadata Rules**. Suggested-but-new values are visually flagged in the queue (yellow) so you can review them before approving.

---

## Manual analysis

The **Manual** page lets you trigger analysis on any document in your archive — useful for:
- Documents that arrived before automation was enabled
- Re-analysing documents after changing the prompt or LLM model
- Documents where the automatic analysis produced a poor result

You can filter by tag to narrow the list, select multiple documents, and queue them for analysis in bulk. Per-document overrides for provider, model, and analysis mode are available when analysing a single document.

---

## Audit log

Every metadata write is recorded in the **Audit** page:
- Old value → new value for each changed field
- Whether the change came from a manual approval, auto-apply, or a webhook trigger
- Linked to the originating suggestion

Audit entries are pruned after `audit_retention_days` (default 180 days, minimum 30).
