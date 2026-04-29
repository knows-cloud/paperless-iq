import { useState, useEffect } from "react";
import { useTheme } from "./ThemeProvider";
import SettingsPage from "./pages/SettingsPage";
import QueuePage from "./pages/QueuePage";
import ManualPage from "./pages/ManualPage";
import AuditPage from "./pages/AuditPage";
import DiscoveryPage from "./pages/DiscoveryPage";

type Page = "manual" | "queue" | "discovery" | "audit" | "settings";

const VALID_PAGES: Set<string> = new Set(["manual", "queue", "discovery", "audit", "settings"]);

const NAV_ITEMS: Array<{ id: Page; label: string; defaultIcon: string }> = [
  { id: "manual",    label: "Analysis",       defaultIcon: "🔍" },
  { id: "queue",     label: "Approval Queue", defaultIcon: "📋" },
  { id: "discovery", label: "Discovery",      defaultIcon: "💬" },
  { id: "audit",     label: "Audit Log",      defaultIcon: "📜" },
  { id: "settings",  label: "Settings",       defaultIcon: "⚙️" },
];

function getPageFromHash(): Page {
  const hash = window.location.hash.replace("#", "");
  return VALID_PAGES.has(hash) ? (hash as Page) : "manual";
}

export default function App() {
  const [page, setPage] = useState<Page>(getPageFromHash);
  const theme = useTheme();

  useEffect(() => {
    const onHashChange = () => setPage(getPageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (p: Page) => {
    window.location.hash = p;
    setPage(p);
  };

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          {theme.logo && (
            <img src={`/logos/${theme.logo}`} alt="Paperless IQ"
              style={{ width: "40px", height: "40px", borderRadius: "8px", marginBottom: "0.5rem", objectFit: "contain" }} />
          )}
          <h1>Paperless IQ</h1>
          <div className="subtitle">AI Document Intelligence</div>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(item => (
            <a key={item.id} href={`#${item.id}`}
              className={page === item.id ? "active" : ""}
              onClick={e => { e.preventDefault(); navigate(item.id); }}>
              <span className="nav-icon">{theme.nav_icons[item.id] ?? item.defaultIcon}</span>
              {item.label}
            </a>
          ))}
        </nav>
      </aside>
      <main className="main-content">
        {page === "manual" && <ManualPage />}
        {page === "queue" && <QueuePage />}
        {page === "discovery" && <DiscoveryPage />}
        {page === "audit" && <AuditPage />}
        {page === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
