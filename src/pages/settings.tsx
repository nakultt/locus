import { useState, useEffect } from "react";
import { Moon, Sun, User, Bell, Palette, Grid, Cpu, Check, X, Loader2, AlertTriangle, LogOut, Activity } from "lucide-react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  checkLLMStatus,
  fetchIntegrationHealth,
  type IntegrationHealthEntry,
  type LLMStatus,
} from "@/lib/api";
import { timeAgo } from "@/lib/datetime";


const Settings = () => {
  const [isDark, setIsDark] = useState(false);
  const navigate = useNavigate();
  const { user } = useAuth();

  // Local model backend status
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [isLoadingLlm, setIsLoadingLlm] = useState(true);

  // Whether the background loops are actually reaching each integration.
  const [health, setHealth] = useState<IntegrationHealthEntry[]>([]);

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
  
  // Poll the local model backend so the badge reflects load/eject in the MoE app
  const refreshLlmStatus = async () => {
    try {
      setLlmStatus(await checkLLMStatus());
    } catch (err) {
      console.error("Failed to check local model status:", err);
      setLlmStatus({
        available: false,
        message: "Cannot reach the Locus backend.",
      });
    } finally {
      setIsLoadingLlm(false);
    }
  };

  // Health changes on the poller's schedule (minutes), not the model's, so it
  // is fetched once rather than on the 15s model-status interval.
  const refreshHealth = async () => {
    try {
      setHealth(await fetchIntegrationHealth());
    } catch (err) {
      // A failure here must not blank the page; the section simply stays empty.
      console.error("Failed to fetch integration health:", err);
    }
  };

  useEffect(() => {
    refreshLlmStatus();
    refreshHealth();
    const interval = setInterval(refreshLlmStatus, 15000);
    return () => clearInterval(interval);
  }, []);

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
          {/* Local Model Backend */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-card border border-border rounded-xl overflow-hidden"
          >
            <div className="flex items-center gap-3 p-4 border-b border-border bg-gradient-to-r from-blue-500/10 to-purple-500/10">
              <Cpu size={20} className="text-blue-500" />
              <div className="flex-1">
                <h2 className="font-semibold text-foreground">Local Model</h2>
                <p className="text-xs text-muted-foreground">
                  Locus runs entirely on your machine
                </p>
              </div>
              <button
                onClick={refreshLlmStatus}
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                Refresh
              </button>
            </div>

            <div className="p-4">
              {isLoadingLlm ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 size={16} className="animate-spin" />
                  <span className="text-sm">Checking model server...</span>
                </div>
              ) : (
                <>
                  <div
                    className={`flex items-start gap-2 mb-4 p-2.5 rounded-lg text-sm ${
                      llmStatus?.available
                        ? "bg-green-500/10 text-green-600 dark:text-green-400"
                        : "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
                    }`}
                  >
                    {llmStatus?.available ? (
                      <Check size={14} className="mt-0.5 shrink-0" />
                    ) : (
                      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    )}
                    <span>{llmStatus?.message}</span>
                  </div>

                  {llmStatus?.base_url && (
                    <dl className="space-y-1.5 text-xs">
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted-foreground">Endpoint</dt>
                        <dd className="font-mono text-foreground truncate">
                          {llmStatus.base_url}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted-foreground">Fast model</dt>
                        <dd className="font-mono text-foreground truncate">
                          {llmStatus.fast_model}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted-foreground">Smart model</dt>
                        <dd className="font-mono text-foreground truncate">
                          {llmStatus.smart_model}
                        </dd>
                      </div>
                    </dl>
                  )}

                  {!llmStatus?.available && (
                    <p className="mt-3 text-xs text-muted-foreground">
                      Open MoE Model Manager and load a text model. No API key
                      is required.
                    </p>
                  )}
                </>
              )}
            </div>
          </motion.div>

          {/* Integration health.
              The background loops swallow their own failures so one dead
              integration cannot stop the others. This is where that silence
              surfaces — a Gmail token that expired days ago otherwise shows
              up only as QA replies no longer arriving.

              Rendered only when there is something to report: a service is
              listed once it has been attempted, and "never attempted" is not
              a state worth a row. */}
          {health.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-card border border-border rounded-xl overflow-hidden"
            >
              <div className="flex items-center gap-3 p-4 border-b border-border bg-muted/30">
                <Activity size={20} className="text-muted-foreground" />
                <div className="flex-1">
                  <h2 className="font-semibold text-foreground">
                    Integration health
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    What the background loops last saw
                  </p>
                </div>
                <button
                  onClick={refreshHealth}
                  className="text-xs text-primary hover:underline"
                >
                  Refresh
                </button>
              </div>

              <div className="divide-y divide-border">
                {health.map((entry) => (
                  <div key={entry.service} className="p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        {entry.healthy ? (
                          <Check
                            size={14}
                            className="text-green-600 dark:text-green-400 shrink-0"
                          />
                        ) : (
                          <AlertTriangle
                            size={14}
                            className="text-yellow-600 dark:text-yellow-400 shrink-0"
                          />
                        )}
                        <span className="font-medium text-foreground capitalize">
                          {entry.service}
                        </span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        last worked {timeAgo(entry.last_success_at)}
                      </span>
                    </div>

                    {/* The error is shown only while it is the current state.
                        A message from a failure that has since recovered
                        would read as a live problem. */}
                    {!entry.healthy && (
                      <div className="mt-2 rounded-lg bg-yellow-500/10 px-2.5 py-2">
                        <p className="text-xs text-foreground">
                          {entry.consecutive_failures} failed attempt
                          {entry.consecutive_failures === 1 ? "" : "s"} in a
                          row, most recently{" "}
                          {timeAgo(entry.last_failure_at)}.
                        </p>
                        {entry.last_error && (
                          <p className="mt-1 font-mono text-[11px] text-muted-foreground break-words">
                            {entry.last_error}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}

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
