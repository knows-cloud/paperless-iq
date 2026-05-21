import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { setLang, type Lang } from "./i18n";

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
  ui_language: string;
  chip_color: string;
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
  ui_language: "en",
  chip_color: "",
};

const ThemeContext = createContext<Theme>(DEFAULT_THEME);

export function useTheme() { return useContext(ThemeContext); }

/** Alpha-blend overlay colour onto a base colour (both as #rrggbb). */
function blendHex(base: string, overlay: string, alpha: number): string {
  if (!base || base.length < 7 || !overlay || overlay.length < 7) return base;
  const br = parseInt(base.slice(1, 3), 16);
  const bg = parseInt(base.slice(3, 5), 16);
  const bb = parseInt(base.slice(5, 7), 16);
  const or = parseInt(overlay.slice(1, 3), 16);
  const og = parseInt(overlay.slice(3, 5), 16);
  const ob = parseInt(overlay.slice(5, 7), 16);
  const r = Math.round(br * (1 - alpha) + or * alpha);
  const g = Math.round(bg * (1 - alpha) + og * alpha);
  const b = Math.round(bb * (1 - alpha) + ob * alpha);
  return `#${[r, g, b].map(c => c.toString(16).padStart(2, "0")).join("")}`;
}

/** Relative luminance per WCAG 2.1 (0 = black, 1 = white). */
function luminance(hex: string): number {
  if (!hex || hex.length < 7) return 1;
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** Return [primary, secondary, muted] foreground colors for a given background. */
function contrastColors(bgHex: string, threshold = 0.35): [string, string, string] {
  const isDark = luminance(bgHex) < threshold;
  return isDark
    ? ["#e2e8f0", "rgba(226,232,240,0.65)", "rgba(226,232,240,0.38)"]  // light text on dark bg
    : ["#1a1d21", "rgba(26,29,33,0.65)",    "rgba(26,29,33,0.38)"];    // dark text on light bg
}

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
  // Blend the alt overlay onto the base card colour to get the true effective background,
  // then derive contrast text colours for that surface.
  const effectiveAltBg = blendHex(theme.card_color || "#ffffff", altHex, altAlpha);
  const [altPri, altSec, altMut] = contrastColors(effectiveAltBg);
  root.style.setProperty("--text-on-card-alt",           altPri);
  root.style.setProperty("--text-on-card-alt-secondary", altSec);
  root.style.setProperty("--text-on-card-alt-muted",     altMut);
  root.style.setProperty("--success-on-card-alt", luminance(effectiveAltBg) < 0.35 ? "#4ade80" : "#16a34a");
  root.style.setProperty("--error-on-card-alt",   luminance(effectiveAltBg) < 0.35 ? "#f87171" : "#dc2626");

  // ── Contrast-adaptive text variables ─────────────────────────────────────
  // Card text
  const isDarkCard = luminance(theme.card_color || "#ffffff") < 0.35;
  const [cardPri, cardSec, cardMut] = contrastColors(theme.card_color || "#ffffff");
  root.style.setProperty("--text-on-card",           cardPri);
  root.style.setProperty("--text-on-card-secondary", cardSec);
  root.style.setProperty("--text-on-card-muted",     cardMut);
  root.style.setProperty("--success-on-card", isDarkCard ? "#4ade80" : "#16a34a");
  root.style.setProperty("--error-on-card",   isDarkCard ? "#f87171" : "#dc2626");

  // Body text — honour user-configured text_color when it has sufficient contrast
  const bodyBg  = theme.bg_color   || "#f8f9fb";
  const isDarkBody = luminance(bodyBg) < 0.35;
  const [computedBodyPri, computedBodySec] = contrastColors(bodyBg);
  const userText = theme.text_color || (isDarkBody ? "#e2e8f0" : "#2d3239");
  const bgLum   = luminance(bodyBg);
  const utLum   = luminance(userText);
  const bodyContrastRatio = (Math.max(bgLum, utLum) + 0.05) / (Math.min(bgLum, utLum) + 0.05);
  let bodyPri: string, bodySec: string;
  if (bodyContrastRatio >= 3.0 && /^#[0-9a-f]{6}$/i.test(userText)) {
    // User-set colour has adequate readability — use it and derive secondary with opacity
    bodyPri = userText;
    const r = parseInt(userText.slice(1, 3), 16);
    const g = parseInt(userText.slice(3, 5), 16);
    const b = parseInt(userText.slice(5, 7), 16);
    bodySec = `rgba(${r},${g},${b},0.60)`;
  } else {
    bodyPri = computedBodyPri;
    bodySec = computedBodySec;
  }
  root.style.setProperty("--text-on-body",           bodyPri);
  root.style.setProperty("--text-on-body-secondary", bodySec);
  // Semantic status colours that stay readable on any body background
  root.style.setProperty("--success-text", isDarkBody ? "#4ade80" : "#16a34a");
  root.style.setProperty("--error-text",   isDarkBody ? "#f87171" : "#dc2626");
  // Override static CSS vars with theme-adaptive versions
  root.style.setProperty("--error",   isDarkBody ? "#f87171" : "#dc2626");
  root.style.setProperty("--success", isDarkBody ? "#4ade80" : "#16a34a");
  root.style.setProperty("--warning", isDarkBody ? "#fbbf24" : "#d97706");
  // Input fields background (dark cards need a lighter surface for readability)
  root.style.setProperty("--bg-input", isDarkCard ? "rgba(255,255,255,0.07)" : "#ffffff");
  // Error/warning notification bands (for inline chips/banners on cards)
  root.style.setProperty("--error-band-bg",     isDarkCard ? "rgba(248,113,113,0.15)" : "#ffcdd2");
  root.style.setProperty("--error-band-border",  isDarkCard ? "rgba(248,113,113,0.35)" : "rgba(220,38,38,0.30)");
  root.style.setProperty("--warning-band-bg",    isDarkCard ? "rgba(251,191,36,0.12)" : "#fef9ee");
  root.style.setProperty("--warning-band-border", isDarkCard ? "rgba(251,191,36,0.35)" : "#fde68a");

  // ── Chat / Discovery surface variables ───────────────────────────────────
  // All colours adapt to the body background so DiscoveryPage is readable
  // on both dark and light themes without any hardcoded colours there.
  const D = isDarkBody;  // shorthand
  root.style.setProperty("--chat-user-bg",               D ? "rgba(99,102,241,0.22)"  : "var(--petrol-100)");
  root.style.setProperty("--chat-user-border",           D ? "rgba(99,102,241,0.35)"  : "var(--petrol-200)");
  root.style.setProperty("--chat-assistant-bg",          D ? "rgba(255,255,255,0.05)" : "var(--bg-card)");
  root.style.setProperty("--chat-assistant-border",      D ? "rgba(255,255,255,0.10)" : "var(--gray-200)");
  root.style.setProperty("--chat-source-bg",             D ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.02)");
  root.style.setProperty("--chat-source-border",         D ? "rgba(255,255,255,0.08)" : "var(--gray-200)");
  root.style.setProperty("--chat-passage-bg",            D ? "rgba(0,0,0,0.22)"       : "rgba(0,0,0,0.04)");
  root.style.setProperty("--chat-passage-border",        D ? "rgba(99,102,241,0.40)"  : "var(--petrol-300)");
  root.style.setProperty("--chat-divider",               D ? "rgba(255,255,255,0.07)" : "var(--gray-200)");
  root.style.setProperty("--chat-accent-text",           D ? "rgba(147,153,255,0.90)" : "var(--petrol-600)");
  root.style.setProperty("--chat-accent-bg",             D ? "rgba(99,102,241,0.15)"  : "var(--petrol-50)");
  root.style.setProperty("--chat-accent-border",         D ? "rgba(99,102,241,0.30)"  : "var(--petrol-200)");
  root.style.setProperty("--chat-number-bg",             D ? "rgba(99,102,241,0.20)"  : "var(--petrol-100)");
  root.style.setProperty("--chat-number-text",           D ? "rgba(147,153,255,0.90)" : "var(--petrol-700)");
  root.style.setProperty("--chat-suggestion-bg",         D ? "rgba(99,102,241,0.08)"  : "var(--petrol-50)");
  root.style.setProperty("--chat-suggestion-bg-hover",   D ? "rgba(99,102,241,0.18)"  : "var(--petrol-100)");
  root.style.setProperty("--chat-suggestion-border",     D ? "rgba(99,102,241,0.35)"  : "var(--petrol-200)");
  root.style.setProperty("--chat-suggestion-border-hover",D ? "rgba(99,102,241,0.60)" : "var(--petrol-300)");
  root.style.setProperty("--chat-suggestion-text",       D ? "rgba(226,232,240,0.75)" : "var(--petrol-700)");
  root.style.setProperty("--chat-code-bg",               D ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.07)");
  root.style.setProperty("--chat-blockquote-bg",         D ? "rgba(99,102,241,0.08)"  : "var(--petrol-50)");
  root.style.setProperty("--chat-blockquote-border",     D ? "rgba(99,102,241,0.60)"  : "var(--petrol-400)");
  root.style.setProperty("--chat-blockquote-text",       D ? "rgba(226,232,240,0.80)" : "var(--petrol-800)");
  root.style.setProperty("--chat-ai-label",              D ? "rgba(226,232,240,0.35)" : "var(--text-on-body-secondary)");
  root.style.setProperty("--chat-ai-icon-bg",            D ? "rgba(99,102,241,0.25)"  : "var(--petrol-100)");
  root.style.setProperty("--chat-loading",               D ? "rgba(226,232,240,0.45)" : "var(--text-on-body-secondary)");
  root.style.setProperty("--chat-enter-hint",            D ? "rgba(226,232,240,0.25)" : "var(--text-on-body-secondary)");
  // Score badge colours for relevance indicators
  root.style.setProperty("--score-high-text",   D ? "#4ade80" : "#16a34a");
  root.style.setProperty("--score-high-bg",     D ? "rgba(74,222,128,0.10)"  : "rgba(22,163,74,0.10)");
  root.style.setProperty("--score-high-border", D ? "rgba(74,222,128,0.40)"  : "rgba(22,163,74,0.40)");
  root.style.setProperty("--score-med-text",    D ? "#facc15" : "#b45309");
  root.style.setProperty("--score-med-bg",      D ? "rgba(250,204,21,0.10)"  : "rgba(180,83,9,0.10)");
  root.style.setProperty("--score-med-border",  D ? "rgba(250,204,21,0.40)"  : "rgba(180,83,9,0.40)");
  root.style.setProperty("--score-low-text",    D ? "#94a3b8" : "#64748b");
  root.style.setProperty("--score-low-bg",      D ? "rgba(148,163,184,0.10)" : "rgba(100,116,139,0.10)");
  root.style.setProperty("--score-low-border",  D ? "rgba(148,163,184,0.40)" : "rgba(100,116,139,0.40)");

  // Sidebar text + surface colours
  const sidebarDark = luminance(theme.sidebar_from || "#0a3344") < 0.3;
  const [sidePri, sideMut] = contrastColors(theme.sidebar_from || "#0a3344", 0.3);
  root.style.setProperty("--text-on-sidebar",       sidePri);
  root.style.setProperty("--text-on-sidebar-muted", sideMut);
  root.style.setProperty("--sidebar-divider",      sidebarDark ? "rgba(255,255,255,0.1)"  : "rgba(0,0,0,0.12)");
  root.style.setProperty("--sidebar-hover-bg",     sidebarDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)");
  root.style.setProperty("--sidebar-active-bg",    sidebarDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)");
  // Status indicator dots — always blue/red regardless of theme palette
  root.style.setProperty("--status-ok",    sidebarDark ? "#60a5fa" : "#2563eb");
  root.style.setProperty("--status-error", sidebarDark ? "#f87171" : "#dc2626");
  // Card border adapts to card background lightness
  root.style.setProperty("--card-border",  isDarkCard ? "rgba(255,255,255,0.10)" : "var(--gray-200)");

  // ── Chip / tag badge colours ─────────────────────────────────────────────
  // Uses a separate configurable chip colour; falls back to the petrol palette.
  const chipHex = (theme.chip_color || "").trim();
  const chipPalette = /^#[0-9a-f]{6}$/i.test(chipHex)
    ? derivePalette(chipHex)
    : palette;
  // Derive chip text via WCAG contrast so light chip colors always get dark text
  const chipBg100 = chipPalette["--petrol-100"] ?? "#d4eef4";
  const chipBg50  = chipPalette["--petrol-50"]  ?? "#edf7fa";
  const chipBg600 = chipPalette["--petrol-600"] ?? "#1a7288";
  const [chipText100] = contrastColors(chipBg100);
  const [chipText50]  = contrastColors(chipBg50);
  root.style.setProperty("--chip-bg",           chipBg100);
  root.style.setProperty("--chip-text",         chipText100);
  root.style.setProperty("--chip-border",       chipPalette["--petrol-200"] ?? "#a3dae5");
  root.style.setProperty("--chip-bg-subtle",    chipBg50);
  root.style.setProperty("--chip-subtle-text",  chipText50);
  const [chipFilledText] = contrastColors(chipBg600);
  root.style.setProperty("--chip-filled-bg",    chipBg600);
  root.style.setProperty("--chip-filled-border",chipPalette["--petrol-700"] ?? "#135a6e");
  root.style.setProperty("--chip-filled-text",  chipFilledText);

  // ── Darker button border shades ──────────────────────────────────────────
  // Used by .btn-danger and .btn-success for the slightly darker border.
  root.style.setProperty("--error-dark",   isDarkBody ? "#dc2626" : "#991b1b");
  root.style.setProperty("--success-dark", isDarkBody ? "#16a34a" : "#14532d");
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(DEFAULT_THEME);

  useEffect(() => {
    api.getTheme().then(t => {
      setTheme(t);
      applyTheme(t);
      if (t.ui_language) setLang(t.ui_language as Lang);
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
