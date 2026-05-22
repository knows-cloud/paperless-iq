interface Props {
  s: Record<string, unknown>;
  themePrimary: string;
  setThemePrimary: (v: string) => void;
  themeTextColor: string;
  setThemeTextColor: (v: string) => void;
  themeChipColor: string;
  setThemeChipColor: (v: string) => void;
  themeSidebarFrom: string;
  setThemeSidebarFrom: (v: string) => void;
  themeSidebarTo: string;
  setThemeSidebarTo: (v: string) => void;
  themeBgColor: string;
  setThemeBgColor: (v: string) => void;
  themeCardColor: string;
  setThemeCardColor: (v: string) => void;
  themeCardAltHex: string;
  setThemeCardAltHex: (v: string) => void;
  themeCardAltOpacity: number;
  setThemeCardAltOpacity: (v: number) => void;
  themeFont: string;
  setThemeFont: (v: string) => void;
  themeFontSize: string;
  setThemeFontSize: (v: string) => void;
  themeLogo: string;
  setThemeLogo: (v: string) => void;
  themeNavIcons: Record<string, string>;
  setThemeNavIcons: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  logoNames: string[];
}

export function AppearanceTab({
  s,
  themePrimary, setThemePrimary,
  themeTextColor, setThemeTextColor,
  themeChipColor, setThemeChipColor,
  themeSidebarFrom, setThemeSidebarFrom,
  themeSidebarTo, setThemeSidebarTo,
  themeBgColor, setThemeBgColor,
  themeCardColor, setThemeCardColor,
  themeCardAltHex, setThemeCardAltHex,
  themeCardAltOpacity, setThemeCardAltOpacity,
  themeFont, setThemeFont,
  themeFontSize, setThemeFontSize,
  themeLogo, setThemeLogo,
  themeNavIcons, setThemeNavIcons,
  logoNames,
}: Props) {
  const sectionHead: React.CSSProperties = {
    marginTop: "1rem", borderBottom: "1px solid var(--gray-200)", paddingBottom: "0.3rem",
  };

  return (<>
    <div className="card">
      <h3>Theme</h3>

      <h4 style={sectionHead}>Colors</h4>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Primary Color</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themePrimary} onChange={e => setThemePrimary(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themePrimary} onChange={e => setThemePrimary(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Text Color</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeTextColor} onChange={e => setThemeTextColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeTextColor} onChange={e => setThemeTextColor(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Tag / Chip Color</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeChipColor || themePrimary} onChange={e => setThemeChipColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeChipColor} onChange={e => setThemeChipColor(e.target.value)} placeholder="Leave empty to follow primary" style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
          <small>Color for tag and attribute chips. Leave empty to use the primary color.</small>
        </div>
      </div>

      <h4 style={sectionHead}>Sidebar</h4>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Gradient Top</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeSidebarFrom} onChange={e => setThemeSidebarFrom(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeSidebarFrom} onChange={e => setThemeSidebarFrom(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Gradient Bottom</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeSidebarTo} onChange={e => setThemeSidebarTo(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeSidebarTo} onChange={e => setThemeSidebarTo(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
        </div>
      </div>

      <h4 style={sectionHead}>Content Area</h4>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Page Background</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeBgColor} onChange={e => setThemeBgColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeBgColor} onChange={e => setThemeBgColor(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Card Background</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeCardColor} onChange={e => setThemeCardColor(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeCardColor} onChange={e => setThemeCardColor(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "200px" }}>
          <label>Alternating Row</label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input type="color" value={themeCardAltHex} onChange={e => setThemeCardAltHex(e.target.value)} style={{ width: "40px", height: "34px", padding: "2px", cursor: "pointer" }} />
            <input value={themeCardAltHex} onChange={e => setThemeCardAltHex(e.target.value)} style={{ fontSize: "0.85rem", fontFamily: "'Roboto Mono', monospace", flex: 1 }} />
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.35rem" }}>
            <label style={{ fontSize: "0.8rem", color: "var(--text-on-card-muted)", margin: 0, minWidth: "65px" }}>Opacity {themeCardAltOpacity}%</label>
            <input type="range" min="0" max="100" value={themeCardAltOpacity} onChange={e => setThemeCardAltOpacity(Number(e.target.value))} style={{ flex: 1 }} />
          </div>
        </div>
      </div>

      <h4 style={sectionHead}>Typography</h4>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        <div className="form-group" style={{ flex: 2, minWidth: "200px" }}>
          <label>Font</label>
          <select value={themeFont} onChange={e => setThemeFont(e.target.value)} style={{ fontSize: "0.85rem" }}>
            <option value="Roboto">Roboto</option>
            <option value="Open Sans">Open Sans</option>
            <option value="Inter">Inter</option>
            <option value="Fira Sans">Fira Sans</option>
            <option value="Source Sans 3">Source Sans 3</option>
            <option value="Nunito">Nunito</option>
            <option value="Ubuntu">Ubuntu</option>
            <option value="Noto Sans">Noto Sans (full Unicode)</option>
            <option value="JetBrains Mono">JetBrains Mono</option>
            <option value="Fira Code">Fira Code</option>
          </select>
        </div>
        <div className="form-group" style={{ flex: 1, minWidth: "100px" }}>
          <label>Size</label>
          <select value={themeFontSize} onChange={e => setThemeFontSize(e.target.value)} style={{ fontSize: "0.85rem" }}>
            <option value="12px">12px</option>
            <option value="13px">13px</option>
            <option value="14px">14px</option>
            <option value="15px">15px</option>
            <option value="16px">16px</option>
          </select>
        </div>
      </div>

      <h4 style={sectionHead}>Branding</h4>
      <div className="form-group" style={{ marginTop: "0.75rem" }}>
        <label>Logo</label>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {logoNames.map(name => (
            <div key={name} onClick={() => setThemeLogo(name)}
              style={{
                cursor: "pointer", padding: "0.35rem", borderRadius: "var(--radius-sm)",
                border: themeLogo === name ? "2px solid var(--petrol-600)" : "2px solid var(--gray-200)",
                background: themeLogo === name ? "var(--petrol-50)" : "var(--bg-card)",
              }}>
              <img src={`/logos/${name}`} alt={name}
                style={{ width: "48px", height: "48px", objectFit: "contain", display: "block" }} />
            </div>
          ))}
        </div>
      </div>
      <div className="form-group">
        <label>Navigation Icons</label>
        <small style={{ display: "block", marginBottom: "0.5rem" }}>Emoji or Unicode symbol for each section.</small>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {[
            { id: "manual", label: "Analysis" },
            { id: "queue", label: "Queue" },
            { id: "discovery", label: "Discovery" },
            { id: "audit", label: "Audit" },
            { id: "settings", label: "Settings" },
          ].map(item => (
            <div key={item.id} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.2rem" }}>
              <input value={themeNavIcons[item.id] ?? ""} onChange={e => setThemeNavIcons(prev => ({ ...prev, [item.id]: e.target.value }))}
                style={{ width: "3rem", textAlign: "center", fontSize: "1.1rem", padding: "0.3rem" }} />
              <span style={{ fontSize: "0.7rem", color: "var(--gray-500)" }}>{item.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>

    <div className="card">
      <h3>Language &amp; System</h3>
      <div className="form-group">
        <label htmlFor="ui_language">Interface Language</label>
        <select id="ui_language" name="ui_language" defaultValue={String(s.ui_language ?? "en")}>
          <option value="en">English</option>
          <option value="de">Deutsch</option>
          <option value="fr">Français</option>
          <option value="es">Español</option>
          <option value="it">Italiano</option>
        </select>
        <small>Language for the Paperless IQ user interface. Refresh the page after saving.</small>
      </div>
      <div className="form-group">
        <label htmlFor="audit_retention_days">Audit Log Retention (days, min 90)</label>
        <input id="audit_retention_days" name="audit_retention_days" type="number" min="90" defaultValue={String(s.audit_retention_days)} />
        <small>Audit log entries older than this are automatically deleted.</small>
      </div>
    </div>
  </>);
}
