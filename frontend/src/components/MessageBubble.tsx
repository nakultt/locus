import React from "react";

interface Message {
  id: string;
  text: string;
  sender: "user" | "bot";
  timestamp: string;
  imageUrl?: string;
  status?: "processing" | "completed";
}

interface MessageBubbleProps {
  message: Message;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message }) => {
  const isUser = message.sender === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-6`}>
      <div className={`flex flex-col max-w-[70%] ${isUser ? "items-end" : "items-start"}`}>
        {/* Message Bubble */}
        <div
          className={`rounded-xl px-4 py-3 shadow-md backdrop-blur-sm ${
            isUser
              ? "bg-gradient-to-br from-cyan-500 to-blue-600 text-white rounded-br-sm"
              : "bg-white/90 text-gray-900 border border-gray-200/50 rounded-bl-sm"
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
        {/* Metadata */}
        <div className={`flex items-center gap-2 mt-2 text-xs text-gray-500 ${isUser ? "justify-end" : "justify-start"}`}>
          <span>{message.timestamp}</span>
          {message.status && (
            <span className={`px-2 py-0.5 rounded-full text-xs ${
              message.status === "processing"
                ? "bg-yellow-100 text-yellow-800"
                : "bg-green-100 text-green-800"
            }`}>
              {message.status}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default MessageBubble;


