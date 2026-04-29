import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { t } from "../i18n";

export default function AuditPage() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const { data, isLoading } = useQuery({ queryKey: ["audit", filters], queryFn: () => api.getAuditLog(filters) });
  const [importMsg, setImportMsg] = useState("");

  const handleExport = async () => {
    const config = await api.exportConfig();
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "paperless-iq-config.json"; a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    try {
      const data = JSON.parse(text);
      const result = await api.importConfig(data);
      setImportMsg(`Applied: ${result.applied.length} fields. Skipped: ${result.skipped.length} fields.`);
    } catch (err) { setImportMsg(`Import failed: ${(err as Error).message}`); }
  };

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  return (
    <div>
      <h2>{t("nav.audit")}</h2>
      <div className="card">
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
          <input placeholder="Document ID" style={{ maxWidth: "140px" }}
            onChange={e => setFilters(f => ({ ...f, document_id: e.target.value }))} />
          <select onChange={e => setFilters(f => ({ ...f, change_source: e.target.value }))}>
            <option value="">All sources</option>
            <option value="ai">AI</option>
            <option value="human">Human</option>
          </select>
        </div>
        {isLoading ? <p>Loading…</p> : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>Doc</th>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>Field</th>
                  <th style={{ padding: "0.4rem 0.5rem", maxWidth: "200px" }}>Previous</th>
                  <th style={{ padding: "0.4rem 0.5rem", maxWidth: "200px" }}>New</th>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>Source</th>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>Time</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--gray-200)" }}>
                    <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>{String(e.document_id)}</td>
                    <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>{String(e.field_name)}</td>
                    <td style={{ padding: "0.4rem 0.5rem", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>{String(e.previous_value ?? "—")}</td>
                    <td style={{ padding: "0.4rem 0.5rem", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>{String(e.new_value ?? "—")}</td>
                    <td style={{ padding: "0.4rem 0.5rem" }}>
                      <span className={`badge badge-${e.change_source === "ai" ? "pending" : "approved"}`}>{String(e.change_source)}</span>
                    </td>
                    <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap", fontSize: "0.8rem", color: "var(--gray-500)" }}>
                      {new Date(String(e.changed_at)).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {items.length === 0 && !isLoading && <p style={{ color: "var(--gray-500)", marginTop: "0.5rem" }}>No audit entries found.</p>}
      </div>

      <h3 style={{ marginTop: "1.5rem" }}>Import / Export</h3>
      <div className="card">
        <button className="btn btn-primary" onClick={handleExport} style={{ marginRight: "0.5rem" }}>Export Config</button>
        <label className="btn" style={{ cursor: "pointer" }}>
          Import Config
          <input type="file" accept=".json" onChange={handleImport} style={{ display: "none" }} />
        </label>
        {importMsg && <p className="success" style={{ marginTop: "0.5rem" }}>{importMsg}</p>}
      </div>
    </div>
  );
}
