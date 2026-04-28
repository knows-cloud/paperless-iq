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
      <p style={{ fontSize: "0.85rem", color: "#666", margin: "0 0 0.75rem" }}>
        Ask questions about your documents. Answers are grounded in your actual document content with citations.
      </p>

      <div style={{ flex: 1, overflowY: "auto", marginBottom: "0.75rem" }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "#999", marginTop: "3rem" }}>
            <p style={{ fontSize: "1.1rem" }}>Ask anything about your documents</p>
            <p style={{ fontSize: "0.85rem" }}>e.g. "What invoices did I receive from Amazon in 2024?" or "Find my travel documents for Gran Canaria"</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: "1rem" }}>
            <div style={{
              padding: "0.75rem",
              borderRadius: "8px",
              background: msg.role === "user" ? "#e3f2fd" : "#f5f5f5",
              maxWidth: "90%",
              marginLeft: msg.role === "user" ? "auto" : "0",
            }}>
              {msg.loading ? (
                <p style={{ color: "#666", fontStyle: "italic", margin: 0 }}>Searching documents and generating answer…</p>
              ) : msg.error ? (
                <p className="error" style={{ margin: 0 }}>{msg.error}</p>
              ) : (
                <div style={{ whiteSpace: "pre-wrap", fontSize: "0.9rem", lineHeight: 1.6 }}>{msg.content}</div>
              )}
            </div>
            {msg.sources && msg.sources.length > 0 && (
              <div style={{ marginTop: "0.5rem", paddingLeft: "0.5rem" }}>
                <p style={{ fontSize: "0.8rem", color: "#666", margin: "0 0 0.25rem", fontWeight: 600 }}>Sources:</p>
                {msg.sources.map((src, j) => (
                  <div key={j} style={{ fontSize: "0.8rem", marginBottom: "0.4rem", padding: "0.5rem", background: "#fafafa", borderRadius: "4px", border: "1px solid #eee" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <a href={src.deeplink_url} target="_blank" rel="noopener noreferrer"
                        style={{ fontWeight: 600, color: "#1565c0", textDecoration: "none" }}>
                        {src.title || `Document #${src.document_id}`}
                      </a>
                      <span style={{ color: "#999", fontSize: "0.75rem" }}>
                        {Math.round(src.score * 100)}% match
                      </span>
                    </div>
                    {src.snippet && (
                      <p style={{ margin: "0.25rem 0 0", color: "#555", fontSize: "0.78rem", lineHeight: 1.4 }}>
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
