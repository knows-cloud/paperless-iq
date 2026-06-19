# Discovery — Conversational Document Search

Discovery lets you ask natural-language questions about your document archive and get grounded, cited answers. It's a retrieval-augmented generation (RAG) pipeline with multi-turn conversation support, automatic query reformulation, and long-term memory.

---

## How it works

### Per-question flow

```
Question → (Reformulate if follow-up) → Vector search
         → Retrieve relevant memories
         → LLM call with context + history
         → Answer + source citations
         → Append turn to session
         → (Compress if session is long)
```

1. **Session** — each conversation is a server-side session. Open a new session to start fresh; resume an existing one to continue where you left off.

2. **Query reformulation** — follow-up questions like "when does that expire?" are rewritten into standalone search queries before hitting the vector store, so retrieval stays accurate even deep in a conversation. Only triggered when there is prior conversation history.

3. **Vector search** — the (possibly reformulated) query is embedded and used to find the most relevant document chunks from your archive. The number of results, minimum score, and whether to use hybrid search are all configurable.

4. **Memory retrieval** — relevant facts from past conversations are fetched from the memory store and injected into the system prompt. Only facts above a relevance threshold are included.

5. **LLM call** — the configured LLM receives: the system prompt (instructions + memories + any rolling summary of older turns) + the most recent turns + fresh document context. It generates an answer with inline source citations.

6. **Source citations** — every answer links to the documents it drew from. Citations appear inline in the answer and as a collapsible list below. Deep-links take you directly to the document in Paperless NGX.

---

## Multi-turn conversations

Conversations are unlimited in length. The context window is managed automatically:

- The most recent **8 turns** are included verbatim
- When the window exceeds that, older turns are **compressed into a rolling prose summary** by the LLM — so history is preserved but context stays bounded
- The summary is carried forward and prepended to every subsequent call

This means you can have long, branching conversations without hitting model context limits or paying for exponentially growing context.

---

## Long-term memory

When you close a session, Paperless IQ extracts memorable facts from the full conversation. Examples of what gets stored:

> "Telekom contract ends 2025-08, €30/month"  
> "Home insurance renewed automatically unless cancelled by October"  
> "Annual tax deadline in Germany is 31 July for self-employed"

**Deduplication:** each new fact is compared against existing memories by cosine similarity. If a near-duplicate already exists (distance ≤ 0.08), it updates the existing memory rather than adding a copy.

**Injection:** at the start of every new session, memories relevant to the current query are semantically retrieved and injected into the system prompt. The model starts each conversation with prior context from day one.

**Management:** go to **Settings → Memories** to see every stored fact. You can edit, delete, or clear all memories. A global toggle (`memory_enabled`) enables or disables the entire feature.

---

## Re-ranking

Re-ranking improves retrieval precision by rescoring the top-K retrieved chunks as `(query, passage)` pairs, so the model sees only the most relevant passages.

Three methods are available:

| Method | Description | Recommendation |
|--------|-------------|----------------|
| `llm` | Uses your configured chat LLM to rate passages listwise | Cheapest operationally; no extra deps. Default. |
| `local` | `bge-reranker-v2-m3` cross-encoder runs in-process on CPU | Higher quality; adds latency; saturates CPU on busy boxes. |
| `api` | Amazon Bedrock Rerank API | Good quality; per-call AWS cost; requires Bedrock as LLM provider. |

Re-ranking is **off by default**. Enable it in **Settings → AI Provider → Re-ranking**.

> **Latency warning:** `local` reranking is CPU-bound. If automation is also running (continuous inbox polling), it shares the same CPU and both paths contend. Switch to `llm` rerank if Discovery feels sluggish.

---

## Search quality tuning

All search tuning settings are applied **live** — no re-index required:

| Setting | What it does |
|---------|-------------|
| **Overfetch multiplier** | Fetches `top_n × multiplier` candidates, then re-ranks or scores them. Higher = better recall, more post-processing. |
| **Min Score** | Drops results below this score. ⚠️ The meaning of the score depends on the mode — see below. |
| **Hybrid search** (Qdrant only) | Combines dense semantic vectors with sparse BM25 keyword vectors via RRF fusion. Better recall on exact terms. Requires a re-index to build sparse vectors. |

### Understanding "Min Score"

`search_min_score` is frequently misunderstood because its meaning changes with the active mode:

| Mode | What the score is |
|------|------------------|
| Dense only | `(cosine + 1) / 2` — inflated: unrelated docs score ~0.5, loose matches ~0.6–0.8 |
| Hybrid, no rerank | RRF min-max normalised per query — the top result is **always 1.0**, the worst is 0.0. Relative, not absolute. |
| Reranker on | The reranker's score overrides the above. LLM reranker: `rating/10`. Local cross-encoder: calibrated sigmoid. |

**Practical advice:**
- In hybrid mode, raising `min_score` trims lower-ranked candidates *relative to the query* — it doesn't demand more "absolutely" relevant matches. The top result is always ~1.0 even when nothing in the archive is relevant.
- For genuine relevance gating, enable a reranker rather than chasing a higher `min_score`.
- In dense-only mode, a threshold of `0.45` is already quite permissive (unrelated docs naturally score ~0.5).

See [[Settings#similarity-search-tuning]] for full details.

---

## Embedding refresh and search quality

Discovery search quality depends on your documents being embedded with the **current embedding model**. If you change the model (or chunking settings), existing vectors become inconsistent with new ones. After any such change:

1. Go to **Settings → Access Control**
2. Click **Re-index Vector Store**

If you just changed metadata via the approval queue (not the embedding model), the embedding refresh mode controls when those documents get re-embedded with their updated metadata prefix — see [[Settings#embedding-refresh]].

---

## Accessing Discovery

The **Discovery** page is visible to users with the `can_discover` permission flag. Paperless-NGX admins get it automatically when `sync_ng_admins` is on.
