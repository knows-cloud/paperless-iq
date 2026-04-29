import { useState, useEffect } from "react";
import SettingsPage from "./pages/SettingsPage";
import QueuePage from "./pages/QueuePage";
import ManualPage from "./pages/ManualPage";
import AuditPage from "./pages/AuditPage";
import DiscoveryPage from "./pages/DiscoveryPage";

type Page = "manual" | "queue" | "discovery" | "audit" | "settings";

const VALID_PAGES: Set<string> = new Set(["manual", "queue", "discovery", "audit", "settings"]);

const NAV_ITEMS: Array<{ id: Page; label: string; icon: string }> = [
  { id: "manual",    label: "Analysis",       icon: "🔍" },
  { id: "queue",     label: "Approval Queue", icon: "📋" },
  { id: "discovery", label: "Discovery",      icon: "💬" },
  { id: "audit",     label: "Audit Log",      icon: "📜" },
  { id: "settings",  label: "Settings",       icon: "⚙️" },
];

function getPageFromHash(): Page {
  const hash = window.location.hash.replace("#", "");
  return VALID_PAGES.has(hash) ? (hash as Page) : "manual";
}

export default function App() {
  const [page, setPage] = useState<Page>(getPageFromHash);

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
          <h1>Paperless IQ</h1>
          <div className="subtitle">AI Document Intelligence</div>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(item => (
            <a key={item.id} href={`#${item.id}`}
              className={page === item.id ? "active" : ""}
              onClick={e => { e.preventDefault(); navigate(item.id); }}>
              <span className="nav-icon">{item.icon}</span>
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
