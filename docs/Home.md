# Paperless IQ

**Paperless IQ adds LLM intelligence to your [Paperless-NGX](https://docs.paperless-ngx.com/) archive — self-hosted, privacy-first, and built for non-English collections.**

It connects to your existing Paperless-NGX instance and layers on:

- **AI metadata analysis** — an LLM reads every document and suggests structured metadata (tags, correspondent, document type, storage path, custom fields)
- **Approval workflow** — every suggestion is reviewed in a queue before anything is written back to Paperless
- **Conversational search** — ask natural-language questions about your archive and get grounded, cited answers
- **Long-term memory** — key facts from past conversations are extracted and injected into future ones
- **Library grooming** — detect and merge duplicate tags/correspondents/types; scan for mis-tagged documents

No cloud dependency required. Runs fully air-gapped with [Ollama](https://ollama.com/) and the local ChromaDB vector store.

---

## Documentation

| Page | What it covers |
|------|---------------|
| [[Getting-Started]] | Prerequisites, Docker installation, first-run checklist |
| [[Document-Analysis]] | How the analysis pipeline works, OCR vs. vision mode, the approval queue |
| [[Discovery]] | Conversational search, RAG pipeline, long-term memory |
| [[Automation]] | Inbox poller, scheduled batch runs, cron expressions |
| [[Grooming]] | Entity descriptions, duplicate detection, mismatch scanning |
| [[LLM-Providers]] | Setup guide for Ollama, Anthropic, OpenAI, and Amazon Bedrock |
| [[Vector-Stores]] | ChromaDB vs. Qdrant vs. Bedrock KB; migration between backends |
| [[Settings]] | Every configurable setting with caveats |
| [[Troubleshooting]] | Common problems and their fixes |
| [[Architecture]] | System overview, module responsibilities, data flows (developer reference) |

---

## Quick comparison with Paperless-NGX v3

| | Paperless-NGX v3 | Paperless IQ |
|---|---|---|
| LLM metadata suggestions | Title, tags, correspondent, doc type | All of those + **custom fields** |
| LLM providers | OpenAI-compatible + Ollama | Ollama · Anthropic · OpenAI · **Amazon Bedrock** |
| Approval workflow | Inline suggestions | Full queue — editable, stackable, batch actions |
| Image-only PDFs | Azure cloud OCR | **On-premise vision analysis** |
| Document search | FAISS | ChromaDB · **Qdrant hybrid search** · Bedrock KB |
| Long-term memory | — | Facts extracted per session, deduplicated, reinjected |
| Re-ranking | — | LLM · local cross-encoder · Amazon Bedrock Rerank |
| Audit log | — | Field-level change history |
| Runs air-gapped | Yes | Yes (Ollama + local ChromaDB) |
