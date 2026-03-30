import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

export default function QueuePage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["queue"], queryFn: () => api.getQueue({ status: "pending" }) });

  const approve = useMutation({
    mutationFn: (id: string) => api.approveItem(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const reject = useMutation({
    mutationFn: (id: string) => api.rejectItem(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  if (isLoading) return <p>Loading queue…</p>;
  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  return (
    <div>
      <h2>Approval Queue</h2>
      {items.length === 0 && <p>No pending suggestions.</p>}
      {items.map((item) => (
        <div key={String(item.id)} className="card">
          <p><strong>Document {String(item.document_id)}</strong> — {String(item.title ?? "Untitled")}</p>
          <p>Tags: {Array.isArray(item.tags) ? item.tags.join(", ") : "—"}</p>
          <p>Correspondent: {String(item.correspondent ?? "—")}</p>
          <p>Type: {String(item.document_type ?? "—")}</p>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button className="btn btn-success" onClick={() => approve.mutate(String(item.id))}>Approve</button>
            <button className="btn btn-danger" onClick={() => reject.mutate(String(item.id))}>Reject</button>
          </div>
        </div>
      ))}
    </div>
  );
}
