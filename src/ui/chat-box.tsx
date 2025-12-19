import { useState, useEffect, useRef } from "react";
import {
  Lightbulb,
  Paperclip,
  Send,
  Wrench,
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import {
  streamChatMessage,
  type ActionResult,
  type TaskUpdate,
  type StreamEvent,
  type TaskStatusType,
} from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  actions?: ActionResult[];
}

interface TaskProgress {
  tasks: TaskUpdate[];
  currentTaskId: string | null;
  status: string;
  isActive: boolean;
}


const PLACEHOLDERS = [
  "Ask me anything...",
  "What can I help you with?",
  "Start a conversation...",
  "Type your message here...",
];

// Service icon mapping
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
    default:
      return "🔧";
  }
};

// Tool Action Card component
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

// Task Progress Panel - Shows live task execution status
const TaskProgressPanel = ({
  tasks,
  status,
}: {
  tasks: TaskUpdate[];
  status: string;
}) => {
  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const failedCount = tasks.filter((t) => t.status === "failed").length;

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="bg-card border border-border rounded-xl p-4 mb-4 shadow-sm"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin text-primary" />
          <span className="text-sm font-medium text-foreground">
            {status || `Executing tasks...`}
          </span>
        </div>
        <span className="text-xs text-muted-foreground">
          {completedCount}/{tasks.length} completed
          {failedCount > 0 && ` • ${failedCount} failed`}
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-muted rounded-full overflow-hidden mb-4">
        <motion.div
          className="h-full bg-gradient-to-r from-primary to-primary/70"
          initial={{ width: 0 }}
          animate={{ width: `${(completedCount / tasks.length) * 100}%` }}
          transition={{ duration: 0.3 }}
        />
      </div>

      {/* Task list */}
      <div className="space-y-2">
        {tasks.map((task) => (
          <motion.div
            key={task.task_id}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            className={`flex items-center gap-3 p-2.5 rounded-lg transition-colors ${
              task.status === "in_progress"
                ? "bg-primary/10 border border-primary/30"
                : task.status === "completed"
                ? "bg-green-500/10"
                : task.status === "failed"
                ? "bg-red-500/10"
                : "bg-muted/30"
            }`}
          >
            {/* Status Icon */}
            <div className="flex-shrink-0">
              {task.status === "pending" && (
                <Clock className="w-4 h-4 text-muted-foreground" />
              )}
              {task.status === "in_progress" && (
                <Loader2 className="w-4 h-4 animate-spin text-primary" />
              )}
              {task.status === "completed" && (
                <CheckCircle className="w-4 h-4 text-green-500" />
              )}
              {task.status === "failed" && (
                <XCircle className="w-4 h-4 text-red-500" />
              )}
            </div>

            {/* Service Icon */}
            <span className="text-base flex-shrink-0">
              {getServiceIcon(task.service)}
            </span>

            {/* Description */}
            <div className="flex-1 min-w-0">
              <p className="text-sm text-foreground truncate">
                {task.description}
              </p>
              {task.result && task.status === "completed" && (
                <p className="text-xs text-green-600 truncate mt-0.5">
                  ✓ {task.result.substring(0, 60)}...
                </p>
              )}
              {task.error && (
                <p className="text-xs text-red-400 truncate mt-0.5">
                  {task.error}
                </p>
              )}
            </div>

            {/* Status Badge */}
            <span
              className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${
                task.status === "in_progress"
                  ? "bg-primary text-primary-foreground"
                  : task.status === "completed"
                  ? "bg-green-500 text-white"
                  : task.status === "failed"
                  ? "bg-red-500 text-white"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {task.status === "in_progress"
                ? "Running..."
                : task.status === "pending"
                ? "Waiting"
                : task.status}
            </span>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
};

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
const ChatInterface = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [showPlaceholder, setShowPlaceholder] = useState(true);
  const [isActive, setIsActive] = useState(false);
  const [thinkActive, setThinkActive] = useState(false);
  const [taskProgress, setTaskProgress] = useState<TaskProgress>({
    tasks: [],
    currentTaskId: null,
    status: "",
    isActive: false,
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const { user } = useAuth();

  // Scroll to bottom when new messages arrive or task progress updates
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, taskProgress]);

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

  // Cleanup abort on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current();
      }
    };
  }, []);

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
    const messageContent = inputValue.trim();
    setInputValue("");
    setIsLoading(true);
    setTaskProgress({
      tasks: [],
      currentTaskId: null,
      status: "Analyzing your request...",
      isActive: true,
    });

    if (!user?.id) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: "Please log in to use the chat",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setIsLoading(false);
      setTaskProgress((prev) => ({ ...prev, isActive: false }));
      return;
    }

    // Use streaming API for real-time updates
    abortRef.current = streamChatMessage(
      user.id,
      messageContent,
      // onEvent - handle each SSE event
      (event: StreamEvent) => {
        switch (event.event_type) {
          case "planning":
            setTaskProgress((prev) => ({
              ...prev,
              status: event.data.status || "Planning...",
            }));
            break;

          case "plan":
            // Received the task plan
            if (event.data.tasks) {
              const tasks: TaskUpdate[] = event.data.tasks.map((t) => ({
                ...t,
                status: "pending" as TaskStatusType,
              }));
              setTaskProgress({
                tasks,
                currentTaskId: null,
                status: `Executing ${tasks.length} tasks...`,
                isActive: true,
              });
            }
            break;

          case "task_started":
            setTaskProgress((prev) => ({
              ...prev,
              currentTaskId: event.data.task_id || null,
              status: `Running: ${event.data.description || event.data.action}`,
              tasks: prev.tasks.map((t) =>
                t.task_id === event.data.task_id
                  ? { ...t, status: "in_progress" as TaskStatusType }
                  : t
              ),
            }));
            break;

          case "task_completed":
            setTaskProgress((prev) => ({
              ...prev,
              tasks: prev.tasks.map((t) =>
                t.task_id === event.data.task_id
                  ? {
                      ...t,
                      status: "completed" as TaskStatusType,
                      result: event.data.result,
                    }
                  : t
              ),
            }));
            break;

          case "task_failed":
            setTaskProgress((prev) => ({
              ...prev,
              tasks: prev.tasks.map((t) =>
                t.task_id === event.data.task_id
                  ? {
                      ...t,
                      status: "failed" as TaskStatusType,
                      error: event.data.error,
                    }
                  : t
              ),
            }));
            break;

          case "complete": {
            // Final response - add AI message
            const aiMessage: Message = {
              id: (Date.now() + 1).toString(),
              role: "assistant",
              content: event.data.message || "Tasks completed.",
              timestamp: new Date(),
              actions: event.data.actions_taken,
            };
            setMessages((prev) => [...prev, aiMessage]);
            setTaskProgress((prev) => ({
              ...prev,
              status: "Complete!",
              isActive: false,
            }));
            setIsLoading(false);
            break;
          }

          case "error": {
            const errorMsg: Message = {
              id: (Date.now() + 1).toString(),
              role: "assistant",
              content: event.data.message || "An error occurred.",
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, errorMsg]);
            setTaskProgress((prev) => ({ ...prev, isActive: false }));
            setIsLoading(false);
            break;
          }
        }
      },
      // onError
      (error: Error) => {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content: error.message || "Sorry, I encountered an error.",
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
        setTaskProgress((prev) => ({ ...prev, isActive: false }));
        setIsLoading(false);
      },
      // onComplete
      () => {
        // Stream finished
        if (isLoading) {
          setIsLoading(false);
          setTaskProgress((prev) => ({ ...prev, isActive: false }));
        }
      }
    );
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
            {/* Show TaskProgressPanel when streaming with tasks */}
            {taskProgress.isActive && taskProgress.tasks.length > 0 && (
              <TaskProgressPanel
                tasks={taskProgress.tasks}
                status={taskProgress.status}
              />
            )}
            {/* Show simple loading indicator when no task plan yet */}
            {isLoading && taskProgress.tasks.length === 0 && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex justify-start mb-4"
              >
                <div className="py-2">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin text-primary" />
                    <span className="text-sm text-muted-foreground">
                      {taskProgress.status || "Processing..."}
                    </span>
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
