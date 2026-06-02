import { Group, Tooltip, ActionIcon, Text } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";

interface Props {
  label: string;
  tip: string;
  required?: boolean;
}

export function InfoLabel({ label, tip, required }: Props) {
  return (
    <Group gap={4} wrap="nowrap">
      <Text size="sm" fw={500}>
        {label}
        {required && <Text span c="red" ml={2}>*</Text>}
      </Text>
      <Tooltip label={tip} multiline w={260} withArrow position="top-start">
        <ActionIcon variant="transparent" size="xs" color="dimmed" style={{ cursor: "help" }}>
          <IconInfoCircle size={14} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}
