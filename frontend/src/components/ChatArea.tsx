import React, { useEffect, useRef } from "react";
import type { ChatMessage } from "./types";
import MessageBubble from "./MessageBubble";
import ChatInput from "./ChatInput";

export const ChatArea: React.FC<{
  messages: ChatMessage[];
  onSend: (text: string) => void;
  onAction?: (id: string, actionId: string) => void;
  isProcessing?: boolean;
}> = ({ messages, onSend, onAction, isProcessing = false }) => {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <main className="relative flex-1 overflow-hidden bg-gradient-to-b from-white/40 to-transparent p-6 pt-20 dark:from-slate-900/40">
      <div className="mx-auto flex h-full max-w-5xl flex-1 flex-col">
        <div className="flex-1 overflow-y-auto pb-40">
          <div className="mx-auto w-full space-y-6">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} onActionClick={onAction} />
            ))}
            <div ref={endRef} />
          </div>
        </div>

        <div className="pointer-events-auto fixed bottom-6 left-1/2 z-40 w-full max-w-3xl -translate-x-1/2 px-4">
          <div className="rounded-full bg-white/6 px-3 py-2 backdrop-blur-md shadow-lg dark:bg-slate-800/50">
            <ChatInput isProcessing={isProcessing} onSubmit={onSend} />
          </div>
        </div>
      </div>
    </main>
  );
};

export default ChatArea;
