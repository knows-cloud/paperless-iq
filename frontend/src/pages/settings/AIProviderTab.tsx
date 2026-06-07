import { Select, TextInput, PasswordInput, NumberInput, Paper, Text, Divider, Stack, Badge, Switch, Checkbox } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { InfoLabel } from "../../components/InfoLabel";
import {
  LLM_MODEL_DEFAULTS,
  EMBED_MODEL_DEFAULTS,
  VECTOR_STORE_BACKENDS,
  CHUNK_STRATEGIES,
  RERANK_METHODS,
  QDRANT_MODES,
  QDRANT_QUANTIZATIONS,
} from "./constants";

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
  // Vector store
  vectorStoreBackend: string;
  setVectorStoreBackend: (v: string) => void;
  qdrantApiKey: string;
  setQdrantApiKey: (v: string) => void;
  // Reranker
  rerankEnabled: boolean;
  setRerankEnabled: (v: boolean) => void;
  rerankMethod: string;
  setRerankMethod: (v: string) => void;
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
  vectorStoreBackend, setVectorStoreBackend,
  qdrantApiKey, setQdrantApiKey,
  rerankEnabled, setRerankEnabled,
  rerankMethod, setRerankMethod,
}: Props) {
  const { t } = useTranslation();

  const qdrantApiKeyStored = Boolean((s as Record<string, unknown>)?.qdrant_api_key_stored);

  return (
    <Stack gap="md">
      {/* ── LLM Provider ─────────────────────────────────────────────────────── */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("aiProvider.llm.title")}</Text>
        <Stack gap="md">
          <Select
            label={t("aiProvider.provider.label")}
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
            label={t("aiProvider.model.label")}
            name="llm_model"
            value={llmModel}
            onChange={e => {
              setLlmModel(e.target.value);
              localStorage.setItem(`piq_llm_model_${selectedProvider}`, e.target.value);
            }}
            placeholder={
              selectedProvider === "ollama"  ? t("aiProvider.model.placeholderOllama") :
              selectedProvider === "bedrock" ? t("aiProvider.model.placeholderBedrock") :
                                               t("aiProvider.model.placeholderOther")
            }
          />

          {selectedProvider === "ollama" && (
            <TextInput
              label={t("aiProvider.ollama.url.label")}
              value={ollamaUrl}
              onChange={e => setOllamaUrl(e.target.value)}
              placeholder="http://localhost:11434"
              description={t("aiProvider.ollama.url.description")}
            />
          )}

          {selectedProvider === "bedrock" && (
            <>
              <TextInput
                label={t("aiProvider.bedrock.region.label")}
                value={bedrockRegion}
                onChange={e => setBedrockRegion(e.target.value)}
                placeholder="e.g. eu-central-1, us-east-1"
              />
              <TextInput
                label={t("aiProvider.bedrock.accessKeyId.label")}
                value={bedrockAccessKeyId}
                onChange={e => setBedrockAccessKeyId(e.target.value)}
                placeholder="AKIA..."
                autoComplete="off"
              />
              <PasswordInput
                label={
                  <span>
                    {t("aiProvider.bedrock.secretKey.label")}{" "}
                    {Boolean(s?.bedrock_has_secret) && (
                      <Badge size="xs" color="teal" variant="light" ml={6}>{t("common.credential.stored")}</Badge>
                    )}
                  </span>
                }
                value={bedrockSecretKey}
                onChange={e => setBedrockSecretKey(e.target.value)}
                placeholder={s?.bedrock_has_secret ? t("common.credential.keepExisting") : t("aiProvider.bedrock.secretKey.placeholder")}
              />
              <PasswordInput
                label={
                  <span>
                    {t("aiProvider.bedrock.sessionToken.label")}{" "}
                    <Text span size="xs" c="dimmed">{t("aiProvider.bedrock.sessionToken.optional")}</Text>
                    {Boolean(s?.bedrock_has_session_token) && (
                      <Badge size="xs" color="teal" variant="light" ml={6}>{t("common.credential.stored")}</Badge>
                    )}
                  </span>
                }
                value={bedrockSessionToken}
                onChange={e => setBedrockSessionToken(e.target.value)}
                placeholder={s?.bedrock_has_session_token ? t("common.credential.keepExisting") : t("aiProvider.bedrock.sessionToken.placeholder")}
                description={t("aiProvider.bedrock.sessionToken.description")}
              />
            </>
          )}

          {selectedProvider !== "ollama" && selectedProvider !== "bedrock" && (
            <PasswordInput
              label={t("aiProvider.apiKey.label")}
              name="llm_credentials"
              defaultValue=""
              placeholder={t("common.credential.keepExisting")}
              description={t("aiProvider.apiKey.description")}
            />
          )}

          {selectedProvider === "openai" && (
            <TextInput
              label={t("aiProvider.openai.baseUrl.label")}
              name="openai_base_url"
              defaultValue={String(s.openai_base_url ?? "")}
              placeholder="https://your-server/v1"
              description={t("aiProvider.openai.baseUrl.description")}
            />
          )}

          <Divider label={t("aiProvider.context.divider")} labelPosition="left" />
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={t("aiProvider.contextWindow.label")}
              name="context_window_chars"
              min={1000}
              defaultValue={Number(s.context_window_chars ?? 128000)}
              description={t("aiProvider.contextWindow.description")}
              style={{ flex: 2, minWidth: "200px" }}
            />
            <NumberInput
              label={t("aiProvider.visionThreshold.label")}
              name="vision_max_pages_warning"
              min={1}
              defaultValue={Number(s.vision_max_pages_warning ?? 5)}
              description={t("aiProvider.visionThreshold.description")}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("aiProvider.visionDpi.label")} tip={t("aiProvider.visionDpi.tip")} />}
              name="vision_render_dpi"
              min={72}
              max={400}
              defaultValue={Number(s.vision_render_dpi ?? 150)}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("aiProvider.llmTimeout.label")} tip={t("aiProvider.llmTimeout.tip")} />}
              name="llm_timeout_seconds"
              min={0}
              defaultValue={Number(s.llm_timeout_seconds ?? 120)}
              description={t("aiProvider.llmTimeout.description")}
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>
        </Stack>
      </Paper>

      {/* ── Embeddings ───────────────────────────────────────────────────────── */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("aiProvider.embeddings.title")}</Text>
        <Text size="sm" c="dimmed" mb="md">{t("aiProvider.embeddings.subtitle")}</Text>
        <Stack gap="md">
          <Select
            label={t("aiProvider.embeddings.provider.label")}
            name="embed_provider"
            value={selectedEmbedProvider}
            onChange={v => {
              const p = v ?? "ollama";
              setSelectedEmbedProvider(p);
              const stored = localStorage.getItem(`piq_embed_model_${p}`);
              setEmbedModel(stored ?? EMBED_MODEL_DEFAULTS[p] ?? "");
            }}
            description={t("aiProvider.embeddings.provider.description")}
            data={[
              { value: "ollama", label: "Ollama" },
              { value: "bedrock", label: t("aiProvider.embeddings.bedrockOption") },
              { value: "openai", label: "OpenAI" },
            ]}
          />

          {selectedEmbedProvider === "ollama" && (
            <>
              <Text size="sm" p="sm" style={{ background: "var(--mantine-color-teal-0)", borderRadius: "var(--mantine-radius-sm)" }}>
                {t("aiProvider.embeddings.ollama.hintPre")} <code>ollama pull nomic-embed-text</code>. {t("aiProvider.embeddings.ollama.hintPost")}
              </Text>
              <TextInput
                label={t("aiProvider.embeddings.model.label")}
                name="embedding_model"
                value={embedModel}
                onChange={e => {
                  setEmbedModel(e.target.value);
                  localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
                }}
                placeholder="nomic-embed-text"
                description={t("aiProvider.embeddings.model.description")}
              />
              <NumberInput
                label={<InfoLabel label={t("aiProvider.embeddings.concurrency.label")} tip={t("aiProvider.embeddings.concurrency.tip")} />}
                name="embed_concurrency"
                min={1}
                max={16}
                defaultValue={Number(s.embed_concurrency ?? 1)}
              />
              {selectedProvider !== "ollama" && (
                <TextInput
                  label={t("aiProvider.embeddings.ollama.urlEmbed.label")}
                  value={ollamaUrl}
                  onChange={e => setOllamaUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                  description={t("aiProvider.embeddings.ollama.urlEmbed.description")}
                />
              )}
            </>
          )}

          {selectedEmbedProvider === "bedrock" && (
            <Select
              label={t("aiProvider.embeddings.bedrock.model.label")}
              name="embedding_model"
              value={embedModel || "amazon.titan-embed-text-v1"}
              onChange={v => {
                setEmbedModel(v ?? "amazon.titan-embed-text-v1");
                localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, v ?? "");
              }}
              description={t("aiProvider.embeddings.bedrock.model.description")}
              data={[
                { value: "amazon.titan-embed-text-v2:0", label: t("aiProvider.embeddings.bedrock.titanV2") },
                { value: "cohere.embed-multilingual-v3", label: t("aiProvider.embeddings.bedrock.cohereMulti") },
                { value: "cohere.embed-english-v3",      label: t("aiProvider.embeddings.bedrock.cohereEn") },
                { value: "amazon.titan-embed-text-v1",   label: t("aiProvider.embeddings.bedrock.titanV1") },
              ]}
            />
          )}

          {selectedEmbedProvider === "openai" && (
            <>
              <TextInput
                label={t("aiProvider.embeddings.model.label")}
                name="embedding_model"
                value={embedModel}
                onChange={e => {
                  setEmbedModel(e.target.value);
                  localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
                }}
                placeholder="text-embedding-3-small"
                description={t("aiProvider.embeddings.model.description")}
              />
              <NumberInput
                label={<InfoLabel label={t("aiProvider.embeddings.concurrency.label")} tip={t("aiProvider.embeddings.concurrency.tip")} />}
                name="embed_concurrency"
                min={1}
                max={16}
                defaultValue={Number(s.embed_concurrency ?? 1)}
              />
              <Text size="sm" c="dimmed" p="sm" style={{ background: "var(--mantine-color-teal-0)", borderRadius: "var(--mantine-radius-sm)" }}>
                {t("aiProvider.embeddings.openai.hint")}
              </Text>
            </>
          )}
        </Stack>
      </Paper>

      {/* ── Vector Store ─────────────────────────────────────────────────────── */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("aiProvider.vectorStore.title")}</Text>
        <Stack gap="md">
          <Select
            label={<InfoLabel label={t("aiProvider.vectorStore.backend.label")} tip={t("aiProvider.vectorStore.backend.tip")} />}
            name="vector_store_backend"
            value={vectorStoreBackend}
            onChange={v => setVectorStoreBackend(v ?? "local")}
            data={VECTOR_STORE_BACKENDS.map(b => ({ value: b.value, label: t(b.labelKey) }))}
          />

          {vectorStoreBackend === "bedrock_kb" && (
            <TextInput
              label={t("aiProvider.vectorStore.kbId.label")}
              name="bedrock_kb_id"
              defaultValue={String(s.bedrock_kb_id ?? "")}
              placeholder={t("aiProvider.vectorStore.kbId.placeholder")}
            />
          )}

          {vectorStoreBackend === "qdrant" && (
            <Stack gap="sm">
              <Select
                label={<InfoLabel label={t("aiProvider.vectorStore.qdrantMode.label")} tip={t("aiProvider.vectorStore.qdrantMode.tip")} />}
                name="qdrant_mode"
                defaultValue={String(s.qdrant_mode ?? "local")}
                data={QDRANT_MODES.map(m => ({ value: m.value, label: t(m.labelKey) }))}
              />
              <TextInput
                label={<InfoLabel label={t("aiProvider.vectorStore.qdrantUrl.label")} tip={t("aiProvider.vectorStore.qdrantUrl.tip")} />}
                name="qdrant_url"
                defaultValue={String(s.qdrant_url ?? "http://qdrant:6333")}
                placeholder="http://qdrant:6333"
              />
              <PasswordInput
                label={
                  <span>
                    <InfoLabel label={t("aiProvider.vectorStore.qdrantApiKey.label")} tip={t("aiProvider.vectorStore.qdrantApiKey.tip")} />
                    {qdrantApiKeyStored && (
                      <Badge size="xs" color="teal" variant="light" ml={6}>{t("common.credential.stored")}</Badge>
                    )}
                  </span>
                }
                value={qdrantApiKey}
                onChange={e => setQdrantApiKey(e.target.value)}
                placeholder={qdrantApiKeyStored ? t("common.credential.keepExisting") : t("aiProvider.vectorStore.qdrantApiKey.placeholder")}
                description={t("aiProvider.vectorStore.qdrantApiKey.description")}
              />
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                <TextInput
                  label={<InfoLabel label={t("aiProvider.vectorStore.qdrantCollection.label")} tip={t("aiProvider.vectorStore.qdrantCollection.tip")} />}
                  name="qdrant_collection"
                  defaultValue={String(s.qdrant_collection ?? "paperless_iq_chunks")}
                  style={{ flex: 1, minWidth: "180px" }}
                />
                <TextInput
                  label={<InfoLabel label={t("aiProvider.vectorStore.qdrantMemoryCollection.label")} tip={t("aiProvider.vectorStore.qdrantMemoryCollection.tip")} />}
                  name="qdrant_memory_collection"
                  defaultValue={String(s.qdrant_memory_collection ?? "piq_memories")}
                  style={{ flex: 1, minWidth: "180px" }}
                />
              </div>
            </Stack>
          )}

          {/* Chunking — affects how documents are embedded/stored (changing requires re-indexing) */}
          <Divider label={t("aiProvider.search.chunkingDivider")} labelPosition="left" />
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={<InfoLabel label={t("aiProvider.search.chunkSize.label")} tip={t("aiProvider.search.chunkSize.tip")} />}
              name="chunk_size"
              min={100} max={8000}
              defaultValue={Number(s.chunk_size ?? 1000)}
              description={t("aiProvider.search.reindexHint")}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("aiProvider.search.chunkOverlap.label")} tip={t("aiProvider.search.chunkOverlap.tip")} />}
              name="chunk_overlap"
              min={0} max={2000}
              defaultValue={Number(s.chunk_overlap ?? 200)}
              description={t("aiProvider.search.reindexHint")}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <Select
              label={<InfoLabel label={t("aiProvider.search.chunkStrategy.label")} tip={t("aiProvider.search.chunkStrategy.tip")} />}
              name="chunk_strategy"
              defaultValue={String(s.chunk_strategy ?? "char")}
              description={t("aiProvider.search.reindexHint")}
              data={CHUNK_STRATEGIES.map(c => ({ value: c.value, label: t(c.labelKey) }))}
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>

          {/* Backend-specific index build params (changing requires re-indexing) */}
          {vectorStoreBackend === "local" && (
            <>
              <Divider label={t("aiProvider.search.chromaHnswDivider")} labelPosition="left" />
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                <NumberInput
                  label={<InfoLabel label={t("aiProvider.search.chromaSearchEf.label")} tip={t("aiProvider.search.chromaSearchEf.tip")} />}
                  name="chroma_hnsw_search_ef"
                  min={10} max={2000}
                  defaultValue={Number(s.chroma_hnsw_search_ef ?? 100)}
                  style={{ flex: 1, minWidth: "160px" }}
                />
                <NumberInput
                  label={<InfoLabel label={t("aiProvider.search.chromaM.label")} tip={t("aiProvider.search.chromaM.tip")} />}
                  name="chroma_hnsw_m"
                  min={4} max={64}
                  defaultValue={Number(s.chroma_hnsw_m ?? 16)}
                  description={t("aiProvider.search.reindexHint")}
                  style={{ flex: 1, minWidth: "160px" }}
                />
                <NumberInput
                  label={<InfoLabel label={t("aiProvider.search.chromaConstructionEf.label")} tip={t("aiProvider.search.chromaConstructionEf.tip")} />}
                  name="chroma_hnsw_construction_ef"
                  min={10} max={2000}
                  defaultValue={Number(s.chroma_hnsw_construction_ef ?? 100)}
                  description={t("aiProvider.search.reindexHint")}
                  style={{ flex: 1, minWidth: "160px" }}
                />
              </div>
            </>
          )}

          {vectorStoreBackend === "qdrant" && (
            <>
              <Divider label={t("aiProvider.search.qdrantHnswDivider")} labelPosition="left" />
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                <NumberInput
                  label={<InfoLabel label={t("aiProvider.search.qdrantEf.label")} tip={t("aiProvider.search.qdrantEf.tip")} />}
                  name="qdrant_hnsw_ef"
                  min={10} max={2000}
                  defaultValue={Number(s.qdrant_hnsw_ef ?? 128)}
                  style={{ flex: 1, minWidth: "160px" }}
                />
                <NumberInput
                  label={<InfoLabel label={t("aiProvider.search.qdrantM.label")} tip={t("aiProvider.search.qdrantM.tip")} />}
                  name="qdrant_hnsw_m"
                  min={4} max={64}
                  defaultValue={Number(s.qdrant_hnsw_m ?? 16)}
                  description={t("aiProvider.search.reindexHint")}
                  style={{ flex: 1, minWidth: "160px" }}
                />
                <Select
                  label={<InfoLabel label={t("aiProvider.search.qdrantQuantization.label")} tip={t("aiProvider.search.qdrantQuantization.tip")} />}
                  name="qdrant_quantization"
                  defaultValue={String(s.qdrant_quantization ?? "none")}
                  description={t("aiProvider.search.reindexHint")}
                  data={QDRANT_QUANTIZATIONS.map(q => ({ value: q.value, label: t(q.labelKey) }))}
                  style={{ flex: 1, minWidth: "160px" }}
                />
              </div>
            </>
          )}
        </Stack>
      </Paper>

      {/* ── Similarity Search Tuning ─────────────────────────────────────────── */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("aiProvider.search.title")}</Text>
        <Stack gap="md">

          {/* Common query-time knobs */}
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={<InfoLabel label={t("aiProvider.search.overfetch.label")} tip={t("aiProvider.search.overfetch.tip")} />}
              name="search_overfetch_multiplier"
              min={1} max={20}
              defaultValue={Number(s.search_overfetch_multiplier ?? 5)}
              style={{ flex: 1, minWidth: "150px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("aiProvider.search.minScore.label")} tip={t("aiProvider.search.minScore.tip")} />}
              name="search_min_score"
              min={0} max={1} step={0.05}
              decimalScale={2}
              defaultValue={Number(s.search_min_score ?? 0)}
              style={{ flex: 1, minWidth: "150px" }}
            />
          </div>

          {/* Hybrid search — a query strategy, so it lives with search tuning (Qdrant only) */}
          {vectorStoreBackend === "qdrant" && (
            <Checkbox
              label={<InfoLabel label={t("aiProvider.search.qdrantHybrid.label")} tip={t("aiProvider.search.qdrantHybrid.tip")} />}
              name="qdrant_hybrid_search"
              defaultChecked={Boolean(s.qdrant_hybrid_search)}
            />
          )}

          {/* Reranker */}
          <Divider label={t("aiProvider.search.rerankDivider")} labelPosition="left" />
          <Switch
            label={<InfoLabel label={t("aiProvider.search.rerankEnabled.label")} tip={t("aiProvider.search.rerankEnabled.tip")} />}
            checked={rerankEnabled}
            onChange={e => setRerankEnabled(e.currentTarget.checked)}
          />
          {rerankEnabled && (
            <Stack gap="sm">
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                <Select
                  label={<InfoLabel label={t("aiProvider.search.rerankMethod.label")} tip={t("aiProvider.search.rerankMethod.tip")} />}
                  name="rerank_method"
                  value={rerankMethod}
                  onChange={v => setRerankMethod(v ?? "llm")}
                  data={RERANK_METHODS.map(m => ({ value: m.value, label: t(m.labelKey) }))}
                  style={{ flex: 1, minWidth: "180px" }}
                />
                <NumberInput
                  label={<InfoLabel label={t("aiProvider.search.rerankTopK.label")} tip={t("aiProvider.search.rerankTopK.tip")} />}
                  name="rerank_top_k"
                  min={1} max={100}
                  defaultValue={Number(s.rerank_top_k ?? 20)}
                  style={{ flex: 1, minWidth: "140px" }}
                />
              </div>
              {rerankMethod === "local" && (
                <TextInput
                  label={<InfoLabel label={t("aiProvider.search.rerankModel.label")} tip={t("aiProvider.search.rerankModel.tip")} />}
                  name="rerank_model"
                  defaultValue={String(s.rerank_model ?? "BAAI/bge-reranker-v2-m3")}
                  description={t("aiProvider.search.rerankModel.description")}
                />
              )}
              {rerankMethod === "api" && (
                <TextInput
                  label={<InfoLabel label={t("aiProvider.search.rerankModel.label")} tip={t("aiProvider.search.rerankModel.tip")} />}
                  name="rerank_model"
                  defaultValue={String(s.rerank_model ?? "amazon.rerank-v1:0")}
                  placeholder="amazon.rerank-v1:0"
                  description={t("aiProvider.search.rerankApiDescription")}
                />
              )}
            </Stack>
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}
