import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api";

export default function ManualPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<unknown[]>([]);
  const [docId, setDocId] = useState("");

  const searchMut = useMutation({
    mutationFn: (q: string) => api.search(q),
    onSuccess: (data) => setSearchResults(data.results ?? []),
  });

  const analyzeMut = useMutation({
    mutationFn: (id: number) => api.analyze(id),
  });

  return (
    <div>
      <h2>Manual Analysis</h2>
      <div className="card">
        <div className="form-group">
          <label htmlFor="doc-id">Document ID</label>
          <input id="doc-id" value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="Enter document ID" />
        </div>
        <button className="btn btn-primary" onClick={() => docId && analyzeMut.mutate(Number(docId))}>
          Analyze
        </button>
        {analyzeMut.isSuccess && <p className="success">Analysis triggered.</p>}
        {analyzeMut.isError && <p className="error">{(analyzeMut.error as Error).message}</p>}
      </div>

      <h2>Semantic Search</h2>
      <div className="card">
        <div className="form-group">
          <label htmlFor="search-q">Query</label>
          <input id="search-q" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Ask a question…" />
        </div>
        <button className="btn btn-primary" onClick={() => searchQuery && searchMut.mutate(searchQuery)}>
          Search
        </button>
        {searchResults.length > 0 && (
          <ul style={{ marginTop: "1rem" }}>
            {searchResults.map((r, i) => {
              const result = r as Record<string, unknown>;
              return (
                <li key={i} style={{ marginBottom: "0.5rem" }}>
                  <strong>{String(result.document_title)}</strong>: {String(result.passage)}
                  {result.deeplink_url && <a href={String(result.deeplink_url)} target="_blank" rel="noreferrer"> [open]</a>}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
