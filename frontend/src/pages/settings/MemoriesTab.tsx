import { Switch, Button, Textarea, ActionIcon, Paper, Text, Group, Stack, Loader, Box } from "@mantine/core";
import { IconEdit, IconX } from "@tabler/icons-react";
import { api } from "../../api";

export type MemoryItem = {
  id: string;
  text: string;
  created_at: string;
  updated_at: string;
  source_session_id: string | null;
};

interface Props {
  memoryEnabled: boolean;
  setMemoryEnabled: (v: boolean) => void;
  memories: MemoryItem[];
  setMemories: React.Dispatch<React.SetStateAction<MemoryItem[]>>;
  memoriesLoading: boolean;
  editingMemoryId: string | null;
  setEditingMemoryId: (v: string | null) => void;
  editMemoryText: string;
  setEditMemoryText: (v: string) => void;
  clearMemoriesConfirm: boolean;
  setClearMemoriesConfirm: (v: boolean) => void;
}

export function MemoriesTab({
  memoryEnabled, setMemoryEnabled,
  memories, setMemories,
  memoriesLoading,
  editingMemoryId, setEditingMemoryId,
  editMemoryText, setEditMemoryText,
  clearMemoriesConfirm, setClearMemoriesConfirm,
}: Props) {
  return (
    <Paper withBorder p="md" radius="md">
      <Text fw={600} mb="xs">Long-term Memory</Text>

      <Switch
        label="Enable long-term memory"
        checked={memoryEnabled}
        onChange={e => setMemoryEnabled(e.currentTarget.checked)}
        description="When enabled, key facts are automatically extracted from Discovery conversations and injected as context in future chats. Facts are deduplicated — similar entries are merged rather than duplicated."
        mb="lg"
      />

      <Group justify="space-between" mb="sm">
        <Text size="xs" fw={500} tt="uppercase" c="dimmed">
          Learned facts {memories.length > 0 && `(${memories.length})`}
        </Text>
        {memories.length > 0 && !clearMemoriesConfirm && (
          <Button size="xs" color="red" variant="light" onClick={() => setClearMemoriesConfirm(true)}>
            Clear all
          </Button>
        )}
        {clearMemoriesConfirm && (
          <Group gap="xs">
            <Text size="xs">Are you sure?</Text>
            <Button size="xs" color="red" onClick={async () => {
              await api.clearMemories();
              setMemories([]);
              setClearMemoriesConfirm(false);
            }}>
              Yes, clear
            </Button>
            <Button size="xs" variant="default" onClick={() => setClearMemoriesConfirm(false)}>
              Cancel
            </Button>
          </Group>
        )}
      </Group>

      {memoriesLoading ? (
        <Group gap="xs" mt="sm"><Loader size="xs" /><Text size="sm" c="dimmed">Loading…</Text></Group>
      ) : memories.length === 0 ? (
        <Text size="sm" c="dimmed" mt="sm">
          No memories yet. Facts will appear here after Discovery conversations are closed.
        </Text>
      ) : (
        <Stack gap={6}>
          {memories.map(mem => (
            <Box
              key={mem.id}
              p="sm"
              style={{
                display: "flex", alignItems: "flex-start", gap: "0.6rem",
                background: "var(--mantine-color-default-hover)",
                border: "1px solid var(--mantine-color-default-border)",
                borderRadius: "var(--mantine-radius-sm)",
              }}
            >
              <Text c="teal" size="sm" style={{ flexShrink: 0, lineHeight: 1.6 }}>•</Text>

              {editingMemoryId === mem.id ? (
                <Stack gap="xs" style={{ flex: 1 }}>
                  <Textarea
                    value={editMemoryText}
                    onChange={e => setEditMemoryText(e.target.value)}
                    rows={2}
                    autoFocus
                  />
                  <Group gap="xs">
                    <Button size="xs" onClick={async () => {
                      await api.updateMemory(mem.id, editMemoryText);
                      setEditingMemoryId(null);
                      setMemories(prev => prev.map(m => m.id === mem.id ? { ...m, text: editMemoryText } : m));
                    }}>
                      Save
                    </Button>
                    <Button size="xs" variant="default" onClick={() => setEditingMemoryId(null)}>
                      Cancel
                    </Button>
                  </Group>
                </Stack>
              ) : (
                <Text size="sm" style={{ flex: 1, lineHeight: 1.55, paddingTop: "0.1rem" }}>
                  {mem.text}
                </Text>
              )}

              {editingMemoryId !== mem.id && (
                <Group gap={4} style={{ flexShrink: 0 }}>
                  <ActionIcon
                    size="sm" variant="subtle" color="gray"
                    title="Edit"
                    onClick={() => { setEditingMemoryId(mem.id); setEditMemoryText(mem.text); }}
                  >
                    <IconEdit size={14} />
                  </ActionIcon>
                  <ActionIcon
                    size="sm" variant="subtle" color="red"
                    title="Delete"
                    onClick={async () => {
                      await api.deleteMemory(mem.id);
                      setMemories(prev => prev.filter(m => m.id !== mem.id));
                    }}
                  >
                    <IconX size={14} />
                  </ActionIcon>
                </Group>
              )}
            </Box>
          ))}
        </Stack>
      )}

      {memories.length > 0 && (
        <Text size="xs" c="dimmed" mt="sm">
          Most recent: {new Date(memories[0].updated_at).toLocaleDateString()}
        </Text>
      )}
    </Paper>
  );
}
