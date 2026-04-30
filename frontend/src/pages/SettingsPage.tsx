import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useRef } from "react";
import { api, type PaperlessEntity, type PaperlessCustomField, type ConnectionTestResult } from "../api";
import { t } from "../i18n";

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
  const docTypes = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
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
  const [showAdvancedTemplates, setShowAdvancedTemplates] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [promptText, setPromptText] = useState("");
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
  const [themeLogo, setThemeLogo] = useState("iq_1.png");
  const [themeNavIcons, setThemeNavIcons] = useState<Record<string, string>>({});
  const [translateLang, setTranslateLang] = useState("de");
  const [translating, setTranslating] = useState(false);
  const [settingsTab, setSettingsTab] = useState("llm");
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
      setSelectedProvider(String(s.llm_provider ?? "ollama"));
      setPromptText(String(s.global_prompt_template ?? ""));
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
      setThemeLogo(String(s.theme_logo ?? "iq_1.png"));
      setThemeNavIcons((s.theme_nav_icons as Record<string, string>) ?? {});
    }
  }, [s]);

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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["theme"] }); setMsg("Saved. Refresh to see theme changes."); },
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
    const values: Record<string, unknown> = {};
    fd.forEach((v, k) => { values[k] = v; });

    if (values.audit_retention_days) values.audit_retention_days = Number(values.audit_retention_days);
    if (values.poll_interval_seconds) values.poll_interval_seconds = Number(values.poll_interval_seconds);
    if (values.batch_size) values.batch_size = Number(values.batch_size);
    if (values.context_window_chars) values.context_window_chars = Number(values.context_window_chars);
    if (values.similar_docs_count) values.similar_docs_count = Number(values.similar_docs_count);
    if (values.frequency_fallback_count !== undefined) values.frequency_fallback_count = Number(values.frequency_fallback_count);
    if (values.inbox_tag_id) values.inbox_tag_id = values.inbox_tag_id ? Number(values.inbox_tag_id) : null;
    else values.inbox_tag_id = null;

    values.auto_apply = fd.get("auto_apply") === "on";
    values.automation_enabled = fd.get("automation_enabled") === "on";
    values.smart_entity_selection = fd.get("smart_entity_selection") === "on";

    for (const key of ["schedule_cron", "bedrock_kb_id", "target_language"]) {
      if (values[key] === "") values[key] = null;
    }
    if (!values.llm_credentials || values.llm_credentials === "__REDACTED__") {
      delete values.llm_credentials;
    }
    // Normalize ollama_url: keep it only when provider is ollama, default if empty
    if (values.llm_provider !== "ollama") {
      delete values.ollama_url;
    } else if (!values.ollama_url || String(values.ollama_url).trim() === "") {
      values.ollama_url = "http://localhost:11434";
    }

    // Collect field descriptions (remove form keys, set as structured object)
    const allDescs: Record<string, string> = {};
    for (const f of METADATA_FIELDS) {
      const v = fd.get(`field_desc_${f.key}`);
      if (v && String(v).trim()) allDescs[f.key] = String(v).trim();
      delete values[`field_desc_${f.key}`];
    }
    // Custom field descriptions
    for (const cfId of selectedCustomFields) {
      const v = fd.get(`field_desc_cf:${cfId}`);
      if (v && String(v).trim()) allDescs[`cf:${cfId}`] = String(v).trim();
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
  const docTypeList = (docTypes.data ?? []) as PaperlessEntity[];

  type SettingsTab = "llm" | "prompts" | "smartSelection" | "fields" | "policies" | "automation" | "localization" | "theme";
  const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
    { id: "llm", label: "LLM Provider" },
    { id: "prompts", label: "Prompts" },
    { id: "smartSelection", label: "Smart Selection" },
    { id: "fields", label: "Field Instructions" },
    { id: "policies", label: "Creation Policies" },
    { id: "automation", label: "Automation" },
    { id: "localization", label: "Language & Audit" },
    { id: "theme", label: "Theme" },
  ];

  return (
    <div>
      <h2>{t("nav.settings")}</h2>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "1.5rem" }}>
        <div style={{ minWidth: "160px", flexShrink: 0 }}>
          {SETTINGS_TABS.map(tab => (
            <button key={tab.id} type="button"
              onClick={() => setSettingsTab(tab.id)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "0.5rem 0.75rem", marginBottom: "2px",
                background: settingsTab === tab.id ? "var(--petrol-50)" : "transparent",
                border: "none", borderLeft: settingsTab === tab.id ? "3px solid var(--petrol-600)" : "3px solid transparent",
                color: settingsTab === tab.id ? "var(--petrol-800)" : "var(--gray-600)",
                fontWeight: settingsTab === tab.id ? 600 : 400,
                fontSize: "0.85rem", cursor: "pointer", borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
              }}>
              {tab.label}
            </button>
          ))}
          <div style={{ marginTop: "1rem" }}>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }}>{t("settings.save")}</button>
            {msg && <p className={mutation.isError ? "error" : "success"} style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>{msg}</p>}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>

        {/* ── LLM Provider ── */}
        {settingsTab === "llm" && (
        <div className="card">
          <h3>LLM Provider</h3>
          <div className="form-group">
            <label htmlFor="llm_provider">Provider</label>
            <select id="llm_provider" name="llm_provider" defaultValue={String(s.llm_provider)}
              onChange={e => setSelectedProvider(e.target.value)}>
              <option value="bedrock">Amazon Bedrock</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="llm_model">Model</label>
            <input id="llm_model" name="llm_model" defaultValue={String(s.llm_model)}
              placeholder={selectedProvider === "ollama" ? "e.g. llama3, mistral, gemma2" : "e.g. claude-3-haiku, gpt-4o-mini"} />
          </div>
          {selectedProvider === "ollama" ? (
            <div className="form-group">
              <label htmlFor="ollama_url">Ollama Server URL</label>
              <input id="ollama_url" name="ollama_url" defaultValue={String(s.ollama_url ?? "http://localhost:11434")}
                placeholder="http://localhost:11434" />
              <small>The URL of your Ollama instance. No API key needed.</small>
            </div>
          ) : (
            <div className="form-group">
              <label htmlFor="llm_credentials">API Key / Credentials</label>
              <input id="llm_credentials" name="llm_credentials" type="password" defaultValue="" placeholder="Leave blank to keep current" />
              <small>Encrypted at rest. Leave empty to keep existing credentials.</small>
            </div>
          )}
        </div>
        )}

        {/* ── System Prompt ── */}
        {settingsTab === "prompts" && (<>
        <div className="card">
          <h3>System Prompt</h3>
          <div className="form-group">
            <label htmlFor="global_prompt_template">Global prompt (system instruction for the LLM)</label>
            <textarea id="global_prompt_template" name="global_prompt_template" rows={10}
              value={promptText}
              onChange={e => setPromptText(e.target.value)}
              style={{ fontFamily: "monospace", fontSize: "0.85rem" }} />
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.35rem" }}>
              <small style={{ flex: 1 }}>
                Use {"{{content}}"} as placeholder for document text.
              </small>
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
            <label htmlFor="default_analysis_mode">Default Analysis Mode</label>
            <select id="default_analysis_mode" name="default_analysis_mode" defaultValue={String(s.default_analysis_mode)}>
              <option value="ocr">OCR Text</option>
              <option value="full_document">Full Document</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="context_window_chars">Context Window (characters)</label>
            <input id="context_window_chars" name="context_window_chars" type="number" min="1000"
              defaultValue={String(s.context_window_chars ?? 128000)} />
            <small>Maximum characters of document content sent to the LLM. Increase for models with large context windows. Default: 128,000.</small>
          </div>
        </div>
        </>)}

        {/* ── Smart Entity Selection ── */}
        {settingsTab === "smartSelection" && (
        <div className="card">
          <h3>Smart Entity Selection</h3>
          <p style={{ fontSize: "0.85rem", color: "#666", marginBottom: "1rem" }}>
            When enabled, uses vector similarity to find processed documents similar to the one being analyzed,
            and sends only their tags/correspondents/types to the LLM — plus a frequency-based fallback set.
            This dramatically reduces prompt size and improves suggestion accuracy.
          </p>
          <p style={{ fontSize: "0.85rem", color: "#555", marginBottom: "1rem", background: "#f0f4ff", padding: "0.75rem", borderRadius: "4px", border: "1px solid #d0d8f0" }}>
            Embeddings are generated using the Ollama server configured above. Make sure the embedding model
            is pulled on your Ollama instance (<code>ollama pull nomic-embed-text</code>). This is independent
            of the LLM used for analysis — embedding models are small and fast.
          </p>
          <div className="form-group">
            <label><input type="checkbox" name="smart_entity_selection" defaultChecked={Boolean(s.smart_entity_selection ?? true)} /> Enable smart entity selection</label>
          </div>
          <div className="form-group">
            <label htmlFor="embedding_model">Embedding model (Ollama)</label>
            <input id="embedding_model" name="embedding_model"
              defaultValue={String(s.embedding_model ?? "nomic-embed-text")}
              placeholder="nomic-embed-text" />
            <small>Ollama model used for document embeddings. Must support the embed API. Runs on the same Ollama server as your LLM.</small>
          </div>
          <div className="form-group">
            <label htmlFor="similar_docs_count">Similar documents to consider</label>
            <input id="similar_docs_count" name="similar_docs_count" type="number" min="1" max="50"
              defaultValue={String(s.similar_docs_count ?? 10)} />
            <small>How many similar processed documents to use for entity suggestions.</small>
          </div>
          <div className="form-group">
            <label htmlFor="frequency_fallback_count">Frequency fallback count</label>
            <input id="frequency_fallback_count" name="frequency_fallback_count" type="number" min="0" max="100"
              defaultValue={String(s.frequency_fallback_count ?? 20)} />
            <small>Top-N most common entities added as fallback (handles cold start and rare categories).</small>
          </div>
        </div>
        )}

        {/* ── Per-Field Descriptions ── */}
        {settingsTab === "fields" && (<>
        <div className="card">
          <h3>Field Instructions</h3>
          <p style={{ fontSize: "0.85rem", color: "#666", marginBottom: "1rem" }}>
            Give the LLM specific instructions for each metadata field it should populate.
            Leave blank to let the LLM decide based on the system prompt alone.
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
            <p style={{ fontSize: "0.85rem", color: "#666" }}>
              {customFields.isError ? "Cannot load custom fields from Paperless NGX." : "No custom fields found."}
            </p>
          )}
          {cfList.map(cf => {
            const isSelected = selectedCustomFields.includes(cf.id);
            return (
              <div key={cf.id} style={{ marginBottom: "0.75rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                  <input type="checkbox" checked={isSelected} onChange={() => toggleCustomField(cf.id)} />
                  {cf.name} <small style={{ color: "#888" }}>({cf.data_type})</small>
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
        </div>
        </>)}

        {/* ── Creation Policies ── */}
        {settingsTab === "policies" && (
        <div className="card">
          <h3>Creation Policies</h3>
          <p style={{ fontSize: "0.85rem", color: "var(--gray-500)", marginBottom: "1rem" }}>
            Controls whether the LLM can suggest values that don't exist yet in Paperless NGX.
            With "Existing only", unknown values are removed from suggestions.
            With "Allow new", unknown values are kept and highlighted — you decide at approval time whether to create them.
          </p>
          <p style={{ fontSize: "0.82rem", color: "var(--warning)", marginBottom: "1rem", background: "#fef9ee", padding: "0.65rem 0.75rem", borderRadius: "var(--radius-sm)", border: "1px solid #fde68a" }}>
            ⚠️ With auto-apply enabled, "Allow new" will create new tags, correspondents, and document types
            automatically without review. This can lead to clutter. Consider adding instructions in your
            system prompt like: "Only use values from the provided lists. Do not invent new tags or correspondents."
          </p>
          <div className="form-group">
            <label htmlFor="tag_creation_policy">Tag Creation Policy</label>
            <select id="tag_creation_policy" name="tag_creation_policy" defaultValue={String(s.tag_creation_policy)}>
              <option value="existing_only">Existing only — remove unknown tags from suggestions</option>
              <option value="allow_new">Allow new — keep unknown tags, create on approval</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="correspondent_creation_policy">Correspondent Creation Policy</label>
            <select id="correspondent_creation_policy" name="correspondent_creation_policy" defaultValue={String(s.correspondent_creation_policy)}>
              <option value="existing_only">Existing only — remove unknown correspondents</option>
              <option value="allow_new">Allow new — keep unknown correspondents, create on approval</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="doctype_creation_policy">Document Type Creation Policy</label>
            <select id="doctype_creation_policy" name="doctype_creation_policy" defaultValue={String(s.doctype_creation_policy)}>
              <option value="existing_only">Existing only — remove unknown document types</option>
              <option value="allow_new">Allow new — keep unknown types, create on approval</option>
            </select>
          </div>
        </div>
        )}

        {/* ── Automation ── */}
        {settingsTab === "automation" && (<>
        <div className="card">
          <h3>Automation</h3>
          <div style={{ marginBottom: "1rem" }}>
            <button
              type="button"
              onClick={() => connectionTestMutation.mutate()}
              disabled={testingConnection}
              style={{ marginRight: "0.5rem" }}
            >
              {testingConnection ? "Testing…" : "Test Connection"}
            </button>
            {connectionTestResult && (
              <span style={{
                color: connectionTestResult.status === "ok" ? "#2e7d32" : "#c62828",
                fontSize: "0.9rem",
              }}>
                {connectionTestResult.status === "ok"
                  ? `Connected${connectionTestResult.version ? ` (Paperless NGX ${connectionTestResult.version})` : ""}`
                  : `Connection failed: ${connectionTestResult.detail ?? "Unknown error"}`}
              </span>
            )}
          </div>
          <div className="form-group">
            <label><input type="checkbox" name="automation_enabled" defaultChecked={Boolean(s.automation_enabled)} /> Enable automation</label>
            <small>Automatically polls for new documents with the inbox tag and analyzes them.</small>
          </div>
          <div className="form-group">
            <label><input type="checkbox" name="auto_apply" defaultChecked={Boolean(s.auto_apply)} /> Auto-apply suggestions (skip approval queue)</label>
            <small style={{ color: "var(--warning)" }}>
              ⚠️ When enabled, AI suggestions are applied to documents immediately without human review.
              Combined with "Allow new" creation policies, this will create new tags/correspondents/types automatically.
            </small>
          </div>
          <div className="form-group">
            <label htmlFor="inbox_tag_search">Inbox Tag (documents to process)</label>
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
                  style={{ position: "absolute", right: "8px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: "1rem", color: "#888", padding: "0 4px" }}
                  aria-label="Clear tag selection">×</button>
              )}
              {showTagDropdown && (
                <ul style={{
                  position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10,
                  background: "#fff", border: "1px solid #ccc", borderTop: "none",
                  maxHeight: "200px", overflowY: "auto", margin: 0, padding: 0,
                  listStyle: "none", boxShadow: "0 2px 6px rgba(0,0,0,0.1)"
                }}>
                  {tagSearch && (
                    <li style={{ padding: "6px 10px", cursor: "pointer", color: "#888", fontSize: "0.85rem" }}
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
                        onMouseEnter={e => (e.currentTarget.style.background = "#f0f0f0")}
                        onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
                        {t.name}
                      </li>
                    ))}
                  {tagList.filter(t => t.name.toLowerCase().includes((tagSearch || "").toLowerCase())).length === 0 && (
                    <li style={{ padding: "6px 10px", color: "#888", fontSize: "0.85rem" }}>No matching tags</li>
                  )}
                </ul>
              )}
              <input type="hidden" name="inbox_tag_id" value={inboxTagId} />
            </div>
            {tags.isError && <small style={{ color: "#c00" }}>Cannot load tags from Paperless NGX.</small>}
          </div>
          <div className="form-group">
            <label htmlFor="poll_interval_seconds">Poll Interval (seconds)</label>
            <input id="poll_interval_seconds" name="poll_interval_seconds" type="number" min="1" defaultValue={String(s.poll_interval_seconds)} />
          </div>
          <div className="form-group">
            <label htmlFor="batch_size">Batch Size</label>
            <input id="batch_size" name="batch_size" type="number" min="1" defaultValue={String(s.batch_size)} />
          </div>
          <div className="form-group">
            <label htmlFor="schedule_cron">Schedule (cron expression)</label>
            <input id="schedule_cron" name="schedule_cron" defaultValue={String(s.schedule_cron ?? "")} placeholder="e.g. 0 */6 * * *" />
          </div>
        </div>

        {/* ── Vector Store ── */}
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

        {/* ── Localization & Audit ── */}
        {settingsTab === "localization" && (
        <div className="card">
          <h3>Localization &amp; Audit</h3>
          <div className="form-group">
            <label htmlFor="ui_language">Interface Language</label>
            <select id="ui_language" name="ui_language" defaultValue={String(s.ui_language ?? "en")}>
              <option value="en">English</option>
              <option value="de">Deutsch</option>
              <option value="fr">Français</option>
              <option value="es">Español</option>
              <option value="it">Italiano</option>
            </select>
            <small>Language for the Paperless IQ user interface. Refresh after saving.</small>
          </div>
          <div className="form-group">
            <label htmlFor="target_language">LLM Output Language</label>
            <input id="target_language" name="target_language" defaultValue={String(s.target_language ?? "")} placeholder="e.g. de, fr, es (leave empty for English)" />
            <small>Language the LLM should use for metadata values (title, tags, etc.). Leave empty for English.</small>
          </div>
          <div className="form-group">
            <label htmlFor="audit_retention_days">Audit Retention (days, min 90)</label>
            <input id="audit_retention_days" name="audit_retention_days" type="number" min="90" defaultValue={String(s.audit_retention_days)} />
          </div>
        </div>
        )}

        {/* ── Theme ── */}
        {settingsTab === "theme" && (
        <div className="card">
          <h3>Theme</h3>

          <h4 style={{ marginTop: "0.5rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem" }}>Colors</h4>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
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
          </div>

          <h4 style={{ marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem" }}>Sidebar</h4>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
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

          <h4 style={{ marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem" }}>Content Area</h4>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
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
                <label style={{ fontSize: "0.8rem", color: "var(--gray-500)", margin: 0, minWidth: "65px" }}>Opacity {themeCardAltOpacity}%</label>
                <input type="range" min="0" max="100" value={themeCardAltOpacity} onChange={e => setThemeCardAltOpacity(Number(e.target.value))} style={{ flex: 1 }} />
              </div>
            </div>
          </div>

          <h4 style={{ marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem" }}>Typography</h4>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
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

          <h4 style={{ marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem" }}>Branding</h4>

          <div className="form-group">
            <label>Logo</label>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              {(logos.data ?? []).map(name => (
                <div key={name} onClick={() => setThemeLogo(name)}
                  style={{
                    cursor: "pointer", padding: "0.35rem", borderRadius: "var(--radius-sm)",
                    border: themeLogo === name ? "2px solid var(--petrol-600)" : "2px solid var(--gray-200)",
                    background: themeLogo === name ? "var(--petrol-50)" : "white",
                  }}>
                  <img src={`/logos/${name}`} alt={name}
                    style={{ width: "48px", height: "48px", objectFit: "contain", display: "block" }} />
                </div>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label>Navigation Icons</label>
            <small style={{ display: "block", marginBottom: "0.5rem" }}>Emoji or Unicode symbols for each section.</small>
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
        )}

        </div>
      </form>
    </div>
  );
}
