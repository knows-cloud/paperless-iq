import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Title, Text, Group, Box, Button, Paper, Badge, ActionIcon,
  Anchor, Textarea, Loader, Stack, Drawer,
} from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { api } from "../api";
import { t } from "../i18n";
import { MarkdownText, Source } from "../components/MarkdownText";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  loading?: boolean;
  error?: string;
}

const SUGGESTED_QUERIES = [
  "What contracts are currently active and when do they expire?",
  "Which documents mention a notice period or cancellation clause?",
  "What are the payment terms in my contracts?",
  "Find documents that mention a penalty or liability clause",
  "Which documents involve automatic renewal?",
  "What insurance policies do I have and what do they cover?",
];

// ---------------------------------------------------------------------------
// Source card (right panel)
// ---------------------------------------------------------------------------

function SourceCard({ src, index, highlighted }: { src: Source; index: number; highlighted: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const PREVIEW = 220;
  const needsTruncation = src.snippet.length > PREVIEW;
  const displayText = expanded || !needsTruncation ? src.snippet : src.snippet.slice(0, PREVIEW) + "…";
  const scoreColor = src.score > 0.75 ? "teal" : src.score > 0.5 ? "yellow" : "gray";

  return (
    <Paper
      id={`source-${index + 1}`}
      withBorder
      p="sm"
      radius="md"
      mb="sm"
      style={{
        transition: "background 0.3s, border-color 0.3s",
        ...(highlighted ? {
          background: "var(--mantine-color-teal-light)",
          borderColor: "var(--mantine-color-teal-3)",
        } : {}),
      }}
    >
      <Group gap="xs" align="flex-start" wrap="nowrap">
        <Box
          style={{
            background: "var(--mantine-color-teal-6)",
            color: "white",
            borderRadius: "50%",
            width: 20, height: 20, minWidth: 20,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: "0.65rem", fontWeight: 700, flexShrink: 0, marginTop: 2,
          }}
        >
          {index + 1}
        </Box>

        <Box style={{ flex: 1, minWidth: 0 }}>
          <Text size="sm" fw={600} mb={4} style={{ wordBreak: "break-word", lineHeight: 1.35 }}>
            {src.title || `Document #${src.document_id}`}
          </Text>

          <Group gap={6} wrap="wrap">
            <Badge size="xs" variant="outline" color="gray" style={{ fontFamily: "monospace" }}>
              #{src.document_id}
            </Badge>
            <Badge size="xs" color={scoreColor} variant="light">
              {Math.round(src.score * 100)}%
            </Badge>
            <Anchor href={src.deeplink_url} target="_blank" rel="noopener noreferrer" size="xs" ml="auto">
              Open ↗
            </Anchor>
          </Group>

          {src.snippet && (
            <Box
              mt="xs"
              p="xs"
              style={{
                background: "var(--mantine-color-default-hover)",
                borderRadius: "var(--mantine-radius-sm)",
                borderLeft: "2px solid var(--mantine-color-teal-4)",
              }}
            >
              <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
                {displayText}
              </Text>
              {needsTruncation && (
                <Anchor
                  component="button"
                  size="xs"
                  mt={4}
                  onClick={() => setExpanded(e => !e)}
                >
                  {expanded ? "▲ Less" : `▼ +${src.snippet.length - PREVIEW} chars`}
                </Anchor>
              )}
            </Box>
          )}
        </Box>
      </Group>
    </Paper>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function DiscoveryPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [latestSources, setLatestSources] = useState<Source[]>([]);
  const [highlightedSource, setHighlightedSource] = useState<number | null>(null);

  const [sourcesOpen, { open: openSources, close: closeSources }] = useDisclosure(false);
  const isMobile = useMediaQuery("(max-width: 48em)");

  const sessionIdRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const statusQ = useQuery({ queryKey: ["status"], queryFn: api.getStatus, retry: false, staleTime: 60000 });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const scrollToSource = useCallback((n: number) => {
    if (isMobile) openSources();
    setTimeout(() => {
      const el = document.getElementById(`source-${n}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        setHighlightedSource(n);
        setTimeout(() => setHighlightedSource(null), 1800);
      }
    }, isMobile ? 220 : 0);
  }, [isMobile, openSources]);

  const handleSubmit = async (question?: string) => {
    const q = (question ?? input).trim();
    if (!q || loading) return;
    setInput("");
    setMessages(prev => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "", loading: true },
    ]);
    setLoading(true);
    textareaRef.current?.focus();

    try {
      const result = await api.discover(q, 5, sessionIdRef.current);
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
      setLatestSources(result.sources as Source[]);
      if (result.session_id) sessionIdRef.current = result.session_id;
    } catch (err: unknown) {
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: "assistant", content: "", error: (err as Error).message },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleNewConversation = useCallback(async () => {
    if (sessionIdRef.current) {
      try { await api.deleteDiscoverSession(sessionIdRef.current); } catch { /* ignore */ }
      sessionIdRef.current = null;
    }
    setMessages([]);
    setLatestSources([]);
    setInput("");
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const hasInput = input.trim().length > 0;
  const hasSources = latestSources.length > 0;

  return (
    <>
      <style>{`
        @keyframes discoveryMsgIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .discovery-msg-enter { animation: discoveryMsgIn 0.2s ease-out; }
        @keyframes discoveryDot {
          0%, 60%, 100% { transform: translateY(0);    opacity: 0.35; }
          30%            { transform: translateY(-4px); opacity: 1;    }
        }
        .discovery-answer > *:first-child { margin-top: 0 !important; }
        .discovery-answer > *:last-child  { margin-bottom: 0 !important; }
        .discovery-send-btn:hover:not(:disabled) { transform: scale(1.06); }
        .discovery-send-btn:active:not(:disabled) { transform: scale(0.95); }
        /* On mobile the AppShell header is 50px; subtract it from the page height */
        @media (max-width: 48em) {
          .discovery-root { height: calc(100dvh - 50px - 8rem) !important; }
        }
      `}</style>

      <Box className="discovery-root" style={{ display: "flex", flexDirection: "column", height: "calc(100dvh - 8rem)" }}>

        {/* Header */}
        <Group justify="space-between" align="flex-start" mb="sm" style={{ flexShrink: 0 }}>
          <div>
            <Title order={2} mb={4}>{t("discovery.title")}</Title>
            <Text size="sm" c="dimmed">{t("discovery.subtitle")}</Text>
          </div>
          {messages.length > 0 && (
            <Button
              variant="outline"
              color="teal"
              size="sm"
              onClick={handleNewConversation}
              disabled={loading}
              style={{ flexShrink: 0 }}
            >
              ✦ New conversation
            </Button>
          )}
        </Group>

        {/* Two-column body */}
        <Box
          style={{
            display: "flex",
            gap: "1rem",
            flex: 1,
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          {/* ── Chat column ── */}
          <Box style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>

            {/* Messages scroll area */}
            <Box style={{ flex: 1, overflowY: "auto", paddingRight: 2, paddingBottom: 8 }}>

              {/* Empty state */}
              {messages.length === 0 && (
                <Stack gap="xs" pt="xl" style={{ maxWidth: 520 }}>
                  <Text size="lg" fw={600}>{t("discovery.emptyTitle")}</Text>
                  <Text size="sm" c="dimmed" mb="md">{t("discovery.emptyHint")}</Text>
                  <Group gap={6} wrap="wrap">
                    {SUGGESTED_QUERIES.map((q, i) => (
                      <Button
                        key={i}
                        variant="outline"
                        color="gray"
                        size="xs"
                        style={{ borderRadius: 20, fontWeight: 400, textAlign: "left", height: "auto", lineHeight: 1.4 }}
                        onClick={() => handleSubmit(q)}
                      >
                        {q}
                      </Button>
                    ))}
                  </Group>
                </Stack>
              )}

              {/* Messages */}
              {messages.map((msg, i) => (
                <Box key={i} className="discovery-msg-enter" mb="md">
                  {msg.role === "user" ? (
                    /* User bubble — right-aligned, teal filled */
                    <Group justify="flex-end">
                      <Box
                        style={{
                          padding: "0.65rem 1.1rem",
                          borderRadius: "20px 20px 4px 20px",
                          background: "var(--mantine-color-teal-filled)",
                          maxWidth: "78%",
                          fontSize: "0.9rem",
                          lineHeight: 1.55,
                          color: "var(--mantine-color-white)",
                          boxShadow: "var(--mantine-shadow-sm)",
                          wordBreak: "break-word",
                        }}
                      >
                        {msg.content}
                      </Box>
                    </Group>
                  ) : (
                    /* Assistant bubble — left-aligned */
                    <Box style={{ maxWidth: "100%" }}>
                      <Group gap={6} mb={4} pl={2}>
                        <Box
                          style={{
                            width: 18, height: 18,
                            background: "var(--mantine-color-teal-light)",
                            borderRadius: "50%",
                            display: "inline-flex", alignItems: "center", justifyContent: "center",
                            fontSize: "0.65rem", fontWeight: 700,
                            color: "var(--mantine-color-teal-6)",
                          }}
                        >✦</Box>
                        <Text size="xs" c="dimmed">Paperless IQ</Text>
                      </Group>

                      <Paper
                        withBorder
                        p="md"
                        style={{
                          borderRadius: "4px 20px 20px 20px",
                          fontSize: "0.875rem",
                          lineHeight: 1.72,
                          wordBreak: "break-word",
                        }}
                      >
                        {msg.loading ? (
                          <Group gap="sm">
                            <Group gap={4} align="center">
                              {[0, 1, 2].map(k => (
                                <Box key={k} style={{
                                  width: 6, height: 6, borderRadius: "50%",
                                  background: "var(--mantine-color-teal-5)",
                                  display: "inline-block",
                                  animation: `discoveryDot 1.3s ease-in-out ${k * 0.18}s infinite`,
                                }} />
                              ))}
                            </Group>
                            <Text size="sm" c="dimmed">{t("discovery.searching")}</Text>
                          </Group>
                        ) : msg.error ? (
                          <Text size="sm" c="red">⚠ {msg.error}</Text>
                        ) : (
                          <div className="discovery-answer">
                            <MarkdownText
                              text={msg.content}
                              sources={msg.sources}
                              onCiteClick={msg.sources?.length ? scrollToSource : undefined}
                            />
                          </div>
                        )}
                      </Paper>

                      {/* Source reference pills below the bubble */}
                      {msg.sources && msg.sources.length > 0 && (
                        <Group gap={4} mt={4} pl={2}>
                          <Text size="xs" c="dimmed">
                            {msg.sources.length} {msg.sources.length === 1 ? "source" : "sources"} →
                          </Text>
                          {msg.sources.map((src, j) => (
                            <Box
                              key={j}
                              component="button"
                              type="button"
                              title={`${src.title || `#${src.document_id}`} (ID ${src.document_id})`}
                              onClick={() => scrollToSource(j + 1)}
                              style={{
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                                width: 18, height: 18, borderRadius: "50%",
                                background: "var(--mantine-color-teal-6)",
                                color: "white",
                                fontSize: "0.6rem", fontWeight: 700,
                                border: "none", cursor: "pointer",
                                lineHeight: 1,
                              }}
                            >
                              {j + 1}
                            </Box>
                          ))}
                        </Group>
                      )}
                    </Box>
                  )}
                </Box>
              ))}
              <div ref={bottomRef} />
            </Box>

            {/* Mobile: sources drawer trigger — only when sources exist */}
            {hasSources && (
              <Group hiddenFrom="sm" justify="flex-end" py={6} style={{ flexShrink: 0 }}>
                <Button
                  variant="light"
                  color="teal"
                  size="xs"
                  onClick={openSources}
                  style={{ borderRadius: 20 }}
                >
                  📄 Sources ({latestSources.length})
                </Button>
              </Group>
            )}

            {/* Input area */}
            <Box
              style={{
                flexShrink: 0,
                paddingTop: "0.6rem",
                borderTop: "1px solid var(--mantine-color-default-border)",
              }}
            >
              <Box
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  gap: "0.5rem",
                  background: "var(--mantine-color-default)",
                  borderRadius: 24,
                  padding: "0.45rem 0.45rem 0.45rem 1rem",
                  border: "1px solid var(--mantine-color-default-border)",
                  transition: "border-color 0.15s",
                }}
              >
                <Textarea
                  ref={textareaRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={t("discovery.placeholder")}
                  disabled={loading}
                  autosize
                  minRows={1}
                  maxRows={5}
                  style={{ flex: 1 }}
                  styles={{
                    input: {
                      border: "none",
                      background: "transparent",
                      padding: "0.3rem 0",
                      fontSize: "0.9rem",
                      lineHeight: 1.55,
                    },
                    wrapper: { background: "transparent" },
                  }}
                />
                <ActionIcon
                  className="discovery-send-btn"
                  radius="xl"
                  size="lg"
                  variant={hasInput && !loading ? "filled" : "subtle"}
                  color={hasInput && !loading ? "teal" : "gray"}
                  disabled={loading || !hasInput}
                  onClick={() => handleSubmit()}
                  title="Send (Enter)"
                  style={{ flexShrink: 0, transition: "transform 0.1s" }}
                >
                  {loading ? <Loader size="xs" /> : <span style={{ fontSize: "1rem" }}>↑</span>}
                </ActionIcon>
              </Box>
              <Text size="xs" c="dimmed" mt={4} ml={4}>
                Enter · Shift+Enter for newline
              </Text>
            </Box>
          </Box>

          {/* ── Sources panel (desktop only) ── */}
          {hasSources && (
            <Box
              visibleFrom="sm"
              style={{
                width: 300,
                flexShrink: 0,
                overflowY: "auto",
                borderLeft: "1px solid var(--mantine-color-default-border)",
                paddingLeft: "1rem",
              }}
            >
              <Group justify="space-between" align="baseline" mb="sm">
                <Text size="xs" fw={700} tt="uppercase" c="dimmed" style={{ letterSpacing: "0.07em" }}>
                  {t("discovery.sources")} {latestSources.length}
                </Text>
                {statusQ.data?.paperless_public_url && (
                  <Anchor
                    href={statusQ.data.paperless_public_url as string}
                    target="_blank"
                    rel="noopener noreferrer"
                    size="xs"
                  >
                    Open Paperless ↗
                  </Anchor>
                )}
              </Group>
              {latestSources.map((src, j) => (
                <SourceCard
                  key={j}
                  src={src}
                  index={j}
                  highlighted={highlightedSource === j + 1}
                />
              ))}
            </Box>
          )}
        </Box>
      </Box>

      {/* ── Sources drawer (mobile only) ── */}
      <Drawer
        opened={sourcesOpen}
        onClose={closeSources}
        position="right"
        size={320}
        title={
          <Group gap="xs">
            <Text fw={700} size="sm">{t("discovery.sources")} {latestSources.length}</Text>
            {statusQ.data?.paperless_public_url && (
              <Anchor
                href={statusQ.data.paperless_public_url as string}
                target="_blank"
                rel="noopener noreferrer"
                size="xs"
              >
                Open Paperless ↗
              </Anchor>
            )}
          </Group>
        }
      >
        {latestSources.map((src, j) => (
          <SourceCard
            key={j}
            src={src}
            index={j}
            highlighted={highlightedSource === j + 1}
          />
        ))}
      </Drawer>
    </>
  );
}
