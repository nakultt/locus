"use client";

import { useSearchParams } from "next/navigation";
import { ChatInterface } from "@/features/chat/chat-interface";

/**
 * Reads the conversation id out of the query string.
 *
 * Split from the page so the `useSearchParams` call sits under its own
 * Suspense boundary. Next opts a whole route out of static rendering when that
 * hook is used without one, and the error surfaces only at build time.
 */
export function ChatRoute() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");

  return <ChatInterface conversationId={id ? parseInt(id, 10) : undefined} />;
}
