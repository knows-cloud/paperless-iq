import { useState, useEffect } from "react";
import {
  Stack, Paper, Text, Switch, Button, Group, Badge, Divider,
  Alert, Loader, Table, ActionIcon, Tooltip, Anchor, NumberInput,
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useTranslation } from "react-i18next";
import { api } from "../../api";
import type { UserPermissions } from "../../api";

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

interface Props {
  s: Record<string, unknown>;
  onReindex: () => void;
  reindexing: boolean;
  onReindexSince: () => void;
  reindexingSince: boolean;
  reindexSinceDate: string;
  onReindexSinceDateChange: (date: string) => void;
  onResetTracking: () => void;
  resettingTracking: boolean;
  onResetRejected: () => void;
  resettingRejected: boolean;
  maintenanceMsg: string | null;
}

export function AccessControlTab({
  s,
  onReindex, reindexing,
  onReindexSince, reindexingSince,
  reindexSinceDate, onReindexSinceDateChange,
  onResetTracking, resettingTracking,
  onResetRejected, resettingRejected,
  maintenanceMsg,
}: Props) {
  const { t } = useTranslation();
  const [users, setUsers] = useState<UserPermissions[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const PERM_FLAGS: Array<{ key: keyof Omit<UserPermissions, "username" | "ng_admin" | "updated_at" | "has_piq_record">; label: string }> = [
    { key: "can_access",     label: t("acl.perm.access") },
    { key: "can_view_queue", label: t("acl.perm.queue") },
    { key: "can_approve",    label: t("common.approve") },
    { key: "can_analyze",    label: t("common.analyze") },
    { key: "can_discover",   label: t("nav.discovery") },
    { key: "can_settings",   label: t("nav.settings") },
    { key: "can_groom",      label: t("acl.perm.groom") },
  ];

  const SECTIONS = [
    { id: "section-access-control",   label: t("acl.settings.title") },
    { id: "section-user-permissions", label: t("acl.sections.users") },
    { id: "section-audit-log",        label: t("acl.sections.audit") },
    { id: "section-maintenance",      label: t("acl.sections.maintenance") },
  ];

  function loadUsers() {
    setLoading(true);
    api.listPiqUsers()
      .then(setUsers)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadUsers(); }, []);

  async function togglePerm(user: UserPermissions, key: keyof Omit<UserPermissions, "username" | "ng_admin" | "updated_at" | "has_piq_record">, value: boolean) {
    setSaving(user.username);
    setMsg(null);
    setError(null);
    const updated = { ...user, [key]: value };
    try {
      await api.updatePiqUser(user.username, {
        can_access:     updated.can_access,
        can_view_queue: updated.can_view_queue,
        can_approve:    updated.can_approve,
        can_analyze:    updated.can_analyze,
        can_discover:   updated.can_discover,
        can_settings:   updated.can_settings,
        can_groom:      updated.can_groom,
      });
      setUsers(prev => prev.map(u => u.username === user.username
        ? { ...u, [key]: value, has_piq_record: true }
        : u
      ));
      setMsg(t("acl.users.savedPerms", { user: user.username }));
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(null);
    }
  }

  async function deleteUser(username: string) {
    setSaving(username);
    try {
      await api.deletePiqUser(username);
      setUsers(prev => prev.map(u => u.username === username
        ? { ...u, has_piq_record: false, can_access: false, can_view_queue: false, can_approve: false, can_analyze: false, can_discover: false, can_settings: false, can_groom: false }
        : u
      ));
      setDeleteConfirm(null);
      setMsg(t("acl.users.removedRecord", { user: username }));
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(null);
    }
  }

  return (
    <Stack gap="md">
      {/* Section navigation */}
      <Group gap="xs" pb="xs" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
        <Text size="xs" c="dimmed" fw={500}>{t("acl.jumpTo")}</Text>
        {SECTIONS.map(sec => (
          <Anchor key={sec.id} size="xs" onClick={() => scrollTo(sec.id)} style={{ cursor: "pointer" }}>
            {sec.label}
          </Anchor>
        ))}
      </Group>

      {/* ── Access Control Settings ─────────────────────────────────── */}
      <Paper id="section-access-control" withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("acl.settings.title")}</Text>
        <Text size="sm" c="dimmed" mb="md">{t("acl.settings.description")}</Text>
        <Switch
          name="sync_ng_admins"
          label={t("acl.settings.syncLabel")}
          defaultChecked={Boolean(s.sync_ng_admins !== false)}
        />
      </Paper>

      {/* ── User Permissions ────────────────────────────────────────── */}
      <Paper id="section-user-permissions" withBorder p="md" radius="md">
        <Group justify="space-between" mb="md">
          <Text fw={600}>{t("acl.sections.users")}</Text>
          <Button size="xs" variant="subtle" onClick={loadUsers} loading={loading}>{t("common.refresh")}</Button>
        </Group>

        {error && <Alert color="red" variant="light" mb="sm">{error}</Alert>}
        {msg   && <Alert color="teal" variant="light" mb="sm">{msg}</Alert>}

        {loading ? (
          <Loader size="sm" />
        ) : users.length === 0 ? (
          <Text size="sm" c="dimmed">{t("acl.users.noUsers")}</Text>
        ) : (
          <Table striped highlightOnHover withTableBorder withColumnBorders style={{ fontSize: "0.8rem" }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("common.username")}</Table.Th>
                {PERM_FLAGS.map(f => <Table.Th key={f.key} style={{ textAlign: "center" }}>{f.label}</Table.Th>)}
                <Table.Th style={{ textAlign: "center" }}>{t("common.actions")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {users.map(user => (
                <Table.Tr key={user.username} style={!user.has_piq_record ? { opacity: 0.65 } : undefined}>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm">{user.username}</Text>
                      {user.ng_admin && (
                        <Tooltip label={t("acl.users.ngAdminTooltip")}>
                          <Badge size="xs" color="blue" variant="light">{t("common.ngAdmin")}</Badge>
                        </Tooltip>
                      )}
                      {!user.has_piq_record && (
                        <Tooltip label={t("acl.users.noRecordTooltip")}>
                          <Badge size="xs" color="gray" variant="outline">{t("common.noRecord")}</Badge>
                        </Tooltip>
                      )}
                    </Group>
                  </Table.Td>
                  {PERM_FLAGS.map(f => (
                    <Table.Td key={f.key} style={{ textAlign: "center" }}>
                      <Switch
                        size="xs"
                        checked={user[f.key] as boolean}
                        disabled={saving === user.username}
                        onChange={e => togglePerm(user, f.key, e.currentTarget.checked)}
                      />
                    </Table.Td>
                  ))}
                  <Table.Td style={{ textAlign: "center" }}>
                    {user.has_piq_record ? (
                      deleteConfirm === user.username ? (
                        <Group gap="xs" justify="center" wrap="nowrap">
                          <ActionIcon
                            size="xs" color="red" variant="filled"
                            loading={saving === user.username}
                            onClick={() => deleteUser(user.username)}
                          >✓</ActionIcon>
                          <ActionIcon
                            size="xs" variant="subtle"
                            onClick={() => setDeleteConfirm(null)}
                          >✕</ActionIcon>
                        </Group>
                      ) : (
                        <ActionIcon
                          size="xs" color="red" variant="subtle"
                          onClick={() => setDeleteConfirm(user.username)}
                        ><IconTrash size={14} /></ActionIcon>
                      )
                    ) : (
                      <Text size="xs" c="dimmed">—</Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <Text size="xs" c="dimmed" mt="sm">{t("acl.users.footer")}</Text>
      </Paper>

      {/* ── Audit Log ───────────────────────────────────────────────── */}
      <Paper id="section-audit-log" withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("acl.sections.audit")}</Text>
        <Text size="sm" c="dimmed" mb="md">{t("acl.audit.description")}</Text>
        <NumberInput
          label={t("acl.audit.retention.label")}
          name="audit_retention_days"
          min={30}
          style={{ maxWidth: 260 }}
          defaultValue={Number(s.audit_retention_days ?? 180)}
          description={t("acl.audit.retention.description")}
        />
      </Paper>

      {/* ── Maintenance ─────────────────────────────────────────────── */}
      <Paper id="section-maintenance" withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("acl.sections.maintenance")}</Text>
        <Text size="sm" c="dimmed" mb="md">{t("acl.maintenance.description")}</Text>
        {maintenanceMsg && (
          <Alert color="teal" variant="light" mb="sm">{maintenanceMsg}</Alert>
        )}
        <Divider label={t("acl.maintenance.vectorStore")} labelPosition="left" mb="sm" />
        <Group gap="sm" mb="xs">
          <Button variant="light" color="teal" size="sm" loading={reindexing} onClick={onReindex}>
            {t("acl.maintenance.reindexAll")}
          </Button>
          <Text size="xs" c="dimmed" style={{ alignSelf: "center" }}>{t("acl.maintenance.reindexAllDesc")}</Text>
        </Group>
        <Group gap="sm" mb="md" align="flex-end">
          <div>
            <Text size="xs" c="dimmed" mb={4}>{t("acl.maintenance.reindexSinceLabel")}</Text>
            <input
              type="date"
              value={reindexSinceDate}
              onChange={e => onReindexSinceDateChange(e.target.value)}
              style={{ fontSize: 13, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--mantine-color-default-border)" }}
            />
          </div>
          <Button variant="light" color="teal" size="sm" loading={reindexingSince} disabled={!reindexSinceDate} onClick={onReindexSince}>
            {t("acl.maintenance.reindexSince")}
          </Button>
        </Group>
        <Divider label={t("acl.maintenance.tracking")} labelPosition="left" mb="sm" />
        <Group gap="sm">
          <Button variant="light" color="orange" size="sm" loading={resettingTracking} onClick={onResetTracking}>
            {t("acl.maintenance.resetSeen")}
          </Button>
          <Button variant="light" color="red" size="sm" loading={resettingRejected} onClick={onResetRejected}>
            {t("acl.maintenance.resetRejected")}
          </Button>
          <Text size="xs" c="dimmed" style={{ alignSelf: "center" }}>{t("acl.maintenance.resetDesc")}</Text>
        </Group>
      </Paper>
    </Stack>
  );
}
