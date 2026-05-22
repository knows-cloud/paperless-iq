import { api } from "../../api";

export type MemoryItem = {
  id: string;
  text: string;
  created_at: string;
  updated_at: string;
  source_session_id: string | null;
};

interface Props {
  memoryEnabled: boolean;
  setMemoryEnabled: (v: boolean) => void;
  memories: MemoryItem[];
  setMemories: React.Dispatch<React.SetStateAction<MemoryItem[]>>;
  memoriesLoading: boolean;
  editingMemoryId: string | null;
  setEditingMemoryId: (v: string | null) => void;
  editMemoryText: string;
  setEditMemoryText: (v: string) => void;
  clearMemoriesConfirm: boolean;
  setClearMemoriesConfirm: (v: boolean) => void;
}

export function MemoriesTab({
  memoryEnabled, setMemoryEnabled,
  memories, setMemories,
  memoriesLoading,
  editingMemoryId, setEditingMemoryId,
  editMemoryText, setEditMemoryText,
  clearMemoriesConfirm, setClearMemoriesConfirm,
}: Props) {
  const sectionHead: React.CSSProperties = {
    marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem",
  };

  return (
    <div className="card">
      <h3>Long-term Memory</h3>

      {/* Enable toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.65rem", marginBottom: "0.4rem" }}>
        <input
          type="checkbox"
          id="memory_enabled_toggle"
          checked={memoryEnabled}
          onChange={e => setMemoryEnabled(e.target.checked)}
          style={{ width: "1rem", height: "1rem" }}
        />
        <label htmlFor="memory_enabled_toggle" style={{ fontWeight: 500, fontSize: "0.9rem", cursor: "pointer", margin: 0 }}>
          Enable long-term memory
        </label>
      </div>
      <p style={{ fontSize: "0.82rem", color: "var(--text-on-card-secondary, var(--gray-600))", marginBottom: "1.25rem", lineHeight: 1.5 }}>
        When enabled, key facts are automatically extracted from Discovery conversations and injected as context in future chats.
        Facts are deduplicated — similar entries are merged rather than duplicated.
      </p>

      {/* Section header + Clear all */}
      <div style={{ ...sectionHead, display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 0 }}>
        <h4 style={{ margin: 0, fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--gray-500)" }}>
          Learned facts {memories.length > 0 && `(${memories.length})`}
        </h4>
        {memories.length > 0 && !clearMemoriesConfirm && (
          <button type="button" className="btn btn-danger" style={{ padding: "0.25rem 0.65rem", fontSize: "0.76rem" }}
            onClick={() => setClearMemoriesConfirm(true)}>
            Clear all
          </button>
        )}
        {clearMemoriesConfirm && (
          <span style={{ fontSize: "0.8rem", display: "flex", gap: "0.5rem", alignItems: "center" }}>
            Are you sure?
            <button type="button" className="btn btn-danger" style={{ padding: "0.2rem 0.55rem", fontSize: "0.76rem" }}
              onClick={async () => {
                await api.clearMemories();
                setMemories([]);
                setClearMemoriesConfirm(false);
              }}>Yes, clear</button>
            <button type="button" className="btn" style={{ padding: "0.2rem 0.55rem", fontSize: "0.76rem" }}
              onClick={() => setClearMemoriesConfirm(false)}>Cancel</button>
          </span>
        )}
      </div>

      {/* Memories list */}
      {memoriesLoading ? (
        <p style={{ fontSize: "0.83rem", color: "var(--gray-500)", marginTop: "0.75rem" }}>Loading…</p>
      ) : memories.length === 0 ? (
        <p style={{ fontSize: "0.83rem", color: "var(--gray-500)", marginTop: "0.75rem" }}>
          No memories yet. Facts will appear here after Discovery conversations are closed.
        </p>
      ) : (
        <div style={{ marginTop: "0.5rem" }}>
          {memories.map(mem => (
            <div key={mem.id} style={{
              display: "flex", alignItems: "flex-start", gap: "0.6rem",
              padding: "0.55rem 0.75rem",
              background: "var(--gray-50)",
              border: "1px solid var(--gray-200)",
              borderRadius: "var(--radius-sm)",
              marginBottom: "0.4rem",
            }}>
              <span style={{ color: "var(--petrol-400)", fontSize: "1rem", lineHeight: 1.5, flexShrink: 0 }}>•</span>

              {editingMemoryId === mem.id ? (
                <div style={{ flex: 1 }}>
                  <textarea
                    value={editMemoryText}
                    onChange={e => setEditMemoryText(e.target.value)}
                    rows={2}
                    style={{
                      width: "100%", resize: "vertical", fontSize: "0.83rem",
                      padding: "0.35rem 0.5rem", borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--petrol-400)", fontFamily: "inherit",
                      background: "var(--bg-input)", color: "var(--gray-800)",
                    }}
                    autoFocus
                  />
                  <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.3rem" }}>
                    <button type="button" className="btn btn-primary" style={{ padding: "0.25rem 0.65rem", fontSize: "0.76rem" }}
                      onClick={async () => {
                        await api.updateMemory(mem.id, editMemoryText);
                        setEditingMemoryId(null);
                        setMemories(prev => prev.map(m => m.id === mem.id ? { ...m, text: editMemoryText } : m));
                      }}>Save</button>
                    <button type="button" className="btn" style={{ padding: "0.25rem 0.65rem", fontSize: "0.76rem" }}
                      onClick={() => setEditingMemoryId(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <span style={{ flex: 1, fontSize: "0.83rem", lineHeight: 1.55, color: "var(--gray-800)", paddingTop: "0.1rem" }}>
                  {mem.text}
                </span>
              )}

              {editingMemoryId !== mem.id && (
                <div style={{ display: "flex", gap: "0.35rem", flexShrink: 0 }}>
                  <button type="button" title="Edit" style={{
                    background: "none", border: "none", cursor: "pointer",
                    fontSize: "0.85rem", color: "var(--gray-500)", padding: "0.1rem 0.25rem",
                    borderRadius: "var(--radius-sm)",
                  }}
                    onClick={() => { setEditingMemoryId(mem.id); setEditMemoryText(mem.text); }}>
                    ✎
                  </button>
                  <button type="button" title="Delete" style={{
                    background: "none", border: "none", cursor: "pointer",
                    fontSize: "0.85rem", color: "var(--error)", padding: "0.1rem 0.25rem",
                    borderRadius: "var(--radius-sm)",
                  }}
                    onClick={async () => {
                      await api.deleteMemory(mem.id);
                      setMemories(prev => prev.filter(m => m.id !== mem.id));
                    }}>
                    ✕
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Date hint for last entry */}
      {memories.length > 0 && (
        <p style={{ fontSize: "0.72rem", color: "var(--gray-400)", marginTop: "0.5rem" }}>
          Most recent: {new Date(memories[0].updated_at).toLocaleDateString()}
        </p>
      )}
    </div>
  );
}
