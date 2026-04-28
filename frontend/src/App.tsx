import { useState } from "react";
import SettingsPage from "./pages/SettingsPage";
import QueuePage from "./pages/QueuePage";
import ManualPage from "./pages/ManualPage";
import AuditPage from "./pages/AuditPage";
import DiscoveryPage from "./pages/DiscoveryPage";

type Page = "manual" | "queue" | "discovery" | "audit" | "settings";

export default function App() {
  const [page, setPage] = useState<Page>("manual");

  return (
    <div className="app">
      <h1>Paperless IQ</h1>
      <nav>
        <a href="#" className={page === "manual" ? "active" : ""} onClick={() => setPage("manual")}>Analysis</a>
        <a href="#" className={page === "queue" ? "active" : ""} onClick={() => setPage("queue")}>Approval Queue</a>
        <a href="#" className={page === "discovery" ? "active" : ""} onClick={() => setPage("discovery")}>Discovery</a>
        <a href="#" className={page === "audit" ? "active" : ""} onClick={() => setPage("audit")}>Audit Log</a>
        <a href="#" className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}>Settings</a>
      </nav>
      {page === "manual" && <ManualPage />}
      {page === "queue" && <QueuePage />}
      {page === "discovery" && <DiscoveryPage />}
      {page === "audit" && <AuditPage />}
      {page === "settings" && <SettingsPage />}
    </div>
  );
}
