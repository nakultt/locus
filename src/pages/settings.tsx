import { useState, useEffect } from "react";
import { Moon, Sun, User, Bell, Palette, Grid, Key, Check, X, Loader2, ExternalLink, AlertTriangle, LogOut } from "lucide-react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { setGeminiKey, checkGeminiKey, deleteGeminiKey, type GeminiKeyStatus } from "@/lib/api";

const Settings = () => {
  const [isDark, setIsDark] = useState(false);
  const navigate = useNavigate();
  const { user } = useAuth();
  
  // Gemini API Key state
  const [apiKey, setApiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState<GeminiKeyStatus | null>(null);
  const [isLoadingKey, setIsLoadingKey] = useState(true);
  const [isSavingKey, setIsSavingKey] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [keySuccess, setKeySuccess] = useState<string | null>(null);

  // Edit Profile State
  const [isEditProfileOpen, setIsEditProfileOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [isUpdatingProfile, setIsUpdatingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null);
  const { updateProfile, logout } = useAuth();

  // Check initial theme
  useEffect(() => {
    const isDarkMode = document.documentElement.classList.contains("dark");
    setIsDark(isDarkMode);
  }, []);
  
  // Check if user has a Gemini key on load
  useEffect(() => {
    const checkKey = async () => {
      if (!user?.id) return;
      
      try {
        const result = await checkGeminiKey(user.id);
        setKeyStatus(result);
      } catch (err) {
        console.error("Failed to check Gemini key:", err);
      } finally {
        setIsLoadingKey(false);
      }
    };

    checkKey();
  }, [user?.id]);
  
  // Clear messages after 5 seconds
  useEffect(() => {
    if (keyError || keySuccess) {
      const timer = setTimeout(() => {
        setKeyError(null);
        setKeySuccess(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [keyError, keySuccess]);

  // Initialize edit form when opening modal
  useEffect(() => {
    if (isEditProfileOpen && user) {
      setEditName(user.name || "");
      setEditEmail(user.email || "");
      setEditPassword("");
      setProfileError(null);
      setProfileSuccess(null);
    }
  }, [isEditProfileOpen, user]);

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    
    setIsUpdatingProfile(true);
    setProfileError(null);
    setProfileSuccess(null);
    
    try {
      await updateProfile({
        name: editName,
        email: editEmail,
        password: editPassword || undefined // Only send if set
      });
      setProfileSuccess("Profile updated successfully!");
      setTimeout(() => setIsEditProfileOpen(false), 1500);
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Failed to update profile");
    } finally {
      setIsUpdatingProfile(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  // Toggle theme
  const toggleTheme = () => {
    const newDarkMode = !isDark;
    setIsDark(newDarkMode);
    if (newDarkMode) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  };
  
  const handleSaveKey = async () => {
    if (!user?.id || !apiKey.trim()) return;

    setIsSavingKey(true);
    setKeyError(null);
    setKeySuccess(null);

    try {
      const result = await setGeminiKey(user.id, apiKey.trim());
      setKeyStatus(result);
      setKeySuccess("Gemini API key saved successfully!");
      setApiKey("");
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to save API key");
    } finally {
      setIsSavingKey(false);
    }
  };

  const handleDeleteKey = async () => {
    if (!user?.id) return;

    setIsSavingKey(true);
    setKeyError(null);
    setKeySuccess(null);

    try {
      const result = await deleteGeminiKey(user.id);
      setKeyStatus(result);
      setKeySuccess("Gemini API key removed");
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to delete API key");
    } finally {
      setIsSavingKey(false);
    }
  };

  const settingsSections = [
    {
      title: "Appearance",
      icon: Palette,
      items: [
        {
          label: "Dark Mode",
          description: "Toggle dark theme",
          action: (
            <button
              onClick={toggleTheme}
              className="relative w-14 h-8 bg-muted rounded-full p-1 transition-colors"
            >
              <motion.div
                animate={{ x: isDark ? 24 : 0 }}
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
                className="w-6 h-6 bg-primary rounded-full flex items-center justify-center"
              >
                {isDark ? (
                  <Moon size={14} className="text-primary-foreground" />
                ) : (
                  <Sun size={14} className="text-primary-foreground" />
                )}
              </motion.div>
            </button>
          ),
        },
      ],
    },
    {
      title: "Account",
      icon: User,
      items: [
        {
          label: "Profile",
          description: "Manage your account details",
          action: (
            <button 
              onClick={() => setIsEditProfileOpen(true)}
              className="px-4 py-2 text-sm bg-secondary hover:bg-secondary/80 rounded-lg transition"
            >
              Edit
            </button>
          ),
        },
        {
          label: "Log Out",
          description: "Sign out of your account",
          action: (
            <button 
              onClick={handleLogout}
              className="px-4 py-2 text-sm bg-red-500/10 text-red-500 hover:bg-red-500/20 rounded-lg transition flex items-center gap-2"
            >
              <LogOut size={14} />
              Log Out
            </button>
          ),
        },
      ],
    },
    {
      title: "Notifications",
      icon: Bell,
      items: [
        {
          label: "Push Notifications",
          description: "Receive push notifications",
          action: (
            <button className="relative w-14 h-8 bg-muted rounded-full p-1">
              <motion.div className="w-6 h-6 bg-muted-foreground/50 rounded-full" />
            </button>
          ),
        },
      ],
    },
    {
      title: "Integrations",
      icon: Grid,
      items: [
        {
          label: "Connected Apps",
          description: "Manage Slack, Notion, Jira and other integrations",
          action: (
            <button
              onClick={() => navigate("/integrations/integrations-page")}
              className="px-4 py-2 text-sm bg-secondary hover:bg-secondary/80 rounded-lg transition"
            >
              Manage
            </button>
          ),
        },
      ],
    },
  ];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto p-6">
        <h1 className="text-2xl font-bold text-foreground mb-6">Settings</h1>

        <div className="space-y-6">
          {/* Gemini API Key Section - Priority */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-card border border-border rounded-xl overflow-hidden"
          >
            <div className="flex items-center gap-3 p-4 border-b border-border bg-gradient-to-r from-blue-500/10 to-purple-500/10">
              <Key size={20} className="text-blue-500" />
              <div className="flex-1">
                <h2 className="font-semibold text-foreground">Gemini API Key</h2>
                <p className="text-xs text-muted-foreground">
                  Required for AI-powered chat
                </p>
              </div>
              <a
                href="https://aistudio.google.com/app/apikey"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                Get key <ExternalLink size={10} />
              </a>
            </div>
            
            <div className="p-4">
              {isLoadingKey ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 size={16} className="animate-spin" />
                  <span className="text-sm">Loading...</span>
                </div>
              ) : (
                <>
                  {/* Status indicator */}
                  <div className={`flex items-center gap-2 mb-4 p-2.5 rounded-lg text-sm ${
                    keyStatus?.has_key 
                      ? "bg-green-500/10 text-green-600 dark:text-green-400"
                      : "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
                  }`}>
                    {keyStatus?.has_key ? (
                      <>
                        <Check size={14} />
                        <span>API key configured</span>
                      </>
                    ) : (
                      <>
                        <AlertTriangle size={14} />
                        <span>No API key - Chat won't work</span>
                      </>
                    )}
                  </div>

                  {/* API Key Input */}
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={keyStatus?.has_key ? "Enter new key to update" : "Enter your Gemini API key"}
                      className="flex-1 px-3 py-2 bg-background border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                    <button
                      onClick={handleSaveKey}
                      disabled={!apiKey.trim() || isSavingKey}
                      className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 transition"
                    >
                      {isSavingKey ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Check size={14} />
                      )}
                      Save
                    </button>
                  </div>

                  {keyStatus?.has_key && (
                    <button
                      onClick={handleDeleteKey}
                      disabled={isSavingKey}
                      className="mt-2 text-xs text-red-500 hover:text-red-600 flex items-center gap-1 transition"
                    >
                      <X size={12} />
                      Remove API key
                    </button>
                  )}

                  {/* Messages */}
                  {keyError && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="mt-3 p-2 bg-red-500/10 text-red-500 rounded-lg text-xs"
                    >
                      {keyError}
                    </motion.div>
                  )}
                  {keySuccess && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="mt-3 p-2 bg-green-500/10 text-green-500 rounded-lg text-xs"
                    >
                      {keySuccess}
                    </motion.div>
                  )}
                </>
              )}
            </div>
          </motion.div>

          {/* Other Settings Sections */}
          {settingsSections.map((section) => (
            <motion.div
              key={section.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-card border border-border rounded-xl overflow-hidden"
            >
              <div className="flex items-center gap-3 p-4 border-b border-border bg-muted/30">
                <section.icon size={20} className="text-muted-foreground" />
                <h2 className="font-semibold text-foreground">
                  {section.title}
                </h2>
              </div>
              <div className="divide-y divide-border">
                {section.items.map((item, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between p-4 hover:bg-muted/20 transition"
                  >
                    <div>
                      <p className="font-medium text-foreground">
                        {item.label}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {item.description}
                      </p>
                    </div>
                    {item.action}
                  </div>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        {/* App Info */}
        <div className="mt-8 text-center text-sm text-muted-foreground">
          <p>Locus v1.0.0</p>
          <p className="mt-1">© 2024 Locus. All rights reserved.</p>
        </div>
      </div>

      {/* Edit Profile Modal */}
      {isEditProfileOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm">
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-md bg-card border border-border rounded-xl shadow-lg overflow-hidden"
          >
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h2 className="text-lg font-semibold">Edit Profile</h2>
              <button 
                onClick={() => setIsEditProfileOpen(false)}
                className="p-1 hover:bg-muted rounded-full transition"
              >
                <X size={20} />
              </button>
            </div>
            
            <form onSubmit={handleUpdateProfile} className="p-4 space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Name</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="Your Name"
                />
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Email</label>
                <input
                  type="email"
                  value={editEmail}
                  onChange={(e) => setEditEmail(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="name@example.com"
                />
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">New Password (Optional)</label>
                <input
                  type="password"
                  value={editPassword}
                  onChange={(e) => setEditPassword(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="Leave blank to keep current"
                />
              </div>

              {profileError && (
                <div className="p-3 bg-red-500/10 text-red-500 rounded-lg text-sm">
                  {profileError}
                </div>
              )}
              
              {profileSuccess && (
                <div className="p-3 bg-green-500/10 text-green-500 rounded-lg text-sm">
                  {profileSuccess}
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  type="button"
                  onClick={() => setIsEditProfileOpen(false)}
                  className="px-4 py-2 mr-2 text-sm text-foreground hover:bg-muted rounded-lg transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUpdatingProfile}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {isUpdatingProfile && <Loader2 size={14} className="animate-spin" />}
                  Save Changes
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </div>
  );
};

export default Settings;
