import { Suspense } from "react";
import { ChatRoute } from "@/features/chat/chat-route";

export default function ChatbotPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <p className="text-sm text-muted">Loading chat…</p>
        </div>
      }
    >
      <ChatRoute />
    </Suspense>
  );
}
