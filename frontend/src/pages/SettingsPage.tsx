import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useRef } from "react";
import { api, type PaperlessEntity, type PaperlessCustomField, type ConnectionTestResult } from "../api";
import { t } from "../i18n";
import { ConnectionTab } from "./settings/ConnectionTab";
import { AIProviderTab } from "./settings/AIProviderTab";
import { PromptsFieldsTab } from "./settings/PromptsFieldsTab";
import { MetadataRulesTab } from "./settings/MetadataRulesTab";
import { AutomationTab } from "./settings/AutomationTab";
import { AppearanceTab } from "./settings/AppearanceTab";
import { MemoriesTab, type MemoryItem } from "./settings/MemoriesTab";
import { METADATA_FIELDS, LLM_MODEL_DEFAULTS, EMBED_MODEL_DEFAULTS } from "./settings/constants";

type SettingsTab = "connection" | "aiProvider" | "promptsFields" | "metadataRules" | "automation" | "appearance" | "memories";

const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: "connection",    label: "Connection" },
  { id: "aiProvider",    label: "AI Provider" },
  { id: "promptsFields", label: "Prompts & Fields" },
  { id: "metadataRules", label: "Metadata Rules" },
  { id: "automation",    label: "Automation" },
  { id: "appearance",    label: "Appearance" },
  { id: "memories",      label: "💡 Memories" },
];

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const customFields = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });
  const logos = useQuery({ queryKey: ["logos"], queryFn: api.getLogos, retry: false });

  const [msg, setMsg] = useState("");
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("connection");

  // Connection tab
  const [paperlessPublicUrl, setPaperlessPublicUrl] = useState("");
  const [inboxTagId, setInboxTagId] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [connectionTestResult, setConnectionTestResult] = useState<ConnectionTestResult | null>(null);
  const [testingConnection, setTestingConnection] = useState(false);
  const tagDropdownRef = useRef<HTMLDivElement>(null);

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

  // Prompts & Fields tab
  const [promptText, setPromptText] = useState("");
  const [translateLang, setTranslateLang] = useState("de");
  const [translating, setTranslating] = useState(false);
  const [fieldDescs, setFieldDescs] = useState<Record<string, string>>({});
  const [selectedCustomFields, setSelectedCustomFields] = useState<number[]>([]);

  // Appearance tab
  const [themePrimary, setThemePrimary] = useState("#1a7288");
  const [themeSidebarFrom, setThemeSidebarFrom] = useState("#0a3344");
  const [themeSidebarTo, setThemeSidebarTo] = useState("#0e4458");
  const [themeFont, setThemeFont] = useState("Roboto");
  const [themeFontSize, setThemeFontSize] = useState("14px");
  const [themeTextColor, setThemeTextColor] = useState("#2d3239");
  const [themeBgColor, setThemeBgColor] = useState("#f8f9fb");
  const [themeCardColor, setThemeCardColor] = useState("#ffffff");
  const [themeCardAltHex, setThemeCardAltHex] = useState("#1a7288");
  const [themeCardAltOpacity, setThemeCardAltOpacity] = useState(12);
  const [themeChipColor, setThemeChipColor] = useState("");
  const [themeLogo, setThemeLogo] = useState("iq_1.png");
  const [themeNavIcons, setThemeNavIcons] = useState<Record<string, string>>({});

  // Memories tab
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(false);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editMemoryText, setEditMemoryText] = useState("");
  const [clearMemoriesConfirm, setClearMemoriesConfirm] = useState(false);

  // Unused-by-form-but-kept state (per-field / per-doctype prompt templates)
  const [perFieldPrompts, setPerFieldPrompts] = useState<Record<string, string>>({});
  const [perDoctypePrompts, setPerDoctypePrompts] = useState<Record<string, string>>({});

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
      if (s.bedrock_region)       setBedrockRegion(String(s.bedrock_region));
      if (s.bedrock_access_key_id) setBedrockAccessKeyId(String(s.bedrock_access_key_id));
    }

    const serverModel = String(s.llm_model ?? LLM_MODEL_DEFAULTS[prov] ?? "");
    if (serverModel) localStorage.setItem(`piq_llm_model_${prov}`, serverModel);
    setLlmModel(serverModel);

    const serverEmbedModel = String(s.embedding_model ?? EMBED_MODEL_DEFAULTS[embedProv] ?? "");
    if (serverEmbedModel) localStorage.setItem(`piq_embed_model_${embedProv}`, serverEmbedModel);
    setEmbedModel(serverEmbedModel);

    setPromptText(String(s.global_prompt_template ?? ""));
    setPaperlessPublicUrl(String(s.paperless_public_url ?? ""));
    setPerFieldPrompts((s.per_field_prompt_templates as Record<string, string>) ?? {});
    setPerDoctypePrompts(
      Object.fromEntries(
        Object.entries((s.per_doctype_prompt_templates as Record<string, string>) ?? {}).map(([k, v]) => [String(k), v])
      )
    );

    setThemePrimary(String(s.theme_primary_color ?? "#1a7288"));
    setThemeSidebarFrom(String(s.theme_sidebar_from ?? "#0a3344"));
    setThemeSidebarTo(String(s.theme_sidebar_to ?? "#0e4458"));
    setThemeFont(String(s.theme_font ?? "Roboto"));
    setThemeFontSize(String(s.theme_font_size ?? "14px"));
    setThemeTextColor(String(s.theme_text_color ?? "#2d3239"));
    setThemeBgColor(String(s.theme_bg_color ?? "#f8f9fb"));
    setThemeCardColor(String(s.theme_card_color ?? "#ffffff"));
    setThemeCardAltHex(String(s.theme_card_alt_hex ?? "#1a7288"));
    setThemeCardAltOpacity(Number(s.theme_card_alt_opacity ?? 12));
    setThemeChipColor(String(s.theme_chip_color ?? ""));
    setThemeLogo(String(s.theme_logo ?? "iq_1.png"));
    setThemeNavIcons((s.theme_nav_icons as Record<string, string>) ?? {});
    setMemoryEnabled(s.memory_enabled !== false);
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

  // ── Close tag dropdown on outside click ───────────────────────────────────
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (tagDropdownRef.current && !tagDropdownRef.current.contains(e.target as Node)) {
        setShowTagDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const mutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["theme"] });
      setMsg(t("settings.saved"));
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const connectionTestMutation = useMutation({
    mutationFn: api.testPaperlessConnection,
    onMutate:  () => { setTestingConnection(true); setConnectionTestResult(null); },
    onSuccess: (data) => { setConnectionTestResult(data); setTestingConnection(false); },
    onError:   (e: Error) => { setConnectionTestResult({ status: "error", detail: e.message }); setTestingConnection(false); },
  });

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
      values.auto_apply          = fd.get("auto_apply") === "on";
      values.automation_enabled  = fd.get("automation_enabled") === "on";
    }
    if (settingsTab === "metadataRules") {
      values.smart_entity_selection = fd.get("smart_entity_selection") === "on";
    }
    if (settingsTab === "memories") {
      values.memory_enabled = memoryEnabled;
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

    values.ollama_url      = ollamaUrl.trim() || "http://localhost:11434";
    values.embed_provider  = selectedEmbedProvider;

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

    values.global_prompt_template = promptText;
    values.paperless_public_url   = paperlessPublicUrl.trim() || null;
    values.inbox_tag_id           = inboxTagId ? Number(inboxTagId) : null;

    values.theme_primary_color   = themePrimary;
    values.theme_sidebar_from    = themeSidebarFrom;
    values.theme_sidebar_to      = themeSidebarTo;
    values.theme_font            = themeFont;
    values.theme_font_size       = themeFontSize;
    values.theme_text_color      = themeTextColor;
    values.theme_bg_color        = themeBgColor;
    values.theme_card_color      = themeCardColor;
    values.theme_card_alt_hex    = themeCardAltHex;
    values.theme_card_alt_opacity = themeCardAltOpacity;
    values.theme_chip_color      = themeChipColor;
    values.theme_logo            = themeLogo;
    values.theme_nav_icons       = themeNavIcons;

    setMsg("");
    mutation.mutate(values);
  };

  const toggleCustomField = (cfId: number) => {
    setSelectedCustomFields(prev =>
      prev.includes(cfId) ? prev.filter(id => id !== cfId) : [...prev, cfId]
    );
  };

  if (isLoading) return <p>Loading settings…</p>;
  if (error)     return <p className="error">Failed to load settings.</p>;
  if (!s)        return null;

  const cfList   = (customFields.data ?? []) as PaperlessCustomField[];
  const tagList  = (tags.data ?? []) as PaperlessEntity[];
  const logoNames = (logos.data ?? []) as string[];

  const tabBtnStyle = (id: string): React.CSSProperties => ({
    display: "block", width: "100%", textAlign: "left",
    padding: "0.5rem 0.75rem", marginBottom: "2px",
    background: settingsTab === id ? "var(--sidebar-hover-bg, rgba(0,0,0,0.06))" : "transparent",
    border: "none",
    borderLeft: settingsTab === id ? "3px solid var(--petrol-600)" : "3px solid transparent",
    color: settingsTab === id ? "var(--text-on-body)" : "var(--text-on-body-secondary, var(--gray-600))",
    fontWeight: settingsTab === id ? 600 : 400,
    fontSize: "0.85rem", cursor: "pointer",
    borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
  });

  return (
    <div>
      <h2>{t("nav.settings")}</h2>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "1.5rem" }}>

        {/* ── Tab sidebar ── */}
        <div style={{ minWidth: "160px", flexShrink: 0 }}>
          {SETTINGS_TABS.map(tab => (
            <button key={tab.id} type="button" onClick={() => setSettingsTab(tab.id)} style={tabBtnStyle(tab.id)}>
              {tab.label}
            </button>
          ))}
          <div style={{ marginTop: "1rem" }}>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }}>{t("settings.save")}</button>
            {msg && <p className={mutation.isError ? "error" : "success"} style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>{msg}</p>}
          </div>
        </div>

        {/* ── Tab content ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {settingsTab === "connection" && (
            <ConnectionTab
              paperlessPublicUrl={paperlessPublicUrl}
              setPaperlessPublicUrl={setPaperlessPublicUrl}
              inboxTagId={inboxTagId}
              setInboxTagId={setInboxTagId}
              tagSearch={tagSearch}
              setTagSearch={setTagSearch}
              showTagDropdown={showTagDropdown}
              setShowTagDropdown={setShowTagDropdown}
              tagDropdownRef={tagDropdownRef}
              tagList={tagList}
              tagsError={tags.isError}
              connectionTestResult={connectionTestResult}
              testingConnection={testingConnection}
              onTestConnection={() => connectionTestMutation.mutate()}
            />
          )}

          {settingsTab === "aiProvider" && (
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
            />
          )}

          {settingsTab === "promptsFields" && (
            <PromptsFieldsTab
              s={s}
              promptText={promptText}
              setPromptText={setPromptText}
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
          )}

          {settingsTab === "metadataRules" && (
            <MetadataRulesTab s={s} />
          )}

          {settingsTab === "automation" && (
            <AutomationTab s={s} />
          )}

          {settingsTab === "appearance" && (
            <AppearanceTab
              s={s}
              themePrimary={themePrimary}
              setThemePrimary={setThemePrimary}
              themeTextColor={themeTextColor}
              setThemeTextColor={setThemeTextColor}
              themeChipColor={themeChipColor}
              setThemeChipColor={setThemeChipColor}
              themeSidebarFrom={themeSidebarFrom}
              setThemeSidebarFrom={setThemeSidebarFrom}
              themeSidebarTo={themeSidebarTo}
              setThemeSidebarTo={setThemeSidebarTo}
              themeBgColor={themeBgColor}
              setThemeBgColor={setThemeBgColor}
              themeCardColor={themeCardColor}
              setThemeCardColor={setThemeCardColor}
              themeCardAltHex={themeCardAltHex}
              setThemeCardAltHex={setThemeCardAltHex}
              themeCardAltOpacity={themeCardAltOpacity}
              setThemeCardAltOpacity={setThemeCardAltOpacity}
              themeFont={themeFont}
              setThemeFont={setThemeFont}
              themeFontSize={themeFontSize}
              setThemeFontSize={setThemeFontSize}
              themeLogo={themeLogo}
              setThemeLogo={setThemeLogo}
              themeNavIcons={themeNavIcons}
              setThemeNavIcons={setThemeNavIcons}
              logoNames={logoNames}
            />
          )}

          {settingsTab === "memories" && (
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
          )}
        </div>
      </form>
    </div>
  );
}
