import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

interface Theme {
  primary_color: string;
  sidebar_from: string;
  sidebar_to: string;
  font: string;
  font_size: string;
  text_color: string;
  bg_color: string;
  card_color: string;
  card_alt_hex: string;
  card_alt_opacity: number;
  logo: string;
  nav_icons: Record<string, string>;
}

const DEFAULT_THEME: Theme = {
  primary_color: "#1a7288",
  sidebar_from: "#0a3344",
  sidebar_to: "#0e4458",
  font: "Roboto",
  font_size: "14px",
  text_color: "#2d3239",
  bg_color: "#f8f9fb",
  card_color: "#ffffff",
  card_alt_hex: "#1a7288",
  card_alt_opacity: 12,
  logo: "iq_1.png",
  nav_icons: { manual: "🔍", queue: "📋", discovery: "💬", audit: "📜", settings: "⚙️" },
};

const ThemeContext = createContext<Theme>(DEFAULT_THEME);

export function useTheme() { return useContext(ThemeContext); }

/** Derive a full palette from a single primary hex color. */
function derivePalette(hex: string): Record<string, string> {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const mix = (t: number, c: number) => Math.round(c + (255 - c) * t);
  const dark = (t: number, c: number) => Math.round(c * (1 - t));
  const toHex = (r: number, g: number, b: number) =>
    `#${[r, g, b].map(c => c.toString(16).padStart(2, "0")).join("")}`;
  return {
    "--petrol-900": toHex(dark(0.6, r), dark(0.6, g), dark(0.6, b)),
    "--petrol-800": toHex(dark(0.45, r), dark(0.45, g), dark(0.45, b)),
    "--petrol-700": toHex(dark(0.3, r), dark(0.3, g), dark(0.3, b)),
    "--petrol-600": hex,
    "--petrol-500": toHex(mix(0.1, r), mix(0.1, g), mix(0.1, b)),
    "--petrol-400": toHex(mix(0.25, r), mix(0.25, g), mix(0.25, b)),
    "--petrol-300": toHex(mix(0.45, r), mix(0.45, g), mix(0.45, b)),
    "--petrol-200": toHex(mix(0.65, r), mix(0.65, g), mix(0.65, b)),
    "--petrol-100": toHex(mix(0.82, r), mix(0.82, g), mix(0.82, b)),
    "--petrol-50": toHex(mix(0.92, r), mix(0.92, g), mix(0.92, b)),
  };
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  // Derive palette from primary color
  const palette = derivePalette(theme.primary_color);
  for (const [key, val] of Object.entries(palette)) root.style.setProperty(key, val);
  // Sidebar gradient
  root.style.setProperty("--bg-sidebar", `linear-gradient(180deg, ${theme.sidebar_from} 0%, ${theme.sidebar_to} 100%)`);
  // Font — load from Google Fonts if not already loaded
  const fontName = theme.font || "Roboto";
  const linkId = "theme-font-link";
  let link = document.getElementById(linkId) as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.id = linkId;
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  const fontParam = fontName.replace(/ /g, "+");
  link.href = `https://fonts.googleapis.com/css2?family=${fontParam}:wght@300;400;500;700&display=swap`;
  root.style.setProperty("font-family", `'${fontName}', system-ui, sans-serif`);
  // Font size, text color, backgrounds
  root.style.setProperty("font-size", theme.font_size || "14px");
  root.style.setProperty("color", theme.text_color || "#2d3239");
  root.style.setProperty("--bg-body", theme.bg_color || "#f8f9fb");
  root.style.setProperty("--bg-card", theme.card_color || "#ffffff");
  // Card alt: combine hex + opacity into rgba
  const altHex = theme.card_alt_hex || "#1a7288";
  const altR = parseInt(altHex.slice(1, 3), 16);
  const altG = parseInt(altHex.slice(3, 5), 16);
  const altB = parseInt(altHex.slice(5, 7), 16);
  const altAlpha = (theme.card_alt_opacity ?? 12) / 100;
  root.style.setProperty("--card-alt-bg", `rgba(${altR}, ${altG}, ${altB}, ${altAlpha})`);
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(DEFAULT_THEME);

  useEffect(() => {
    api.getTheme().then(t => {
      setTheme(t);
      applyTheme(t);
    }).catch(() => {
      applyTheme(DEFAULT_THEME);
    });
  }, []);

  // Re-apply when theme changes (e.g. after settings save)
  useEffect(() => { applyTheme(theme); }, [theme]);

  return (
    <ThemeContext.Provider value={theme}>
      {children}
    </ThemeContext.Provider>
  );
}

/** Hook to refresh theme from server (call after saving theme settings). */
export function useRefreshTheme() {
  const [, setTheme] = useState<Theme>(DEFAULT_THEME);
  return async () => {
    try {
      const t = await api.getTheme();
      setTheme(t);
      applyTheme(t);
    } catch { /* ignore */ }
  };
}
