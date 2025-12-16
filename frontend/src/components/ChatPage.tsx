import React, { useState, useRef, useEffect } from "react";

// Message interface for type safety
interface Message {
  id: string;
  text: string;
  sender: "user" | "bot";
  timestamp: string;
  imageUrl?: string;
}

// Command history item interface
interface HistoryItem {
  id: string;
  command: string;
  timestamp: string;
}

/**
 * Professional Chatbot Main Page Component
 * Features:
 * - Top header with notification, settings, and profile icons
 * - Right-side collapsible command history panel
 * - Main chat area with user/bot message bubbles
 * - Chat input with voice, image upload, and send functionality
 * - Ash/gray color theme matching login page
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
  const [inputText, setInputText] = useState("");
  const [isHistoryOpen, setIsHistoryOpen] = useState(true);
  const [isVoiceActive, setIsVoiceActive] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Command history (mock data)
  const [commandHistory] = useState<HistoryItem[]>([
    { id: "h1", command: "Create a Jira ticket for bug fix", timestamp: "10:30 AM" },
    { id: "h2", command: "Send notification to Slack channel", timestamp: "09:15 AM" },
    { id: "h3", command: "Update Salesforce opportunity status", timestamp: "Yesterday" },
    { id: "h4", command: "Generate weekly report", timestamp: "Yesterday" },
    { id: "h5", command: "Schedule team meeting", timestamp: "2 days ago" },
    { id: "h6", command: "Check integration health status", timestamp: "3 days ago" },
  ]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Handle sending a message
  const handleSend = () => {
    if (!inputText.trim() && !imagePreview) return;

    const newMessage: Message = {
      id: Date.now().toString(),
      text: inputText,
      sender: "user",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      imageUrl: imagePreview || undefined,
    };

    setMessages((prev) => [...prev, newMessage]);
    setInputText("");
    setImagePreview(null);

    // Simulate bot response
    setTimeout(() => {
      const botResponse: Message = {
        id: (Date.now() + 1).toString(),
        text: "I've received your message. Let me process that for you.",
        sender: "bot",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, botResponse]);
    }, 1000);
  };

  // Handle voice input toggle
  const handleVoiceToggle = () => {
    setIsVoiceActive(!isVoiceActive);
    // In a real app, this would start/stop voice recording
  };

  // Handle image upload
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreview(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  // Handle history item click
  const handleHistoryClick = (item: HistoryItem) => {
    setSelectedHistoryId(item.id);
    setInputText(item.command);
  };

  // Handle key press in input
  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen bg-gray-100 overflow-hidden">
      {/* Main Chat Container */}
      <div className="flex-1 flex flex-col">
        {/* Top Header - Fixed */}
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm z-10">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 text-white text-sm font-semibold shadow-md">
              AI
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-900">AI Assistant</h1>
              <p className="text-xs text-gray-500">Enterprise Chat Interface</p>
            </div>
          </div>

          {/* Header Icons */}
          <div className="flex items-center gap-4">
            {/* Notification Icon */}
            <button
              type="button"
              className="relative p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              title="Notifications"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                />
              </svg>
              <span className="absolute top-1 right-1 h-2 w-2 bg-red-500 rounded-full border-2 border-white"></span>
            </button>

            {/* Settings Icon */}
            <button
              type="button"
              className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              title="Settings"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
            </button>

            {/* User Profile Icon */}
            <button
              type="button"
              className="p-1 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors"
              title="Profile"
            >
              <div className="h-8 w-8 rounded-full bg-gradient-to-br from-cyan-400 to-blue-500 flex items-center justify-center text-white text-sm font-medium shadow-sm">
                JD
              </div>
            </button>
          </div>
        </header>

        {/* Main Chat Area */}
        <div className="flex-1 overflow-hidden flex">
          {/* Chat Messages Container */}
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div className={`flex flex-col max-w-[70%] ${message.sender === "user" ? "items-end" : "items-start"}`}>
                    {/* Message Bubble */}
                    <div
                      className={`rounded-2xl px-4 py-3 shadow-sm ${
                        message.sender === "user"
                          ? "bg-cyan-500 text-white"
                          : "bg-white text-gray-900 border border-gray-200"
                      }`}
                    >
                      {message.imageUrl && (
                        <img
                          src={message.imageUrl}
                          alt="Uploaded"
                          className="mb-2 rounded-lg max-w-full h-auto max-h-64 object-cover"
                        />
                      )}
                      <p className="text-sm whitespace-pre-wrap break-words">{message.text}</p>
                    </div>
                    {/* Timestamp */}
                    <span className="text-xs text-gray-500 mt-1 px-1">{message.timestamp}</span>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* Chat Input Section */}
            <div className="bg-white border-t border-gray-200 px-6 py-4">
              {/* Image Preview */}
              {imagePreview && (
                <div className="mb-3 relative inline-block">
                  <img
                    src={imagePreview}
                    alt="Preview"
                    className="h-20 w-20 object-cover rounded-lg border border-gray-300"
                  />
                  <button
                    type="button"
                    onClick={() => setImagePreview(null)}
                    className="absolute -top-2 -right-2 h-5 w-5 bg-red-500 text-white rounded-full flex items-center justify-center text-xs hover:bg-red-600 transition-colors"
                  >
                    ×
                  </button>
                </div>
              )}

              {/* Input Container */}
              <div className="flex items-end gap-3">
                <div className="flex-1 relative">
                  <input
                    type="text"
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Type your message..."
                    className="w-full px-4 py-3 pr-32 border border-gray-300 rounded-xl bg-white text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-shadow"
                  />

                  {/* Icons inside input */}
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-2">
                    {/* Voice Assistant Icon */}
                    <button
                      type="button"
                      onClick={handleVoiceToggle}
                      className={`p-2 rounded-lg transition-colors ${
                        isVoiceActive
                          ? "bg-red-100 text-red-600 animate-pulse"
                          : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                      }`}
                      title="Voice Assistant"
                    >
                      <svg
                        className="w-5 h-5"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                        xmlns="http://www.w3.org/2000/svg"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
                        />
                      </svg>
                    </button>

                    {/* Image Upload Icon */}
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                      title="Upload Image"
                    >
                      <svg
                        className="w-5 h-5"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                        xmlns="http://www.w3.org/2000/svg"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
                        />
                      </svg>
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      onChange={handleImageUpload}
                      className="hidden"
                    />
                  </div>
                </div>

                {/* Send Button */}
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={!inputText.trim() && !imagePreview}
                  className="p-3 bg-cyan-500 text-white rounded-xl hover:bg-cyan-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors shadow-md hover:shadow-lg"
                  title="Send Message"
                >
                  <svg
                    className="w-5 h-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                    />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          {/* Right-Side Command History Panel */}
          <div
            className={`bg-white border-l border-gray-200 transition-all duration-300 ${
              isHistoryOpen ? "w-80" : "w-0"
            } overflow-hidden flex flex-col`}
          >
            {isHistoryOpen && (
              <>
                {/* History Header */}
                <div className="px-4 py-4 border-b border-gray-200 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-900">Command History</h2>
                  <button
                    type="button"
                    onClick={() => setIsHistoryOpen(false)}
                    className="p-1 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                    title="Close History"
                  >
                    <svg
                      className="w-5 h-5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      xmlns="http://www.w3.org/2000/svg"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </div>

                {/* History List */}
                <div className="flex-1 overflow-y-auto px-2 py-2">
                  <div className="space-y-1">
                    {commandHistory.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => handleHistoryClick(item)}
                        className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${
                          selectedHistoryId === item.id
                            ? "bg-cyan-50 border border-cyan-200 text-cyan-900"
                            : "hover:bg-gray-50 text-gray-700 border border-transparent"
                        }`}
                      >
                        <p className="text-sm font-medium truncate">{item.command}</p>
                        <p className="text-xs text-gray-500 mt-0.5">{item.timestamp}</p>
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* History Toggle Button (when closed) */}
        {!isHistoryOpen && (
          <button
            type="button"
            onClick={() => setIsHistoryOpen(true)}
            className="fixed right-4 top-1/2 -translate-y-1/2 p-3 bg-white border border-gray-200 rounded-lg shadow-md hover:bg-gray-50 transition-colors z-20"
            title="Open History"
          >
            <svg
              className="w-5 h-5 text-gray-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
};

export default ChatPage;
