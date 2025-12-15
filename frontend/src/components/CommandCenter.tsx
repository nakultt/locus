import React, { useMemo, useState } from "react";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";
import { NotificationToast, Toast } from "./NotificationToast";
import type { ChatMessage, MessageIntent } from "./types";

const nowTime = () => new Date().toLocaleTimeString([], { timeStyle: "short" });

const detectIntent = (text: string): MessageIntent => {
  const lower = text.toLowerCase();
  if (lower.includes("jira")) return "jira";
  if (lower.includes("slack")) return "slack";
  if (lower.includes("servicenow") || lower.includes("incident"))
    return "servicenow";
  if (lower.includes("meet") || lower.includes("calendar"))
    return "calendar";
  if (lower.includes("github") || lower.includes("pull request"))
    return "github";
  return "generic";
};

export const CommandCenter: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "system",
      content:
        "Welcome to Integration Store Command Center. Ask in natural language and I’ll orchestrate Jira, Slack, ServiceNow, Google Workspace and GitHub for you.",
      timestamp: nowTime(),
      intent: "generic",
      meta: {
        summary:
          "Try: “Create a Jira ticket, notify Slack, and schedule a follow-up meeting.”",
        actions: [
          { id: "show-templates", label: "View Templates", type: "secondary" },
          { id: "view-logs", label: "Open Audit Log", type: "secondary" },
        ],
      },
    },
  ]);

  const [isProcessing, setIsProcessing] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (toast: Omit<Toast, "id">) => {
    setToasts((prev) => [
      ...prev,
      { id: crypto.randomUUID(), ...toast },
    ]);
  };

  const handleSubmit = (text: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: nowTime(),
      intent: detectIntent(text),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsProcessing(true);

    // Simulated orchestration / workflow explanation
    setTimeout(() => {
      const intent = detectIntent(text);

      const systemMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "system",
        content:
          "This is a preview of how your command would execute. Wire this component to your backend to perform real actions.",
        timestamp: nowTime(),
        intent,
        meta: {
          summary: buildSummary(intent, text),
          urgency: inferUrgency(text),
          actions: buildActions(intent),
          tags: ["simulated", "safe-preview"],
        },
      };

      setMessages((prev) => [...prev, systemMsg]);
      addToast({
        variant: "success",
        message:
          "Command parsed successfully. Connect your APIs to enable live automation.",
      });
      setIsProcessing(false);
    }, 900);
  };

  const handleActionClick = (messageId: string, actionId: string) => {
    addToast({
      variant: "info",
      message: `Action “${actionId}” clicked for message ${messageId}. Connect this to your workflow engine.`,
    });
  };

  const handleDismissToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const integrations = useMemo(
    () => [
      { id: "jira", label: "Jira", status: "connected" as const },
      { id: "slack", label: "Slack", status: "connected" as const },
      { id: "calendar", label: "Google Workspace", status: "connected" as const },
      { id: "servicenow", label: "ServiceNow", status: "pending" as const },
      { id: "github", label: "GitHub", status: "connected" as const },
    ],
    []
  );

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 flex flex-col">
      {/* Top bar */}
      <header className="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-violet-500 text-xs font-semibold text-slate-950 shadow-md">
              IS
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-semibold">
                Integration Store
              </span>
              <span className="text-[11px] text-slate-400">
                Unified Command Center
              </span>
            </div>
          </div>

          <div className="hidden items-center gap-3 text-[11px] text-slate-400 sm:flex">
            <div className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-2.5 py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(16,185,129,0.25)]" />
              <span>Orchestrator Ready</span>
            </div>
            <span className="hidden sm:inline text-slate-500">
              All actions are simulated in this UI.
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-4 py-4 sm:px-6 sm:py-6 lg:flex-row">
        {/* Sidebar */}
        <aside className="w-full space-y-4 rounded-2xl border border-slate-800/80 bg-slate-950/80 p-4 text-xs text-slate-300 shadow-[0_18px_45px_rgba(15,23,42,0.85)] lg:w-64">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
              Integrations
            </h2>
            <div className="mt-2 space-y-1.5">
              {integrations.map((i) => (
                <div
                  key={i.id}
                  className="flex items-center justify-between rounded-lg bg-slate-900/80 px-2.5 py-1.5"
                >
                  <span>{i.label}</span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] ${
                      i.status === "connected"
                        ? "bg-emerald-500/10 text-emerald-300"
                        : "bg-amber-500/10 text-amber-200"
                    }`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-current" />
                    <span className="capitalize">
                      {i.status}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
              Templates
            </h2>
            <ul className="mt-2 space-y-1.5 text-[11px] text-slate-400">
              <li>• Incident triage & escalation</li>
              <li>• Release coordination</li>
              <li>• On-call handoff</li>
              <li>• Weekly ops summary</li>
            </ul>
          </div>
        </aside>

        {/* Chat column */}
        <section className="flex min-h-[420px] flex-1 flex-col overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-950/90 shadow-[0_18px_45px_rgba(15,23,42,0.9)]">
          <div className="border-b border-slate-800/80 px-4 py-2.5 text-xs text-slate-400 flex items-center justify-between">
            <span>Command Thread</span>
            {isProcessing && (
              <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
                Processing…
              </span>
            )}
          </div>
          <MessageList
            messages={messages}
            onActionClick={handleActionClick}
          />
          <ChatInput
            isProcessing={isProcessing}
            onSubmit={handleSubmit}
          />
        </section>
      </main>

      <NotificationToast
        toasts={toasts}
        onDismiss={handleDismissToast}
      />
    </div>
  );
};

function buildSummary(intent: MessageIntent, text: string): string {
  switch (intent) {
    case "jira":
      return "Will create or update a Jira issue, then return the key and status for follow‑up automations.";
    case "slack":
      return "Will post an update to the requested Slack channel and mention relevant stakeholders.";
    case "servicenow":
      return "Will create/update a ServiceNow incident and sync state back to the command thread.";
    case "calendar":
      return "Will propose one or more meeting slots and send invitations via Google Calendar.";
    case "github":
      return "Will analyze GitHub pull requests or issues and surface the most relevant changes.";
    default:
      return `Will interpret your request and route it across tools as needed: “${text.slice(
        0,
        120
      )}…”`;
  }
}

function inferUrgency(text: string): "low" | "normal" | "high" {
  const lower = text.toLowerCase();
  if (lower.includes("sev1") || lower.includes("critical") || lower.includes("production down")) {
    return "high";
  }
  if (lower.includes("tomorrow") || lower.includes("next week")) {
    return "normal";
  }
  return "low";
}

export default CommandCenter;


