import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { Title, Stack, Group, Button, Text, Tabs, Center, Loader, Alert } from "@mantine/core";
import { api, type PaperlessEntity, type PaperlessCustomField, type ConnectionTestResult } from "../api";
import { useTranslation } from "react-i18next";
import { ConnectionTab } from "./settings/ConnectionTab";
import { AIProviderTab } from "./settings/AIProviderTab";
import { PromptsFieldsTab } from "./settings/PromptsFieldsTab";
import { MetadataRulesTab } from "./settings/MetadataRulesTab";
import { AutomationTab } from "./settings/AutomationTab";
import { AppearanceTab } from "./settings/AppearanceTab";
import { MemoriesTab, type MemoryItem } from "./settings/MemoriesTab";
import { AccessControlTab } from "./settings/AccessControlTab";
import { GroomingTab } from "./settings/GroomingTab";
import { METADATA_FIELDS, LLM_MODEL_DEFAULTS, EMBED_MODEL_DEFAULTS } from "./settings/constants";

type SettingsTab = "connection" | "aiProvider" | "promptsFields" | "metadataRules" | "automation" | "appearance" | "memories" | "accessControl" | "grooming";

export default function SettingsPage() {
  const { t } = useTranslation();
  const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
    { id: "connection",    label: t("settings.tabs.connection") },
    { id: "aiProvider",    label: t("settings.tabs.aiProvider") },
    { id: "promptsFields", label: t("settings.tabs.promptsFields") },
    { id: "metadataRules", label: t("settings.tabs.metadataRules") },
    { id: "automation",    label: t("settings.tabs.automation") },
    { id: "appearance",    label: t("settings.tabs.appearance") },
    { id: "memories",      label: t("settings.tabs.memories") },
    { id: "accessControl", label: t("settings.tabs.accessControl") },
    { id: "grooming",      label: t("settings.tabs.grooming") },
  ];
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const customFields = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });

  const [msg, setMsg] = useState("");
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("connection");

  // Connection tab
  const [paperlessPublicUrl, setPaperlessPublicUrl] = useState("");
  const [paperlessIqInternalUrl, setPaperlessIqInternalUrl] = useState("");
  const [inboxTagId, setInboxTagId] = useState("");
  const [connectionTestResult, setConnectionTestResult] = useState<ConnectionTestResult | null>(null);
  const [testingConnection, setTestingConnection] = useState(false);
  const [webhookResult, setWebhookResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [registeringWebhook, setRegisteringWebhook] = useState(false);

  // AI Provider tab
  const [selectedProvider, setSelectedProvider] = useState("");
  const [selectedEmbedProvider, setSelectedEmbedProvider] = useState("ollama");
  const [llmModel, setLlmModel] = useState("");
  const [embedModel, setEmbedModel] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [bedrockRegion, setBedrockRegion] = useState("");
  const [bedrockAccessKeyId, setBedrockAccessKeyId] = useState("");
  const [bedrockSecretKey, setBedrockSecretKey] = useState("");
  const [bedrockSessionToken, setBedrockSessionToken] = useState("");
  // Vector store + search tuning
  const [vectorStoreBackend, setVectorStoreBackend] = useState("local");
  const [qdrantApiKey, setQdrantApiKey] = useState("");
  const [rerankEnabled, setRerankEnabled] = useState(false);
  const [rerankMethod, setRerankMethod] = useState("llm");
  const [embedRefreshMode, setEmbedRefreshMode] = useState("immediate");
  const [embedRefreshHour, setEmbedRefreshHour] = useState(3);
  // needs_reindex banner (set on successful settings save)
  const [needsReindex, setNeedsReindex] = useState(false);
  const [reindexReason, setReindexReason] = useState("");
  const [reindexReasonCode, setReindexReasonCode] = useState("");
  const [canMigrate, setCanMigrate] = useState(false);

  // Prompts & Fields tab
  const [promptText, setPromptText] = useState("");
  const [discoveryPrompt, setDiscoveryPrompt] = useState("");
  const [translateLang, setTranslateLang] = useState("de");
  const [translating, setTranslating] = useState(false);
  const [fieldDescs, setFieldDescs] = useState<Record<string, string>>({});
  const [selectedCustomFields, setSelectedCustomFields] = useState<number[]>([]);

  // Appearance tab (Mantine-based)
  const [mantineColor, setMantineColor] = useState("teal");
  const [colorScheme, setColorScheme] = useState("dark");
  const [themeFont, setThemeFont] = useState("Roboto");
  const [themeFontSize, setThemeFontSize] = useState("14px");
  const [themeNavIcons, setThemeNavIcons] = useState<Record<string, string>>({});

  // Access control / maintenance tab
  const [reindexing, setReindexing] = useState(false);
  const [reindexingSince, setReindexingSince] = useState(false);
  const [reindexSinceDate, setReindexSinceDate] = useState("");
  const [resettingTracking, setResettingTracking] = useState(false);
  const [resettingRejected, setResettingRejected] = useState(false);
  const [maintenanceMsg, setMaintenanceMsg] = useState<string | null>(null);

  // Memories tab
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(false);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editMemoryText, setEditMemoryText] = useState("");
  const [clearMemoriesConfirm, setClearMemoriesConfirm] = useState(false);

  const [perFieldPrompts, setPerFieldPrompts] = useState<Record<string, string>>({});
  const [perDoctypePrompts, setPerDoctypePrompts] = useState<Record<string, string>>({});

  // Grooming tab
  const [groomingEnabled, setGroomingEnabled] = useState(false);
  const [groomingEntityTypes, setGroomingEntityTypes] = useState<string[]>(["tag", "correspondent", "document_type"]);
  const [groomingDedupNameThreshold, setGroomingDedupNameThreshold] = useState(0.85);
  const [groomingDedupEmbedThreshold, setGroomingDedupEmbedThreshold] = useState(0.90);
  const [groomingDescSampleDocs, setGroomingDescSampleDocs] = useState(5);
  const [groomingDescSnippetChars, setGroomingDescSnippetChars] = useState(300);
  const [groomingAddThreshold, setGroomingAddThreshold] = useState(0.80);
  const [groomingRemoveThreshold, setGroomingRemoveThreshold] = useState(0.35);
  const [groomingRemovePercentile, setGroomingRemovePercentile] = useState(10);
  const [groomingMinSupportingChunks, setGroomingMinSupportingChunks] = useState(2);
  const [groomingScanTopK, setGroomingScanTopK] = useState(100);
  const [groomingMaxSuggestionsPerScan, setGroomingMaxSuggestionsPerScan] = useState(50);
  const [groomingScanCron, setGroomingScanCron] = useState("");
  const [groomingResuggestAfterDays, setGroomingResuggestAfterDays] = useState(0);

  const s = data as Record<string, unknown> | undefined;

  // ── Initialise state from server data ──────────────────────────────────────
  useEffect(() => {
    if (!s) return;

    setFieldDescs((s.field_descriptions as Record<string, string>) ?? {});
    const cfIds = Object.keys((s.field_descriptions as Record<string, string>) ?? {})
      .filter(k => k.startsWith("cf:"))
      .map(k => parseInt(k.split(":")[1], 10))
      .filter(n => !isNaN(n));
    setSelectedCustomFields(cfIds);

    setInboxTagId(s.inbox_tag_id ? String(s.inbox_tag_id) : "");

    const prov = String(s.llm_provider ?? "ollama");
    setSelectedProvider(prov);
    const embedProv = String(s.embed_provider ?? "ollama");
    setSelectedEmbedProvider(embedProv);
    setOllamaUrl(String(s.ollama_url ?? "http://localhost:11434"));
    if (prov === "bedrock") {
      if (s.bedrock_region)        setBedrockRegion(String(s.bedrock_region));
      if (s.bedrock_access_key_id) setBedrockAccessKeyId(String(s.bedrock_access_key_id));
    }

    const serverModel = String(s.llm_model ?? LLM_MODEL_DEFAULTS[prov] ?? "");
    if (serverModel) localStorage.setItem(`piq_llm_model_${prov}`, serverModel);
    setLlmModel(serverModel);

    const serverEmbedModel = String(s.embedding_model ?? EMBED_MODEL_DEFAULTS[embedProv] ?? "");
    if (serverEmbedModel) localStorage.setItem(`piq_embed_model_${embedProv}`, serverEmbedModel);
    setEmbedModel(serverEmbedModel);

    setPromptText(String(s.global_prompt_template ?? ""));
    setDiscoveryPrompt(String(s.discovery_system_prompt ?? ""));
    setPaperlessPublicUrl(String(s.paperless_public_url ?? ""));
    setPaperlessIqInternalUrl(String(s.paperless_iq_internal_url ?? ""));
    setPerFieldPrompts((s.per_field_prompt_templates as Record<string, string>) ?? {});
    setPerDoctypePrompts(
      Object.fromEntries(
        Object.entries((s.per_doctype_prompt_templates as Record<string, string>) ?? {}).map(([k, v]) => [String(k), v])
      )
    );

    setMantineColor(String(s.mantine_color ?? "teal"));
    setColorScheme(String(s.color_scheme ?? "dark"));
    setThemeFont(String(s.theme_font ?? "Roboto"));
    setThemeFontSize(String(s.theme_font_size ?? "14px"));
    setThemeNavIcons((s.theme_nav_icons as Record<string, string>) ?? {});
    setMemoryEnabled(s.memory_enabled !== false);
    setVectorStoreBackend(String(s.vector_store_backend ?? "local"));
    setRerankEnabled(Boolean(s.rerank_enabled));
    setRerankMethod(String(s.rerank_method ?? "llm"));
    setEmbedRefreshMode(String(s.embed_refresh_mode ?? "immediate"));
    setEmbedRefreshHour(Number(s.embed_refresh_hour ?? 3));

    setGroomingEnabled(Boolean(s.grooming_enabled));
    setGroomingEntityTypes((s.grooming_entity_types as string[]) ?? ["tag", "correspondent", "document_type"]);
    setGroomingDedupNameThreshold(Number(s.grooming_dedup_name_threshold ?? 0.85));
    setGroomingDedupEmbedThreshold(Number(s.grooming_dedup_embed_threshold ?? 0.90));
    setGroomingDescSampleDocs(Number(s.grooming_desc_sample_docs ?? 5));
    setGroomingDescSnippetChars(Number(s.grooming_desc_snippet_chars ?? 300));
    setGroomingAddThreshold(Number(s.grooming_add_threshold ?? 0.80));
    setGroomingRemoveThreshold(Number(s.grooming_remove_threshold ?? 0.35));
    setGroomingRemovePercentile(Number(s.grooming_remove_percentile ?? 10));
    setGroomingMinSupportingChunks(Number(s.grooming_min_supporting_chunks ?? 2));
    setGroomingScanTopK(Number(s.grooming_scan_top_k ?? 100));
    setGroomingMaxSuggestionsPerScan(Number(s.grooming_max_suggestions_per_scan ?? 50));
    setGroomingScanCron(String(s.grooming_scan_cron ?? ""));
    setGroomingResuggestAfterDays(Number(s.grooming_resuggest_after_days ?? 0));
  }, [s]);

  // ── Load memories when Memories tab opens ──────────────────────────────────
  useEffect(() => {
    if (settingsTab !== "memories") return;
    setMemoriesLoading(true);
    api.getMemories()
      .then(setMemories)
      .catch(() => {})
      .finally(() => setMemoriesLoading(false));
  }, [settingsTab]);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const mutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["theme"] });
      setMsg(t("settings.saved"));
      if (data?.needs_reindex) {
        setNeedsReindex(true);
        setReindexReason(String(data.reindex_reason ?? ""));
        setReindexReasonCode(String(data.reindex_reason_code ?? ""));
        setCanMigrate(Boolean(data.can_migrate));
      } else {
        setNeedsReindex(false);
      }
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const connectionTestMutation = useMutation({
    mutationFn: api.testPaperlessConnection,
    onMutate:  () => { setTestingConnection(true); setConnectionTestResult(null); },
    onSuccess: (data) => { setConnectionTestResult(data); setTestingConnection(false); },
    onError:   (e: Error) => { setConnectionTestResult({ status: "error", detail: e.message }); setTestingConnection(false); },
  });

  const registerWebhookMutation = useMutation({
    mutationFn: api.registerWebhook,
    onMutate:  () => { setRegisteringWebhook(true); setWebhookResult(null); },
    onSuccess: (data) => { setWebhookResult({ ok: true, detail: data.detail }); setRegisteringWebhook(false); },
    onError:   (e: Error) => { setWebhookResult({ ok: false, detail: e.message }); setRegisteringWebhook(false); },
  });

  async function handleReindex() {
    setReindexing(true);
    setMaintenanceMsg(null);
    try {
      const r = await api.triggerReindex();
      setMaintenanceMsg(r.detail);
    } catch (e: unknown) {
      setMaintenanceMsg((e as Error).message);
    } finally {
      setReindexing(false);
    }
  }

  async function handleReindexSince() {
    if (!reindexSinceDate) return;
    setReindexingSince(true);
    setMaintenanceMsg(null);
    try {
      const r = await api.reindexSince(reindexSinceDate);
      setMaintenanceMsg(r.detail);
    } catch (e: unknown) {
      setMaintenanceMsg((e as Error).message);
    } finally {
      setReindexingSince(false);
    }
  }

  async function handleResetTracking() {
    setResettingTracking(true);
    setMaintenanceMsg(null);
    try {
      const r = await api.resetTracking();
      setMaintenanceMsg(`Tracking reset — ${r.cleared} records cleared.`);
    } catch (e: unknown) {
      setMaintenanceMsg((e as Error).message);
    } finally {
      setResettingTracking(false);
    }
  }

  async function handleResetRejected() {
    setResettingRejected(true);
    setMaintenanceMsg(null);
    try {
      const r = await api.resetRejected();
      setMaintenanceMsg(`Reset complete — ${r.deleted_suggestions} suggestions deleted, ${r.cleared_tracking} tracking records cleared.`);
    } catch (e: unknown) {
      setMaintenanceMsg((e as Error).message);
    } finally {
      setResettingRejected(false);
    }
  }

  // ── Form submit ────────────────────────────────────────────────────────────
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);

    // Start from the full current settings so hidden-tab values are preserved
    const values: Record<string, unknown> = { ...(s ?? {}) };
    fd.forEach((v, k) => { values[k] = v; });

    if (fd.has("audit_retention_days"))    values.audit_retention_days    = Number(values.audit_retention_days);
    if (fd.has("poll_interval_seconds"))   values.poll_interval_seconds   = Number(values.poll_interval_seconds);
    if (fd.has("batch_size"))              values.batch_size              = Number(values.batch_size);
    if (fd.has("context_window_chars"))    values.context_window_chars    = Number(values.context_window_chars);
    if (fd.has("similar_docs_count"))      values.similar_docs_count      = Number(values.similar_docs_count);
    if (fd.has("frequency_fallback_count")) values.frequency_fallback_count = Number(values.frequency_fallback_count);

    if (settingsTab === "automation") {
      values.auto_apply         = fd.get("auto_apply") === "on";
      values.automation_enabled = fd.get("automation_enabled") === "on";
    }
    // webhook_secret is auto-managed — never send it from the UI
    delete values.webhook_secret;
    if (settingsTab === "metadataRules") {
      values.smart_entity_selection = fd.get("smart_entity_selection") === "on";
    }
    if (settingsTab === "memories") {
      values.memory_enabled = memoryEnabled;
    }
    if (settingsTab === "accessControl") {
      values.sync_ng_admins = fd.get("sync_ng_admins") === "on";
    }

    for (const key of ["schedule_cron", "bedrock_kb_id", "target_language"]) {
      if (values[key] === "") values[key] = null;
    }

    if (selectedProvider === "bedrock") {
      const hasAny = bedrockRegion.trim() || bedrockAccessKeyId.trim()
        || bedrockSecretKey.trim() || s?.bedrock_has_secret;
      if (hasAny) {
        const creds: Record<string, string> = {
          region:            bedrockRegion.trim(),
          access_key_id:     bedrockAccessKeyId.trim(),
          secret_access_key: bedrockSecretKey.trim() || "__KEEP__",
        };
        if (bedrockSessionToken.trim()) {
          creds.session_token = bedrockSessionToken.trim();
        } else if (s?.bedrock_has_session_token) {
          creds.session_token = "__KEEP__";
        }
        values.llm_credentials = JSON.stringify(creds);
      }
    }
    if (!values.llm_credentials || values.llm_credentials === "__REDACTED__") {
      delete values.llm_credentials;
    }

    values.ollama_url     = ollamaUrl.trim() || "http://localhost:11434";
    values.embed_provider = selectedEmbedProvider;

    if (settingsTab === "aiProvider") {
      // Cast number fields that come from NumberInput as strings
      for (const k of [
        "search_overfetch_multiplier", "search_min_score",
        "chunk_size", "chunk_overlap",
        "chroma_hnsw_search_ef", "chroma_hnsw_m", "chroma_hnsw_construction_ef",
        "qdrant_hnsw_ef", "qdrant_hnsw_m",
        "rerank_top_k", "embed_concurrency", "embed_batch_size", "llm_timeout_seconds",
      ]) {
        if (fd.has(k)) values[k] = Number(values[k]);
      }
      // Boolean toggles
      values.rerank_enabled       = rerankEnabled;
      values.qdrant_hybrid_search = fd.get("qdrant_hybrid_search") === "on";
      // Embed refresh — always from React state
      values.embed_refresh_mode   = embedRefreshMode;
      values.embed_refresh_hour   = embedRefreshHour;
      // Qdrant API key: send new value or __REDACTED__ (backend drops redacted → preserves stored)
      if (qdrantApiKey.trim()) {
        values.qdrant_api_key = qdrantApiKey.trim();
      } else {
        values.qdrant_api_key = "__REDACTED__";
      }
      // Pre-flight §3.4: search_ef must cover overfetch candidates
      const ef = vectorStoreBackend === "qdrant"
        ? Number(values.qdrant_hnsw_ef ?? s?.qdrant_hnsw_ef ?? 128)
        : Number(values.chroma_hnsw_search_ef ?? s?.chroma_hnsw_search_ef ?? 100);
      const needed = Number(values.similar_docs_count ?? s?.similar_docs_count ?? 10)
                   * Number(values.search_overfetch_multiplier ?? s?.search_overfetch_multiplier ?? 5);
      const efField = vectorStoreBackend === "qdrant" ? "qdrant_hnsw_ef" : "chroma_hnsw_search_ef";
      if (ef < needed) {
        setMsg(t("aiProvider.search.efValidationError", { ef, efField, needed }));
        return;
      }
    }

    // Field descriptions — always from React state
    const allDescs: Record<string, string> = {};
    for (const f of METADATA_FIELDS) {
      const v = fieldDescs[f.key];
      if (v && v.trim()) allDescs[f.key] = v.trim();
      delete values[`field_desc_${f.key}`];
    }
    for (const cfId of selectedCustomFields) {
      const v = fieldDescs[`cf:${cfId}`];
      if (v && v.trim()) allDescs[`cf:${cfId}`] = v.trim();
      delete values[`field_desc_cf:${cfId}`];
    }
    values.field_descriptions = allDescs;

    const pfTemplates: Record<string, string> = {};
    for (const [k, v] of Object.entries(perFieldPrompts)) {
      if (v.trim()) pfTemplates[k] = v.trim();
    }
    values.per_field_prompt_templates = pfTemplates;

    const pdtTemplates: Record<string, string> = {};
    for (const [k, v] of Object.entries(perDoctypePrompts)) {
      if (v.trim()) pdtTemplates[k] = v.trim();
    }
    values.per_doctype_prompt_templates = pdtTemplates;

    values.global_prompt_template     = promptText;
    values.discovery_system_prompt    = discoveryPrompt || null;
    values.paperless_public_url       = paperlessPublicUrl.trim() || null;
    values.paperless_iq_internal_url  = paperlessIqInternalUrl.trim();
    values.inbox_tag_id               = inboxTagId ? Number(inboxTagId) : null;

    // Mantine-based theme — always from React state
    values.mantine_color  = mantineColor;
    values.color_scheme   = colorScheme;
    values.theme_font     = themeFont;
    values.theme_font_size = themeFontSize;
    values.theme_nav_icons = themeNavIcons;

    // Grooming — always from React state
    values.grooming_enabled                = groomingEnabled;
    values.grooming_entity_types           = groomingEntityTypes;
    values.grooming_dedup_name_threshold   = groomingDedupNameThreshold;
    values.grooming_dedup_embed_threshold  = groomingDedupEmbedThreshold;
    values.grooming_desc_sample_docs       = groomingDescSampleDocs;
    values.grooming_desc_snippet_chars     = groomingDescSnippetChars;
    values.grooming_add_threshold          = groomingAddThreshold;
    values.grooming_remove_threshold       = groomingRemoveThreshold;
    values.grooming_remove_percentile      = groomingRemovePercentile;
    values.grooming_min_supporting_chunks  = groomingMinSupportingChunks;
    values.grooming_scan_top_k             = groomingScanTopK;
    values.grooming_max_suggestions_per_scan = groomingMaxSuggestionsPerScan;
    values.grooming_scan_cron              = groomingScanCron.trim() || null;
    values.grooming_resuggest_after_days   = groomingResuggestAfterDays;

    setMsg("");
    mutation.mutate(values);
  };

  const toggleCustomField = (cfId: number) => {
    setSelectedCustomFields(prev =>
      prev.includes(cfId) ? prev.filter(id => id !== cfId) : [...prev, cfId]
    );
  };

  if (isLoading) return <Center h={200}><Loader /></Center>;
  if (error)     return <Alert color="red" variant="light">Failed to load settings.</Alert>;
  if (!s)        return null;

  const cfList    = (customFields.data ?? []) as PaperlessCustomField[];
  const tagList   = (tags.data ?? []) as PaperlessEntity[];

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Title order={2}>{t("nav.settings")}</Title>
          <Group gap="sm" align="center">
            <Button type="submit" loading={mutation.isPending}>{t("settings.save")}</Button>
            {msg && <Text size="sm" c={mutation.isError ? "red" : "teal"}>{msg}</Text>}
          </Group>
        </Group>

        {needsReindex && (
          <Alert
            color="yellow"
            title={t("aiProvider.vectorStore.needsReindexTitle")}
            withCloseButton
            onClose={() => setNeedsReindex(false)}
          >
            <Text size="sm" mb="xs">{
              reindexReasonCode
                ? t(`aiProvider.vectorStore.reindexReason.${reindexReasonCode}`)
                : (reindexReason || t("aiProvider.vectorStore.needsReindexDefault"))
            }</Text>
            <Group gap="sm">
              {canMigrate && (
                <Button
                  size="xs"
                  variant="filled"
                  color="yellow"
                  onClick={async () => {
                    setMaintenanceMsg(null);
                    try {
                      const res = await api.migrateVectorStore();
                      if (res.needs_reindex) {
                        setMaintenanceMsg(t("aiProvider.vectorStore.migrateNeedsReindex"));
                      } else {
                        setMaintenanceMsg(t("aiProvider.vectorStore.migrateDone", { count: res.migrated }));
                        setNeedsReindex(false);
                      }
                    } catch {
                      setMaintenanceMsg(t("aiProvider.vectorStore.migrateFailed"));
                    }
                  }}
                >
                  {t("aiProvider.vectorStore.migrateBtn")}
                </Button>
              )}
              <Button
                size="xs"
                variant="outline"
                color="yellow"
                loading={reindexing}
                onClick={handleReindex}
              >
                {t("aiProvider.vectorStore.reindexBtn")}
              </Button>
            </Group>
            {maintenanceMsg && <Text size="xs" mt="xs" c="dimmed">{maintenanceMsg}</Text>}
          </Alert>
        )}

        <Tabs variant="pills" value={settingsTab} onChange={v => setSettingsTab(v as SettingsTab)}>
          <Tabs.List mb="md">
            {SETTINGS_TABS.map(tab => (
              <Tabs.Tab key={tab.id} value={tab.id}>{tab.label}</Tabs.Tab>
            ))}
          </Tabs.List>

          <Tabs.Panel value="connection" keepMounted={false}>
            <ConnectionTab
              paperlessPublicUrl={paperlessPublicUrl}
              setPaperlessPublicUrl={setPaperlessPublicUrl}
              paperlessIqInternalUrl={paperlessIqInternalUrl}
              setPaperlessIqInternalUrl={setPaperlessIqInternalUrl}
              inboxTagId={inboxTagId}
              setInboxTagId={setInboxTagId}
              tagList={tagList}
              tagsError={tags.isError}
              connectionTestResult={connectionTestResult}
              testingConnection={testingConnection}
              onTestConnection={() => connectionTestMutation.mutate()}
              webhookResult={webhookResult}
              registeringWebhook={registeringWebhook}
              onRegisterWebhook={() => registerWebhookMutation.mutate()}
            />
          </Tabs.Panel>

          <Tabs.Panel value="aiProvider" keepMounted={false}>
            <AIProviderTab
              s={s}
              selectedProvider={selectedProvider}
              setSelectedProvider={setSelectedProvider}
              selectedEmbedProvider={selectedEmbedProvider}
              setSelectedEmbedProvider={setSelectedEmbedProvider}
              llmModel={llmModel}
              setLlmModel={setLlmModel}
              embedModel={embedModel}
              setEmbedModel={setEmbedModel}
              ollamaUrl={ollamaUrl}
              setOllamaUrl={setOllamaUrl}
              bedrockRegion={bedrockRegion}
              setBedrockRegion={setBedrockRegion}
              bedrockAccessKeyId={bedrockAccessKeyId}
              setBedrockAccessKeyId={setBedrockAccessKeyId}
              bedrockSecretKey={bedrockSecretKey}
              setBedrockSecretKey={setBedrockSecretKey}
              bedrockSessionToken={bedrockSessionToken}
              setBedrockSessionToken={setBedrockSessionToken}
              vectorStoreBackend={vectorStoreBackend}
              setVectorStoreBackend={setVectorStoreBackend}
              qdrantApiKey={qdrantApiKey}
              setQdrantApiKey={setQdrantApiKey}
              rerankEnabled={rerankEnabled}
              setRerankEnabled={setRerankEnabled}
              rerankMethod={rerankMethod}
              setRerankMethod={setRerankMethod}
              embedRefreshMode={embedRefreshMode}
              setEmbedRefreshMode={setEmbedRefreshMode}
              embedRefreshHour={embedRefreshHour}
              setEmbedRefreshHour={setEmbedRefreshHour}
            />
          </Tabs.Panel>

          <Tabs.Panel value="promptsFields" keepMounted={false}>
            <PromptsFieldsTab
              s={s}
              promptText={promptText}
              setPromptText={setPromptText}
              discoveryPrompt={discoveryPrompt}
              setDiscoveryPrompt={setDiscoveryPrompt}
              translateLang={translateLang}
              setTranslateLang={setTranslateLang}
              translating={translating}
              setTranslating={setTranslating}
              fieldDescs={fieldDescs}
              setFieldDescs={setFieldDescs}
              selectedCustomFields={selectedCustomFields}
              toggleCustomField={toggleCustomField}
              cfList={cfList}
              customFieldsIsError={customFields.isError}
            />
          </Tabs.Panel>

          <Tabs.Panel value="metadataRules" keepMounted={false}>
            <MetadataRulesTab s={s} />
          </Tabs.Panel>

          <Tabs.Panel value="automation" keepMounted={false}>
            <AutomationTab s={s} />
          </Tabs.Panel>

          <Tabs.Panel value="appearance" keepMounted={false}>
            <AppearanceTab
              mantineColor={mantineColor}
              setMantineColor={setMantineColor}
              colorScheme={colorScheme}
              setColorScheme={setColorScheme}
              themeFont={themeFont}
              setThemeFont={setThemeFont}
              themeFontSize={themeFontSize}
              setThemeFontSize={setThemeFontSize}
              themeNavIcons={themeNavIcons}
              setThemeNavIcons={setThemeNavIcons}
            />
          </Tabs.Panel>

          <Tabs.Panel value="memories" keepMounted={false}>
            <MemoriesTab
              memoryEnabled={memoryEnabled}
              setMemoryEnabled={setMemoryEnabled}
              memories={memories}
              setMemories={setMemories}
              memoriesLoading={memoriesLoading}
              editingMemoryId={editingMemoryId}
              setEditingMemoryId={setEditingMemoryId}
              editMemoryText={editMemoryText}
              setEditMemoryText={setEditMemoryText}
              clearMemoriesConfirm={clearMemoriesConfirm}
              setClearMemoriesConfirm={setClearMemoriesConfirm}
            />
          </Tabs.Panel>

          <Tabs.Panel value="accessControl" keepMounted={false}>
            <AccessControlTab
              s={s}
              onReindex={handleReindex}
              reindexing={reindexing}
              onReindexSince={handleReindexSince}
              reindexingSince={reindexingSince}
              reindexSinceDate={reindexSinceDate}
              onReindexSinceDateChange={setReindexSinceDate}
              onResetTracking={handleResetTracking}
              resettingTracking={resettingTracking}
              onResetRejected={handleResetRejected}
              resettingRejected={resettingRejected}
              maintenanceMsg={maintenanceMsg}
            />
          </Tabs.Panel>

          <Tabs.Panel value="grooming" keepMounted={false}>
            <GroomingTab
              groomingEnabled={groomingEnabled}
              setGroomingEnabled={setGroomingEnabled}
              groomingEntityTypes={groomingEntityTypes}
              setGroomingEntityTypes={setGroomingEntityTypes}
              groomingDedupNameThreshold={groomingDedupNameThreshold}
              setGroomingDedupNameThreshold={setGroomingDedupNameThreshold}
              groomingDedupEmbedThreshold={groomingDedupEmbedThreshold}
              setGroomingDedupEmbedThreshold={setGroomingDedupEmbedThreshold}
              groomingDescSampleDocs={groomingDescSampleDocs}
              setGroomingDescSampleDocs={setGroomingDescSampleDocs}
              groomingDescSnippetChars={groomingDescSnippetChars}
              setGroomingDescSnippetChars={setGroomingDescSnippetChars}
              groomingAddThreshold={groomingAddThreshold}
              setGroomingAddThreshold={setGroomingAddThreshold}
              groomingRemoveThreshold={groomingRemoveThreshold}
              setGroomingRemoveThreshold={setGroomingRemoveThreshold}
              groomingRemovePercentile={groomingRemovePercentile}
              setGroomingRemovePercentile={setGroomingRemovePercentile}
              groomingMinSupportingChunks={groomingMinSupportingChunks}
              setGroomingMinSupportingChunks={setGroomingMinSupportingChunks}
              groomingScanTopK={groomingScanTopK}
              setGroomingScanTopK={setGroomingScanTopK}
              groomingMaxSuggestionsPerScan={groomingMaxSuggestionsPerScan}
              setGroomingMaxSuggestionsPerScan={setGroomingMaxSuggestionsPerScan}
              groomingScanCron={groomingScanCron}
              setGroomingScanCron={setGroomingScanCron}
              groomingResuggestAfterDays={groomingResuggestAfterDays}
              setGroomingResuggestAfterDays={setGroomingResuggestAfterDays}
            />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </form>
  );
}
