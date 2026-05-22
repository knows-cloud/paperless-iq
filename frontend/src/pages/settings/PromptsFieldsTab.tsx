import { api, type PaperlessCustomField } from "../../api";

const METADATA_FIELDS = [
  { key: "title", label: "Title", description: "How should the LLM generate the document title?" },
  { key: "tags", label: "Tags", description: "How should the LLM select or suggest tags?" },
  { key: "correspondent", label: "Correspondent", description: "How should the LLM identify the correspondent?" },
  { key: "document_type", label: "Document Type", description: "How should the LLM classify the document type?" },
  { key: "storage_path", label: "Storage Path / Folder", description: "How should the LLM suggest a storage path?" },
  { key: "created", label: "Date / Created", description: "How should the LLM determine the document date?" },
];

interface Props {
  s: Record<string, unknown>;
  promptText: string;
  setPromptText: (v: string) => void;
  translateLang: string;
  setTranslateLang: (v: string) => void;
  translating: boolean;
  setTranslating: (v: boolean) => void;
  fieldDescs: Record<string, string>;
  setFieldDescs: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  selectedCustomFields: number[];
  toggleCustomField: (cfId: number) => void;
  cfList: PaperlessCustomField[];
  customFieldsIsError: boolean;
}

export function PromptsFieldsTab({
  s,
  promptText, setPromptText,
  translateLang, setTranslateLang,
  translating, setTranslating,
  fieldDescs, setFieldDescs,
  selectedCustomFields, toggleCustomField,
  cfList, customFieldsIsError,
}: Props) {
  return (<>
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
          {customFieldsIsError ? "Cannot load custom fields from Paperless NGX." : "No custom fields found."}
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
  </>);
}
