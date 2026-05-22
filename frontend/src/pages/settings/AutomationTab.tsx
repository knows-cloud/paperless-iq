interface Props {
  s: Record<string, unknown>;
}

export function AutomationTab({ s }: Props) {
  const sectionHead: React.CSSProperties = {
    marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem",
  };

  return (
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
  );
}
