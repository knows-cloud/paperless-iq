import { useState, useEffect } from "react";
import { useTheme } from "./ThemeProvider";
import StatusPanel from "./StatusPanel";
import { t } from "./i18n";
import SettingsPage from "./pages/SettingsPage";
import QueuePage from "./pages/QueuePage";
import ManualPage from "./pages/ManualPage";
import AuditPage from "./pages/AuditPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import ProcessingPage from "./pages/ProcessingPage";
import LoginPage from "./pages/LoginPage";
import { api, clearStoredToken } from "./api";

type Page = "manual" | "queue" | "discovery" | "processing" | "audit" | "settings";

const VALID_PAGES: Set<string> = new Set(["manual", "queue", "discovery", "processing", "audit", "settings"]);

const NAV_ITEMS: Array<{ id: Page; labelKey: string; defaultIcon: string }> = [
  { id: "manual",     labelKey: "nav.analysis",       defaultIcon: "🔍" },
  { id: "queue",      labelKey: "nav.queue",           defaultIcon: "📋" },
  { id: "discovery",  labelKey: "nav.discovery",       defaultIcon: "💬" },
  { id: "processing", labelKey: "nav.processing",      defaultIcon: "⚡" },
  { id: "audit",      labelKey: "nav.audit",           defaultIcon: "📜" },
  { id: "settings",   labelKey: "nav.settings",        defaultIcon: "⚙️" },
];

function getPageFromHash(): Page {
  const hash = window.location.hash.replace("#", "");
  return VALID_PAGES.has(hash) ? (hash as Page) : "manual";
}

export default function App() {
  const [page, setPage] = useState<Page>(getPageFromHash);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const theme = useTheme();

  // Auth state
  const [authChecked, setAuthChecked] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authUser, setAuthUser] = useState<string | null>(null);

  // Check auth on mount; retry until the backend responds.
  // A failed getMe() (e.g. backend still starting) must NOT open the app —
  // that would cause StatusPanel to poll /api/status without a token, filling
  // the container log with 401s forever.
  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      while (!cancelled) {
        try {
          const me = await api.getMe();
          if (cancelled) return;
          setAuthRequired(me.auth_required);
          setAuthUser(me.user);
          setAuthChecked(true);
          return; // success — stop retrying
        } catch {
          if (cancelled) return;
          // Backend not ready yet — wait 2 s then retry
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    }

    checkAuth();

    // On logout (401 from any API call), re-run the auth check so the
    // login page appears without requiring a full page reload.
    const handleLogout = () => {
      setAuthUser(null);
      setAuthChecked(false);
      checkAuth();
    };
    window.addEventListener("piq-logout", handleLogout);
    return () => {
      cancelled = true;
      window.removeEventListener("piq-logout", handleLogout);
    };
  }, []);

  useEffect(() => {
    const onHashChange = () => setPage(getPageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (p: Page) => {
    window.location.hash = p;
    setPage(p);
    setSidebarOpen(false);
  };

  function handleLogin(user: string) {
    setAuthUser(user);
  }

  async function handleLogout() {
    try { await api.logout(); } catch { /* ignore */ }
    clearStoredToken();
    setAuthUser(null);
  }

  // Wait for the initial auth check before rendering anything
  if (!authChecked) {
    return null;
  }

  // Show login page when auth is required and the user is not logged in
  if (authRequired && !authUser) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <div className="app-layout">
      {/* Hamburger — fixed top-left, visible on mobile only */}
      <button
        className="sidebar-toggle"
        onClick={() => setSidebarOpen(o => !o)}
        aria-label="Toggle navigation"
      >
        {sidebarOpen ? "✕" : "☰"}
      </button>

      {/* Semi-transparent backdrop — tapping it closes the drawer */}
      <div
        className={`sidebar-overlay${sidebarOpen ? " sidebar--open" : ""}`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`sidebar${sidebarOpen ? " sidebar--open" : ""}`}>
        <div className="sidebar-header">
          {theme.logo && (
            <img src={`/logos/${theme.logo}`} alt="Paperless IQ"
              style={{ width: "40px", height: "40px", borderRadius: "8px", marginBottom: "0.5rem", objectFit: "contain" }} />
          )}
          <h1>{t("app.title")}</h1>
          <div className="subtitle">{t("app.subtitle")}</div>
        </div>
        <StatusPanel />
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(item => (
            <a key={item.id} href={`#${item.id}`}
              className={page === item.id ? "active" : ""}
              onClick={e => { e.preventDefault(); navigate(item.id); }}>
              <span className="nav-icon">{theme.nav_icons[item.id] ?? item.defaultIcon}</span>
              {t(item.labelKey)}
            </a>
          ))}
        </nav>

        {/* Logout button — only shown when auth is active */}
        {authRequired && authUser && (
          <div style={{ marginTop: "auto", padding: "1rem 0.75rem 0.5rem" }}>
            <div style={{
              fontSize: "0.75rem",
              color: "var(--text-on-sidebar-muted)",
              marginBottom: "0.4rem",
              paddingLeft: "0.25rem",
            }}>
              {t("app.signedInAs")} <strong style={{ color: "var(--text-on-sidebar)" }}>{authUser}</strong>
            </div>
            <button
              onClick={handleLogout}
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                borderRadius: "8px",
                border: "1px solid var(--sidebar-divider)",
                background: "transparent",
                color: "var(--text-on-sidebar-muted)",
                fontSize: "0.85rem",
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              🚪 {t("app.signOut")}
            </button>
          </div>
        )}
      </aside>
      <main className="main-content">
        {page === "manual" && <ManualPage />}
        {page === "queue" && <QueuePage />}
        {page === "discovery" && <DiscoveryPage />}
        {page === "processing" && <ProcessingPage />}
        {page === "audit" && <AuditPage />}
        {page === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
