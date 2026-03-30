import { useState } from "react";
import SettingsPage from "./pages/SettingsPage";
import QueuePage from "./pages/QueuePage";
import ManualPage from "./pages/ManualPage";
import AuditPage from "./pages/AuditPage";

type Page = "settings" | "queue" | "manual" | "audit";

export default function App() {
  const [page, setPage] = useState<Page>("settings");

  return (
    <div className="app">
      <h1>Paperless IQ</h1>
      <nav>
        <a href="#" className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}>Settings</a>
        <a href="#" className={page === "queue" ? "active" : ""} onClick={() => setPage("queue")}>Approval Queue</a>
        <a href="#" className={page === "manual" ? "active" : ""} onClick={() => setPage("manual")}>Manual / Search</a>
        <a href="#" className={page === "audit" ? "active" : ""} onClick={() => setPage("audit")}>Audit Log</a>
      </nav>
      {page === "settings" && <SettingsPage />}
      {page === "queue" && <QueuePage />}
      {page === "manual" && <ManualPage />}
      {page === "audit" && <AuditPage />}
    </div>
  );
}
