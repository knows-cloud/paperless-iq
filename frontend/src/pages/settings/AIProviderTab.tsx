import { Select, TextInput, PasswordInput, NumberInput, Paper, Text, Divider, Stack, Badge } from "@mantine/core";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  return (
    <Stack gap="md">
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
            <Select
              label={t("aiProvider.analysisMode.label")}
              name="default_analysis_mode"
              defaultValue={String(s.default_analysis_mode ?? "ocr")}
              data={[
                { value: "ocr", label: t("aiProvider.analysisMode.ocr") },
                { value: "full_document", label: t("aiProvider.analysisMode.vision") },
              ]}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={t("aiProvider.visionThreshold.label")}
              name="vision_max_pages_warning"
              min={1}
              defaultValue={Number(s.vision_max_pages_warning ?? 5)}
              description={t("aiProvider.visionThreshold.description")}
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>
        </Stack>
      </Paper>

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
            <Text size="sm" c="dimmed" p="sm" style={{ background: "var(--mantine-color-teal-0)", borderRadius: "var(--mantine-radius-sm)" }}>
              {t("aiProvider.embeddings.openai.hint")}
            </Text>
          )}
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("aiProvider.vectorStore.title")}</Text>
        <Stack gap="md">
          <Select
            label={t("aiProvider.vectorStore.backend.label")}
            name="vector_store_backend"
            defaultValue={String(s.vector_store_backend ?? "local")}
            data={[
              { value: "local",      label: t("aiProvider.vectorStore.local") },
              { value: "bedrock_kb", label: t("aiProvider.vectorStore.bedrockKb") },
            ]}
          />
          <TextInput
            label={t("aiProvider.vectorStore.kbId.label")}
            name="bedrock_kb_id"
            defaultValue={String(s.bedrock_kb_id ?? "")}
            placeholder={t("aiProvider.vectorStore.kbId.placeholder")}
          />
        </Stack>
      </Paper>
    </Stack>
  );
}
