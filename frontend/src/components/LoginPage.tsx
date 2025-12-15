import React, { useState, FormEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";

// Types for role and component props
type UserRole = "admin" | "user";

interface LoginPageProps {
  /**
   * Optional callback fired on successful login.
   * Use this if you want to plug in real auth logic or custom routing.
   */
  onLoginSuccess?: (payload: { role: UserRole; email: string }) => void;
}

/**
 * Enterprise-style login page for:
 * - Project: "Integration Store / DewDrop Framework"
 * - Brand title: "Integration Store"
 * - Subtitle: "Unified Command Center for Enterprise Apps"
 *
 * Tech stack:
 * - React + TypeScript
 * - Tailwind CSS for styling
 * - Framer Motion for subtle, modern animations
 *
 * This component is ready to plug into an existing React app
 * that already has Tailwind and Framer Motion configured.
 */
export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  // Form state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("admin");

  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Basic email validation regex (simple and sufficient for frontend checks)
  const isValidEmail = (value: string) =>
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

  /**
   * Handle submit with simple client-side validation.
   * Replace the "fake" timeout with real API integration if needed.
   */
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validation
    if (!email.trim() || !password.trim()) {
      setError("Please fill in all required fields.");
      return;
    }

    if (!isValidEmail(email)) {
      setError("Please enter a valid email address.");
      return;
    }

    // Simulate async login
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);

      // In real-world usage, replace this with actual authentication logic.
      // Call the optional callback first so the host app can hook into routing.
      onLoginSuccess?.({ role, email });

      // Simple role-based redirect as a sensible default.
      if (role === "admin") {
        window.location.assign("/admin");
      } else {
        window.location.assign("/dashboard");
      }
    }, 1200);
  };

  // Framer Motion variants for page and card animations
  // Cast as `any` to keep TS happy with the easing definitions while
  // still leveraging Framer Motion's runtime behavior.
  const pageVariants: any = {
    hidden: { opacity: 0, scale: 0.98, y: 8 },
    visible: {
      opacity: 1,
      scale: 1,
      y: 0,
      transition: {
        duration: 0.5,
        ease: [0.16, 1, 0.3, 1], // "anticipate" style curve (21st.dev inspired)
      },
    },
  };

  const cardVariants: any = {
    hidden: { opacity: 0, y: 16 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.4,
        ease: [0.16, 1, 0.3, 1],
      },
    },
  };

  const errorVariants: any = {
    hidden: { opacity: 0, y: -4 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.2, ease: "easeOut" },
    },
    exit: {
      opacity: 0,
      y: -4,
      transition: { duration: 0.15, ease: "easeIn" },
    },
  };

  return (
    <motion.div
      className="min-h-screen bg-slate-950 text-slate-50 flex items-center justify-center px-4 py-8"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      {/* Background gradient + subtle glow */}
      <div className="pointer-events-none fixed inset-0">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.18),_transparent_55%),_radial-gradient(circle_at_bottom,_rgba(139,92,246,0.2),_transparent_55%)]" />
        <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-slate-900/80 to-transparent" />
      </div>

      {/* Main card container */}
      <motion.div
        className="relative z-10 w-full max-w-md"
        variants={cardVariants}
      >
        <div className="mb-8 text-center">
          <motion.div
            className="inline-flex items-center gap-2 rounded-full border border-slate-800/60 bg-slate-900/60 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400 backdrop-blur"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15, duration: 0.35 }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(16,185,129,0.25)]" />
            Integration Store / DewDrop Framework
          </motion.div>

          <motion.h1
            className="mt-5 text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.22, duration: 0.4 }}
          >
            Integration Store
          </motion.h1>

          <motion.p
            className="mt-2 text-sm text-slate-400 sm:text-base"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.26, duration: 0.4 }}
          >
            Unified Command Center for Enterprise Apps
          </motion.p>
        </div>

        {/* Glassmorphism-style card */}
        <div className="relative overflow-hidden rounded-2xl border border-slate-800/70 bg-slate-950/70 shadow-[0_18px_45px_rgba(15,23,42,0.85)] backdrop-blur-xl">
          {/* Subtle accent border on top */}
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-cyan-400/0 via-cyan-400/70 to-violet-500/0" />

          <div className="relative p-6 sm:p-8">
            {/* Role selection */}
            <section aria-labelledby="role-label">
              <p
                id="role-label"
                className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400"
              >
                Role
              </p>

              <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-slate-900/80 p-1.5 text-xs text-slate-300 sm:text-sm">
                {/* Admin Toggle */}
                <motion.button
                  type="button"
                  onClick={() => setRole("admin")}
                  whileHover={{ y: -1, transition: { duration: 0.16 } }}
                  whileTap={{ scale: 0.97 }}
                  className={`flex items-center justify-center gap-2 rounded-lg px-2.5 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-0 focus-visible:ring-offset-slate-900 ${
                    role === "admin"
                      ? "bg-slate-50 text-slate-950 shadow-sm"
                      : "bg-transparent text-slate-400 hover:bg-slate-800/90"
                  }`}
                  aria-pressed={role === "admin"}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
                  <span>Admin</span>
                </motion.button>

                {/* User Toggle */}
                <motion.button
                  type="button"
                  onClick={() => setRole("user")}
                  whileHover={{ y: -1, transition: { duration: 0.16 } }}
                  whileTap={{ scale: 0.97 }}
                  className={`flex items-center justify-center gap-2 rounded-lg px-2.5 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-0 focus-visible:ring-offset-slate-900 ${
                    role === "user"
                      ? "bg-slate-50 text-slate-950 shadow-sm"
                      : "bg-transparent text-slate-400 hover:bg-slate-800/90"
                  }`}
                  aria-pressed={role === "user"}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
                  <span>Employee / User</span>
                </motion.button>
              </div>

              {/* Visually hidden native radios for accessibility / forms if needed */}
              <fieldset className="sr-only">
                <legend>Role</legend>
                <label>
                  <input
                    type="radio"
                    name="role"
                    value="admin"
                    checked={role === "admin"}
                    onChange={() => setRole("admin")}
                  />
                  Admin
                </label>
                <label>
                  <input
                    type="radio"
                    name="role"
                    value="user"
                    checked={role === "user"}
                    onChange={() => setRole("user")}
                  />
                  Employee / User
                </label>
              </fieldset>
            </section>

            {/* Login form */}
            <form
              className="mt-6 space-y-5"
              onSubmit={handleSubmit}
              noValidate
            >
              {/* Email field */}
              <motion.div
                className="space-y-1.5"
                whileHover={{ y: -1 }}
                transition={{ duration: 0.18 }}
              >
                <label
                  htmlFor="email"
                  className="block text-xs font-medium text-slate-300"
                >
                  Email
                </label>
                <motion.div
                  className="relative"
                  whileFocus={{
                    boxShadow:
                      "0 0 0 1px rgba(56,189,248,0.7), 0 0 0 12px rgba(8,47,73,0.6)",
                  }}
                  transition={{ duration: 0.22, ease: "easeOut" }}
                >
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="block w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2.5 text-sm text-slate-50 shadow-sm outline-none transition focus:border-cyan-400 focus:bg-slate-900/80 focus:ring-1 focus:ring-cyan-400 placeholder:text-slate-500"
                    placeholder="you@enterprise.com"
                  />
                </motion.div>
              </motion.div>

              {/* Password field */}
              <motion.div
                className="space-y-1.5"
                whileHover={{ y: -1 }}
                transition={{ duration: 0.18 }}
              >
                <label
                  htmlFor="password"
                  className="block text-xs font-medium text-slate-300"
                >
                  Password
                </label>
                <motion.div
                  className="relative"
                  whileFocus={{
                    boxShadow:
                      "0 0 0 1px rgba(139,92,246,0.75), 0 0 0 12px rgba(30,64,175,0.6)",
                  }}
                  transition={{ duration: 0.22, ease: "easeOut" }}
                >
                  <input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="block w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2.5 text-sm text-slate-50 shadow-sm outline-none transition focus:border-violet-400 focus:bg-slate-900/80 focus:ring-1 focus:ring-violet-400 placeholder:text-slate-500"
                    placeholder="Enter your password"
                  />
                </motion.div>
              </motion.div>

              {/* Error message with gentle motion */}
              <AnimatePresence>
                {error && (
                  <motion.div
                    className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200"
                    variants={errorVariants}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    role="alert"
                  >
                    {error}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Submit button */}
              <motion.button
                type="submit"
                disabled={isLoading}
                whileHover={{
                  y: -1,
                  boxShadow:
                    "0 18px 40px rgba(34,211,238,0.35), 0 0 0 1px rgba(56,189,248,0.35)",
                }}
                whileTap={{ scale: 0.97, y: 0 }}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-400 via-sky-400 to-violet-400 px-4 py-2.5 text-sm font-medium text-slate-950 shadow-[0_12px_30px_rgba(56,189,248,0.45)] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-80"
              >
                {isLoading ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                    <span>Signing you in…</span>
                  </>
                ) : (
                  <>
                    <span>Enter Command Center</span>
                    <span className="text-xs text-slate-900/80">
                      ({role === "admin" ? "Admin" : "User"})
                    </span>
                  </>
                )}
              </motion.button>
            </form>

            <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
              By continuing, you acknowledge that access to the Integration
              Store is monitored and audited in accordance with enterprise
              security policies.
            </p>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
};

export default LoginPage;


