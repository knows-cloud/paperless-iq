import { useState } from "react";
import SettingsPage from "./pages/SettingsPage";
import QueuePage from "./pages/QueuePage";
import ManualPage from "./pages/ManualPage";
import AuditPage from "./pages/AuditPage";
import DiscoveryPage from "./pages/DiscoveryPage";

type Page = "manual" | "queue" | "discovery" | "audit" | "settings";

const NAV_ITEMS: Array<{ id: Page; label: string; icon: string }> = [
  { id: "manual",    label: "Analysis",       icon: "🔍" },
  { id: "queue",     label: "Approval Queue", icon: "📋" },
  { id: "discovery", label: "Discovery",      icon: "💬" },
  { id: "audit",     label: "Audit Log",      icon: "📜" },
  { id: "settings",  label: "Settings",       icon: "⚙️" },
];

export default function App() {
  const [page, setPage] = useState<Page>("manual");

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>Paperless IQ</h1>
          <div className="subtitle">AI Document Intelligence</div>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(item => (
            <a key={item.id} href="#"
              className={page === item.id ? "active" : ""}
              onClick={e => { e.preventDefault(); setPage(item.id); }}>
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
