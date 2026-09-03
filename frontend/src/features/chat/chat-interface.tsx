"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowUp,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Cpu,
  FileText,
  GitPullRequest,
  Loader2,
  Mail,
  MessagesSquare,
  PanelLeft,
  Sparkles,
  Square,
  Ticket,
  Wrench,
  XCircle,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "@/features/auth/auth-context";
import MarkdownMessage from "@/features/chat/markdown-message";
import {
  ConversationRail,
  useConversations,
} from "@/features/chat/conversation-rail";
import {
  checkLLMStatus,
  getConversationMessages,
  streamChatMessage,
  type ActionResult,
  type Message as ApiMessage,
  type StreamEvent,
} from "@/lib/api";
import { Avatar } from "@/components/ui/avatar";
import { Button, IconButton } from "@/components/ui/button";
import { Dialog, Sheet } from "@/components/ui/overlay";
import { Notice } from "@/components/ui/surface";
import { cn } from "@/lib/utils";

/**
 * Chat.
 *
 * Three structural changes from what this replaces. The conversation list came
 * out of the global sidebar and into a rail that belongs to this page. The
 * composer is a growing textarea rather than a single-line `<input>` inside a
 * spring-animated container that changed height on focus — you could not see
 * the second line of what you were typing, and Shift+Enter did nothing. And a
 * run in progress can be stopped: the stream already returned an abort handle,
 * and nothing was wired to it, so a request that picked the wrong tool ran to
 * completion with no way to interrupt it.
 *
 * The emoji service map is gone. Thirteen emoji at 18px rendering differently
 * on every platform is not an icon set.
 */

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  actions?: ActionResult[];
}

interface LiveTask {
  task_id: string;
  service: string;
  action: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  result?: string;
  error?: string;
}

/**
 * Rendered elements rather than component types.
 *
 * Looking a component *type* up by name and binding it to a capitalised local
 * inside a render body is how a component gets recreated on every render —
 * `react-hooks/static-components` flags it, correctly. Elements are inert, so
 * the map holds those and the call site just interpolates one.
 */
const ICON_CLASS = "size-3.5";

const SERVICE_ICON: Record<string, React.ReactNode> = {
  slack: <MessagesSquare className={ICON_CLASS} />,
  jira: <Ticket className={ICON_CLASS} />,
  linear: <Ticket className={ICON_CLASS} />,
  gmail: <Mail className={ICON_CLASS} />,
  calendar: <Calendar className={ICON_CLASS} />,
  meet: <Calendar className={ICON_CLASS} />,
  notion: <FileText className={ICON_CLASS} />,
  docs: <FileText className={ICON_CLASS} />,
  sheets: <FileText className={ICON_CLASS} />,
  slides: <FileText className={ICON_CLASS} />,
  drive: <FileText className={ICON_CLASS} />,
  forms: <FileText className={ICON_CLASS} />,
  github: <GitPullRequest className={ICON_CLASS} />,
};

const iconFor = (service: string): React.ReactNode =>
  SERVICE_ICON[service?.toLowerCase()] ?? <Wrench className={ICON_CLASS} />;

const SUGGESTIONS = [
  {
    icon: MessagesSquare,
    label: "What did the team decide about the retry gate?",
  },
  { icon: Ticket, label: "Summarise the tickets assigned to me this week" },
  { icon: Calendar, label: "Find me two hours for deep work tomorrow" },
  { icon: Mail, label: "Draft a QA brief for the last merge" },
];

/* ── Tool run ─────────────────────────────────────────────────────────────── */

function ToolRun({
  service,
  action,
  description,
  status,
  result,
  error,
}: {
  service: string;
  action: string;
  description?: string;
  status: LiveTask["status"] | "done";
  result?: string;
  error?: string;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "flex items-start gap-3 rounded-md border px-3.5 py-2.5",
        status === "failed"
          ? "border-danger-border bg-danger-soft"
          : status === "in_progress"
            ? "border-info-border bg-info-soft"
            : "border-line bg-surface-2"
      )}
    >
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-pill bg-surface text-subtle">
        {iconFor(service)}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{action}</span>
          {status === "in_progress" && (
            <Loader2 className="size-3.5 shrink-0 animate-spin text-info" aria-hidden />
          )}
          {(status === "completed" || status === "done") && (
            <CheckCircle2 className="size-3.5 shrink-0 text-success" aria-hidden />
          )}
          {status === "failed" && (
            <XCircle className="size-3.5 shrink-0 text-danger" aria-hidden />
          )}
        </div>
        {description && (
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{description}</p>
        )}
        {result && (status === "completed" || status === "done") && (
          <p className="mt-1 line-clamp-2 text-xs text-muted">{result}</p>
        )}
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      </div>
    </motion.div>
  );
}

/* ── Message ──────────────────────────────────────────────────────────────── */

function Bubble({
  message,
  userName,
  userEmail,
}: {
  message: ChatMessage;
  userName?: string | null;
  userEmail?: string | null;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[80%] rounded-xl rounded-br-sm bg-surface-3 px-4 py-3">
          <p className="whitespace-pre-wrap text-body leading-relaxed text-ink">
            {message.content}
          </p>
        </div>
        <Avatar name={userName} email={userEmail} size="sm" className="mt-0.5" />
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <span
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-pill bg-accent-soft"
        aria-hidden
      >
        <Sparkles className="size-3.5 text-accent-strong" />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        {/* What it actually did, before what it says about it. A tool that
            failed is the most useful thing on screen and used to be a truncated
            line under the answer. */}
        {message.actions && message.actions.length > 0 && (
          <div className="mb-3 space-y-1.5">
            {message.actions.map((action, i) => (
              <ToolRun
                key={i}
                service={action.service}
                action={action.action}
                status={action.success ? "done" : "failed"}
                result={action.result}
                error={action.error}
              />
            ))}
          </div>
        )}
        <MarkdownMessage content={message.content} />
      </div>
    </div>
  );
}

/* ── Composer ─────────────────────────────────────────────────────────────── */

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  smart,
  onSmartChange,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  smart: boolean;
  onSmartChange: (v: boolean) => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow to fit, up to a ceiling. Measured off `scrollHeight` after resetting
  // the height, because otherwise it only ever grows and never shrinks when
  // text is deleted.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    // A defined box, not a hairline. This is the one control on the page and
    // the default border let it dissolve into the ground beneath it.
    <div className="rounded-xl border border-line-strong bg-surface p-2 shadow-md transition-[border-color,box-shadow] focus-within:border-accent focus-within:ring-[3px] focus-within:ring-accent/20">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask across your connected tools…"
        aria-label="Message"
        className="block max-h-[200px] w-full resize-none bg-transparent px-3 py-2.5 text-body leading-relaxed text-ink outline-none placeholder:text-subtle"
      />

      <div className="flex items-center gap-2 px-1 pb-0.5 pt-1">
        <button
          type="button"
          onClick={() => onSmartChange(!smart)}
          aria-pressed={smart}
          title="Use the higher-intelligence model. Slower."
          className={cn(
            "inline-flex items-center gap-1.5 rounded-pill border px-3 py-1.5 text-xs font-medium transition-colors",
            smart
              ? "border-accent bg-accent-soft text-accent-strong"
              : "border-line text-muted hover:border-line-strong hover:text-ink"
          )}
        >
          <Sparkles className="size-3.5" aria-hidden />
          Smart
        </button>

        <span className="ml-auto hidden text-xs text-subtle sm:inline">
          <kbd className="font-mono">Enter</kbd> to send ·{" "}
          <kbd className="font-mono">Shift+Enter</kbd> for a new line
        </span>

        {/* A run in progress can be stopped. The stream already handed back an
            abort function and nothing called it. */}
        {busy ? (
          <IconButton label="Stop generating" variant="secondary" onClick={onStop}>
            <Square className="fill-current" />
          </IconButton>
        ) : (
          <IconButton
            label="Send"
            variant="primary"
            onClick={onSend}
            disabled={!value.trim()}
          >
            <ArrowUp />
          </IconButton>
        )}
      </div>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export function ChatInterface({
  conversationId: initialConversationId,
}: {
  conversationId?: number;
}) {
  const { user } = useAuth();
  const router = useRouter();
  const { conversations, loading: loadingRail, reload } = useConversations();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [status, setStatus] = useState("");
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [smart, setSmart] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [railPinned, setRailPinned] = useState(true);
  const [modelDown, setModelDown] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<number | undefined>(
    initialConversationId
  );

  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, liveTasks, status]);

  // Cancel any in-flight stream when the component goes away, or the socket
  // outlives the page that was reading from it.
  useEffect(() => () => abortRef.current?.(), []);

  useEffect(() => {
    setConversationId(initialConversationId);
    if (!initialConversationId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoadingHistory(true);
    getConversationMessages(initialConversationId)
      .then((apiMessages) => {
        if (cancelled) return;
        setMessages(
          apiMessages.map((m: ApiMessage) => ({
            id: String(m.id),
            role: m.role as "user" | "assistant",
            content: m.content,
            timestamp: new Date(m.created_at),
            actions: m.actions_taken,
          }))
        );
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialConversationId]);

  const stop = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    setBusy(false);
    setStatus("");
    setLiveTasks([]);
  }, []);

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || busy) return;

    if (!user?.id) {
      setModelDown("You need to be signed in to use chat.");
      return;
    }

    // The model server holds one model at a time, so an unavailable one is a
    // configuration state with a remediation, not an opaque connection error.
    try {
      const llm = await checkLLMStatus();
      if (!llm.available) {
        setModelDown(llm.message);
        return;
      }
    } catch {
      setModelDown(
        "Cannot reach the Locus backend. Check that it is running on this machine."
      );
      return;
    }

    const userMessage: ChatMessage = {
      id: `u${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setBusy(true);
    setStatus("Reading your request…");
    setLiveTasks([]);

    abortRef.current = streamChatMessage(
      content,
      (event: StreamEvent) => {
        // A new conversation gets its id from the first event that carries
        // one; the URL is then corrected so a refresh does not start over.
        const newId = event.data?.conversation_id as number | undefined;
        if (newId && !conversationId) {
          setConversationId(newId);
          router.replace(`/chatbot?id=${newId}`, { scroll: false });
        }

        switch (event.event_type) {
          case "planning":
            setStatus(event.data.status || "Planning…");
            break;

          case "plan":
            if (event.data.tasks) {
              const tasks: LiveTask[] = event.data.tasks.map((t) => ({
                task_id: t.task_id,
                service: t.service,
                action: t.action,
                description: t.description,
                status: "pending",
              }));
              setLiveTasks(tasks);
              setStatus(
                `Running ${tasks.length} step${tasks.length === 1 ? "" : "s"}…`
              );
            }
            break;

          case "task_started":
            setStatus(`Calling ${event.data.service || "a tool"}…`);
            setLiveTasks((prev) => {
              const exists = prev.some((t) => t.task_id === event.data.task_id);
              if (exists) {
                return prev.map((t) =>
                  t.task_id === event.data.task_id
                    ? { ...t, status: "in_progress" as const }
                    : t
                );
              }
              if (!event.data.task_id) return prev;
              return [
                ...prev,
                {
                  task_id: event.data.task_id,
                  service: event.data.service || "unknown",
                  action: event.data.action || "unknown",
                  description: event.data.description || "",
                  status: "in_progress" as const,
                },
              ];
            });
            break;

          case "task_completed":
            setLiveTasks((prev) =>
              prev.map((t) =>
                t.task_id === event.data.task_id
                  ? { ...t, status: "completed", result: event.data.result }
                  : t
              )
            );
            break;

          case "task_failed":
            setLiveTasks((prev) =>
              prev.map((t) =>
                t.task_id === event.data.task_id
                  ? { ...t, status: "failed", error: event.data.error }
                  : t
              )
            );
            break;

          case "complete": {
            setMessages((prev) => [
              ...prev,
              {
                id: `a${Date.now()}`,
                role: "assistant",
                content: event.data.message || "Done.",
                timestamp: new Date(),
                actions: event.data.actions_taken as ActionResult[],
              },
            ]);
            setBusy(false);
            setStatus("");
            setLiveTasks([]);
            reload();
            break;
          }

          case "error": {
            setMessages((prev) => [
              ...prev,
              {
                id: `e${Date.now()}`,
                role: "assistant",
                content: event.data.message || "Something went wrong.",
                timestamp: new Date(),
              },
            ]);
            setBusy(false);
            setStatus("");
            setLiveTasks([]);
            break;
          }
        }
      },
      (error: Error) => {
        setMessages((prev) => [
          ...prev,
          {
            id: `e${Date.now()}`,
            role: "assistant",
            content: `That request failed: ${error.message}`,
            timestamp: new Date(),
          },
        ]);
        setBusy(false);
        setStatus("");
        setLiveTasks([]);
      },
      () => {
        setBusy(false);
        setStatus("");
      },
      conversationId
    );
  };

  const empty = messages.length === 0 && !busy && !loadingHistory;

  return (
    <div className="flex min-h-0 flex-1">
      {/* ── Rail ──────────────────────────────────────────────────────────
          Pinned by default on a wide screen, collapsible, and a drawer below
          `lg`. It is chat's own furniture, not the application's. */}
      {railPinned && (
        <aside className="hidden w-72 shrink-0 border-r border-line bg-surface-2/40 lg:flex lg:flex-col">
          <ConversationRail
            conversations={conversations}
            loading={loadingRail}
            activeId={conversationId}
            onCollapse={() => setRailPinned(false)}
          />
        </aside>
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* ── Conversation bar ──────────────────────────────────────────
            No bottom rule. This bar sits immediately under the application
            header, which draws its own, so a border here produced two
            horizontal lines a few pixels apart with a row of icons trapped
            between them. The transcript below has enough air to separate
            itself. */}
        <div className="flex items-center gap-2 px-4 py-2.5 sm:px-6">
          {!railPinned && (
            <IconButton
              label="Show conversations"
              variant="ghost"
              size="sm"
              className="hidden lg:inline-flex"
              onClick={() => setRailPinned(true)}
            >
              <PanelLeft />
            </IconButton>
          )}
          <IconButton
            label="Conversations"
            variant="ghost"
            size="sm"
            className="lg:hidden"
            onClick={() => setRailOpen(true)}
          >
            <PanelLeft />
          </IconButton>

          <p className="min-w-0 truncate text-sm font-medium text-ink">
            {conversations.find((c) => c.id === conversationId)?.title ??
              "New conversation"}
          </p>

          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() => router.push("/chatbot")}
          >
            New chat
          </Button>
        </div>

        {/* ── Transcript ──────────────────────────────────────────────── */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          <div className="mx-auto max-w-3xl">
            {loadingHistory ? (
              <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Loading conversation…
              </div>
            ) : empty ? (
              <Welcome onPick={(text) => send(text)} />
            ) : (
              <div className="space-y-6">
                {messages.map((m) => (
                  <Bubble
                    key={m.id}
                    message={m}
                    userName={user?.name}
                    userEmail={user?.email}
                  />
                ))}

                {busy && (
                  <div className="flex gap-3">
                    <span
                      className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-pill bg-accent-soft"
                      aria-hidden
                    >
                      <Sparkles className="size-3.5 animate-pulse text-accent-strong" />
                    </span>
                    <div className="min-w-0 flex-1 space-y-2 pt-1">
                      <p
                        className="flex items-center gap-2 text-sm text-muted"
                        aria-live="polite"
                      >
                        <Loader2 className="size-3.5 animate-spin" aria-hidden />
                        {status || "Working…"}
                      </p>
                      <AnimatePresence initial={false}>
                        {liveTasks.map((task) => (
                          <ToolRun key={task.task_id} {...task} />
                        ))}
                      </AnimatePresence>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        {/* ── Composer ──────────────────────────────────────────────────
            No rule above it either. The composer is a defined box sitting on
            the ground; a full-width line behind it just draws the same
            separation twice, less well. */}
        <div className="relative bg-bg px-4 pb-4 pt-2 sm:px-6">
          {/* A fade, where a rule used to be.
              The transcript scrolls under the composer, and a hard line across
              the window said "the page ends here" — which is wrong, there is
              more above. Dissolving the last few rows into the ground says the
              true thing instead: content continues, it is just passing behind
              this. It sits outside the padded box and ignores the pointer, so
              the composer under it stays fully clickable. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 -top-12 h-12 bg-gradient-to-b from-transparent to-bg"
          />
          <div className="mx-auto max-w-3xl">
            <Composer
              value={input}
              onChange={setInput}
              onSend={() => send()}
              onStop={stop}
              busy={busy}
              smart={smart}
              onSmartChange={setSmart}
            />
          </div>
        </div>
      </div>

      {/* Mobile rail */}
      <Sheet
        open={railOpen}
        onClose={() => setRailOpen(false)}
        title="Conversations"
        width="narrow"
        side="left"
      >
        <ConversationRail
          conversations={conversations}
          loading={loadingRail}
          activeId={conversationId}
          onPick={() => setRailOpen(false)}
          className="-mx-5"
        />
      </Sheet>

      {/* The model server holds one model at a time, so this is a
          configuration state with a fix, not an error. */}
      <Dialog
        open={!!modelDown}
        onClose={() => setModelDown(null)}
        size="sm"
        title="No model is loaded"
        description={modelDown ?? undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModelDown(null)}>
              Close
            </Button>
            <Button asChild data-autofocus>
              <Link href="/settings?tab=system">
                <Cpu aria-hidden />
                Check the server
              </Link>
            </Button>
          </>
        }
      >
        <Notice tone="info" icon={<Cpu aria-hidden />}>
          Open MoE Model Manager and load a text model. Inference is local and
          loopback-bound — no API key is required, and nothing you type here
          leaves this machine.
        </Notice>
      </Dialog>
    </div>
  );
}

/**
 * The empty state.
 *
 * Four things this can actually do, as clickable prompts. "Start a conversation
 * below. I'm here to help you with anything you need" told nobody what the
 * product connects to, which is the entire reason to use this over any other
 * chat window.
 */
function Welcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center py-12 text-center sm:py-20">
      <span
        className="flex size-12 items-center justify-center rounded-pill bg-accent-soft"
        aria-hidden
      >
        <Sparkles className="size-5 text-accent-strong" />
      </span>
      <h2 className="mt-5 text-[1.75rem] leading-tight tracking-[-0.026em] text-ink">
        What do you need?
      </h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
        Locus can read and act across every tool you have connected — GitHub,
        Jira, Slack, Linear and Google Workspace.
      </p>

      <div className="mt-8 grid w-full max-w-xl gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => onPick(s.label)}
            className="flex items-start gap-3 rounded-lg border border-line bg-surface px-4 py-3.5 text-left transition-colors hover:border-line-strong hover:bg-surface-2"
          >
            <s.icon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
            <span className="text-sm leading-snug text-ink">{s.label}</span>
          </button>
        ))}
      </div>

      <p className="mt-8 flex items-center gap-1.5 text-xs text-subtle">
        <ChevronDown className="size-3.5" aria-hidden />
        Or type your own below
      </p>
    </div>
  );
}

export { ChatInterface as AIChatInput };
