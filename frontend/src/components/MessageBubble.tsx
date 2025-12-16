import React from "react";
import type { ChatMessage } from "./types";

interface MessageBubbleProps {
  message: ChatMessage;
  onActionClick?: (messageId: string, actionId: string) => void;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  message,
  onActionClick,
}) => {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  const baseBubble =
    "inline-flex max-w-xl flex-col gap-2 rounded-2xl px-3.5 py-2.5 text-sm shadow-sm";

  const bubbleClass = isUser
    ? `${baseBubble} bg-cyan-500 text-slate-950 rounded-br-sm`
    : `${baseBubble} bg-slate-800/90 text-slate-50 border border-slate-700/80 rounded-bl-sm`;

  const containerClass = isUser
    ? "flex justify-end"
    : "flex justify-start";

  return (
    <div className={containerClass}>
      <div className="flex max-w-full items-end gap-2">
        {!isUser && (
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-violet-500 text-xs font-semibold text-slate-950 shadow-md">
            IS
          </div>
        )}

        <div className="space-y-1">
          <div className={bubbleClass}>
            {isSystem && message.intent && (
              <p className="text-[10px] uppercase tracking-[0.16em] text-cyan-200/80">
                {message.intent.toUpperCase()} • System
              </p>
            )}

            <p className="whitespace-pre-wrap break-words">
              {message.content}
            </p>

            {message.meta?.summary && (
              <div className="mt-1 rounded-xl bg-slate-900/70 px-3 py-2 text-xs text-slate-300 border border-slate-700/70">
                <p className="font-medium text-slate-100 mb-1">
                  Summary
                </p>
                <p>{message.meta.summary}</p>
              </div>
            )}

            {message.meta?.actions && message.meta.actions.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-2">
                {message.meta.actions.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    onClick={() =>
                      onActionClick?.(message.id, action.id)
                    }
                    className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium transition ${
                      action.type === "primary"
                        ? "border-cyan-400 bg-cyan-500 text-slate-950 hover:bg-cyan-400"
                        : "border-slate-600 bg-slate-900/60 text-slate-100 hover:bg-slate-800"
                    }`}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 text-[10px] text-slate-500">
            <span>{message.timestamp}</span>
            {message.meta?.urgency && (
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${
                  message.meta.urgency === "high"
                    ? "bg-red-500/15 text-red-300"
                    : message.meta.urgency === "normal"
                    ? "bg-amber-500/15 text-amber-200"
                    : "bg-emerald-500/10 text-emerald-200"
                }`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                <span className="capitalize">
                  {message.meta.urgency} priority
                </span>
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default MessageBubble;


