import { useState, useEffect, useRef } from "react";
import { Lightbulb, Paperclip, Send } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

const PLACEHOLDERS = [
  "Ask me anything...",
  "What can I help you with?",
  "Start a conversation...",
  "Type your message here...",
];

// Message component for individual messages
const ChatMessage = ({ message }: { message: Message }) => {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}
    >
      {isUser ? (
        // Human message - cylindrical rounded bubble
        <div className="max-w-[70%] bg-secondary text-secondary-foreground px-4 py-3 rounded-[1.25rem] rounded-br-[0.25rem] shadow-sm">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
      ) : (
        // AI message - plain text, no bubble
        <div className="max-w-[85%] py-2">
          <p className="text-sm leading-relaxed text-foreground whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
      )}
    </motion.div>
  );
};

// Main Chat Interface component
const ChatInterface = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [showPlaceholder, setShowPlaceholder] = useState(true);
  const [isActive, setIsActive] = useState(false);
  const [thinkActive, setThinkActive] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Cycle placeholder text when input is inactive
  useEffect(() => {
    if (isActive || inputValue) return;

    const interval = setInterval(() => {
      setShowPlaceholder(false);
      setTimeout(() => {
        setPlaceholderIndex((prev) => (prev + 1) % PLACEHOLDERS.length);
        setShowPlaceholder(true);
      }, 400);
    }, 3000);

    return () => clearInterval(interval);
  }, [isActive, inputValue]);

  // Close input when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(event.target as Node)
      ) {
        if (!inputValue) setIsActive(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [inputValue]);

  const handleActivate = () => setIsActive(true);

  const sendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsLoading(true);

    // Simulate AI response (replace with actual API call)
    setTimeout(() => {
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content:
          "I'm Locus, your AI assistant. I received your message: \"" +
          userMessage.content +
          '"\n\nThis is a demo response. Connect me to your backend API for real responses!',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, aiMessage]);
      setIsLoading(false);
    }, 1500);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const containerVariants = {
    collapsed: {
      height: 68,
      boxShadow: "0 2px 8px 0 rgba(0,0,0,0.08)",
      transition: { type: "spring", stiffness: 120, damping: 18 },
    },
    expanded: {
      height: 128,
      boxShadow: "0 8px 32px 0 rgba(0,0,0,0.16)",
      transition: { type: "spring", stiffness: 120, damping: 18 },
    },
  };

  const placeholderContainerVariants = {
    initial: {},
    animate: { transition: { staggerChildren: 0.025 } },
    exit: { transition: { staggerChildren: 0.015, staggerDirection: -1 } },
  };

  const letterVariants = {
    initial: { opacity: 0, filter: "blur(12px)", y: 10 },
    animate: {
      opacity: 1,
      filter: "blur(0px)",
      y: 0,
      transition: {
        opacity: { duration: 0.25 },
        filter: { duration: 0.4 },
        y: { type: "spring", stiffness: 80, damping: 20 },
      },
    },
    exit: {
      opacity: 0,
      filter: "blur(12px)",
      y: -10,
      transition: {
        opacity: { duration: 0.2 },
        filter: { duration: 0.3 },
        y: { type: "spring", stiffness: 80, damping: 20 },
      },
    },
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          // Welcome state
          <div className="flex flex-col items-center justify-center h-full text-center">
            <h2 className="text-2xl font-semibold text-foreground mb-2">
              Welcome to Locus
            </h2>
            <p className="text-muted-foreground max-w-md">
              Start a conversation below. I'm here to help you with anything you
              need.
            </p>
          </div>
        ) : (
          // Messages list
          <div className="max-w-3xl mx-auto">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
            {isLoading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex justify-start mb-4"
              >
                <div className="py-2">
                  <div className="flex gap-1">
                    <motion.span
                      animate={{ opacity: [0.4, 1, 0.4] }}
                      transition={{ duration: 1.5, repeat: Infinity }}
                      className="w-2 h-2 bg-muted-foreground rounded-full"
                    />
                    <motion.span
                      animate={{ opacity: [0.4, 1, 0.4] }}
                      transition={{
                        duration: 1.5,
                        repeat: Infinity,
                        delay: 0.2,
                      }}
                      className="w-2 h-2 bg-muted-foreground rounded-full"
                    />
                    <motion.span
                      animate={{ opacity: [0.4, 1, 0.4] }}
                      transition={{
                        duration: 1.5,
                        repeat: Infinity,
                        delay: 0.4,
                      }}
                      className="w-2 h-2 bg-muted-foreground rounded-full"
                    />
                  </div>
                </div>
              </motion.div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area - Fixed at bottom */}
      <div className="bg-background p-4">
        <div className="max-w-3xl mx-auto">
          <motion.div
            ref={wrapperRef}
            className="w-full"
            variants={containerVariants}
            animate={isActive || inputValue ? "expanded" : "collapsed"}
            initial="collapsed"
            style={{
              overflow: "hidden",
              borderRadius: 32,
              background: "var(--card)",
            }}
            onClick={handleActivate}
          >
            <div className="flex flex-col items-stretch w-full h-full border border-border rounded-[32px]">
              {/* Input Row */}
              <div className="flex items-center gap-2 p-3 w-full ">
                <button
                  className="p-2 rounded-full hover:bg-accent transition"
                  title="Attach file"
                  type="button"
                  tabIndex={-1}
                >
                  <Paperclip size={20} className="text-muted-foreground" />
                </button>

                {/* Text Input & Placeholder */}
                <div className="relative flex-1">
                  <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={handleKeyPress}
                    className="flex-1 border-0 outline-0 rounded-md py-2 text-base bg-transparent w-full font-normal text-foreground"
                    style={{ position: "relative", zIndex: 1 }}
                    onFocus={handleActivate}
                  />
                  <div className="absolute left-0 top-0 w-full h-full pointer-events-none flex items-center py-2">
                    <AnimatePresence mode="wait">
                      {showPlaceholder && !isActive && !inputValue && (
                        <motion.span
                          key={placeholderIndex}
                          className="absolute left-0 top-1/2 -translate-y-1/2 text-muted-foreground select-none pointer-events-none"
                          style={{
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            zIndex: 0,
                          }}
                          variants={placeholderContainerVariants}
                          initial="initial"
                          animate="animate"
                          exit="exit"
                        >
                          {PLACEHOLDERS[placeholderIndex]
                            .split("")
                            .map((char, i) => (
                              <motion.span
                                key={i}
                                variants={letterVariants}
                                style={{ display: "inline-block" }}
                              >
                                {char === " " ? "\u00A0" : char}
                              </motion.span>
                            ))}
                        </motion.span>
                      )}
                    </AnimatePresence>
                  </div>
                </div>

                <button
                  onClick={sendMessage}
                  disabled={!inputValue.trim() || isLoading}
                  className="flex items-center gap-1 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-primary-foreground p-2.5 rounded-full font-medium justify-center transition"
                  title="Send"
                  type="button"
                >
                  <Send size={18} />
                </button>
              </div>

              {/* Expanded Controls */}
              <motion.div
                className="w-full flex justify-start px-4 items-center text-sm"
                variants={{
                  hidden: {
                    opacity: 0,
                    y: 20,
                    pointerEvents: "none" as const,
                    transition: { duration: 0.25 },
                  },
                  visible: {
                    opacity: 1,
                    y: 0,
                    pointerEvents: "auto" as const,
                    transition: { duration: 0.35, delay: 0.08 },
                  },
                }}
                initial="hidden"
                animate={isActive || inputValue ? "visible" : "hidden"}
                style={{ marginTop: 8, paddingBottom: 12 }}
              >
                <div className="flex gap-3 items-center">
                  {/* Think Toggle */}
                  <button
                    className={`flex items-center gap-1 px-4 py-2 rounded-full transition-all font-medium group ${
                      thinkActive
                        ? "bg-blue-600/10 outline outline-blue-600/60 text-blue-950 dark:text-blue-200"
                        : "bg-accent text-accent-foreground hover:bg-accent/80"
                    }`}
                    title="Think"
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setThinkActive((a) => !a);
                    }}
                  >
                    <Lightbulb
                      className="group-hover:fill-yellow-300 transition-all"
                      size={18}
                    />
                    Think
                  </button>
                </div>
              </motion.div>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
};

// Export both the new ChatInterface and keep the old AIChatInput for backward compatibility
export { ChatInterface };
export { ChatInterface as AIChatInput };
