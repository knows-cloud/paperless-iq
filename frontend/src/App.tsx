import { useState, useEffect } from "react";
import {
  AppShell, Burger, NavLink, Text, Group, Box, Button,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconLogin } from "@tabler/icons-react";
import { NAV_ICON_PALETTE } from "./pages/settings/nav-icon-palette";
import { useTheme } from "./ThemeProvider";
import { PiqLogo } from "./PiqLogo";
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
import type { UserPermissions } from "./api";
import { PermissionsContext } from "./PermissionsContext";

type Page = "manual" | "queue" | "discovery" | "processing" | "audit" | "settings";

const VALID_PAGES: Set<string> = new Set(["manual", "queue", "discovery", "processing", "audit", "settings"]);

const NAV_ITEMS: Array<{ id: Page; labelKey: string; defaultIconName: string }> = [
  { id: "manual",     labelKey: "nav.analysis",   defaultIconName: "FileSearch"   },
  { id: "queue",      labelKey: "nav.queue",       defaultIconName: "ListCheck"    },
  { id: "discovery",  labelKey: "nav.discovery",   defaultIconName: "Sparkles"     },
  { id: "processing", labelKey: "nav.processing",  defaultIconName: "Activity"     },
  { id: "audit",      labelKey: "nav.audit",       defaultIconName: "ClipboardList"},
  { id: "settings",   labelKey: "nav.settings",    defaultIconName: "Settings"     },
];

function getPageFromHash(): Page {
  const hash = window.location.hash.replace("#", "");
  return VALID_PAGES.has(hash) ? (hash as Page) : "manual";
}

export default function App() {
  const [page, setPage] = useState<Page>(getPageFromHash);
  const [mobileOpened, { toggle: toggleMobile, close: closeMobile }] = useDisclosure();
  const theme = useTheme();
  const { colorScheme } = useMantineColorScheme();

  const [authChecked, setAuthChecked] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authUser, setAuthUser] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<UserPermissions | null>(null);

  async function loadPermissions() {
    try {
      const p = await api.getMyPermissions();
      setPermissions(p);
    } catch {
      setPermissions(null);
    }
  }

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
          if (me.user || !me.auth_required) {
            await loadPermissions();
          }
          return;
        } catch {
          if (cancelled) return;
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    }

    checkAuth();

    const handleLogout = () => {
      setAuthUser(null);
      setPermissions(null);
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
    closeMobile();
  };

  async function handleLogout() {
    try { await api.logout(); } catch { /* ignore */ }
    clearStoredToken();
    setAuthUser(null);
  }

  if (!authChecked) return null;

  if (authRequired && !authUser) {
    return (
      <LoginPage
        onLogin={async user => {
          setAuthUser(user);
          await loadPermissions();
        }}
      />
    );
  }

  const perms: UserPermissions = permissions ?? {
    username: authUser ?? "",
    ng_admin: false,
    can_access: true,
    can_view_queue: true,
    can_approve: true,
    can_analyze: true,
    can_discover: true,
    can_settings: true,
  };

  function canViewPage(id: Page): boolean {
    if (!authRequired) return true;
    switch (id) {
      case "manual":     return perms.can_analyze;
      case "queue":      return perms.can_view_queue || perms.can_approve;
      case "discovery":  return perms.can_discover;
      case "processing": return perms.can_analyze || perms.can_settings;
      case "audit":      return perms.can_access;
      case "settings":   return perms.can_settings;
      default:           return false;
    }
  }

  const navbarBg = colorScheme === "dark" ? "dark.8" : "gray.0";

  return (
    <AppShell
      header={{ height: { base: 50, sm: 0 } }}
      navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !mobileOpened } }}
      padding={0}
    >
      {/* Mobile burger — only visible below sm breakpoint */}
      <AppShell.Header hiddenFrom="sm" h={50} px="md" style={{ display: "flex", alignItems: "center" }}>
        <Group>
          <Burger opened={mobileOpened} onClick={toggleMobile} size="sm" />
          <Text fw={700} size="sm">Paperless IQ</Text>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar bg={navbarBg} withBorder>
        {/* Brand */}
        <Box p="md" pb="xs">
          <Group gap="sm" wrap="nowrap">
            <div>
              <PiqLogo size={30} />
              <Text size="xs" c="dimmed" lh={1.4} mt={2}>{t("app.subtitle")}</Text>
            </div>
          </Group>
        </Box>

        <StatusPanel />

        {/* Nav items */}
        <Box p="xs" style={{ flex: 1 }}>
          {NAV_ITEMS.filter(item => canViewPage(item.id)).map(item => (
            <NavLink
              key={item.id}
              href={`#${item.id}`}
              label={t(item.labelKey)}
              leftSection={(() => {
                const name = theme.nav_icons[item.id] || item.defaultIconName;
                const Icon = NAV_ICON_PALETTE[name];
                return Icon ? <Icon size={18} /> : null;
              })()}
              active={page === item.id}
              variant="light"
              color="teal"
              styles={{ root: { borderRadius: "var(--mantine-radius-sm)", marginBottom: 2 } }}
              onClick={e => { e.preventDefault(); navigate(item.id); }}
            />
          ))}
        </Box>

        {/* Signed-in user + logout */}
        {authRequired && authUser && (
          <Box p="md" pt="xs" style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
            <Text size="xs" c="dimmed" mb={6}>
              {t("app.signedInAs")} <Text span fw={600} c="var(--mantine-color-text)">{authUser}</Text>
            </Text>
            <Button
              variant="subtle"
              color="red"
              size="xs"
              fullWidth
              justify="left"
              leftSection={<IconLogin size={14} />}
              onClick={handleLogout}
            >
              {t("app.signOut")}
            </Button>
          </Box>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        <Box p="xl" maw={1100}>
          <PermissionsContext.Provider value={perms}>
            {page === "manual"     && canViewPage("manual")     && <ManualPage />}
            {page === "queue"      && canViewPage("queue")      && <QueuePage />}
            {page === "discovery"  && canViewPage("discovery")  && <DiscoveryPage />}
            {page === "processing" && canViewPage("processing") && <ProcessingPage />}
            {page === "audit"      && canViewPage("audit")      && <AuditPage />}
            {page === "settings"   && canViewPage("settings")   && <SettingsPage />}
          </PermissionsContext.Provider>
        </Box>
      </AppShell.Main>
    </AppShell>
  );
}
