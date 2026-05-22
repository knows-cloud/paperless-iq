interface Props {
  s: Record<string, unknown>;
}

export function MetadataRulesTab({ s }: Props) {
  return (<>
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
  </>);
}
