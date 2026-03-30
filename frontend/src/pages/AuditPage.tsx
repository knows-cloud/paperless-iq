import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "../api";

export default function AuditPage() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const { data, isLoading } = useQuery({ queryKey: ["audit", filters], queryFn: () => api.getAuditLog(filters) });

  const exportMut = useMutation({ mutationFn: api.exportConfig });
  const [importMsg, setImportMsg] = useState("");

  const handleExport = async () => {
    const config = await api.exportConfig();
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "paperless-iq-config.json";
    a.click();
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
    } catch (err) {
      setImportMsg(`Import failed: ${(err as Error).message}`);
    }
  };

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  return (
    <div>
      <h2>Audit Log</h2>
      <div className="card">
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <input placeholder="Document ID" onChange={(e) => setFilters((f) => ({ ...f, document_id: e.target.value }))} />
          <select onChange={(e) => setFilters((f) => ({ ...f, change_source: e.target.value }))}>
            <option value="">All sources</option>
            <option value="ai">AI</option>
            <option value="human">Human</option>
          </select>
        </div>
        {isLoading ? <p>Loading…</p> : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Document</th><th>Field</th><th>Previous</th><th>New</th><th>Source</th><th>Time</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #dee2e6" }}>
                  <td>{String(e.document_id)}</td>
                  <td>{String(e.field_name)}</td>
                  <td>{String(e.previous_value ?? "—")}</td>
                  <td>{String(e.new_value ?? "—")}</td>
                  <td>{String(e.change_source)}</td>
                  <td>{String(e.changed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Import / Export</h2>
      <div className="card">
        <button className="btn btn-primary" onClick={handleExport} style={{ marginRight: "0.5rem" }}>Export Config</button>
        <label className="btn btn-primary" style={{ cursor: "pointer" }}>
          Import Config
          <input type="file" accept=".json" onChange={handleImport} style={{ display: "none" }} />
        </label>
        {importMsg && <p className="success" style={{ marginTop: "0.5rem" }}>{importMsg}</p>}
      </div>
    </div>
  );
}
