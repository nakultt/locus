"use client";
import { Suspense } from "react";
import { AppLayout } from "@/ui/app-layout";
import ChatbotComponent from "@/components/pages/chatbot";

export default function ChatbotPage() {
  return (
    <AppLayout>
      <Suspense fallback={<div>Loading chat...</div>}>
        <ChatbotComponent />
      </Suspense>
    </AppLayout>
  );
}
