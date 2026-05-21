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
      setImportMsg(t("audit.importSuccess", { applied: String(result.applied.length), skipped: String(result.skipped.length) }));
    } catch (err) { setImportMsg(`${t("audit.importFailed")} ${(err as Error).message}`); }
  };

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  return (
    <div>
      <h2>{t("nav.audit")}</h2>
      <div className="card">
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
          <input placeholder={t("audit.colDoc") + " ID"} style={{ maxWidth: "140px" }}
            onChange={e => setFilters(f => ({ ...f, document_id: e.target.value }))} />
          <select onChange={e => setFilters(f => ({ ...f, change_source: e.target.value }))}>
            <option value="">{t("audit.allSources")}</option>
            <option value="ai">{t("audit.aiSource")}</option>
            <option value="human">{t("audit.humanSource")}</option>
          </select>
        </div>
        {isLoading ? <p>{t("audit.loading")}</p> : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{
                  textAlign: "left",
                  borderBottom: "2px solid var(--card-border, var(--gray-200))",
                  color: "var(--text-on-card-secondary)",
                }}>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap", fontWeight: 600 }}>{t("audit.colDoc")}</th>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap", fontWeight: 600 }}>{t("audit.colField")}</th>
                  <th style={{ padding: "0.4rem 0.5rem", maxWidth: "200px", fontWeight: 600 }}>{t("audit.colPrevious")}</th>
                  <th style={{ padding: "0.4rem 0.5rem", maxWidth: "200px", fontWeight: 600 }}>{t("audit.colNew")}</th>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap", fontWeight: 600 }}>{t("audit.colSource")}</th>
                  <th style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap", fontWeight: 600 }}>{t("audit.colTime")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e, i) => (
                  <tr key={i} className={i % 2 === 1 ? "card-alt" : ""}>
                    <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>{String(e.document_id)}</td>
                    <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>{String(e.field_name)}</td>
                    <td style={{ padding: "0.4rem 0.5rem", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>{String(e.previous_value ?? "—")}</td>
                    <td style={{ padding: "0.4rem 0.5rem", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>{String(e.new_value ?? "—")}</td>
                    <td style={{ padding: "0.4rem 0.5rem" }}>
                      <span className={`badge badge-${e.change_source === "ai" ? "pending" : "approved"}`}>{String(e.change_source)}</span>
                    </td>
                    <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap", fontSize: "0.8rem", color: "var(--text-on-card-muted)" }}>
                      {new Date(String(e.changed_at)).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {items.length === 0 && !isLoading && (
          <p style={{ color: "var(--text-on-card-muted)", marginTop: "0.5rem" }}>{t("audit.empty")}</p>
        )}
      </div>

      <h3 style={{ marginTop: "1.5rem" }}>{t("audit.importExport")}</h3>
      <div className="card">
        <button className="btn btn-primary" onClick={handleExport} style={{ marginRight: "0.5rem" }}>{t("audit.export")}</button>
        <label className="btn" style={{ cursor: "pointer" }}>
          {t("audit.import")}
          <input type="file" accept=".json" onChange={handleImport} style={{ display: "none" }} />
        </label>
        {importMsg && <p className="success" style={{ marginTop: "0.5rem" }}>{importMsg}</p>}
      </div>
    </div>
  );
}
