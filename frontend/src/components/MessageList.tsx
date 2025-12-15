import React, { useEffect, useRef } from "react";
import type { ChatMessage } from "./types";
import { MessageBubble } from "./MessageBubble";

interface MessageListProps {
  messages: ChatMessage[];
  onActionClick?: (messageId: string, actionId: string) => void;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  onActionClick,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto space-y-3 pr-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900/40"
    >
      {messages.length === 0 && (
        <div className="h-full flex items-center justify-center text-xs text-slate-500">
          Start by asking something like{" "}
          <span className="mx-1 rounded-full bg-slate-800/80 px-2 py-1 font-mono text-[11px] text-slate-200">
            Create a Jira ticket and notify Slack
          </span>
        </div>
      )}

      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          onActionClick={onActionClick}
        />
      ))}
    </div>
  );
};

export default MessageList;


