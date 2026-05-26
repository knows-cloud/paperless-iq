/**
 * Inline markdown + citation renderer.
 *
 * Handles: **bold**, *italic*, `code`, blockquotes, bullet/ordered lists,
 * headings (#, ##, ###) and [N] citation badges.
 *
 * Used by DiscoveryPage to render LLM answers with source citations.
 */

import { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Source {
  document_id: number;
  title: string;
  score: number;
  deeplink_url: string;
  snippet: string;
}

// ---------------------------------------------------------------------------
// Inline renderer (bold, italic, code, citation badges)
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
          background: "var(--mantine-color-default-hover)",
          border: "1px solid var(--mantine-color-default-border)",
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
            background: "var(--mantine-color-teal-6)",
            color: "white",
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
// MarkdownText component
// ---------------------------------------------------------------------------

export function MarkdownText({
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
        borderLeft: "3px solid var(--mantine-color-teal-4)",
        background: "var(--mantine-color-default-hover)",
        borderRadius: "0 8px 8px 0",
        fontStyle: "italic",
        color: "var(--mantine-color-dimmed)",
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
        color: "var(--mantine-color-teal-6)",
        textTransform: "uppercase",
        letterSpacing: "0.09em",
        paddingBottom: "0.28rem",
        borderBottom: "1px solid var(--mantine-color-default-border)",
      }}>{renderInline(line.slice(4), onCiteClick, sources)}</p>);
    } else if (line.startsWith("## ")) {
      out.push(<p key={key++} style={{
        margin: "1rem 0 0.35rem",
        fontWeight: 700,
        fontSize: "1rem",
        color: "inherit",
        letterSpacing: "-0.01em",
      }}>{renderInline(line.slice(3), onCiteClick, sources)}</p>);
    } else if (line.startsWith("# ")) {
      out.push(<p key={key++} style={{
        margin: "1rem 0 0.4rem",
        fontWeight: 700,
        fontSize: "1.1rem",
        color: "inherit",
        letterSpacing: "-0.015em",
      }}>{renderInline(line.slice(2), onCiteClick, sources)}</p>);
    } else {
      out.push(<p key={key++} style={{ margin: "0.5rem 0", lineHeight: 1.72 }}>{renderInline(line, onCiteClick, sources)}</p>);
    }
  }
  flushList();
  flushQuote();
  return <>{out}</>;
}
