import { useState, useEffect, useRef } from "react";
import {
  Send,
  Wrench,
  CheckCircle,
  XCircle,
  Lightbulb,
  Loader2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import {
  streamChatMessage,
  getConversationMessages,
  type ActionResult,
  type StreamEvent,
  type Message as ApiMessage,
} from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  actions?: ActionResult[];
}

interface LiveTask {
  task_id: string;
  service: string;
  action: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  result?: string;
  error?: string;
}

const PLACEHOLDERS = [
  "Ask me anything...",
  "What can I help you with?",
  "Start a conversation...",
  "Type your message here...",
];

// Service icon mapping - extended for all services
const getServiceIcon = (service: string) => {
  switch (service.toLowerCase()) {
    case "slack":
      return "💬";
    case "jira":
      return "🎫";
    case "gmail":
      return "📧";
    case "calendar":
      return "📅";
    case "notion":
      return "📝";
    case "docs":
      return "📄";
    case "sheets":
      return "📊";
    case "slides":
      return "📽️";
    case "drive":
      return "📁";
    case "forms":
      return "📋";
    case "meet":
      return "🎥";
    case "github":
      return "🐙";
    case "linear":
      return "🔷";
    case "bugasura":
      return "🐛";
    default:
      return "🔧";
  }
};

// Live Tool Card - shows tools being called in real-time
const LiveToolCard = ({ task }: { task: LiveTask }) => (
  <motion.div
    initial={{ opacity: 0, scale: 0.95, x: -10 }}
    animate={{ opacity: 1, scale: 1, x: 0 }}
    className={`flex items-start gap-3 p-3 rounded-lg border mb-2 ${
      task.status === "in_progress"
        ? "bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800"
        : task.status === "completed"
        ? "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800"
        : task.status === "failed"
        ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800"
        : "bg-muted/50 border-border"
    }`}
  >
    <span className="text-lg">{getServiceIcon(task.service)}</span>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2">
        <Wrench size={14} className="text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">
          {task.action}
        </span>
        {task.status === "in_progress" && (
          <Loader2 size={14} className="text-blue-500 animate-spin" />
        )}
        {task.status === "completed" && (
          <CheckCircle size={14} className="text-green-500" />
        )}
        {task.status === "failed" && (
          <XCircle size={14} className="text-red-500" />
        )}
      </div>
      <p className="text-xs text-muted-foreground mt-1">{task.description}</p>
      {task.result && task.status === "completed" && (
        <p className="text-xs text-green-600 dark:text-green-400 mt-1 truncate">
          {task.result.substring(0, 100)}
          {task.result.length > 100 ? "..." : ""}
        </p>
      )}
      {task.error && (
        <p className="text-xs text-red-400 mt-1">{task.error}</p>
      )}
    </div>
  </motion.div>
);

// Tool Action Card component (for completed messages)
const ToolActionCard = ({ action }: { action: ActionResult }) => (
  <motion.div
    initial={{ opacity: 0, scale: 0.95 }}
    animate={{ opacity: 1, scale: 1 }}
    className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg border border-border mb-2"
  >
    <span className="text-lg">{getServiceIcon(action.service)}</span>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2">
        <Wrench size={14} className="text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">
          {action.action}
        </span>
        {action.success ? (
          <CheckCircle size={14} className="text-green-500" />
        ) : (
          <XCircle size={14} className="text-red-500" />
        )}
      </div>
      {action.result && (
        <p className="text-xs text-muted-foreground mt-1 truncate">
          {action.result.substring(0, 100)}
          {action.result.length > 100 ? "..." : ""}
        </p>
      )}
      {action.error && (
        <p className="text-xs text-red-400 mt-1">{action.error}</p>
      )}
    </div>
  </motion.div>
);

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
        // AI message with tool actions
        <div className="max-w-[85%] py-2">
          {/* Show tool actions if present */}
          {message.actions && message.actions.length > 0 && (
            <div className="mb-3">
              <p className="text-xs text-muted-foreground mb-2">Tools used:</p>
              {message.actions.map((action, idx) => (
                <ToolActionCard key={idx} action={action} />
              ))}
            </div>
          )}
          <p className="text-sm leading-relaxed text-foreground whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
      )}
    </motion.div>
  );
};

// Main Chat Interface component
interface ChatInterfaceProps {
  conversationId?: number;
}

const ChatInterface = ({ conversationId: initialConversationId }: ChatInterfaceProps) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [showPlaceholder, setShowPlaceholder] = useState(true);
  const [isActive, setIsActive] = useState(false);
  const [smartMode, setSmartMode] = useState(false);
  
  // Live streaming state
  const [currentStatus, setCurrentStatus] = useState<string>("");
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<number | undefined>(initialConversationId);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const { user } = useAuth();

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, liveTasks]);

  // Load existing messages when conversationId changes
  useEffect(() => {
    const loadMessages = async () => {
      if (initialConversationId) {
        setIsLoadingHistory(true);
        try {
          const apiMessages = await getConversationMessages(initialConversationId);
          const loadedMessages: Message[] = apiMessages.map((msg: ApiMessage) => ({
            id: msg.id.toString(),
            role: msg.role as "user" | "assistant",
            content: msg.content,
            timestamp: new Date(msg.created_at),
            actions: msg.actions_taken,
          }));
          setMessages(loadedMessages);
        } catch (err) {
          console.error("Failed to load messages:", err);
        } finally {
          setIsLoadingHistory(false);
        }
      } else {
        // Reset for new conversation
        setMessages([]);
        setCurrentConversationId(undefined);
      }
    };
    loadMessages();
  }, [initialConversationId]);

  // Cleanup abort on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current();
      }
    };
  }, []);

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
    setCurrentStatus("Analyzing your request...");
    setLiveTasks([]);

    if (!user?.id) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: "Please log in to use the chat",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setIsLoading(false);
      setCurrentStatus("");
      return;
    }

    // Use streaming API for live updates
    const abort = streamChatMessage(
      user.id,
      userMessage.content,
      // onEvent
      (event: StreamEvent) => {
        // Capture conversation_id from any event
        if (event.data?.conversation_id && !currentConversationId) {
          setCurrentConversationId(event.data.conversation_id as number);
        }
        
        switch (event.event_type) {
          case "planning":
            setCurrentStatus(event.data.status || "Planning tasks...");
            break;

          case "plan":
            if (event.data.tasks) {
              const tasks: LiveTask[] = event.data.tasks.map((t) => ({
                task_id: t.task_id,
                service: t.service,
                action: t.action,
                description: t.description,
                status: "pending" as const,
              }));
              setLiveTasks(tasks);
              setCurrentStatus(`Executing ${tasks.length} task${tasks.length > 1 ? 's' : ''}...`);
            }
            break;

          case "task_started":
            setCurrentStatus(`Calling ${event.data.service || 'tool'}...`);
            setLiveTasks((prev) =>
              prev.map((t) =>
                t.task_id === event.data.task_id
                  ? { ...t, status: "in_progress" as const }
                  : t
              )
            );
            // If task not in list, add it
            setLiveTasks((prev) => {
              const exists = prev.some((t) => t.task_id === event.data.task_id);
              if (!exists && event.data.task_id) {
                return [
                  ...prev,
                  {
                    task_id: event.data.task_id,
                    service: event.data.service || "unknown",
                    action: event.data.action || "unknown",
                    description: event.data.description || "",
                    status: "in_progress" as const,
                  },
                ];
              }
              return prev;
            });
            break;

          case "task_completed":
            setLiveTasks((prev) =>
              prev.map((t) =>
                t.task_id === event.data.task_id
                  ? {
                      ...t,
                      status: "completed" as const,
                      result: event.data.result,
                    }
                  : t
              )
            );
            break;

          case "task_failed":
            setLiveTasks((prev) =>
              prev.map((t) =>
                t.task_id === event.data.task_id
                  ? {
                      ...t,
                      status: "failed" as const,
                      error: event.data.error,
                    }
                  : t
              )
            );
            break;

          case "complete": {
            // Create final AI message with all actions
            const aiMessage: Message = {
              id: (Date.now() + 1).toString(),
              role: "assistant",
              content: event.data.message || "Done!",
              timestamp: new Date(),
              actions: event.data.actions_taken as ActionResult[],
            };
            setMessages((prev) => [...prev, aiMessage]);
            setIsLoading(false);
            setCurrentStatus("");
            setLiveTasks([]);
            break;
          }

          case "error": {
            const errorMessage: Message = {
              id: (Date.now() + 1).toString(),
              role: "assistant",
              content: event.data.message || "An error occurred",
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, errorMessage]);
            setIsLoading(false);
            setCurrentStatus("");
            setLiveTasks([]);
            break;
          }
        }
      },
      // onError
      (error: Error) => {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content: `Sorry, I encountered an error: ${error.message}`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
        setIsLoading(false);
        setCurrentStatus("");
        setLiveTasks([]);
      },
      // onComplete
      () => {
        setIsLoading(false);
        setCurrentStatus("");
      },
      // conversationId
      currentConversationId
    );

    abortRef.current = abort;
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const containerVariants: {
    collapsed: { height: number; boxShadow: string };
    expanded: { height: number; boxShadow: string };
  } = {
    collapsed: {
      height: 68,
      boxShadow: "0 2px 8px 0 rgba(0,0,0,0.08)",
    },
    expanded: {
      height: 128,
      boxShadow: "0 8px 32px 0 rgba(0,0,0,0.16)",
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
    },
    exit: {
      opacity: 0,
      filter: "blur(12px)",
      y: -10,
    },
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {isLoadingHistory ? (
          // Loading history state
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="flex gap-1 mb-4">
              <motion.span
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ duration: 1.5, repeat: Infinity }}
                className="w-2 h-2 bg-muted-foreground rounded-full"
              />
              <motion.span
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ duration: 1.5, repeat: Infinity, delay: 0.2 }}
                className="w-2 h-2 bg-muted-foreground rounded-full"
              />
              <motion.span
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ duration: 1.5, repeat: Infinity, delay: 0.4 }}
                className="w-2 h-2 bg-muted-foreground rounded-full"
              />
            </div>
            <p className="text-muted-foreground">Loading conversation...</p>
          </div>
        ) : messages.length === 0 && !isLoading ? (
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
            
            {/* Live streaming indicator */}
            {isLoading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="mb-4"
              >
                {/* Status indicator */}
                <div className="flex items-center gap-2 mb-3">
                  <Loader2 size={16} className="text-primary animate-spin" />
                  <span className="text-sm text-muted-foreground">
                    {currentStatus || "Processing..."}
                  </span>
                </div>
                
                {/* Live tool execution cards */}
                {liveTasks.length > 0 && (
                  <div className="mb-3">
                    <p className="text-xs text-muted-foreground mb-2">Live execution:</p>
                    <AnimatePresence>
                      {liveTasks.map((task) => (
                        <LiveToolCard key={task.task_id} task={task} />
                      ))}
                    </AnimatePresence>
                  </div>
                )}
                
                {/* Fallback dots if no tasks yet */}
                {liveTasks.length === 0 && (
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
                )}
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
                  {/* Smart Toggle */}
                  <button
                    className={`flex items-center gap-1 px-4 py-2 rounded-full transition-all font-medium group ${
                      smartMode
                        ? "bg-yellow-500/20 outline outline-yellow-500/60 text-yellow-700 dark:text-yellow-300"
                        : "bg-accent text-accent-foreground hover:bg-accent/80"
                    }`}
                    title="Use higher intelligence model"
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSmartMode((s) => !s);
                    }}
                  >
                    <Lightbulb
                      className={`transition-all ${
                        smartMode
                          ? "fill-yellow-400 text-yellow-600"
                          : "group-hover:fill-yellow-300"
                      }`}
                      size={18}
                    />
                    Smart
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
