import { useState, useEffect } from "react";
import {
  Moon,
  Sun,
  User,
  Bell,
  Palette,
  Shield,
  HelpCircle,
  Grid,
} from "lucide-react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";

const Settings = () => {
  const [isDark, setIsDark] = useState(false);
  const navigate = useNavigate();

  // Check initial theme
  useEffect(() => {
    const isDarkMode = document.documentElement.classList.contains("dark");
    setIsDark(isDarkMode);
  }, []);

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
            <button className="px-4 py-2 text-sm bg-secondary hover:bg-secondary/80 rounded-lg transition">
              Edit
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
    </div>
  );
};

export default Settings;
