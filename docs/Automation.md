# Automation

Paperless IQ can process documents automatically — either by watching for new arrivals on an inbox tag, or by running analysis on a schedule. Both mechanisms are configured in **Settings → Automation**.

---

## Inbox poller

The inbox poller continuously watches your Paperless-NGX instance for documents that carry your configured **inbox tag**. When a new document appears, it is queued for analysis automatically.

**Prerequisites:**
- Set an **Inbox Tag** in Settings → Connection. This is the Paperless-NGX tag that marks "needs processing" — commonly named `Inbox`, `To Review`, or similar.
- Turn on **Automation enabled** in Settings → Automation.

**How it works:**
1. Every `poll_interval_seconds` (default: 10 s), the poller calls the Paperless-NGX API and fetches documents with the inbox tag that haven't been processed yet.
2. Each new document is analysed and a suggestion is created in the queue.
3. If **Auto-apply** is enabled, the suggestion is applied to Paperless immediately without manual review. The inbox tag is removed from the document after successful processing.

The poller only processes documents it hasn't seen before. Already-processed documents are tracked in an internal database and won't be re-analysed by the poller (though you can always trigger manual re-analysis from the Manual page).

---

## Scheduled batch analysis

For documents that already exist in your archive (uploaded before automation was enabled, or not tagged with the inbox tag), you can run scheduled batch analysis.

**How it works:**
- Set a **cron expression** in Settings → Automation → Schedule.
- When the schedule fires, Paperless IQ fetches up to `batch_size` unanalysed documents from Paperless and queues them for analysis.
- The batch job and the inbox poller use the same analysis pipeline — the same LLM call, the same queue, the same creation policies.

The inbox poller and the scheduled batch job run **independently** — you can have both on at the same time.

---

## Cron expressions

Both the batch schedule and the grooming scan schedule use standard 5-field cron expressions (croniter):

```
┌──────── minute (0–59)
│  ┌───── hour (0–23)
│  │  ┌── day of month (1–31)
│  │  │  ┌─ month (1–12)
│  │  │  │  ┌── day of week (0–7, 0=Sun)
│  │  │  │  │
*  *  *  *  *
```

**Common examples:**

| Expression | Meaning |
|-----------|---------|
| `0 2 * * *` | Daily at 2:00 AM |
| `0 3 * * 0` | Every Sunday at 3:00 AM |
| `0 */6 * * *` | Every 6 hours |
| `30 1 * * 1-5` | Weekdays at 1:30 AM |

**Notes:**
- Invalid expressions are rejected on save (422 error) — the field won't accept typos.
- Schedule changes take effect within ~30 seconds without a restart.
- Leave empty to disable the schedule.

---

## The webhook

Paperless-NGX can call Paperless IQ's webhook whenever a document is added or updated. This is an alternative (and often faster) trigger than polling.

**Setup:**
1. Go to **Settings → Connection**
2. Click **Register webhook** — this tells Paperless-NGX to send events to Paperless IQ
3. New documents will trigger analysis immediately rather than waiting for the next poll

The webhook is secured with a shared secret that Paperless IQ auto-generates. You can see it in Settings → Connection and rotate it if needed.

If the webhook is registered, document updates (metadata changes from Paperless directly) also trigger a re-embed of the affected document, keeping the vector store in sync.

---

## Auto-apply

When **Auto-apply** is on, every suggestion produced by the inbox poller or batch job is written directly back to Paperless-NGX without any human review step. Suggestions still appear in the Queue page, but they arrive pre-approved.

**Recommended approach:** start with auto-apply **off** while you tune your prompts and creation policies. Once the suggestions look consistently good for your archive, enable auto-apply for hands-off operation.

**Partial automation:** you can enable auto-apply for some document types only by setting per-document-type analysis modes and using the Manual page for exceptions.

---

## Embedding refresh after automation

When a suggestion is approved (or auto-applied), the document's metadata changes. Since Paperless IQ embeds a metadata prefix with each chunk, those vectors become slightly stale after a metadata update.

The **embedding refresh mode** controls when re-embedding happens:

| Mode | Behaviour |
|------|-----------|
| `immediate` (default) | Re-embed immediately after every approval |
| `daily` | Mark the document dirty and re-embed all dirty docs once per day at `embed_refresh_hour` (UTC) |
| `manual` | Mark dirty and wait for the user to flush via Processing → Flush pending |

`daily` and `manual` are useful for metered embedding APIs or large grooming merges — they batch multiple changes into a single re-embed per document. See [[Settings#embedding-refresh]] for full details.

---

## Access control

Automation controls are visible in **Settings → Automation** to users with the `can_settings` permission. The automation state (running / paused) is visible on the **Processing** page to all users with `can_view_queue`.
