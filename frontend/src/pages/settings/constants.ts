// Shared constants used by SettingsPage (orchestrator) and the tab components.
// A value defined here is the single source of truth — never copy it into a tab.

export const LLM_MODEL_DEFAULTS: Record<string, string> = {
  ollama:    "llama3",
  bedrock:   "anthropic.claude-3-haiku-20240307-v1:0",
  anthropic: "claude-3-5-haiku-20241022",
  openai:    "gpt-4o-mini",
};

export const EMBED_MODEL_DEFAULTS: Record<string, string> = {
  ollama:  "nomic-embed-text",
  bedrock: "amazon.titan-embed-text-v1",
  openai:  "text-embedding-3-small",
};

export const METADATA_FIELDS = [
  { key: "title",         label: "Title",                 description: "How should the LLM generate the document title?" },
  { key: "tags",          label: "Tags",                  description: "How should the LLM select or suggest tags?" },
  { key: "correspondent", label: "Correspondent",         description: "How should the LLM identify the correspondent?" },
  { key: "document_type", label: "Document Type",         description: "How should the LLM classify the document type?" },
  { key: "storage_path",  label: "Storage Path / Folder", description: "How should the LLM suggest a storage path?" },
  { key: "created",       label: "Date / Created",        description: "How should the LLM determine the document date?" },
] as const;
