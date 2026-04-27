import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useRef } from "react";
import { api, type PaperlessEntity, type PaperlessCustomField, type ConnectionTestResult } from "../api";

const METADATA_FIELDS = [
  { key: "title", label: "Title", description: "How should the LLM generate the document title?" },
  { key: "tags", label: "Tags", description: "How should the LLM select or suggest tags?" },
  { key: "correspondent", label: "Correspondent", description: "How should the LLM identify the correspondent?" },
  { key: "document_type", label: "Document Type", description: "How should the LLM classify the document type?" },
  { key: "storage_path", label: "Storage Path / Folder", description: "How should the LLM suggest a storage path?" },
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
  const tagDropdownRef = useRef<HTMLDivElement>(null);

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
      // Initialize per-field and per-doctype prompt templates
      setPerFieldPrompts((s.per_field_prompt_templates as Record<string, string>) ?? {});
      setPerDoctypePrompts(
        Object.fromEntries(
          Object.entries((s.per_doctype_prompt_templates as Record<string, string>) ?? {}).map(([k, v]) => [String(k), v])
        )
      );
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
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); setMsg("Saved."); },
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
    if (values.inbox_tag_id) values.inbox_tag_id = values.inbox_tag_id ? Number(values.inbox_tag_id) : null;
    else values.inbox_tag_id = null;

    values.auto_apply = fd.get("auto_apply") === "on";
    values.automation_enabled = fd.get("automation_enabled") === "on";

    for (const key of ["schedule_cron", "bedrock_kb_id", "target_language"]) {
      if (values[key] === "") values[key] = null;
    }
    if (!values.llm_credentials || values.llm_credentials === "__REDACTED__") {
      delete values.llm_credentials;
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

  return (
    <div>
      <h2>Settings</h2>
      <form onSubmit={handleSubmit}>

        {/* ── LLM Provider ── */}
        <div className="card">
          <h3>LLM Provider</h3>
          <div className="form-group">
            <label htmlFor="llm_provider">Provider</label>
            <select id="llm_provider" name="llm_provider" defaultValue={String(s.llm_provider)}>
              <option value="bedrock">Amazon Bedrock</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="llm_model">Model</label>
            <input id="llm_model" name="llm_model" defaultValue={String(s.llm_model)} placeholder="e.g. llama3, claude-3-haiku, gpt-4o-mini" />
          </div>
          <div className="form-group">
            <label htmlFor="llm_credentials">API Key / Credentials</label>
            <input id="llm_credentials" name="llm_credentials" type="password" defaultValue="" placeholder="Leave blank to keep current" />
            <small>Encrypted at rest. Leave empty to keep existing credentials.</small>
          </div>
        </div>

        {/* ── System Prompt ── */}
        <div className="card">
          <h3>System Prompt</h3>
          <div className="form-group">
            <label htmlFor="global_prompt_template">Global prompt (system instruction for the LLM)</label>
            <textarea id="global_prompt_template" name="global_prompt_template" rows={10}
              defaultValue={String(s.global_prompt_template ?? "")}
              style={{ fontFamily: "monospace", fontSize: "0.85rem" }} />
            <small>
              This acts as the system prompt. It describes what information the LLM receives
              (document content, existing tags/correspondents/types/custom fields) and what it must return.
              Use {"{{content}}"} as placeholder for document text.
            </small>
          </div>
          <div className="form-group">
            <label htmlFor="default_analysis_mode">Default Analysis Mode</label>
            <select id="default_analysis_mode" name="default_analysis_mode" defaultValue={String(s.default_analysis_mode)}>
              <option value="ocr">OCR Text</option>
              <option value="full_document">Full Document</option>
            </select>
          </div>
        </div>

        {/* ── Per-Field Descriptions ── */}
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

        {/* ── Advanced Prompt Templates ── */}
        <div className="card">
          <h3
            style={{ cursor: "pointer", userSelect: "none", display: "flex", alignItems: "center", gap: "0.5rem" }}
            onClick={() => setShowAdvancedTemplates(prev => !prev)}
          >
            <span style={{ fontSize: "0.75rem", transition: "transform 0.2s", display: "inline-block", transform: showAdvancedTemplates ? "rotate(90deg)" : "rotate(0deg)" }}>▶</span>
            Advanced Prompt Templates
          </h3>
          {showAdvancedTemplates && (
            <div>
              <p style={{ fontSize: "0.85rem", color: "#666", marginBottom: "1rem", background: "#f8f8f0", padding: "0.75rem", borderRadius: "4px", border: "1px solid #e0e0d0" }}>
                Per-field templates override the global prompt for that specific field.
                Per-document-type templates override both per-field and global prompts when the document type matches.
              </p>

              <h4>Per-Field Templates</h4>
              {METADATA_FIELDS.map(f => (
                <div className="form-group" key={`pft_${f.key}`}>
                  <label htmlFor={`pft_${f.key}`}>{f.label}</label>
                  <textarea
                    id={`pft_${f.key}`}
                    rows={3}
                    value={perFieldPrompts[f.key] ?? ""}
                    onChange={e => setPerFieldPrompts(prev => ({ ...prev, [f.key]: e.target.value }))}
                    placeholder={`Custom prompt template for ${f.label.toLowerCase()}`}
                    style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
                  />
                </div>
              ))}

              <h4 style={{ marginTop: "1rem" }}>Per-Document-Type Templates</h4>
              {docTypeList.length === 0 && (
                <p style={{ fontSize: "0.85rem", color: "#666" }}>
                  {docTypes.isError ? "Cannot load document types from Paperless NGX." : "No document types found."}
                </p>
              )}
              {docTypeList.map(dt => (
                <div className="form-group" key={`pdt_${dt.id}`}>
                  <label htmlFor={`pdt_${dt.id}`}>{dt.name}</label>
                  <textarea
                    id={`pdt_${dt.id}`}
                    rows={3}
                    value={perDoctypePrompts[String(dt.id)] ?? ""}
                    onChange={e => setPerDoctypePrompts(prev => ({ ...prev, [String(dt.id)]: e.target.value }))}
                    placeholder={`Custom prompt template for "${dt.name}" documents`}
                    style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Creation Policies ── */}
        <div className="card">
          <h3>Creation Policies</h3>
          <div className="form-group">
            <label htmlFor="tag_creation_policy">Tag Creation Policy</label>
            <select id="tag_creation_policy" name="tag_creation_policy" defaultValue={String(s.tag_creation_policy)}>
              <option value="existing_only">Existing Only</option>
              <option value="allow_new">Allow New</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="correspondent_creation_policy">Correspondent Creation Policy</label>
            <select id="correspondent_creation_policy" name="correspondent_creation_policy" defaultValue={String(s.correspondent_creation_policy)}>
              <option value="existing_only">Existing Only</option>
              <option value="allow_new">Allow New</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="doctype_creation_policy">Document Type Creation Policy</label>
            <select id="doctype_creation_policy" name="doctype_creation_policy" defaultValue={String(s.doctype_creation_policy)}>
              <option value="existing_only">Existing Only</option>
              <option value="allow_new">Allow New</option>
            </select>
          </div>
        </div>

        {/* ── Automation ── */}
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
          </div>
          <div className="form-group">
            <label><input type="checkbox" name="auto_apply" defaultChecked={Boolean(s.auto_apply)} /> Auto-apply suggestions (skip approval queue)</label>
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

        {/* ── Localization & Audit ── */}
        <div className="card">
          <h3>Localization &amp; Audit</h3>
          <div className="form-group">
            <label htmlFor="target_language">Target Language</label>
            <input id="target_language" name="target_language" defaultValue={String(s.target_language ?? "")} placeholder="e.g. de, fr, es (leave empty for English)" />
          </div>
          <div className="form-group">
            <label htmlFor="audit_retention_days">Audit Retention (days, min 90)</label>
            <input id="audit_retention_days" name="audit_retention_days" type="number" min="90" defaultValue={String(s.audit_retention_days)} />
          </div>
        </div>

        <button type="submit" className="btn btn-primary" style={{ marginTop: "1rem" }}>Save Settings</button>
        {msg && <p className={mutation.isError ? "error" : "success"} style={{ marginTop: "0.5rem" }}>{msg}</p>}
      </form>
    </div>
  );
}
