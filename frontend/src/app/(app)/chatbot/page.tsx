import { Suspense } from "react";
import { ChatRoute } from "@/features/chat/chat-route";

export default function ChatbotPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center">
          <p className="animate-pulse text-muted-foreground">Loading chat...</p>
        </div>
      }
    >
      <ChatRoute />
    </Suspense>
  );
}
