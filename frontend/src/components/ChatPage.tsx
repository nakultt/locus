import React, { useState, useRef, useEffect } from "react";
import Header from "./Header";
import Sidebar from "./Sidebar";
import ChatArea from "./ChatArea";
import ChatInput from "./ChatInput";

// Message interface for type safety
interface Message {
  id: string;
  text: string;
  sender: "user" | "bot";
  timestamp: string;
  imageUrl?: string;
  status?: "processing" | "completed";
}

// Command history item interface
interface HistoryItem {
  id: string;
  command: string;
  description: string;
  timestamp: string;
  group: "today" | "yesterday" | "previous";
}

/**
 * Professional AI Assistant Main Page Component
 * Features:
 * - Top header with branding and global actions
 * - Left sidebar with command history
 * - Main chat area with floating message bubbles
 * - Floating chat input with voice and image support
 * - Light theme matching login page
 */
export const ChatPage: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      text: "Hello! I'm your AI assistant. How can I help you today?",
      sender: "bot",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);

  // Command history (mock data)
  const [commandHistory] = useState<HistoryItem[]>([
    {
      id: "h1",
      command: "Create a Jira ticket for bug fix",
      description: "Automate ticket creation and assignment",
      timestamp: "10:30 AM",
      group: "today"
    },
    {
      id: "h2",
      command: "Send notification to Slack channel",
      description: "Broadcast updates to team",
      timestamp: "09:15 AM",
      group: "today"
    },
    {
      id: "h3",
      command: "Update Salesforce opportunity status",
      description: "Modify deal pipeline information",
      timestamp: "Yesterday",
      group: "yesterday"
    },
    {
      id: "h4",
      command: "Generate weekly report",
      description: "Compile analytics and metrics",
      timestamp: "Yesterday",
      group: "yesterday"
    },
    {
      id: "h5",
      command: "Schedule team meeting",
      description: "Book calendar slots for discussion",
      timestamp: "2 days ago",
      group: "previous"
    },
    {
      id: "h6",
      command: "Check integration health status",
      description: "Monitor system connectivity",
      timestamp: "3 days ago",
      group: "previous"
    },
  ]);

  // Handle sending a message
  const handleSend = (text: string, image?: string) => {
    const newMessage: Message = {
      id: Date.now().toString(),
      text,
      sender: "user",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      imageUrl: image,
    };

    setMessages((prev) => [...prev, newMessage]);

    // Simulate bot response
    setTimeout(() => {
      const botResponse: Message = {
        id: (Date.now() + 1).toString(),
        text: "I've received your message. Let me process that for you.",
        sender: "bot",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        status: "processing",
      };
      setMessages((prev) => [...prev, botResponse]);

      // Mark as completed after a delay
      setTimeout(() => {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === botResponse.id ? { ...msg, status: "completed" as const } : msg
          )
        );
      }, 2000);
    }, 1000);
  };

  // Handle history item click
  const handleHistoryClick = (item: HistoryItem) => {
    setSelectedHistoryId(item.id);
    // In a real app, this would populate the input
  };

  return (
    <div className="h-screen bg-gray-100 flex flex-col">
      {/* Top Header - Fixed */}
      <Header />

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar */}
        <Sidebar
          history={commandHistory}
          selectedId={selectedHistoryId}
          onHistoryClick={handleHistoryClick}
        />

        {/* Chat Area */}
        <div className="flex-1 flex flex-col relative">
          <ChatArea messages={messages} />

          {/* Floating Chat Input */}
          <ChatInput onSend={handleSend} />
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
