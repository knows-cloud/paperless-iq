import { useState, useRef, useEffect } from "react";
import { api } from "../api";

interface Source {
  document_id: number;
  title: string;
  score: number;
  deeplink_url: string;
  snippet: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  loading?: boolean;
  error?: string;
}

export default function DiscoveryPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async () => {
    const q = input.trim();
    if (!q || loading) return;
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: q }, { role: "assistant", content: "", loading: true }]);
    setLoading(true);

    try {
      const result = await api.discover(q, 5);
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (err: unknown) {
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: "", error: (err as Error).message },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 120px)" }}>
      <h2>Discovery</h2>
      <p style={{ fontSize: "0.85rem", color: "var(--gray-500)", margin: "0 0 0.75rem" }}>
        Ask questions about your documents. Answers are grounded in your actual document content with citations.
      </p>

      <div style={{ flex: 1, overflowY: "auto", marginBottom: "0.75rem", padding: "0.5rem 0" }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "var(--gray-400)", marginTop: "3rem" }}>
            <p style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>💬</p>
            <p style={{ fontSize: "1rem", fontWeight: 500, color: "var(--gray-600)" }}>Ask anything about your documents</p>
            <p style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>e.g. "What invoices did I receive from Amazon in 2024?"</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: "1rem" }}>
            <div style={{
              padding: "0.85rem 1rem",
              borderRadius: msg.role === "user" ? "var(--radius-md) var(--radius-md) 4px var(--radius-md)" : "var(--radius-md) var(--radius-md) var(--radius-md) 4px",
              background: msg.role === "user" ? "var(--petrol-100)" : "white",
              border: msg.role === "user" ? "1px solid var(--petrol-200)" : "1px solid var(--gray-200)",
              maxWidth: "90%",
              marginLeft: msg.role === "user" ? "auto" : "0",
              boxShadow: "var(--shadow-sm)",
            }}>
              {msg.loading ? (
                <p style={{ color: "var(--gray-500)", fontStyle: "italic", margin: 0 }}>Searching documents and generating answer…</p>
              ) : msg.error ? (
                <p className="error" style={{ margin: 0 }}>{msg.error}</p>
              ) : (
                <div style={{ whiteSpace: "pre-wrap", fontSize: "0.9rem", lineHeight: 1.7, color: "var(--gray-800)" }}>{msg.content}</div>
              )}
            </div>
            {msg.sources && msg.sources.length > 0 && (
              <div style={{ marginTop: "0.5rem", paddingLeft: "0.25rem" }}>
                <p style={{ fontSize: "0.78rem", color: "var(--gray-500)", margin: "0 0 0.3rem", fontWeight: 500 }}>Sources:</p>
                {msg.sources.map((src, j) => (
                  <div key={j} style={{ fontSize: "0.8rem", marginBottom: "0.35rem", padding: "0.5rem 0.75rem", background: "var(--gray-50)", borderRadius: "var(--radius-sm)", border: "1px solid var(--gray-200)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <a href={src.deeplink_url} target="_blank" rel="noopener noreferrer"
                        style={{ fontWeight: 500, color: "var(--petrol-700)", textDecoration: "none" }}>
                        {src.title || `Document #${src.document_id}`}
                      </a>
                      <span className="badge badge-approved" style={{ fontSize: "0.7rem" }}>
                        {Math.round(src.score * 100)}%
                      </span>
                    </div>
                    {src.snippet && (
                      <p style={{ margin: "0.25rem 0 0", color: "var(--gray-600)", fontSize: "0.78rem", lineHeight: 1.4 }}>
                        {src.snippet.length > 200 ? src.snippet.slice(0, 200) + "…" : src.snippet}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", gap: "0.5rem" }}>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question about your documents…"
          rows={2}
          style={{ flex: 1, resize: "none", fontSize: "0.9rem" }}
          disabled={loading}
        />
        <button className="btn btn-primary" onClick={handleSubmit} disabled={loading || !input.trim()}
          style={{ alignSelf: "flex-end" }}>
          {loading ? "…" : "Ask"}
        </button>
      </div>
    </div>
  );
}
