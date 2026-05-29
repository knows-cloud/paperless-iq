import { useState, FormEvent } from "react";
import {
  Center, Paper, Title, Text, TextInput, PasswordInput,
  Button, Alert, Stack,
} from "@mantine/core";
import { IconLogin2 } from "@tabler/icons-react";
import { useTranslation } from "react-i18next";
import { api, setStoredToken } from "../api";

interface LoginPageProps {
  onLogin: (user: string) => void;
}

export default function LoginPage({ onLogin }: LoginPageProps) {
  const { t } = useTranslation();
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
      setError(err instanceof Error ? err.message : t("login.failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Center mih="100vh">
      <Paper withBorder shadow="lg" p="xl" radius="md" w="100%" maw={380}>
        <Stack align="center" mb="xl" gap={4}>
          <Text size="2.5rem" lh={1}>📄</Text>
          <Title order={2} mt={4}>Paperless IQ</Title>
          <Text size="sm" c="dimmed">{t("login.subtitle")}</Text>
        </Stack>

        <form onSubmit={handleSubmit}>
          <Stack gap="md">
            <TextInput
              label={t("common.username")}
              placeholder="paperless-username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={e => setUsername(e.currentTarget.value)}
              disabled={loading}
            />
            <PasswordInput
              label={t("login.password")}
              placeholder="••••••••"
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.currentTarget.value)}
              disabled={loading}
            />

            {error && (
              <Alert color="red" variant="light">
                {error}
              </Alert>
            )}

            <Button
              type="submit"
              fullWidth
              mt="xs"
              loading={loading}
              disabled={!username.trim() || !password.trim()}
              leftSection={<IconLogin2 size={16} />}
            >
              {t("login.signIn")}
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
