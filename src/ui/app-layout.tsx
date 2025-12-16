import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Home,
  Settings,
  MessageSquare,
  Plus,
  ChevronDown,
  Menu,
  X,
} from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";

interface ChatHistory {
  id: string;
  title: string;
  timestamp: Date;
}

interface AppLayoutProps {
  children: React.ReactNode;
}

// Mock chat history (replace with actual state management)
const mockChatHistory: ChatHistory[] = [
  { id: "1", title: "Getting started with Locus", timestamp: new Date() },
  {
    id: "2",
    title: "Project ideas discussion",
    timestamp: new Date(Date.now() - 86400000),
  },
  {
    id: "3",
    title: "Code review help",
    timestamp: new Date(Date.now() - 172800000),
  },
];

const AppLayout = ({ children }: AppLayoutProps) => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [chatHistoryOpen, setChatHistoryOpen] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  const navItems = [
    { icon: Home, label: "Home", path: "/" },
    { icon: MessageSquare, label: "Chat", path: "/chatbot" },
    { icon: Settings, label: "Settings", path: "/settings" },
  ];

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="flex h-screen bg-background">
      {/* Desktop Sidebar */}
      <aside className="hidden md:flex flex-col w-64 bg-sidebar border-r border-sidebar-border">
        {/* Logo */}
        <div className="p-4 border-b border-sidebar-border">
          <h1 className="text-xl font-bold text-sidebar-foreground">Locus</h1>
        </div>

        {/* New Chat Button */}
        <div className="p-3">
          <button
            onClick={() => navigate("/chatbot")}
            className="w-full flex items-center gap-2 px-4 py-2.5 bg-sidebar-primary text-sidebar-primary-foreground rounded-lg hover:bg-sidebar-primary/90 transition font-medium"
          >
            <Plus size={18} />
            New Chat
          </button>
        </div>

        {/* Chat History */}
        <div className="flex-1 overflow-y-auto px-3">
          <button
            onClick={() => setChatHistoryOpen(!chatHistoryOpen)}
            className="w-full flex items-center justify-between py-2 px-2 text-sm font-medium text-sidebar-foreground/70 hover:text-sidebar-foreground"
          >
            <span>Chat History</span>
            <motion.div
              animate={{ rotate: chatHistoryOpen ? 180 : 0 }}
              transition={{ duration: 0.2 }}
            >
              <ChevronDown size={16} />
            </motion.div>
          </button>

          <AnimatePresence>
            {chatHistoryOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="space-y-1 pb-4">
                  {mockChatHistory.map((chat) => (
                    <button
                      key={chat.id}
                      onClick={() => navigate(`/chatbot?id=${chat.id}`)}
                      className="w-full text-left px-3 py-2 text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground rounded-lg transition truncate"
                    >
                      {chat.title}
                    </button>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Navigation */}
        <nav className="p-3 border-t border-sidebar-border">
          {navItems.map((item) => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition text-sm font-medium ${
                isActive(item.path)
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              }`}
            >
              <item.icon size={18} />
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Mobile Header */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 bg-background border-b border-border">
        <div className="flex items-center justify-between p-4">
          <h1 className="text-lg font-bold">Locus</h1>
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="p-2 hover:bg-accent rounded-lg transition"
          >
            {isSidebarOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </div>

      {/* Mobile Sidebar Overlay */}
      <AnimatePresence>
        {isSidebarOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="md:hidden fixed inset-0 bg-black/50 z-40"
              onClick={() => setIsSidebarOpen(false)}
            />
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="md:hidden fixed left-0 top-0 bottom-0 w-72 bg-sidebar z-50 flex flex-col"
            >
              {/* Mobile sidebar content (same as desktop) */}
              <div className="p-4 border-b border-sidebar-border flex items-center justify-between">
                <h1 className="text-xl font-bold text-sidebar-foreground">
                  Locus
                </h1>
                <button
                  onClick={() => setIsSidebarOpen(false)}
                  className="p-2 hover:bg-sidebar-accent rounded-lg transition"
                >
                  <X size={20} />
                </button>
              </div>

              <div className="p-3">
                <button
                  onClick={() => {
                    navigate("/chatbot");
                    setIsSidebarOpen(false);
                  }}
                  className="w-full flex items-center gap-2 px-4 py-2.5 bg-sidebar-primary text-sidebar-primary-foreground rounded-lg hover:bg-sidebar-primary/90 transition font-medium"
                >
                  <Plus size={18} />
                  New Chat
                </button>
              </div>

              <div className="flex-1 overflow-y-auto px-3">
                <div className="py-2 px-2 text-sm font-medium text-sidebar-foreground/70">
                  Chat History
                </div>
                <div className="space-y-1 pb-4">
                  {mockChatHistory.map((chat) => (
                    <button
                      key={chat.id}
                      onClick={() => {
                        navigate(`/chatbot?id=${chat.id}`);
                        setIsSidebarOpen(false);
                      }}
                      className="w-full text-left px-3 py-2 text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground rounded-lg transition truncate"
                    >
                      {chat.title}
                    </button>
                  ))}
                </div>
              </div>

              <nav className="p-3 border-t border-sidebar-border">
                {navItems.map((item) => (
                  <button
                    key={item.path}
                    onClick={() => {
                      navigate(item.path);
                      setIsSidebarOpen(false);
                    }}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition text-sm font-medium ${
                      isActive(item.path)
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                    }`}
                  >
                    <item.icon size={18} />
                    {item.label}
                  </button>
                ))}
              </nav>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden md:pt-0 pt-16">
        {children}
      </main>
    </div>
  );
};

export { AppLayout };
