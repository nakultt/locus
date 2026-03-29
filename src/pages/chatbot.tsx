import { useSearchParams } from "react-router-dom";
import { ChatInterface } from "@/ui/chat-box";

export default function Chatbot() {
  const [searchParams] = useSearchParams();
  const conversationId = searchParams.get("id");
  
  return (
    <ChatInterface
      conversationId={conversationId ? parseInt(conversationId, 10) : undefined}
    />
  );
}
