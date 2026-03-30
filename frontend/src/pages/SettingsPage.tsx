import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const [msg, setMsg] = useState("");

  const mutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); setMsg("Saved."); },
    onError: (e: Error) => setMsg(e.message),
  });

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const values: Record<string, unknown> = {};
    fd.forEach((v, k) => { values[k] = v; });
    // Convert numeric fields
    if (values.audit_retention_days) values.audit_retention_days = Number(values.audit_retention_days);
    if (values.poll_interval_seconds) values.poll_interval_seconds = Number(values.poll_interval_seconds);
    if (values.batch_size) values.batch_size = Number(values.batch_size);
    values.auto_apply = fd.get("auto_apply") === "on";
    values.automation_enabled = fd.get("automation_enabled") === "on";
    mutation.mutate(values);
  };

  if (isLoading) return <p>Loading settings…</p>;
  if (error) return <p className="error">Failed to load settings.</p>;
  const s = data as Record<string, unknown>;

  return (
    <div className="card">
      <h2>Settings</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="llm_provider">LLM Provider</label>
          <select id="llm_provider" name="llm_provider" defaultValue={String(s.llm_provider)}>
            <option value="bedrock">Amazon Bedrock</option>
            <option value="anthropic">Anthropic</option>
            <option value="ollama">Ollama</option>
            <option value="openai">OpenAI</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="llm_model">Model</label>
          <input id="llm_model" name="llm_model" defaultValue={String(s.llm_model)} />
        </div>
        <div className="form-group">
          <label htmlFor="default_analysis_mode">Analysis Mode</label>
          <select id="default_analysis_mode" name="default_analysis_mode" defaultValue={String(s.default_analysis_mode)}>
            <option value="ocr">OCR Text</option>
            <option value="full_document">Full Document</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="tag_creation_policy">Tag Creation Policy</label>
          <select id="tag_creation_policy" name="tag_creation_policy" defaultValue={String(s.tag_creation_policy)}>
            <option value="existing_only">Existing Only</option>
            <option value="allow_new">Allow New</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="audit_retention_days">Audit Retention (days)</label>
          <input id="audit_retention_days" name="audit_retention_days" type="number" min="90" defaultValue={String(s.audit_retention_days)} />
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
          <label><input type="checkbox" name="auto_apply" defaultChecked={Boolean(s.auto_apply)} /> Auto-apply suggestions</label>
        </div>
        <div className="form-group">
          <label><input type="checkbox" name="automation_enabled" defaultChecked={Boolean(s.automation_enabled)} /> Enable automation</label>
        </div>
        <button type="submit" className="btn btn-primary">Save Settings</button>
        {msg && <p className={mutation.isError ? "error" : "success"}>{msg}</p>}
      </form>
    </div>
  );
}
