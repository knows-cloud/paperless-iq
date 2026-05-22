import { type PaperlessEntity, type ConnectionTestResult } from "../../api";

interface Props {
  paperlessPublicUrl: string;
  setPaperlessPublicUrl: (v: string) => void;
  inboxTagId: string;
  setInboxTagId: (v: string) => void;
  tagSearch: string;
  setTagSearch: (v: string) => void;
  showTagDropdown: boolean;
  setShowTagDropdown: (v: boolean) => void;
  tagDropdownRef: React.RefObject<HTMLDivElement>;
  tagList: PaperlessEntity[];
  tagsError: boolean;
  connectionTestResult: ConnectionTestResult | null;
  testingConnection: boolean;
  onTestConnection: () => void;
}

export function ConnectionTab({
  paperlessPublicUrl, setPaperlessPublicUrl,
  inboxTagId, setInboxTagId,
  tagSearch, setTagSearch,
  showTagDropdown, setShowTagDropdown,
  tagDropdownRef,
  tagList, tagsError,
  connectionTestResult, testingConnection, onTestConnection,
}: Props) {
  const sectionHead: React.CSSProperties = {
    marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem",
  };

  return (
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
        <button type="button" className="btn" onClick={onTestConnection} disabled={testingConnection}>
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
        {tagsError && <small style={{ color: "var(--error-on-card)" }}>Cannot load tags from Paperless NGX.</small>}
      </div>
    </div>
  );
}
