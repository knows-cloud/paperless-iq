import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useRef } from "react";
import { api, type PaperlessEntity, type PaperlessCustomField, type ConnectionTestResult } from "../api";
import { t } from "../i18n";

// Default model names shown when switching to a provider for the first time
const LLM_MODEL_DEFAULTS: Record<string, string> = {
  ollama:    "llama3",
  bedrock:   "anthropic.claude-3-haiku-20240307-v1:0",
  anthropic: "claude-3-5-haiku-20241022",
  openai:    "gpt-4o-mini",
};
const EMBED_MODEL_DEFAULTS: Record<string, string> = {
  ollama:  "nomic-embed-text",
  bedrock: "amazon.titan-embed-text-v1",
  openai:  "text-embedding-3-small",
};

const METADATA_FIELDS = [
  { key: "title", label: "Title", description: "How should the LLM generate the document title?" },
  { key: "tags", label: "Tags", description: "How should the LLM select or suggest tags?" },
  { key: "correspondent", label: "Correspondent", description: "How should the LLM identify the correspondent?" },
  { key: "document_type", label: "Document Type", description: "How should the LLM classify the document type?" },
  { key: "storage_path", label: "Storage Path / Folder", description: "How should the LLM suggest a storage path?" },
  { key: "created", label: "Date / Created", description: "How should the LLM determine the document date?" },
];

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const customFields = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });
  const [msg, setMsg] = useState("");
  const [fieldDescs, setFieldDescs] = useState<Record<string, string>>({});
  const [selectedCustomFields, setSelectedCustomFields] = useState<number[]>([]);
  const [tagSearch, setTagSearch] = useState("");
  const [inboxTagId, setInboxTagId] = useState("");
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [connectionTestResult, setConnectionTestResult] = useState<ConnectionTestResult | null>(null);
  const [testingConnection, setTestingConnection] = useState(false);
  const [perFieldPrompts, setPerFieldPrompts] = useState<Record<string, string>>({});
  const [perDoctypePrompts, setPerDoctypePrompts] = useState<Record<string, string>>({});
  const [selectedProvider, setSelectedProvider] = useState("");
  const [selectedEmbedProvider, setSelectedEmbedProvider] = useState("ollama");
  // Controlled model inputs — remember last-used model per provider so switching
  // back and forth doesn't require retyping the model name each time.
  const [llmModel, setLlmModel] = useState("");
  const [embedModel, setEmbedModel] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [bedrockRegion, setBedrockRegion] = useState("");
  const [bedrockAccessKeyId, setBedrockAccessKeyId] = useState("");
  const [bedrockSecretKey, setBedrockSecretKey] = useState("");
  const [bedrockSessionToken, setBedrockSessionToken] = useState("");
  const [promptText, setPromptText] = useState("");
  const [paperlessPublicUrl, setPaperlessPublicUrl] = useState("");
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
  const [translateLang, setTranslateLang] = useState("de");
  const [translating, setTranslating] = useState(false);
  const [settingsTab, setSettingsTab] = useState("connection");
  const [memoryEnabled, setMemoryEnabled] = useState(true);

  // Memories tab state
  type MemoryItem = { id: string; text: string; created_at: string; updated_at: string; source_session_id: string | null };
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(false);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editMemoryText, setEditMemoryText] = useState("");
  const [clearMemoriesConfirm, setClearMemoriesConfirm] = useState(false);
  const tagDropdownRef = useRef<HTMLDivElement>(null);
  const logos = useQuery({ queryKey: ["logos"], queryFn: api.getLogos, retry: false });

  const s = data as Record<string, unknown> | undefined;

  useEffect(() => {
    if (s) {
      setFieldDescs((s.field_descriptions as Record<string, string>) ?? {});
      // Derive selected custom fields from existing field_descriptions keys
      const cfIds = Object.keys((s.field_descriptions as Record<string, string>) ?? {})
        .filter(k => k.startsWith("cf:"))
        .map(k => parseInt(k.split(":")[1], 10))
        .filter(n => !isNaN(n));
      setSelectedCustomFields(cfIds);
      // Initialize inbox tag ID from settings
      setInboxTagId(s.inbox_tag_id ? String(s.inbox_tag_id) : "");
      const prov = String(s.llm_provider ?? "ollama");
      setSelectedProvider(prov);
      const embedProv = String(s.embed_provider ?? "ollama");
      setSelectedEmbedProvider(embedProv);
      setOllamaUrl(String(s.ollama_url ?? "http://localhost:11434"));
      // Pre-populate non-sensitive Bedrock fields from server (secret stays blank)
      if (prov === "bedrock") {
        if (s.bedrock_region) setBedrockRegion(String(s.bedrock_region));
        if (s.bedrock_access_key_id) setBedrockAccessKeyId(String(s.bedrock_access_key_id));
      }

      // Seed per-provider model memory from server (authoritative source for the
      // currently active provider). Other providers fall back to localStorage.
      const serverModel = String(s.llm_model ?? LLM_MODEL_DEFAULTS[prov] ?? "");
      if (serverModel) localStorage.setItem(`piq_llm_model_${prov}`, serverModel);
      setLlmModel(serverModel);

      const serverEmbedModel = String(s.embedding_model ?? EMBED_MODEL_DEFAULTS[embedProv] ?? "");
      if (serverEmbedModel) localStorage.setItem(`piq_embed_model_${embedProv}`, serverEmbedModel);
      setEmbedModel(serverEmbedModel);
      setPromptText(String(s.global_prompt_template ?? ""));
      setPaperlessPublicUrl(String(s.paperless_public_url ?? ""));
      // Initialize per-field and per-doctype prompt templates
      setPerFieldPrompts((s.per_field_prompt_templates as Record<string, string>) ?? {});
      setPerDoctypePrompts(
        Object.fromEntries(
          Object.entries((s.per_doctype_prompt_templates as Record<string, string>) ?? {}).map(([k, v]) => [String(k), v])
        )
      );
      // Initialize theme
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
    }
  }, [s]);

  // Load memories when the Memories tab is opened
  useEffect(() => {
    if (settingsTab === "memories") {
      setMemoriesLoading(true);
      api.getMemories()
        .then(setMemories)
        .catch(() => {})
        .finally(() => setMemoriesLoading(false));
    }
  }, [settingsTab]);

  // Close tag dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (tagDropdownRef.current && !tagDropdownRef.current.contains(e.target as Node)) {
        setShowTagDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const mutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["theme"] }); setMsg(t("settings.saved")); },
    onError: (e: Error) => setMsg(e.message),
  });

  const connectionTestMutation = useMutation({
    mutationFn: api.testPaperlessConnection,
    onMutate: () => { setTestingConnection(true); setConnectionTestResult(null); },
    onSuccess: (data) => { setConnectionTestResult(data); setTestingConnection(false); },
    onError: (e: Error) => {
      setConnectionTestResult({ status: "error", detail: e.message });
      setTestingConnection(false);
    },
  });

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);

    // Start from the FULL current settings to avoid losing hidden tab values
    const values: Record<string, unknown> = { ...(s ?? {}) };

    // Overlay form fields that are present in the DOM
    fd.forEach((v, k) => { values[k] = v; });

    // Number conversions (only if present in form)
    if (fd.has("audit_retention_days")) values.audit_retention_days = Number(values.audit_retention_days);
    if (fd.has("poll_interval_seconds")) values.poll_interval_seconds = Number(values.poll_interval_seconds);
    if (fd.has("batch_size")) values.batch_size = Number(values.batch_size);
    if (fd.has("context_window_chars")) values.context_window_chars = Number(values.context_window_chars);
    if (fd.has("similar_docs_count")) values.similar_docs_count = Number(values.similar_docs_count);
    if (fd.has("frequency_fallback_count")) values.frequency_fallback_count = Number(values.frequency_fallback_count);

    // Checkboxes: only override if the field is on the current tab
    if (settingsTab === "automation") {
      values.auto_apply = fd.get("auto_apply") === "on";
      values.automation_enabled = fd.get("automation_enabled") === "on";
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

    // Bedrock: build credentials JSON from the separate fields.
    // __KEEP__ signals the backend to retain the currently stored value for
    // that sub-field — lets the user update region/access_key without
    // re-entering the secret key.
    if (selectedProvider === "bedrock") {
      const hasAny = bedrockRegion.trim() || bedrockAccessKeyId.trim()
        || bedrockSecretKey.trim() || s?.bedrock_has_secret;
      if (hasAny) {
        const creds: Record<string, string> = {
          region: bedrockRegion.trim(),
          access_key_id: bedrockAccessKeyId.trim(),
          // blank → keep whatever's stored; non-blank → update to new value
          secret_access_key: bedrockSecretKey.trim() || "__KEEP__",
        };
        if (bedrockSessionToken.trim()) {
          creds.session_token = bedrockSessionToken.trim();
        } else if (s?.bedrock_has_session_token) {
          // Keep existing session token if the field is left blank
          creds.session_token = "__KEEP__";
        }
        values.llm_credentials = JSON.stringify(creds);
      }
    }
    if (!values.llm_credentials || values.llm_credentials === "__REDACTED__") {
      delete values.llm_credentials;
    }

    // Always persist the Ollama URL — it's used for LLM (when provider=ollama)
    // and for embeddings (when embed_provider=ollama), regardless of active tab
    values.ollama_url = ollamaUrl.trim() || "http://localhost:11434";

    // Always persist the embed provider from React state (survives tab switches)
    values.embed_provider = selectedEmbedProvider;

    // Field descriptions — always use React state (works across tabs)
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

    // Collect per-field prompt templates (only non-empty)
    const pfTemplates: Record<string, string> = {};
    for (const [k, v] of Object.entries(perFieldPrompts)) {
      if (v.trim()) pfTemplates[k] = v.trim();
    }
    values.per_field_prompt_templates = pfTemplates;

    // Collect per-doctype prompt templates (only non-empty, keys as int)
    const pdtTemplates: Record<string, string> = {};
    for (const [k, v] of Object.entries(perDoctypePrompts)) {
      if (v.trim()) pdtTemplates[k] = v.trim();
    }
    values.per_doctype_prompt_templates = pdtTemplates;

    // Always send controlled state values (survive tab switches)
    values.global_prompt_template = promptText;
    values.paperless_public_url = paperlessPublicUrl.trim() || null;
    values.inbox_tag_id = inboxTagId ? Number(inboxTagId) : null;

    // Theme values
    values.theme_primary_color = themePrimary;
    values.theme_sidebar_from = themeSidebarFrom;
    values.theme_sidebar_to = themeSidebarTo;
    values.theme_font = themeFont;
    values.theme_font_size = themeFontSize;
    values.theme_text_color = themeTextColor;
    values.theme_bg_color = themeBgColor;
    values.theme_card_color = themeCardColor;
    values.theme_card_alt_hex = themeCardAltHex;
    values.theme_card_alt_opacity = themeCardAltOpacity;
    values.theme_chip_color = themeChipColor;
    values.theme_logo = themeLogo;
    values.theme_nav_icons = themeNavIcons;

    setMsg("");
    mutation.mutate(values);
  };

  const toggleCustomField = (cfId: number) => {
    setSelectedCustomFields(prev =>
      prev.includes(cfId) ? prev.filter(id => id !== cfId) : [...prev, cfId]
    );
  };

  if (isLoading) return <p>Loading settings…</p>;
  if (error) return <p className="error">Failed to load settings.</p>;
  if (!s) return null;

  const cfList = (customFields.data ?? []) as PaperlessCustomField[];
  const tagList = (tags.data ?? []) as PaperlessEntity[];

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

  const tabBtnStyle = (id: string): React.CSSProperties => ({
    display: "block", width: "100%", textAlign: "left",
    padding: "0.5rem 0.75rem", marginBottom: "2px",
    background: settingsTab === id ? "var(--sidebar-hover-bg, rgba(0,0,0,0.06))" : "transparent",
    border: "none", borderLeft: settingsTab === id ? "3px solid var(--petrol-600)" : "3px solid transparent",
    color: settingsTab === id ? "var(--text-on-body)" : "var(--text-on-body-secondary, var(--gray-600))",
    fontWeight: settingsTab === id ? 600 : 400,
    fontSize: "0.85rem", cursor: "pointer", borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
  });

  const sectionHead: React.CSSProperties = {
    marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem",
  };

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

          {/* ── 1. Connection ── */}
          {settingsTab === "connection" && (
          <div className="card">
            <h3>Paperless NGX Connection</h3>
            <div className="form-group">
              <label htmlFor="paperless_public_url">Public URL</label>
              <input id="paperless_public_url" type="url"
                value={paperlessPublicUrl}
                onChange={e => setPaperlessPublicUrl(e.target.value)}
                placeholder="https://paperless.myhome.com or http://192.168.1.10:8000" />
              <small>
                The URL your browser uses to reach Paperless NGX. Used for "Open in Paperless" links.
                Leave empty to fall back to the internal <code>PAPERLESS_URL</code> (only works if accessible from your browser).
              </small>
            </div>
            <div style={{ marginBottom: "1.5rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <button type="button" className="btn" onClick={() => connectionTestMutation.mutate()} disabled={testingConnection}>
                {testingConnection ? "Testing…" : "Test Connection"}
              </button>
              {connectionTestResult && (
                <span style={{
                  color: connectionTestResult.status === "ok" ? "var(--success-on-card)" : "var(--error-on-card)",
                  fontSize: "0.9rem",
                }}>
                  {connectionTestResult.status === "ok"
                    ? `✓ Connected${connectionTestResult.version ? ` (Paperless NGX ${connectionTestResult.version})` : ""}`
                    : `✗ ${connectionTestResult.detail ?? "Unknown error"}`}
                </span>
              )}
            </div>

            <h4 style={sectionHead}>Inbox Tag</h4>
            <div className="form-group" style={{ marginTop: "0.75rem" }}>
              <label htmlFor="inbox_tag_search">Documents with this tag are picked up for processing</label>
              <div ref={tagDropdownRef} style={{ position: "relative" }}>
                <input
                  id="inbox_tag_search"
                  type="text"
                  value={tagSearch || (inboxTagId ? (tagList.find(t => String(t.id) === inboxTagId)?.name ?? "") : "")}
                  placeholder="— Search for a tag —"
                  onChange={e => { setTagSearch(e.target.value); setShowTagDropdown(true); }}
                  onFocus={() => setShowTagDropdown(true)}
                  autoComplete="off"
                />
                {inboxTagId && !showTagDropdown && (
                  <button type="button" onClick={() => { setInboxTagId(""); setTagSearch(""); }}
                    style={{ position: "absolute", right: "8px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: "1rem", color: "var(--text-on-card-muted)", padding: "0 4px" }}
                    aria-label="Clear tag selection">×</button>
                )}
                {showTagDropdown && (
                  <ul style={{
                    position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10,
                    background: "var(--bg-input)", border: "1px solid var(--gray-300)", borderTop: "none",
                    maxHeight: "200px", overflowY: "auto", margin: 0, padding: 0,
                    listStyle: "none", boxShadow: "var(--shadow-md)",
                  }}>
                    {tagSearch && (
                      <li style={{ padding: "6px 10px", cursor: "pointer", color: "var(--text-on-card-muted)", fontSize: "0.85rem" }}
                        onMouseDown={() => { setInboxTagId(""); setTagSearch(""); setShowTagDropdown(false); }}>
                        — Clear selection —
                      </li>
                    )}
                    {tagList
                      .filter(t => t.name.toLowerCase().includes((tagSearch || "").toLowerCase()))
                      .map(t => (
                        <li key={t.id}
                          style={{ padding: "6px 10px", cursor: "pointer" }}
                          onMouseDown={() => { setInboxTagId(String(t.id)); setTagSearch(""); setShowTagDropdown(false); }}
                          onMouseEnter={e => (e.currentTarget.style.background = "var(--petrol-50)")}
                          onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
                          {t.name}
                        </li>
                      ))}
                    {tagList.filter(t => t.name.toLowerCase().includes((tagSearch || "").toLowerCase())).length === 0 && (
                      <li style={{ padding: "6px 10px", color: "var(--text-on-card-muted)", fontSize: "0.85rem" }}>No matching tags</li>
                    )}
                  </ul>
                )}
                <input type="hidden" name="inbox_tag_id" value={inboxTagId} />
              </div>
              {tags.isError && <small style={{ color: "var(--error-on-card)" }}>Cannot load tags from Paperless NGX.</small>}
            </div>
          </div>
          )}

          {/* ── 2. AI Provider ── */}
          {settingsTab === "aiProvider" && (<>
          <div className="card">
            <h3>Language Model (LLM)</h3>
            <div className="form-group">
              <label htmlFor="llm_provider">Provider</label>
              <select id="llm_provider" name="llm_provider" defaultValue={String(s.llm_provider)}
                onChange={e => {
                  const p = e.target.value;
                  setSelectedProvider(p);
                  const stored = localStorage.getItem(`piq_llm_model_${p}`);
                  setLlmModel(stored ?? LLM_MODEL_DEFAULTS[p] ?? "");
                }}>
                <option value="bedrock">Amazon Bedrock</option>
                <option value="anthropic">Anthropic</option>
                <option value="ollama">Ollama</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="llm_model">Model</label>
              <input id="llm_model" name="llm_model" value={llmModel}
                onChange={e => {
                  setLlmModel(e.target.value);
                  localStorage.setItem(`piq_llm_model_${selectedProvider}`, e.target.value);
                }}
                placeholder={
                  selectedProvider === "ollama"    ? "e.g. llama3, mistral, gemma2" :
                  selectedProvider === "bedrock"   ? "e.g. anthropic.claude-3-haiku-20240307-v1:0" :
                                                     "e.g. claude-3-5-haiku-20241022, gpt-4o-mini"
                } />
            </div>
            {selectedProvider === "ollama" ? (
              <div className="form-group">
                <label htmlFor="ollama_url">Ollama Server URL</label>
                <input id="ollama_url" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)}
                  placeholder="http://localhost:11434" />
                <small>The URL of your Ollama instance. No API key needed.</small>
              </div>
            ) : selectedProvider === "bedrock" ? (
              <>
                <div className="form-group">
                  <label htmlFor="bedrock_region">AWS Region</label>
                  <input id="bedrock_region" value={bedrockRegion} onChange={e => setBedrockRegion(e.target.value)}
                    placeholder="e.g. eu-central-1, us-east-1" />
                </div>
                <div className="form-group">
                  <label htmlFor="bedrock_access_key_id">Access Key ID</label>
                  <input id="bedrock_access_key_id" value={bedrockAccessKeyId} onChange={e => setBedrockAccessKeyId(e.target.value)}
                    placeholder="AKIA..." autoComplete="off" />
                </div>
                <div className="form-group">
                  <label htmlFor="bedrock_secret_key">
                    Secret Access Key
                    {Boolean(s?.bedrock_has_secret) && (
                      <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", color: "var(--petrol-600)", fontWeight: 500 }}>✓ stored</span>
                    )}
                  </label>
                  <input id="bedrock_secret_key" type="password" value={bedrockSecretKey} onChange={e => setBedrockSecretKey(e.target.value)}
                    placeholder={s?.bedrock_has_secret ? "••••••••••••••••••••••••  (leave blank to keep)" : "Enter secret access key"} />
                </div>
                <div className="form-group">
                  <label htmlFor="bedrock_session_token">
                    Session Token{" "}
                    <small style={{ fontWeight: 400, color: "var(--gray-500)" }}>(optional — only for temporary STS credentials)</small>
                    {Boolean(s?.bedrock_has_session_token) && (
                      <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", color: "var(--petrol-600)", fontWeight: 500 }}>✓ stored</span>
                    )}
                  </label>
                  <input id="bedrock_session_token" type="password" value={bedrockSessionToken} onChange={e => setBedrockSessionToken(e.target.value)}
                    placeholder={s?.bedrock_has_session_token ? "••••••••••••••••••••••••  (leave blank to keep)" : "Leave blank for permanent IAM user keys"} />
                  <small>
                    Permanent IAM access keys don't need this. Required only when keys came from
                    AWS SSO / <code>aws sts assume-role</code> / <code>aws sts get-session-token</code>.
                    Encrypted at rest using <code>SECRET_KEY</code>.
                  </small>
                </div>
              </>
            ) : (
              <div className="form-group">
                <label htmlFor="llm_credentials">API Key</label>
                <input id="llm_credentials" name="llm_credentials" type="password" defaultValue="" placeholder="Leave blank to keep current" />
                <small>Encrypted at rest. Leave empty to keep existing credentials.</small>
              </div>
            )}
            <h4 style={sectionHead}>Context</h4>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-group" style={{ flex: 2, minWidth: "200px" }}>
                <label htmlFor="context_window_chars">Context Window (characters)</label>
                <input id="context_window_chars" name="context_window_chars" type="number" min="1000"
                  defaultValue={String(s.context_window_chars ?? 128000)} />
                <small>Maximum characters of document content sent to the LLM. Default: 128,000.</small>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "160px" }}>
                <label htmlFor="default_analysis_mode">Default Analysis Mode</label>
                <select id="default_analysis_mode" name="default_analysis_mode" defaultValue={String(s.default_analysis_mode)}>
                  <option value="ocr">OCR Text</option>
                  <option value="full_document">Full Document</option>
                </select>
              </div>
            </div>
          </div>

          <div className="card">
            <h3>Embeddings</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem" }}>
              Used for semantic search and smart entity selection. Can use a different provider than the LLM.
            </p>
            <div className="form-group">
              <label htmlFor="embed_provider">Embedding Provider</label>
              <select id="embed_provider" name="embed_provider" value={selectedEmbedProvider}
                onChange={e => {
                  const p = e.target.value;
                  setSelectedEmbedProvider(p);
                  const stored = localStorage.getItem(`piq_embed_model_${p}`);
                  setEmbedModel(stored ?? EMBED_MODEL_DEFAULTS[p] ?? "");
                }}>
                <option value="ollama">Ollama</option>
                <option value="bedrock">Amazon Bedrock (Titan / Cohere)</option>
                <option value="openai">OpenAI</option>
              </select>
              <small>Provider used to generate document embeddings.</small>
            </div>
            {selectedEmbedProvider === "ollama" ? (
              <>
                <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem", background: "var(--petrol-50)", padding: "0.75rem", borderRadius: "4px", border: "1px solid var(--petrol-200)" }}>
                  Make sure the model is pulled: <code>ollama pull nomic-embed-text</code>. Embedding models are small and fast — independent of the LLM.
                </p>
                <div className="form-group">
                  <label htmlFor="embedding_model">Embedding Model</label>
                  <input id="embedding_model" name="embedding_model"
                    value={embedModel}
                    onChange={e => {
                      setEmbedModel(e.target.value);
                      localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
                    }}
                    placeholder="nomic-embed-text" />
                  <small>Ollama model used for document embeddings. Must support the embed API.</small>
                </div>
                {selectedProvider !== "ollama" && (
                  <div className="form-group">
                    <label htmlFor="ollama_url_embed">Ollama Server URL</label>
                    <input id="ollama_url_embed" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)}
                      placeholder="http://localhost:11434" />
                    <small>URL of your Ollama instance for embedding generation.</small>
                  </div>
                )}
              </>
            ) : selectedEmbedProvider === "bedrock" ? (
              <div className="form-group">
                <label htmlFor="embedding_model">Bedrock Embedding Model</label>
                <select id="embedding_model" name="embedding_model"
                  value={embedModel || "amazon.titan-embed-text-v1"}
                  onChange={e => {
                    setEmbedModel(e.target.value);
                    localStorage.setItem(`piq_embed_model_${selectedEmbedProvider}`, e.target.value);
                  }}>
                  <option value="amazon.titan-embed-text-v2:0">Titan Embed Text v2 — 1024-dim, better quality (recommended)</option>
                  <option value="cohere.embed-multilingual-v3">Cohere Embed Multilingual v3 — best for non-English documents</option>
                  <option value="cohere.embed-english-v3">Cohere Embed English v3 — best for English-only archives</option>
                  <option value="amazon.titan-embed-text-v1">Titan Embed Text v1 — 1536-dim, legacy (keep if already indexed)</option>
                </select>
                <small>
                  Uses the same AWS credentials as your Bedrock LLM.{" "}
                  <strong>Changing the model requires re-indexing</strong> — use Re-index on the Processing page after saving.
                </small>
              </div>
            ) : (
              <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", background: "var(--petrol-50)", padding: "0.75rem", borderRadius: "4px", border: "1px solid var(--petrol-200)" }}>
                Embeddings are generated using OpenAI's <code>text-embedding-3-small</code> (1536-dimensional vectors).
                Uses the same API key as your OpenAI LLM.
              </p>
            )}
          </div>

          <div className="card">
            <h3>Vector Store</h3>
            <div className="form-group">
              <label htmlFor="vector_store_backend">Backend</label>
              <select id="vector_store_backend" name="vector_store_backend" defaultValue={String(s.vector_store_backend)}>
                <option value="local">Local (ChromaDB)</option>
                <option value="bedrock_kb">Amazon Bedrock Knowledge Base</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="bedrock_kb_id">Bedrock Knowledge Base ID</label>
              <input id="bedrock_kb_id" name="bedrock_kb_id" defaultValue={String(s.bedrock_kb_id ?? "")} placeholder="Only needed for Bedrock KB backend" />
            </div>
          </div>
          </>)}

          {/* ── 3. Prompts & Fields ── */}
          {settingsTab === "promptsFields" && (<>
          <div className="card">
            <h3>System Prompt</h3>
            <div className="form-group">
              <label htmlFor="global_prompt_template">Global prompt — system instruction sent to the LLM with every document</label>
              <textarea id="global_prompt_template" name="global_prompt_template" rows={10}
                value={promptText}
                onChange={e => setPromptText(e.target.value)}
                style={{ fontFamily: "monospace", fontSize: "0.85rem" }} />
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.35rem" }}>
                <small style={{ flex: 1 }}>Use {"{{content}}"} as placeholder for document text.</small>
                <select value={translateLang} onChange={e => setTranslateLang(e.target.value)}
                  style={{ fontSize: "0.8rem", padding: "0.2rem 0.4rem", width: "auto" }}>
                  <option value="de">Deutsch</option>
                  <option value="fr">Français</option>
                  <option value="es">Español</option>
                  <option value="it">Italiano</option>
                  <option value="en">English</option>
                </select>
                <button type="button" className="btn" style={{ fontSize: "0.78rem", padding: "0.25rem 0.6rem" }}
                  disabled={translating || !promptText.trim()}
                  onClick={async () => {
                    setTranslating(true);
                    try {
                      const r = await api.translatePrompt(promptText, translateLang);
                      setPromptText(r.translated);
                    } catch (e) { alert((e as Error).message); }
                    setTranslating(false);
                  }}>
                  {translating ? "Translating…" : "Translate"}
                </button>
              </div>
            </div>
            <div className="form-group">
              <label htmlFor="target_language">LLM Output Language</label>
              <input id="target_language" name="target_language" defaultValue={String(s.target_language ?? "")} placeholder="e.g. de, fr, es (leave empty for English)" />
              <small>Language the LLM should use for metadata values (title, tags, etc.). Leave empty for English.</small>
            </div>
          </div>

          <div className="card">
            <h3>Field Instructions</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem" }}>
              Give the LLM specific instructions for each metadata field. Leave blank to let it decide based on the system prompt alone.
            </p>
            {METADATA_FIELDS.map(f => (
              <div className="form-group" key={f.key}>
                <label htmlFor={`field_desc_${f.key}`}>{f.label}</label>
                <textarea id={`field_desc_${f.key}`} name={`field_desc_${f.key}`} rows={2}
                  value={fieldDescs[f.key] ?? ""} onChange={e => setFieldDescs(prev => ({ ...prev, [f.key]: e.target.value }))}
                  placeholder={f.description} />
              </div>
            ))}
            <h4 style={{ marginTop: "1rem" }}>Custom Fields</h4>
            {cfList.length === 0 && (
              <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)" }}>
                {customFields.isError ? "Cannot load custom fields from Paperless NGX." : "No custom fields found."}
              </p>
            )}
            {cfList.map(cf => {
              const isSelected = selectedCustomFields.includes(cf.id);
              return (
                <div key={cf.id} style={{ marginBottom: "0.75rem" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input type="checkbox" checked={isSelected} onChange={() => toggleCustomField(cf.id)} />
                    {cf.name} <small style={{ color: "var(--text-on-card-muted)" }}>({cf.data_type})</small>
                  </label>
                  {isSelected && (
                    <textarea name={`field_desc_cf:${cf.id}`} rows={2} style={{ marginTop: "0.25rem", width: "100%" }}
                      value={fieldDescs[`cf:${cf.id}`] ?? ""} onChange={e => setFieldDescs(prev => ({ ...prev, [`cf:${cf.id}`]: e.target.value }))}
                      placeholder={`Instructions for custom field "${cf.name}"`} />
                  )}
                </div>
              );
            })}
          </div>
          </>)}

          {/* ── 4. Metadata Rules ── */}
          {settingsTab === "metadataRules" && (<>
          <div className="card">
            <h3>Smart Entity Selection</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem" }}>
              When enabled, Paperless IQ finds processed documents similar to the one being analyzed
              and sends only their tags, correspondents, and types to the LLM as candidates.
              This reduces prompt size and significantly improves suggestion accuracy.
            </p>
            <div className="form-group">
              <label><input type="checkbox" name="smart_entity_selection" defaultChecked={Boolean(s.smart_entity_selection ?? true)} />{" "}Enable smart entity selection</label>
            </div>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              <div className="form-group" style={{ flex: 1, minWidth: "180px" }}>
                <label htmlFor="similar_docs_count">Similar documents to consider</label>
                <input id="similar_docs_count" name="similar_docs_count" type="number" min="1" max="50"
                  defaultValue={String(s.similar_docs_count ?? 10)} />
                <small>How many similar processed documents to draw entity candidates from.</small>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "180px" }}>
                <label htmlFor="frequency_fallback_count">Frequency fallback count</label>
                <input id="frequency_fallback_count" name="frequency_fallback_count" type="number" min="0" max="100"
                  defaultValue={String(s.frequency_fallback_count ?? 20)} />
                <small>Top-N most-used entities added as fallback (handles cold-start and rare categories).</small>
              </div>
            </div>
          </div>

          <div className="card">
            <h3>Creation Policies</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--text-on-card-secondary)", marginBottom: "1rem" }}>
              Controls whether the LLM can suggest values that don't yet exist in Paperless NGX.
              "Existing only" removes unknown suggestions; "Allow new" keeps them highlighted for you to decide at approval time.
            </p>
            <p style={{ fontSize: "0.82rem", color: "var(--warning)", marginBottom: "1rem", background: "var(--warning-band-bg, #fef9ee)", padding: "0.65rem 0.75rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--warning-band-border, #fde68a)" }}>
              ⚠️ With auto-apply enabled, "Allow new" will create tags, correspondents, and document types
              automatically without review. Add a note to your system prompt to prevent clutter:
              "Only use values from the provided lists."
            </p>
            <div className="form-group">
              <label htmlFor="tag_creation_policy">Tags</label>
              <select id="tag_creation_policy" name="tag_creation_policy" defaultValue={String(s.tag_creation_policy)}>
                <option value="existing_only">Existing only — remove unknown tags from suggestions</option>
                <option value="allow_new">Allow new — keep unknown tags, create on approval</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="correspondent_creation_policy">Correspondents</label>
              <select id="correspondent_creation_policy" name="correspondent_creation_policy" defaultValue={String(s.correspondent_creation_policy)}>
                <option value="existing_only">Existing only — remove unknown correspondents</option>
                <option value="allow_new">Allow new — keep unknown correspondents, create on approval</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="doctype_creation_policy">Document Types</label>
              <select id="doctype_creation_policy" name="doctype_creation_policy" defaultValue={String(s.doctype_creation_policy)}>
                <option value="existing_only">Existing only — remove unknown document types</option>
                <option value="allow_new">Allow new — keep unknown types, create on approval</option>
              </select>
            </div>
          </div>
          </>)}

          {/* ── 5. Automation ── */}
          {settingsTab === "automation" && (
          <div className="card">
            <h3>Automation</h3>
            <div className="form-group">
              <label><input type="checkbox" name="automation_enabled" defaultChecked={Boolean(s.automation_enabled)} />{" "}Enable automation</label>
              <small>Automatically poll for new documents with the inbox tag and analyze them in the background.</small>
            </div>
            <div className="form-group">
              <label><input type="checkbox" name="auto_apply" defaultChecked={Boolean(s.auto_apply)} />{" "}Auto-apply suggestions (skip approval queue)</label>
              <small style={{ color: "var(--warning)" }}>
                ⚠️ AI suggestions are applied immediately without human review. Combined with "Allow new" creation policies,
                this will create new tags, correspondents, and types automatically.
              </small>
            </div>
            <h4 style={sectionHead}>Schedule</h4>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-group" style={{ flex: 1, minWidth: "160px" }}>
                <label htmlFor="poll_interval_seconds">Poll Interval (seconds)</label>
                <input id="poll_interval_seconds" name="poll_interval_seconds" type="number" min="1" defaultValue={String(s.poll_interval_seconds)} />
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "160px" }}>
                <label htmlFor="batch_size">Batch Size</label>
                <input id="batch_size" name="batch_size" type="number" min="1" defaultValue={String(s.batch_size)} />
                <small>Documents processed per polling cycle.</small>
              </div>
              <div className="form-group" style={{ flex: 2, minWidth: "200px" }}>
                <label htmlFor="schedule_cron">Cron Schedule</label>
                <input id="schedule_cron" name="schedule_cron" defaultValue={String(s.schedule_cron ?? "")} placeholder="e.g. 0 */6 * * *  (every 6 hours)" />
                <small>Optional cron expression to trigger processing on a fixed schedule.</small>
              </div>
            </div>
          </div>
          )}

          {/* ── 6. Appearance ── */}
          {settingsTab === "appearance" && (<>
          <div className="card">
            <h3>Theme</h3>

            <h4 style={sectionHead}>Colors</h4>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Primary Color</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themePrimary} onChange={e => setThemePrimary(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themePrimary} onChange={e => setThemePrimary(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Text Color</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeTextColor} onChange={e => setThemeTextColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeTextColor} onChange={e => setThemeTextColor(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Tag / Chip Color</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeChipColor || themePrimary} onChange={e => setThemeChipColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeChipColor} onChange={e => setThemeChipColor(e.target.value)} placeholder="Leave empty to follow primary" style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
                <small>Color for tag and attribute chips. Leave empty to use the primary color.</small>
              </div>
            </div>

            <h4 style={sectionHead}>Sidebar</h4>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Gradient Top</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeSidebarFrom} onChange={e => setThemeSidebarFrom(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeSidebarFrom} onChange={e => setThemeSidebarFrom(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Gradient Bottom</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeSidebarTo} onChange={e => setThemeSidebarTo(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeSidebarTo} onChange={e => setThemeSidebarTo(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
              </div>
            </div>

            <h4 style={sectionHead}>Content Area</h4>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Page Background</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeBgColor} onChange={e => setThemeBgColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeBgColor} onChange={e => setThemeBgColor(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Card Background</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeCardColor} onChange={e => setThemeCardColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeCardColor} onChange={e => setThemeCardColor(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
                <label>Alternating Row</label>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <input type="color" value={themeCardAltHex} onChange={e => setThemeCardAltHex(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
                  <input value={themeCardAltHex} onChange={e => setThemeCardAltHex(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
                </div>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.35rem" }}>
                  <label style={{ fontSize: "0.8rem", color: "var(--text-on-card-muted)", margin: 0, minWidth: "65px" }}>Opacity {themeCardAltOpacity}%</label>
                  <input type="range" min="0" max="100" value={themeCardAltOpacity} onChange={e => setThemeCardAltOpacity(Number(e.target.value))} style={{ flex: 1 }} />
                </div>
              </div>
            </div>

            <h4 style={sectionHead}>Typography</h4>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <div className="form-group" style={{ flex: 2, minWidth: "200px" }}>
                <label>Font</label>
                <select value={themeFont} onChange={e => setThemeFont(e.target.value)} style={{ fontSize: "0.85rem" }}>
                  <option value="Roboto">Roboto</option>
                  <option value="Open Sans">Open Sans</option>
                  <option value="Inter">Inter</option>
                  <option value="Fira Sans">Fira Sans</option>
                  <option value="Source Sans 3">Source Sans 3</option>
                  <option value="Nunito">Nunito</option>
                  <option value="Ubuntu">Ubuntu</option>
                  <option value="Noto Sans">Noto Sans (full Unicode)</option>
                  <option value="JetBrains Mono">JetBrains Mono</option>
                  <option value="Fira Code">Fira Code</option>
                </select>
              </div>
              <div className="form-group" style={{ flex: 1, minWidth: "100px" }}>
                <label>Size</label>
                <select value={themeFontSize} onChange={e => setThemeFontSize(e.target.value)} style={{ fontSize: "0.85rem" }}>
                  <option value="12px">12px</option>
                  <option value="13px">13px</option>
                  <option value="14px">14px</option>
                  <option value="15px">15px</option>
                  <option value="16px">16px</option>
                </select>
              </div>
            </div>

            <h4 style={sectionHead}>Branding</h4>
            <div className="form-group" style={{ marginTop: "0.75rem" }}>
              <label>Logo</label>
              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                {(logos.data ?? []).map(name => (
                  <div key={name} onClick={() => setThemeLogo(name)}
                    style={{
                      cursor: "pointer", padding: "0.35rem", borderRadius: "var(--radius-sm)",
                      border: themeLogo === name ? "2px solid var(--petrol-600)" : "2px solid var(--gray-200)",
                      background: themeLogo === name ? "var(--petrol-50)" : "var(--bg-card)",
                    }}>
                    <img src={`/logos/${name}`} alt={name}
                      style={{ width: "48px", height: "48px", objectFit: "contain", display: "block" }} />
                  </div>
                ))}
              </div>
            </div>
            <div className="form-group">
              <label>Navigation Icons</label>
              <small style={{ display: "block", marginBottom: "0.5rem" }}>Emoji or Unicode symbol for each section.</small>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {[
                  { id: "manual", label: "Analysis" },
                  { id: "queue", label: "Queue" },
                  { id: "discovery", label: "Discovery" },
                  { id: "audit", label: "Audit" },
                  { id: "settings", label: "Settings" },
                ].map(item => (
                  <div key={item.id} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.2rem" }}>
                    <input value={themeNavIcons[item.id] ?? ""} onChange={e => setThemeNavIcons(prev => ({ ...prev, [item.id]: e.target.value }))}
                      style={{ width: "3rem", textAlign: "center", fontSize: "1.1rem", padding: "0.3rem" }} />
                    <span style={{ fontSize: "0.7rem", color: "var(--gray-500)" }}>{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <h3>Language &amp; System</h3>
            <div className="form-group">
              <label htmlFor="ui_language">Interface Language</label>
              <select id="ui_language" name="ui_language" defaultValue={String(s.ui_language ?? "en")}>
                <option value="en">English</option>
                <option value="de">Deutsch</option>
                <option value="fr">Français</option>
                <option value="es">Español</option>
                <option value="it">Italiano</option>
              </select>
              <small>Language for the Paperless IQ user interface. Refresh the page after saving.</small>
            </div>
            <div className="form-group">
              <label htmlFor="audit_retention_days">Audit Log Retention (days, min 90)</label>
              <input id="audit_retention_days" name="audit_retention_days" type="number" min="90" defaultValue={String(s.audit_retention_days)} />
              <small>Audit log entries older than this are automatically deleted.</small>
            </div>
          </div>
          </>)}

          {/* ── 7. Memories ── */}
          {settingsTab === "memories" && (
          <div className="card">
            <h3>Long-term Memory</h3>

            {/* Enable toggle */}
            <div style={{ display: "flex", alignItems: "center", gap: "0.65rem", marginBottom: "0.4rem" }}>
              <input
                type="checkbox"
                id="memory_enabled_toggle"
                checked={memoryEnabled}
                onChange={e => setMemoryEnabled(e.target.checked)}
                style={{ width: "1rem", height: "1rem" }}
              />
              <label htmlFor="memory_enabled_toggle" style={{ fontWeight: 500, fontSize: "0.9rem", cursor: "pointer", margin: 0 }}>
                Enable long-term memory
              </label>
            </div>
            <p style={{ fontSize: "0.82rem", color: "var(--text-on-card-secondary, var(--gray-600))", marginBottom: "1.25rem", lineHeight: 1.5 }}>
              When enabled, key facts are automatically extracted from Discovery conversations and injected as context in future chats.
              Facts are deduplicated — similar entries are merged rather than duplicated.
            </p>

            {/* Section header + Clear all */}
            <div style={{ ...sectionHead, display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 0 }}>
              <h4 style={{ margin: 0, fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--gray-500)" }}>
                Learned facts {memories.length > 0 && `(${memories.length})`}
              </h4>
              {memories.length > 0 && !clearMemoriesConfirm && (
                <button type="button" className="btn btn-danger" style={{ padding: "0.25rem 0.65rem", fontSize: "0.76rem" }}
                  onClick={() => setClearMemoriesConfirm(true)}>
                  Clear all
                </button>
              )}
              {clearMemoriesConfirm && (
                <span style={{ fontSize: "0.8rem", display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  Are you sure?
                  <button type="button" className="btn btn-danger" style={{ padding: "0.2rem 0.55rem", fontSize: "0.76rem" }}
                    onClick={async () => {
                      await api.clearMemories();
                      setMemories([]);
                      setClearMemoriesConfirm(false);
                    }}>Yes, clear</button>
                  <button type="button" className="btn" style={{ padding: "0.2rem 0.55rem", fontSize: "0.76rem" }}
                    onClick={() => setClearMemoriesConfirm(false)}>Cancel</button>
                </span>
              )}
            </div>

            {/* Memories list */}
            {memoriesLoading ? (
              <p style={{ fontSize: "0.83rem", color: "var(--gray-500)", marginTop: "0.75rem" }}>Loading…</p>
            ) : memories.length === 0 ? (
              <p style={{ fontSize: "0.83rem", color: "var(--gray-500)", marginTop: "0.75rem" }}>
                No memories yet. Facts will appear here after Discovery conversations are closed.
              </p>
            ) : (
              <div style={{ marginTop: "0.5rem" }}>
                {memories.map(mem => (
                  <div key={mem.id} style={{
                    display: "flex", alignItems: "flex-start", gap: "0.6rem",
                    padding: "0.55rem 0.75rem",
                    background: "var(--gray-50)",
                    border: "1px solid var(--gray-200)",
                    borderRadius: "var(--radius-sm)",
                    marginBottom: "0.4rem",
                  }}>
                    <span style={{ color: "var(--petrol-400)", fontSize: "1rem", lineHeight: 1.5, flexShrink: 0 }}>•</span>

                    {editingMemoryId === mem.id ? (
                      <div style={{ flex: 1 }}>
                        <textarea
                          value={editMemoryText}
                          onChange={e => setEditMemoryText(e.target.value)}
                          rows={2}
                          style={{
                            width: "100%", resize: "vertical", fontSize: "0.83rem",
                            padding: "0.35rem 0.5rem", borderRadius: "var(--radius-sm)",
                            border: "1px solid var(--petrol-400)", fontFamily: "inherit",
                            background: "var(--bg-input)", color: "var(--gray-800)",
                          }}
                          autoFocus
                        />
                        <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.3rem" }}>
                          <button type="button" className="btn btn-primary" style={{ padding: "0.25rem 0.65rem", fontSize: "0.76rem" }}
                            onClick={async () => {
                              await api.updateMemory(mem.id, editMemoryText);
                              setEditingMemoryId(null);
                              setMemories(prev => prev.map(m => m.id === mem.id ? { ...m, text: editMemoryText } : m));
                            }}>Save</button>
                          <button type="button" className="btn" style={{ padding: "0.25rem 0.65rem", fontSize: "0.76rem" }}
                            onClick={() => setEditingMemoryId(null)}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <span style={{ flex: 1, fontSize: "0.83rem", lineHeight: 1.55, color: "var(--gray-800)", paddingTop: "0.1rem" }}>
                        {mem.text}
                      </span>
                    )}

                    {editingMemoryId !== mem.id && (
                      <div style={{ display: "flex", gap: "0.35rem", flexShrink: 0 }}>
                        <button type="button" title="Edit" style={{
                          background: "none", border: "none", cursor: "pointer",
                          fontSize: "0.85rem", color: "var(--gray-500)", padding: "0.1rem 0.25rem",
                          borderRadius: "var(--radius-sm)",
                        }}
                          onClick={() => { setEditingMemoryId(mem.id); setEditMemoryText(mem.text); }}>
                          ✎
                        </button>
                        <button type="button" title="Delete" style={{
                          background: "none", border: "none", cursor: "pointer",
                          fontSize: "0.85rem", color: "var(--error)", padding: "0.1rem 0.25rem",
                          borderRadius: "var(--radius-sm)",
                        }}
                          onClick={async () => {
                            await api.deleteMemory(mem.id);
                            setMemories(prev => prev.filter(m => m.id !== mem.id));
                          }}>
                          ✕
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Date hint for last entry */}
            {memories.length > 0 && (
              <p style={{ fontSize: "0.72rem", color: "var(--gray-400)", marginTop: "0.5rem" }}>
                Most recent: {new Date(memories[0].updated_at).toLocaleDateString()}
              </p>
            )}
          </div>
          )}

        </div>
      </form>
    </div>
  );
}
