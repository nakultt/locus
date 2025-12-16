import React, { useEffect, useMemo, useState } from "react";
import type { MessageIntent } from "./types";

interface ChatInputProps {
  isProcessing: boolean;
  onSubmit: (text: string) => void;
}

const SUGGESTED_COMMANDS: Array<{ label: string; value: string }> = [
  {
    label: "Create Jira ticket and notify Slack",
    value: "Create a Jira ticket and notify Slack when it's created",
  },
  {
    label: "Schedule Google Meet",
    value: "Schedule a Google Meet with the architecture team tomorrow at 3pm",
  },
  {
    label: "Update ServiceNow incident",
    value: "Update ServiceNow incident INC-1045 to In Progress",
  },
  {
    label: "Review GitHub PR",
    value: "Summarize open GitHub pull requests and flag urgent ones",
  },
];

const INTENT_HINTS: Record<MessageIntent, string> = {
  jira: "Jira: create/update issues, set priorities, assign owners…",
  slack: "Slack: send updates, notify channels, DM stakeholders…",
  calendar: "Calendar: schedule/modify meetings and reminders…",
  servicenow: "ServiceNow: create/update incidents and requests…",
  github: "GitHub: review PRs, create issues, manage branches…",
  generic: "General automation: combine tools and orchestrate workflows…",
};

export const ChatInput: React.FC<ChatInputProps> = ({
  isProcessing,
  onSubmit,
}) => {
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [selectedSuggestion, setSelectedSuggestion] = useState<number | null>(
    null
  );
  const [micActive, setMicActive] = useState(false);

  const trimmed = value.trim();

  const intent: MessageIntent = useMemo(() => {
    const lower = trimmed.toLowerCase();
    if (lower.includes("jira")) return "jira";
    if (lower.includes("slack")) return "slack";
    if (
      lower.includes("meet") ||
      lower.includes("calendar") ||
      lower.includes("invite")
    )
      return "calendar";
    if (lower.includes("servicenow") || lower.includes("incident"))
      return "servicenow";
    if (lower.includes("github") || lower.includes("pull request"))
      return "github";
    if (!trimmed) return "generic";
    return "generic";
  }, [trimmed]);

  const filteredSuggestions = useMemo(() => {
    if (!trimmed) return SUGGESTED_COMMANDS;
    return SUGGESTED_COMMANDS.filter((s) =>
      s.label.toLowerCase().includes(trimmed.toLowerCase())
    );
  }, [trimmed]);

  useEffect(() => {
    setSelectedSuggestion(
      filteredSuggestions.length > 0 ? 0 : null
    );
  }, [filteredSuggestions.length]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "ArrowDown" && filteredSuggestions.length > 0) {
      e.preventDefault();
      setSelectedSuggestion((prev) => {
        if (prev === null) return 0;
        return (prev + 1) % filteredSuggestions.length;
      });
    } else if (e.key === "ArrowUp" && filteredSuggestions.length > 0) {
      e.preventDefault();
      setSelectedSuggestion((prev) => {
        if (prev === null) return filteredSuggestions.length - 1;
        return (prev - 1 + filteredSuggestions.length) % filteredSuggestions.length;
      });
    } else if (e.key === "Tab" && selectedSuggestion !== null) {
      e.preventDefault();
      setValue(filteredSuggestions[selectedSuggestion].value);
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!trimmed || isProcessing) return;
      onSubmit(trimmed);
      setValue("");
    }
  };

  return (
    <div className="border-t border-slate-800/80 bg-slate-950/90 backdrop-blur-sm px-3 pt-3 pb-3 sm:px-4 sm:pb-4">
      <div className="mx-auto max-w-3xl space-y-2">
        {/* Intent hint */}
        <div className="flex items-center justify-between text-[11px] text-slate-500">
          <p className="truncate pr-4">
            {INTENT_HINTS[intent]}
          </p>
          <p className="hidden sm:inline-flex items-center gap-1 text-[10px] text-slate-600">
            <span className="rounded-full bg-slate-900 px-2 py-0.5">⏎ send</span>
            <span className="rounded-full bg-slate-900 px-2 py-0.5">⇧⏎ new line</span>
          </p>
        </div>

        <div
          className={`relative rounded-2xl border bg-slate-900/80 shadow-[0_0_0_1px_rgba(15,23,42,0.9)] transition ${
            isFocused
              ? "border-cyan-400/80 shadow-[0_0_0_1px_rgba(34,211,238,0.6),0_18px_45px_rgba(15,23,42,0.9)]"
              : "border-slate-700/80"
          }`}
        >
          <div className="relative flex items-center gap-3">
            <button
              type="button"
              onClick={() => setMicActive((s) => !s)}
              className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors ${
                micActive ? "bg-rose-500/20 text-rose-300 animate-pulse" : "bg-transparent text-slate-300 hover:bg-slate-800/60"
              }`}
              aria-pressed={micActive}
              title="Voice Assistant"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 1.5a2.5 2.5 0 00-2.5 2.5v4a2.5 2.5 0 005 0v-4A2.5 2.5 0 0012 1.5z" />
                <path d="M19 11v1a7 7 0 01-14 0v-1" />
                <path d="M12 19v3" />
              </svg>
            </button>

            <textarea
            rows={2}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Ask Integration Store to orchestrate Jira, Slack, ServiceNow and more…"
            className="w-full resize-none rounded-2xl bg-transparent px-3.5 py-2.5 pr-24 text-sm text-slate-50 placeholder:text-slate-500 focus:outline-none"
          />
            <button
              type="button"
              disabled={!trimmed || isProcessing}
              onClick={() => {
                if (!trimmed || isProcessing) return;
                onSubmit(trimmed);
                setValue("");
              }}
              className="absolute bottom-2.5 right-2.5 inline-flex items-center gap-1 rounded-xl bg-cyan-500 px-3 py-1.5 text-xs font-medium text-slate-950 shadow-md hover:bg-cyan-400 disabled:opacity-60 disabled:cursor-not-allowed transition"
            >
              {isProcessing ? (
                <>
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                  <span>Processing</span>
                </>
              ) : (
                <>
                  <span>Send</span>
                  <span className="text-[10px]">⏎</span>
                </>
              )}
            </button>
          </div>

          {/* Mic status / waveform */}
          <div className="mt-2 flex items-center justify-between">
            <div className="flex items-center gap-3 text-[12px] text-slate-400">
              {micActive ? (
                <div className="flex items-center gap-2">
                  <div className="h-3 w-16 overflow-hidden rounded-full bg-gradient-to-r from-rose-500 to-cyan-400">
                    <div className="animate-[wave_1.6s_linear_infinite] h-3 w-16 bg-white/10" />
                  </div>
                  <span className="text-rose-300">Listening…</span>
                </div>
              ) : isProcessing ? (
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
                  <span>Processing…</span>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-slate-400">Voice</span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              {filteredSuggestions.length > 0 && (
                <span className="hidden sm:inline-flex rounded-full bg-slate-900 px-2 py-0.5">Suggestions</span>
              )}
            </div>
          </div>
        </div>
        {/* Suggestions */}
        {filteredSuggestions.length > 0 && (
          <div className="flex flex-wrap gap-2 text-[11px] text-slate-400">
            {filteredSuggestions.slice(0, 3).map((s, index) => (
              <button
                key={s.label}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  setValue(s.value);
                }}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 transition ${
                  selectedSuggestion === index
                    ? "border-cyan-400 bg-cyan-500/10 text-cyan-200"
                    : "border-slate-700 bg-slate-900/70 hover:border-slate-500"
                }`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
                <span>{s.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatInput;


