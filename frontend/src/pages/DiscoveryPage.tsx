import { useState, useRef, useEffect, useCallback, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { t } from "../i18n";

// ---------------------------------------------------------------------------
// Inline markdown + citation renderer
// Handles: **bold**, *italic*, `code`, [N] citations
// ---------------------------------------------------------------------------

function renderInline(
  text: string,
  onCiteClick?: (n: number) => void,
  sources?: Source[],
): ReactNode[] {
  const parts: ReactNode[] = [];
  // Pattern: **bold** | *italic* | `code` | [N] citation
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[(\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1]) {
      parts.push(<strong key={m.index}>{m[1]}</strong>);
    } else if (m[2]) {
      parts.push(<em key={m.index}>{m[2]}</em>);
    } else if (m[3]) {
      parts.push(
        <code key={m.index} style={{
          background: "var(--chat-code-bg)",
          border: "1px solid var(--chat-divider)",
          padding: "2px 6px", borderRadius: "4px",
          fontSize: "0.84em", fontFamily: "monospace",
          letterSpacing: "0.01em",
        }}>
          {m[3]}
        </code>
      );
    } else if (m[4]) {
      // Citation badge [N]
      const n = parseInt(m[4]);
      const src = sources?.[n - 1];
      const tooltip = src
        ? `${src.title || `Document #${src.document_id}`} (ID ${src.document_id})`
        : `Source ${n}`;
      parts.push(
        <button
          key={m.index}
          type="button"
          title={tooltip}
          onClick={() => onCiteClick?.(n)}
          style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            width: "18px", height: "18px", borderRadius: "50%",
            background: "var(--chat-number-bg)",
            color: "var(--chat-number-text)",
            fontSize: "0.62rem", fontWeight: 700,
            border: "none", cursor: onCiteClick ? "pointer" : "default",
            verticalAlign: "middle", margin: "0 1px",
            lineHeight: 1, flexShrink: 0,
            transition: "transform 0.1s, opacity 0.1s",
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.transform = "scale(1.2)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)"; }}
        >
          {n}
        </button>
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// ---------------------------------------------------------------------------
// Full markdown renderer
// ---------------------------------------------------------------------------

function MarkdownText({
  text,
  sources,
  onCiteClick,
}: {
  text: string;
  sources?: Source[];
  onCiteClick?: (n: number) => void;
}) {
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let listItems: { ordered: boolean; text: string }[] = [];
  let quoteLines: string[] = [];
  let key = 0;

  const flushList = () => {
    if (!listItems.length) return;
    const isOrdered = listItems[0].ordered;
    const Tag = isOrdered ? "ol" : "ul";
    out.push(
      <Tag key={key++} style={{ margin: "0.6rem 0 0.6rem 1.4rem", padding: 0 }}>
        {listItems.map((li, i) => (
          <li key={i} style={{ marginBottom: "0.35rem", lineHeight: 1.65 }}>
            {renderInline(li.text, onCiteClick, sources)}
          </li>
        ))}
      </Tag>
    );
    listItems = [];
  };

  const flushQuote = () => {
    if (!quoteLines.length) return;
    out.push(
      <blockquote key={key++} style={{
        margin: "0.75rem 0",
        padding: "0.65rem 1rem",
        borderLeft: "3px solid var(--chat-blockquote-border)",
        background: "var(--chat-blockquote-bg)",
        borderRadius: "0 8px 8px 0",
        fontStyle: "italic",
        color: "var(--chat-blockquote-text)",
        fontSize: "0.85rem",
        lineHeight: 1.65,
      }}>
        {quoteLines.map((l, i) => (
          <span key={i}>
            {renderInline(l, onCiteClick, sources)}
            {i < quoteLines.length - 1 ? <br /> : null}
          </span>
        ))}
      </blockquote>
    );
    quoteLines = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("> ")) { flushList(); quoteLines.push(line.slice(2)); continue; }
    flushQuote();
    if (/^[-*] /.test(line)) { listItems.push({ ordered: false, text: line.slice(2) }); continue; }
    if (/^\d+\. /.test(line)) { listItems.push({ ordered: true, text: line.replace(/^\d+\. /, "") }); continue; }
    flushList();
    // Empty line → small spacer (more controlled than <br />)
    if (!line.trim()) { out.push(<div key={key++} style={{ height: "0.45rem" }} />); continue; }
    if (line.startsWith("### ")) {
      // Section label: small-caps petrol label with a subtle bottom rule
      out.push(<p key={key++} style={{
        margin: "1.1rem 0 0.45rem",
        fontWeight: 700,
        fontSize: "0.72rem",
        color: "var(--chat-accent-text)",
        textTransform: "uppercase",
        letterSpacing: "0.09em",
        paddingBottom: "0.28rem",
        borderBottom: "1px solid var(--chat-divider)",
      }}>{renderInline(line.slice(4), onCiteClick, sources)}</p>);
    } else if (line.startsWith("## ")) {
      out.push(<p key={key++} style={{
        margin: "1rem 0 0.35rem",
        fontWeight: 700,
        fontSize: "1rem",
        color: "var(--text-on-body)",
        letterSpacing: "-0.01em",
      }}>{renderInline(line.slice(3), onCiteClick, sources)}</p>);
    } else if (line.startsWith("# ")) {
      out.push(<p key={key++} style={{
        margin: "1rem 0 0.4rem",
        fontWeight: 700,
        fontSize: "1.1rem",
        color: "var(--text-on-body)",
        letterSpacing: "-0.015em",
      }}>{renderInline(line.slice(2), onCiteClick, sources)}</p>);
    } else {
      out.push(<p key={key++} style={{ margin: "0.5rem 0", lineHeight: 1.72, color: "var(--text-on-body)" }}>{renderInline(line, onCiteClick, sources)}</p>);
    }
  }
  flushList();
  flushQuote();
  return <>{out}</>;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Suggested queries
// ---------------------------------------------------------------------------

const SUGGESTED_QUERIES = [
  "What contracts are currently active and when do they expire?",
  "Which documents mention a notice period or cancellation clause?",
  "What are the payment terms in my contracts?",
  "Find documents that mention a penalty or liability clause",
  "Which documents involve automatic renewal?",
  "What insurance policies do I have and what do they cover?",
];

// ---------------------------------------------------------------------------
// Source card (right panel)
// ---------------------------------------------------------------------------

function SourceCard({
  src,
  index,
  highlighted,
}: {
  src: Source;
  index: number;
  highlighted: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const PREVIEW = 220;
  const needsTruncation = src.snippet.length > PREVIEW;
  const displayText = expanded || !needsTruncation ? src.snippet : src.snippet.slice(0, PREVIEW) + "…";
  const scoreVar = src.score > 0.75 ? "high" : src.score > 0.5 ? "med" : "low";

  return (
    <div
      id={`source-${index + 1}`}
      style={{
        background: highlighted ? "var(--chat-accent-bg)" : "var(--chat-source-bg)",
        border: `1px solid ${highlighted ? "var(--chat-accent-border)" : "var(--chat-source-border)"}`,
        borderRadius: "12px",
        padding: "0.75rem",
        marginBottom: "0.5rem",
        transition: "background 0.3s, border-color 0.3s",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", marginBottom: "0.4rem" }}>
        {/* Number badge */}
        <span style={{
          background: "var(--chat-number-bg)",
          color: "var(--chat-number-text)",
          borderRadius: "50%",
          width: "20px", height: "20px", minWidth: "20px",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "0.65rem", fontWeight: 700, marginTop: "2px",
        }}>
          {index + 1}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title */}
          <p style={{
            margin: 0,
            fontWeight: 600,
            fontSize: "0.83rem",
            color: "var(--text-on-body)",
            lineHeight: 1.35,
            wordBreak: "break-word",
          }}>
            {src.title || `Document #${src.document_id}`}
          </p>
          {/* ID chip + score + open */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", marginTop: "0.3rem", flexWrap: "wrap" }}>
            <span style={{
              fontSize: "0.68rem",
              color: "var(--text-on-body-secondary)",
              background: "var(--chat-passage-bg)",
              border: "1px solid var(--chat-divider)",
              borderRadius: "4px",
              padding: "1px 5px",
              fontFamily: "monospace",
              flexShrink: 0,
            }}>
              #{src.document_id}
            </span>
            <span style={{
              fontSize: "0.68rem",
              color: `var(--score-${scoreVar}-text)`,
              background: `var(--score-${scoreVar}-bg)`,
              border: `1px solid var(--score-${scoreVar}-border)`,
              borderRadius: "10px",
              padding: "1px 6px",
              fontWeight: 600,
              flexShrink: 0,
            }}>
              {Math.round(src.score * 100)}%
            </span>
            <a
              href={src.deeplink_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: "0.68rem",
                color: "var(--chat-accent-text)",
                textDecoration: "none",
                fontWeight: 500,
                flexShrink: 0,
                marginLeft: "auto",
              }}
            >
              Open ↗
            </a>
          </div>
        </div>
      </div>

      {/* Passage */}
      {src.snippet && (
        <div style={{
          marginTop: "0.35rem",
          padding: "0.45rem 0.6rem",
          background: "var(--chat-passage-bg)",
          borderRadius: "6px",
          borderLeft: "2px solid var(--chat-passage-border)",
        }}>
          <p style={{
            margin: 0,
            fontSize: "0.76rem",
            color: "var(--text-on-body-secondary)",
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
          }}>
            {displayText}
          </p>
          {needsTruncation && (
            <button
              onClick={() => setExpanded(e => !e)}
              style={{
                marginTop: "0.3rem",
                background: "none", border: "none",
                color: "var(--chat-accent-text)",
                fontSize: "0.72rem", cursor: "pointer", padding: 0, fontWeight: 500,
              }}
            >
              {expanded ? "▲ Less" : `▼ +${src.snippet.length - PREVIEW} chars`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function DiscoveryPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [latestSources, setLatestSources] = useState<Source[]>([]);
  const [highlightedSource, setHighlightedSource] = useState<number | null>(null);

  // Session ID is kept in a ref — it doesn't drive rendering, just needs to
  // survive between submits.  Null = no session yet (first question creates one).
  const sessionIdRef = useRef<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sourcesPanelRef = useRef<HTMLDivElement>(null);
  const inputContainerRef = useRef<HTMLDivElement>(null);

  // Status query for paperless URL
  const statusQ = useQuery({ queryKey: ["status"], queryFn: api.getStatus, retry: false, staleTime: 60000 });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  const autoResize = useCallback((el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  // Scroll sources panel to a specific source and briefly highlight it
  const scrollToSource = useCallback((n: number) => {
    const el = sourcesPanelRef.current?.querySelector(`#source-${n}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      setHighlightedSource(n);
      setTimeout(() => setHighlightedSource(null), 1800);
    }
  }, []);

  const handleSubmit = async (question?: string) => {
    const q = (question ?? input).trim();
    if (!q || loading) return;
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    setMessages(prev => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "", loading: true },
    ]);
    setLoading(true);
    textareaRef.current?.focus();

    try {
      const result = await api.discover(q, 5, sessionIdRef.current);
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
      setLatestSources(result.sources as Source[]);
      // Store the session ID returned by the backend (set on first response)
      if (result.session_id) sessionIdRef.current = result.session_id;
    } catch (err: unknown) {
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: "", error: (err as Error).message },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleNewConversation = useCallback(async () => {
    if (sessionIdRef.current) {
      try { await api.deleteDiscoverSession(sessionIdRef.current); } catch { /* ignore */ }
      sessionIdRef.current = null;
    }
    setMessages([]);
    setLatestSources([]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const hasInput = input.trim().length > 0;
  const hasSources = latestSources.length > 0;

  return (
    <>
      {/* Responsive layout styles */}
      <style>{`
        .discovery-layout {
          display: flex;
          gap: 1rem;
          min-height: 0;
          overflow: hidden;
        }
        .discovery-chat {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .discovery-sources {
          width: 300px;
          flex-shrink: 0;
          overflow-y: auto;
          border-left: 1px solid var(--chat-divider);
          padding-left: 1rem;
        }
        @media (max-width: 820px) {
          .discovery-layout { flex-direction: column; }
          .discovery-sources {
            width: 100% !important;
            border-left: none;
            border-top: 1px solid var(--chat-divider);
            padding-left: 0;
            padding-top: 0.75rem;
            max-height: 280px;
          }
        }
        .discovery-input-wrap {
          display: flex;
          align-items: flex-end;
          gap: 0.6rem;
          background: var(--bg-input);
          border-radius: 24px;
          padding: 0.45rem 0.45rem 0.45rem 1.1rem;
          border: 1px solid var(--gray-300);
          box-shadow: var(--shadow-sm);
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .discovery-input-wrap:focus-within {
          border-color: var(--petrol-400);
          box-shadow: 0 0 0 3px rgba(33, 153, 153, 0.12);
        }
        .discovery-send-btn {
          width: 34px; height: 34px;
          border-radius: 50%;
          border: none;
          display: flex; align-items: center; justify-content: center;
          font-size: 1rem;
          flex-shrink: 0;
          transition: background 0.2s, color 0.2s, transform 0.1s;
          cursor: pointer;
        }
        .discovery-send-btn:hover:not(:disabled) { transform: scale(1.08); }
        .discovery-send-btn:active:not(:disabled) { transform: scale(0.95); }
        .discovery-msg-enter {
          animation: discoveryMsgIn 0.2s ease-out;
        }
        @keyframes discoveryMsgIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .discovery-chip {
          transition: background 0.15s, border-color 0.15s;
        }
        .discovery-chip:hover {
          background: var(--chat-suggestion-bg-hover) !important;
          border-color: var(--chat-suggestion-border-hover) !important;
        }
        /* Markdown content wrapper — removes top/bottom bleed on first/last child */
        .discovery-answer > *:first-child { margin-top: 0 !important; }
        .discovery-answer > *:last-child  { margin-bottom: 0 !important; }
        /* Animated loading dots */
        @keyframes discoveryDot {
          0%, 60%, 100% { transform: translateY(0);    opacity: 0.35; }
          30%            { transform: translateY(-4px); opacity: 1;    }
        }
      `}</style>

      <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 7rem)" }}>

        {/* Header */}
        <div style={{ flexShrink: 0, marginBottom: "0.6rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "1rem" }}>
          <div>
            <h2 style={{ margin: "0 0 0.2rem" }}>{t("discovery.title")}</h2>
            <p style={{ fontSize: "0.82rem", color: "var(--text-on-body-secondary)", margin: 0 }}>
              {t("discovery.subtitle")}
            </p>
          </div>
          {messages.length > 0 && (
            <button
              onClick={handleNewConversation}
              disabled={loading}
              style={{
                flexShrink: 0,
                padding: "0.35rem 0.85rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--petrol-300)",
                background: "var(--petrol-50)",
                color: "var(--petrol-700)",
                fontSize: "0.8rem",
                fontWeight: 500,
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              ✦ New conversation
            </button>
          )}
        </div>

        {/* Two-column body */}
        <div className="discovery-layout" style={{ flex: 1 }}>

          {/* ── Left: chat column ── */}
          <div className="discovery-chat">

            {/* Messages scroll area */}
            <div style={{ flex: 1, overflowY: "auto", paddingRight: "2px", paddingBottom: "0.5rem" }}>

              {/* Empty state */}
              {messages.length === 0 && (
                <div style={{ paddingTop: "2rem", maxWidth: "520px" }}>
                  <p style={{ fontSize: "1.05rem", fontWeight: 600, color: "var(--text-on-body)", marginBottom: "0.3rem" }}>
                    {t("discovery.emptyTitle")}
                  </p>
                  <p style={{ fontSize: "0.82rem", color: "var(--text-on-body-secondary)", margin: "0 0 1.25rem" }}>
                    {t("discovery.emptyHint")}
                  </p>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem" }}>
                    {SUGGESTED_QUERIES.map((q, i) => (
                      <button
                        key={i}
                        className="discovery-chip"
                        onClick={() => handleSubmit(q)}
                        style={{
                          padding: "0.4rem 0.9rem",
                          borderRadius: "20px",
                          border: "1px solid var(--chat-suggestion-border)",
                          background: "var(--chat-suggestion-bg)",
                          color: "var(--chat-suggestion-text)",
                          fontSize: "0.79rem",
                          cursor: "pointer",
                          textAlign: "left",
                          lineHeight: 1.4,
                        }}
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Messages */}
              {messages.map((msg, i) => (
                <div key={i} className="discovery-msg-enter" style={{ marginBottom: "1rem" }}>
                  {msg.role === "user" ? (
                    /* ── User bubble (right-aligned, filled) ── */
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <div style={{
                        padding: "0.65rem 1.1rem",
                        borderRadius: "20px 20px 4px 20px",
                        background: "var(--petrol-600)",
                        maxWidth: "78%",
                        fontSize: "0.9rem",
                        lineHeight: 1.55,
                        color: "#fff",
                        boxShadow: "var(--shadow-sm)",
                        wordBreak: "break-word",
                      }}>
                        {msg.content}
                      </div>
                    </div>
                  ) : (
                    /* ── Assistant bubble (left-aligned, card surface) ── */
                    <div style={{ maxWidth: "100%" }}>
                      {/* AI label */}
                      <div style={{
                        fontSize: "0.69rem",
                        color: "var(--chat-ai-label)",
                        marginBottom: "0.3rem",
                        display: "flex",
                        alignItems: "center",
                        gap: "0.35rem",
                        paddingLeft: "0.1rem",
                      }}>
                        <span style={{
                          width: "18px", height: "18px",
                          background: "var(--chat-ai-icon-bg)",
                          borderRadius: "50%",
                          display: "inline-flex", alignItems: "center", justifyContent: "center",
                          fontSize: "0.65rem",
                          color: "var(--chat-accent-text)",
                          fontWeight: 700,
                        }}>✦</span>
                        Paperless IQ
                      </div>

                      {/* Content bubble */}
                      <div style={{
                        padding: "1rem 1.2rem",
                        borderRadius: "4px 20px 20px 20px",
                        background: "var(--chat-assistant-bg)",
                        border: "1px solid var(--chat-assistant-border)",
                        fontSize: "0.875rem",
                        lineHeight: 1.72,
                        color: "var(--text-on-body)",
                        boxShadow: "var(--shadow-sm)",
                        wordBreak: "break-word",
                      }}>
                        {msg.loading ? (
                          <span style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}>
                            <span style={{ display: "inline-flex", gap: "4px", alignItems: "center" }}>
                              {[0, 1, 2].map(i => (
                                <span key={i} style={{
                                  width: "6px", height: "6px", borderRadius: "50%",
                                  background: "var(--chat-loading)",
                                  display: "inline-block",
                                  animation: `discoveryDot 1.3s ease-in-out ${i * 0.18}s infinite`,
                                }} />
                              ))}
                            </span>
                            <span style={{ color: "var(--chat-loading)", fontSize: "0.82rem" }}>
                              {t("discovery.searching")}
                            </span>
                          </span>
                        ) : msg.error ? (
                          <span style={{ color: "var(--error-text, var(--error))" }}>⚠ {msg.error}</span>
                        ) : (
                          <div className="discovery-answer">
                            <MarkdownText
                              text={msg.content}
                              sources={msg.sources}
                              onCiteClick={msg.sources?.length ? scrollToSource : undefined}
                            />
                          </div>
                        )}
                      </div>

                      {/* Mini source count below bubble (when sources exist) */}
                      {msg.sources && msg.sources.length > 0 && (
                        <div style={{ marginTop: "0.35rem", paddingLeft: "0.1rem" }}>
                          <span style={{ fontSize: "0.72rem", color: "var(--text-on-body-secondary)" }}>
                            {msg.sources.length} {msg.sources.length === 1 ? "source" : "sources"} →
                          </span>
                          {msg.sources.map((src, j) => (
                            <button
                              key={j}
                              type="button"
                              title={`${src.title || `#${src.document_id}`} (ID ${src.document_id})`}
                              onClick={() => scrollToSource(j + 1)}
                              style={{
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                                width: "18px", height: "18px", borderRadius: "50%",
                                background: "var(--chat-number-bg)",
                                color: "var(--chat-number-text)",
                                fontSize: "0.6rem", fontWeight: 700,
                                border: "none", cursor: "pointer",
                                margin: "0 2px", lineHeight: 1,
                              }}
                            >
                              {j + 1}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            {/* ── Input area (MD3-style) ── */}
            <div style={{ flexShrink: 0, paddingTop: "0.6rem", borderTop: "1px solid var(--chat-divider)" }}>
              <div ref={inputContainerRef} className="discovery-input-wrap">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={e => { setInput(e.target.value); autoResize(e.target); }}
                  onKeyDown={handleKeyDown}
                  placeholder={t("discovery.placeholder")}
                  rows={1}
                  disabled={loading}
                  style={{
                    flex: 1,
                    border: "none",
                    background: "transparent",
                    resize: "none",
                    fontSize: "0.9rem",
                    lineHeight: 1.55,
                    outline: "none",
                    color: "var(--text-on-body)",
                    maxHeight: "120px",
                    overflowY: "auto",
                    padding: "0.3rem 0",
                    fontFamily: "inherit",
                  }}
                />
                <button
                  className="discovery-send-btn"
                  onClick={() => handleSubmit()}
                  disabled={loading || !hasInput}
                  style={{
                    background: hasInput && !loading ? "var(--petrol-600)" : "var(--gray-200)",
                    color: hasInput && !loading ? "#fff" : "var(--gray-500)",
                  }}
                  title="Send (Enter)"
                >
                  {loading ? (
                    <span style={{ fontSize: "0.8rem", animation: "spin 1s linear infinite" }}>⟳</span>
                  ) : "↑"}
                </button>
              </div>
              <p style={{ margin: "0.3rem 0 0 0.25rem", fontSize: "0.68rem", color: "var(--chat-enter-hint)" }}>
                Enter · Shift+Enter for newline
              </p>
            </div>
          </div>

          {/* ── Right: Sources panel ── */}
          {hasSources && (
            <div
              ref={sourcesPanelRef}
              className="discovery-sources"
            >
              <div style={{ flexShrink: 0, marginBottom: "0.65rem", display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                <p style={{
                  margin: 0,
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  color: "var(--text-on-body-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.07em",
                }}>
                  {t("discovery.sources")} {latestSources.length}
                </p>
                {statusQ.data?.paperless_public_url && (
                  <a
                    href={statusQ.data.paperless_public_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: "0.68rem",
                      color: "var(--chat-accent-text)",
                      textDecoration: "none",
                    }}
                  >
                    Open Paperless ↗
                  </a>
                )}
              </div>
              {latestSources.map((src, j) => (
                <SourceCard
                  key={j}
                  src={src}
                  index={j}
                  highlighted={highlightedSource === j + 1}
                />
              ))}
            </div>
          )}

        </div>
      </div>
    </>
  );
}
