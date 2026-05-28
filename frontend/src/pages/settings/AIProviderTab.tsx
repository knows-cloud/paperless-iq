import { Select, TextInput, PasswordInput, NumberInput, Paper, Text, Divider, Stack, Badge } from "@mantine/core";
import { LLM_MODEL_DEFAULTS, EMBED_MODEL_DEFAULTS } from "./constants";

interface Props {
  s: Record<string, unknown>;
  selectedProvider: string;
  setSelectedProvider: (v: string) => void;
  selectedEmbedProvider: string;
  setSelectedEmbedProvider: (v: string) => void;
  llmModel: string;
  setLlmModel: (v: string) => void;
  embedModel: string;
  setEmbedModel: (v: string) => void;
  ollamaUrl: string;
  setOllamaUrl: (v: string) => void;
  bedrockRegion: string;
  setBedrockRegion: (v: string) => void;
  bedrockAccessKeyId: string;
  setBedrockAccessKeyId: (v: string) => void;
  bedrockSecretKey: string;
  setBedrockSecretKey: (v: string) => void;
  bedrockSessionToken: string;
  setBedrockSessionToken: (v: string) => void;
}

export function AIProviderTab({
  s,
  selectedProvider, setSelectedProvider,
  selectedEmbedProvider, setSelectedEmbedProvider,
  llmModel, setLlmModel,
  embedModel, setEmbedModel,
  ollamaUrl, setOllamaUrl,
  bedrockRegion, setBedrockRegion,
  bedrockAccessKeyId, setBedrockAccessKeyId,
  bedrockSecretKey, setBedrockSecretKey,
  bedrockSessionToken, setBedrockSessionToken,
}: Props) {
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">Language Model (LLM)</Text>
        <Stack gap="md">
          <Select
            label="Provider"
            name="llm_provider"
            value={selectedProvider}
            onChange={v => {
              const p = v ?? "ollama";
              setSelectedProvider(p);
              const stored = localStorage.getItem(`piq_llm_model_${p}`);
              setLlmModel(stored ?? LLM_MODEL_DEFAULTS[p] ?? "");
            }}
            data={[
              { value: "bedrock", label: "Amazon Bedrock" },
              { value: "anthropic", label: "Anthropic" },
              { value: "ollama", label: "Ollama" },
              { value: "openai", label: "OpenAI" },
            ]}
          />
          <TextInput
            label="Model"
            name="llm_model"
            value={llmModel}
            onChange={e => {
              setLlmModel(e.target.value);
              localStorage.setItem(`piq_llm_model_${selectedProvider}`, e.target.value);
            }}
            placeholder={
              selectedProvider === "ollama"  ? "e.g. llama3, mistral, gemma2" :
              selectedProvider === "bedrock" ? "e.g. anthropic.claude-3-haiku-20240307-v1:0" :
                                               "e.g. claude-3-5-haiku-20241022, gpt-4o-mini"
            }
          />

          {selectedProvider === "ollama" && (
            <TextInput
              label="Ollama Server URL"
              value={ollamaUrl}
              onChange={e => setOllamaUrl(e.target.value)}
              placeholder="http://localhost:11434"
              description="The URL of your Ollama instance. No API key needed."
            />
          )}

          {selectedProvider === "bedrock" && (
            <>
              <TextInput
                label="AWS Region"
                value={bedrockRegion}
                onChange={e => setBedrockRegion(e.target.value)}
                placeholder="e.g. eu-central-1, us-east-1"
              />
              <TextInput
                label="Access Key ID"
                value={bedrockAccessKeyId}
                onChange={e => setBedrockAccessKeyId(e.target.value)}
                placeholder="AKIA..."
                autoComplete="off"
              />
              <PasswordInput
                label={
                  <span>
                    Secret Access Key{" "}
                    {Boolean(s?.bedrock_has_secret) && (
                      <Badge size="xs" color="teal" variant="light" ml={6}>✓ stored</Badge>
                    )}
                  </span>
                }
                value={bedrockSecretKey}
                onChange={e => setBedrockSecretKey(e.target.value)}
                placeholder={s?.bedrock_has_secret ? "Leave blank to keep existing" : "Enter secret access key"}
              />
              <PasswordInput
                label={
                  <span>
                    Session Token{" "}
                    <Text span size="xs" c="dimmed">(optional — only for temporary STS credentials)</Text>
                    {Boolean(s?.bedrock_has_session_token) && (
                      <Badge size="xs" color="teal" variant="light" ml={6}>✓ stored</Badge>
                    )}
                  </span>
                }
                value={bedrockSessionToken}
                onChange={e => setBedrockSessionToken(e.target.value)}
                placeholder={s?.bedrock_has_session_token ? "Leave blank to keep existing" : "Leave blank for permanent IAM user keys"}
                description="Permanent IAM access keys don't need this. Required only when keys came from AWS SSO / sts assume-role / sts get-session-token. Encrypted at rest using SECRET_KEY."
              />
            </>
          )}

          {selectedProvider !== "ollama" && selectedProvider !== "bedrock" && (
            <PasswordInput
              label="API Key"
              name="llm_credentials"
              defaultValue=""
              placeholder="Leave blank to keep current"
              description="Encrypted at rest. Leave empty to keep existing credentials."
            />
          )}

          <Divider label="Context" labelPosition="left" />
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label="Context Window (characters)"
              name="context_window_chars"
              min={1000}
              defaultValue={Number(s.context_window_chars ?? 128000)}
              description="Maximum characters sent to the LLM. Default: 128,000."
              style={{ flex: 2, minWidth: "200px" }}
            />
            <Select
              label="Default Analysis Mode"
              name="default_analysis_mode"
              defaultValue={String(s.default_analysis_mode ?? "ocr")}
              data={[
                { value: "ocr", label: "OCR Text" },
                { value: "full_document", label: "Full Document (Vision)" },
              ]}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label="Vision Page Warning Threshold"
              name="vision_max_pages_warning"
              min={1}
              defaultValue={Number(s.vision_max_pages_warning ?? 5)}
              description="Show a cost warning when a document has more pages than this before vision analysis."
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Embeddings</Text>
        <Text size="sm" c="dimmed" mb="md">
          Used for semantic search and smart entity selection. Can use a different provider than the LLM.
        </Text>
        <Stack gap="md">
          <Select
            label="Embedding Provider"
            name="embed_provider"
            value={selectedEmbedProvider}
            onChange={v => {
              const p = v ?? "ollama";
              setSelectedEmbedProvider(p);
              const stored = localStorage.getItem(`piq_embed_model_${p}`);
              setEmbedModel(stored ?? EMBED_MODEL_DEFAULTS[p] ?? "");
            }}
            description="Provider used to generate document embeddings."
            data={[
              { value: "ollama", label: "Ollama" },
              { value: "bedrock", label: "Amazon Bedrock (Titan / Cohere)" },
              { value: "openai", label: "OpenAI" },
            ]}
          />

          {selectedEmbedProvider === "ollama" && (
            <>
              <Text size="sm" p="sm" style={{ background: "var(--mantine-color-teal-0)", borderRadius: "var(--mantine-radius-sm)" }}>
                Make sure the model is pulled: <code>ollama pull nomic-embed-text</code>. Embedding models are small and fast — independent of the LLM.
              </Text>
              <TextInput
                label="Embedding Model"
                name="embedding_model"
                value={embedModel}
                onChange={e => {
                  setEmbedModel(e.target.value);
                  localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
                }}
                placeholder="nomic-embed-text"
                description="Ollama model used for document embeddings. Must support the embed API."
              />
              {selectedProvider !== "ollama" && (
                <TextInput
                  label="Ollama Server URL (for embeddings)"
                  value={ollamaUrl}
                  onChange={e => setOllamaUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                  description="URL of your Ollama instance for embedding generation."
                />
              )}
            </>
          )}

          {selectedEmbedProvider === "bedrock" && (
            <Select
              label="Bedrock Embedding Model"
              name="embedding_model"
              value={embedModel || "amazon.titan-embed-text-v1"}
              onChange={v => {
                setEmbedModel(v ?? "amazon.titan-embed-text-v1");
                localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, v ?? "");
              }}
              description="Uses the same AWS credentials as your Bedrock LLM. Changing the model requires re-indexing — use Re-index on the Processing page after saving."
              data={[
                { value: "amazon.titan-embed-text-v2:0", label: "Titan Embed Text v2 — 1024-dim, better quality (recommended)" },
                { value: "cohere.embed-multilingual-v3", label: "Cohere Embed Multilingual v3 — best for non-English documents" },
                { value: "cohere.embed-english-v3", label: "Cohere Embed English v3 — best for English-only archives" },
                { value: "amazon.titan-embed-text-v1", label: "Titan Embed Text v1 — 1536-dim, legacy (keep if already indexed)" },
              ]}
            />
          )}

          {selectedEmbedProvider === "openai" && (
            <Text size="sm" c="dimmed" p="sm" style={{ background: "var(--mantine-color-teal-0)", borderRadius: "var(--mantine-radius-sm)" }}>
              Embeddings are generated using OpenAI's <code>text-embedding-3-small</code> (1536-dimensional vectors).
              Uses the same API key as your OpenAI LLM.
            </Text>
          )}
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">Vector Store</Text>
        <Stack gap="md">
          <Select
            label="Backend"
            name="vector_store_backend"
            defaultValue={String(s.vector_store_backend ?? "local")}
            data={[
              { value: "local", label: "Local (ChromaDB)" },
              { value: "bedrock_kb", label: "Amazon Bedrock Knowledge Base" },
            ]}
          />
          <TextInput
            label="Bedrock Knowledge Base ID"
            name="bedrock_kb_id"
            defaultValue={String(s.bedrock_kb_id ?? "")}
            placeholder="Only needed for Bedrock KB backend"
          />
        </Stack>
      </Paper>
    </Stack>
  );
}
