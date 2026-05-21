import { useState, FormEvent } from "react";
import { api, setStoredToken } from "../api";

interface LoginPageProps {
  onLogin: (user: string) => void;
}

export default function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setError(null);
    setLoading(true);
    try {
      const result = await api.login(username.trim(), password.trim());
      setStoredToken(result.token);
      onLogin(result.user);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--bg-body)",
    }}>
      <div style={{
        background: "var(--bg-card)",
        border: "1px solid var(--card-border, var(--gray-200))",
        borderRadius: "16px",
        padding: "2.5rem 2rem",
        width: "100%",
        maxWidth: "380px",
        boxShadow: "var(--shadow-lg)",
      }}>
        {/* Logo / title */}
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div style={{
            fontSize: "2.5rem",
            marginBottom: "0.5rem",
            lineHeight: 1,
          }}>📄</div>
          <h1 style={{
            margin: 0,
            fontSize: "1.4rem",
            fontWeight: 700,
            color: "var(--text-on-card)",
          }}>Paperless IQ</h1>
          <p style={{
            margin: "0.35rem 0 0",
            fontSize: "0.85rem",
            color: "var(--text-on-card-secondary)",
          }}>Sign in with your Paperless-NGX account</p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            <label style={{ fontSize: "0.8rem", color: "var(--text-on-card-secondary)", fontWeight: 500 }}>
              Username
            </label>
            <input
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={e => setUsername(e.target.value)}
              disabled={loading}
              placeholder="paperless-username"
              style={{
                padding: "0.65rem 0.85rem",
                borderRadius: "8px",
                border: "1px solid var(--gray-300)",
                background: "var(--bg-input)",
                color: "var(--text-on-card)",
                fontSize: "0.95rem",
                outline: "none",
              }}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            <label style={{ fontSize: "0.8rem", color: "var(--text-on-card-secondary)", fontWeight: 500 }}>
              Password
            </label>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              placeholder="••••••••"
              style={{
                padding: "0.65rem 0.85rem",
                borderRadius: "8px",
                border: "1px solid var(--gray-300)",
                background: "var(--bg-input)",
                color: "var(--text-on-card)",
                fontSize: "0.95rem",
                outline: "none",
              }}
            />
          </div>

          {error && (
            <div style={{
              padding: "0.6rem 0.85rem",
              borderRadius: "8px",
              background: "var(--error-band-bg, rgba(220,38,38,0.12))",
              border: "1px solid var(--error-band-border, rgba(220,38,38,0.30))",
              color: "var(--error-on-card)",
              fontSize: "0.85rem",
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password.trim()}
            style={{
              marginTop: "0.5rem",
              padding: "0.75rem",
              borderRadius: "8px",
              border: "none",
              background: loading ? "var(--petrol-400)" : "var(--petrol-600)",
              color: "#fff",
              fontWeight: 600,
              fontSize: "1rem",
              cursor: loading ? "not-allowed" : "pointer",
              transition: "opacity 0.15s",
            }}
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
