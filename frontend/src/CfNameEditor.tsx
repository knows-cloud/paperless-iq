import { useState, useRef, useEffect } from "react";

interface CfNameEditorProps {
  name: string;
  value: unknown;
  isNew: boolean;
  suggestions: string[];
  onRename: (newName: string) => void;
  onChangeValue: (value: string) => void;
  onRemove: () => void;
}

/**
 * Editable custom field row: name (with autocomplete) + value + remove button.
 * Name changes only commit on blur or suggestion selection, not on every keystroke.
 */
export default function CfNameEditor({ name, value, isNew, suggestions, onRename, onChangeValue, onRemove }: CfNameEditorProps) {
  const [editName, setEditName] = useState(name);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  // Sync if parent changes the key (e.g. after rename)
  useEffect(() => { setEditName(name); }, [name]);

  const filtered = editName.trim()
    ? suggestions.filter(s => s.toLowerCase().includes(editName.toLowerCase()) && s.toLowerCase() !== editName.toLowerCase()).slice(0, 8)
    : [];

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setShowSuggestions(false);
        commitName();
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  });

  useEffect(() => { setSelectedIdx(0); }, [editName]);

  const commitName = () => {
    const trimmed = editName.trim();
    if (trimmed && trimmed !== name) onRename(trimmed);
    else setEditName(name); // revert if empty
    setShowSuggestions(false);
  };

  const selectSuggestion = (s: string) => {
    setEditName(s);
    setShowSuggestions(false);
    if (s !== name) onRename(s);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSuggestions && filtered.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, filtered.length - 1)); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); return; }
      if (e.key === "Tab") { e.preventDefault(); selectSuggestion(filtered[selectedIdx]); return; }
    }
    if (e.key === "Enter") { e.preventDefault(); commitName(); }
    if (e.key === "Escape") { setEditName(name); setShowSuggestions(false); }
  };

  const nameStyle = isNew
    ? { color: "var(--error-on-card, #c62828)", fontWeight: 700, fontSize: "0.85rem" }
    : { color: "var(--text-on-card-secondary)", fontSize: "0.85rem" };

  return (
    <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.35rem" }}>
      <div ref={ref} style={{ position: "relative", minWidth: "140px", maxWidth: "180px" }}>
        <input
          value={editName}
          onChange={e => { setEditName(e.target.value); setShowSuggestions(true); }}
          onFocus={() => { if (editName.trim()) setShowSuggestions(true); }}
          onBlur={() => { /* handled by mousedown listener */ }}
          onKeyDown={handleKeyDown}
          style={{ width: "100%", ...nameStyle }}
        />
        {showSuggestions && filtered.length > 0 && (
          <ul style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
            background: "var(--bg-input)", border: "1px solid var(--gray-300)", borderTop: "none",
            borderRadius: "0 0 var(--radius-sm) var(--radius-sm)",
            maxHeight: "150px", overflowY: "auto", margin: 0, padding: 0,
            listStyle: "none", boxShadow: "var(--shadow-md)",
          }}>
            {filtered.map((s, i) => (
              <li key={s}
                style={{
                  padding: "4px 8px", cursor: "pointer", fontSize: "0.83rem",
                  background: i === selectedIdx ? "var(--petrol-50)" : "transparent",
                  color: i === selectedIdx ? "var(--petrol-800)" : "var(--gray-700)",
                }}
                onMouseDown={() => selectSuggestion(s)}
                onMouseEnter={() => setSelectedIdx(i)}>
                {s}
              </li>
            ))}
          </ul>
        )}
      </div>
      <input value={String(value ?? "")} style={{ fontSize: "0.85rem", flex: 1 }}
        onChange={e => onChangeValue(e.target.value)} />
      <button type="button" onClick={onRemove}
        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-on-card-muted)", fontSize: "1rem" }}>×</button>
    </div>
  );
}
