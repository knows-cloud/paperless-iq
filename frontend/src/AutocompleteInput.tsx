import { useState, useRef, useEffect } from "react";

interface AutocompleteInputProps {
  value: string;
  suggestions: string[];
  onChange: (value: string) => void;
  placeholder?: string;
  style?: React.CSSProperties;
}

/** Single-value input with dropdown autocomplete suggestions. */
export default function AutocompleteInput({ value, suggestions, onChange, placeholder, style }: AutocompleteInputProps) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const filtered = value.trim()
    ? suggestions.filter(s => s.toLowerCase().includes(value.toLowerCase()) && s.toLowerCase() !== value.toLowerCase()).slice(0, 8)
    : [];

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setShowSuggestions(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => { setSelectedIdx(0); }, [value]);

  const commit = (val: string) => {
    onChange(val);
    setShowSuggestions(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSuggestions && filtered.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, filtered.length - 1)); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); return; }
      if (e.key === "Tab") {
        e.preventDefault();
        commit(filtered[selectedIdx]);
        return;
      }
    }
    if (e.key === "Escape") { setShowSuggestions(false); }
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <input
        value={value}
        onChange={e => { onChange(e.target.value); setShowSuggestions(true); }}
        onFocus={() => { if (value.trim()) setShowSuggestions(true); }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        style={{ fontSize: "0.85rem", width: "100%", ...style }}
      />
      {showSuggestions && filtered.length > 0 && (
        <ul style={{
          position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
          background: "#fff", border: "1px solid var(--gray-300)", borderTop: "none",
          borderRadius: "0 0 var(--radius-sm) var(--radius-sm)",
          maxHeight: "180px", overflowY: "auto", margin: 0, padding: 0,
          listStyle: "none", boxShadow: "var(--shadow-md)",
        }}>
          {filtered.map((item, i) => (
            <li key={item}
              style={{
                padding: "5px 10px", cursor: "pointer", fontSize: "0.85rem",
                background: i === selectedIdx ? "var(--petrol-50)" : "transparent",
                color: i === selectedIdx ? "var(--petrol-800)" : "var(--gray-700)",
              }}
              onMouseDown={() => commit(item)}
              onMouseEnter={() => setSelectedIdx(i)}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
