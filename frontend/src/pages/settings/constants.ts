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
  bedrock: "amazon.titan-embed-text-v2:0",
  openai:  "text-embedding-3-small",
};

export const VECTOR_STORE_BACKENDS = [
  { value: "local",      labelKey: "aiProvider.vectorStore.local" },
  { value: "qdrant",     labelKey: "aiProvider.vectorStore.qdrant" },
  { value: "bedrock_kb", labelKey: "aiProvider.vectorStore.bedrockKb" },
] as const;

export const CHUNK_STRATEGIES = [
  { value: "char",     labelKey: "aiProvider.search.chunkStrategy.char" },
  { value: "sentence", labelKey: "aiProvider.search.chunkStrategy.sentence" },
] as const;

export const RERANK_METHODS = [
  { value: "llm",   labelKey: "aiProvider.search.rerankMethod.llm" },
  { value: "local", labelKey: "aiProvider.search.rerankMethod.local" },
  { value: "api",   labelKey: "aiProvider.search.rerankMethod.api" },
] as const;

export const QDRANT_MODES = [
  { value: "local", labelKey: "aiProvider.vectorStore.qdrantMode.local" },
  { value: "cloud", labelKey: "aiProvider.vectorStore.qdrantMode.cloud" },
] as const;

export const QDRANT_QUANTIZATIONS = [
  { value: "none",   labelKey: "aiProvider.search.qdrantQuantization.none" },
  { value: "scalar", labelKey: "aiProvider.search.qdrantQuantization.scalar" },
  { value: "binary", labelKey: "aiProvider.search.qdrantQuantization.binary" },
] as const;

export const GROOMING_ENTITY_TYPES = [
  { value: "tag",           labelKey: "grooming.entityType.tag" },
  { value: "correspondent", labelKey: "grooming.entityType.correspondent" },
  { value: "document_type", labelKey: "grooming.entityType.documentType" },
] as const;

export const EMBED_REFRESH_MODES = [
  { value: "immediate", labelKey: "aiProvider.embedRefresh.mode.immediate" },
  { value: "daily",     labelKey: "aiProvider.embedRefresh.mode.daily" },
  { value: "manual",    labelKey: "aiProvider.embedRefresh.mode.manual" },
] as const;

export const METADATA_FIELDS = [
  { key: "title",         label: "Title",                 description: "How should the LLM generate the document title?" },
  { key: "tags",          label: "Tags",                  description: "How should the LLM select or suggest tags?" },
  { key: "correspondent", label: "Correspondent",         description: "How should the LLM identify the correspondent?" },
  { key: "document_type", label: "Document Type",         description: "How should the LLM classify the document type?" },
  { key: "storage_path",  label: "Storage Path / Folder", description: "How should the LLM suggest a storage path?" },
  { key: "created",       label: "Date / Created",        description: "How should the LLM determine the document date?" },
] as const;
