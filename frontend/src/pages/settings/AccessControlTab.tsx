import { useState, useEffect } from "react";
import {
  Stack, Paper, Text, Switch, Button, Group, Badge, Divider,
  Alert, Loader, Table, ActionIcon, Tooltip, Anchor, NumberInput,
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { api } from "../../api";
import type { UserPermissions } from "../../api";

const PERM_FLAGS: Array<{ key: keyof Omit<UserPermissions, "username" | "ng_admin" | "updated_at" | "has_piq_record">; label: string }> = [
  { key: "can_access",     label: "Access" },
  { key: "can_view_queue", label: "Queue" },
  { key: "can_approve",    label: "Approve" },
  { key: "can_analyze",    label: "Analyze" },
  { key: "can_discover",   label: "Discovery" },
  { key: "can_settings",   label: "Settings" },
];

const SECTIONS = [
  { id: "section-access-control",  label: "Access Control" },
  { id: "section-user-permissions", label: "User Permissions" },
  { id: "section-audit-log",       label: "Audit Log" },
  { id: "section-maintenance",     label: "Maintenance" },
];

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

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function AccessControlTab({
  s,
  onReindex,
  reindexing,
  onReindexSince,
  reindexingSince,
  reindexSinceDate,
  onReindexSinceDateChange,
  onResetTracking,
  resettingTracking,
  onResetRejected,
  resettingRejected,
  maintenanceMsg,
}: Props) {
  const [users, setUsers] = useState<UserPermissions[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

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
      });
      setUsers(prev => prev.map(u => u.username === user.username
        ? { ...u, [key]: value, has_piq_record: true }
        : u
      ));
      setMsg(`Saved permissions for ${user.username}.`);
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
      // Keep user in list but mark as no record (they came from Paperless NGX)
      setUsers(prev => prev.map(u => u.username === username
        ? { ...u, has_piq_record: false, can_access: false, can_view_queue: false, can_approve: false, can_analyze: false, can_discover: false, can_settings: false }
        : u
      ));
      setDeleteConfirm(null);
      setMsg(`Removed permission record for ${username}.`);
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
        <Text size="xs" c="dimmed" fw={500}>Jump to:</Text>
        {SECTIONS.map(sec => (
          <Anchor key={sec.id} size="xs" onClick={() => scrollTo(sec.id)} style={{ cursor: "pointer" }}>
            {sec.label}
          </Anchor>
        ))}
      </Group>

      {/* ── Access Control Settings ─────────────────────────────────── */}
      <Paper id="section-access-control" withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Access Control Settings</Text>
        <Text size="sm" c="dimmed" mb="md">
          When sync is enabled, Paperless NGX admins (superuser / staff) automatically receive full Paperless IQ access
          without needing manual permission grants.
        </Text>
        <Switch
          name="sync_ng_admins"
          label="Sync Paperless NGX admins — grant them full PIQ access automatically"
          defaultChecked={Boolean(s.sync_ng_admins !== false)}
        />
      </Paper>

      {/* ── User Permissions ────────────────────────────────────────── */}
      <Paper id="section-user-permissions" withBorder p="md" radius="md">
        <Group justify="space-between" mb="md">
          <Text fw={600}>User Permissions</Text>
          <Button size="xs" variant="subtle" onClick={loadUsers} loading={loading}>Refresh</Button>
        </Group>

        {error && <Alert color="red" variant="light" mb="sm">{error}</Alert>}
        {msg   && <Alert color="teal" variant="light" mb="sm">{msg}</Alert>}

        {loading ? (
          <Loader size="sm" />
        ) : users.length === 0 ? (
          <Text size="sm" c="dimmed">
            No users found. Users appear here after their first login, or when Paperless NGX is connected.
          </Text>
        ) : (
          <Table striped highlightOnHover withTableBorder withColumnBorders style={{ fontSize: "0.8rem" }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Username</Table.Th>
                {PERM_FLAGS.map(f => <Table.Th key={f.key} style={{ textAlign: "center" }}>{f.label}</Table.Th>)}
                <Table.Th style={{ textAlign: "center" }}>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {users.map(user => (
                <Table.Tr key={user.username} style={!user.has_piq_record ? { opacity: 0.65 } : undefined}>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm">{user.username}</Text>
                      {user.ng_admin && (
                        <Tooltip label="Paperless NGX admin">
                          <Badge size="xs" color="blue" variant="light">NG admin</Badge>
                        </Tooltip>
                      )}
                      {!user.has_piq_record && (
                        <Tooltip label="No PIQ record yet — permissions take effect on first login">
                          <Badge size="xs" color="gray" variant="outline">no record</Badge>
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
        <Text size="xs" c="dimmed" mt="sm">
          Users marked <strong>no record</strong> exist in Paperless NGX but have not yet logged into PIQ.
          Permissions you set here take effect on their first login.
          Deleting a record revokes all access — the user can log in again to create a fresh record with default (deny-all) permissions.
        </Text>
      </Paper>

      {/* ── Audit Log ───────────────────────────────────────────────── */}
      <Paper id="section-audit-log" withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Audit Log</Text>
        <Text size="sm" c="dimmed" mb="md">
          Controls how long audit log entries are retained before automatic deletion.
        </Text>
        <NumberInput
          label="Retention period (days, minimum 30)"
          name="audit_retention_days"
          min={30}
          style={{ maxWidth: 260 }}
          defaultValue={Number(s.audit_retention_days ?? 180)}
          description="Default: 180 days (6 months). Entries older than this are deleted automatically."
        />
      </Paper>

      {/* ── Maintenance ─────────────────────────────────────────────── */}
      <Paper id="section-maintenance" withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Maintenance</Text>
        <Text size="sm" c="dimmed" mb="md">
          Administrative actions that rebuild internal state. Use with care.
        </Text>
        {maintenanceMsg && (
          <Alert color="teal" variant="light" mb="sm">{maintenanceMsg}</Alert>
        )}
        <Divider label="Vector store" labelPosition="left" mb="sm" />
        <Group gap="sm" mb="xs">
          <Button
            variant="light" color="teal" size="sm"
            loading={reindexing}
            onClick={onReindex}
          >
            Reindex all documents
          </Button>
          <Text size="xs" c="dimmed" style={{ alignSelf: "center" }}>
            Wipes and rebuilds the vector store from scratch. Required after changing the embedding model.
          </Text>
        </Group>
        <Group gap="sm" mb="md" align="flex-end">
          <div>
            <Text size="xs" c="dimmed" mb={4}>Re-index documents modified on or after:</Text>
            <input
              type="date"
              value={reindexSinceDate}
              onChange={e => onReindexSinceDateChange(e.target.value)}
              style={{ fontSize: 13, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--mantine-color-default-border)" }}
            />
          </div>
          <Button
            variant="light" color="teal" size="sm"
            loading={reindexingSince}
            disabled={!reindexSinceDate}
            onClick={onReindexSince}
          >
            Reindex since date
          </Button>
        </Group>
        <Divider label="Tracking" labelPosition="left" mb="sm" />
        <Group gap="sm">
          <Button
            variant="light" color="orange" size="sm"
            loading={resettingTracking}
            onClick={onResetTracking}
          >
            Reset seen documents
          </Button>
          <Button
            variant="light" color="red" size="sm"
            loading={resettingRejected}
            onClick={onResetRejected}
          >
            Reset rejected suggestions
          </Button>
          <Text size="xs" c="dimmed" style={{ alignSelf: "center" }}>
            Reset forces all documents to be re-analyzed on the next automation cycle.
          </Text>
        </Group>
      </Paper>
    </Stack>
  );
}
