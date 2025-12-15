import React, { useState, FormEvent } from "react";

interface LoginPageProps {
  /**
   * Optional callback fired on successful submit.
   * You can plug in API calls here.
   */
  onSubmit?: (payload: {
    email: string;
    password: string;
    rememberMe: boolean;
  }) => void;
}

/**
 * Clean, professional login page for:
 * - Brand title: "Integration Store"
 * - Subtitle: "Secure Enterprise Sign-In"
 *
 * Tech:
 * - React + TypeScript
 * - Tailwind CSS for styling
 */
export const LoginPage: React.FC<LoginPageProps> = ({ onSubmit }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError("Please fill in both email and password.");
      return;
    }

    onSubmit?.({ email, password, rememberMe });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md">
        <div className="bg-slate-900/90 border border-slate-800 shadow-2xl rounded-2xl px-6 py-8 sm:px-8 sm:py-10">
          {/* Heading */}
          <div className="mb-6 text-center">
            <h1 className="text-2xl sm:text-3xl font-semibold text-slate-50 tracking-tight">
              Integration Store
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Secure Enterprise Sign-In
            </p>
          </div>

          {/* Form */}
          <form className="space-y-5" onSubmit={handleSubmit} noValidate>
            {/* Email */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="block text-xs font-medium text-slate-300"
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@enterprise.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="block w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 shadow-sm outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition"
              />
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="block text-xs font-medium text-slate-300"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="block w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 shadow-sm outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition"
              />
            </div>

            {/* Remember + Forgot */}
            <div className="flex items-center justify-between text-xs text-slate-400">
              <label className="inline-flex items-center gap-2">
                <input
                  id="rememberMe"
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-900 text-cyan-400 focus:ring-cyan-400 focus:ring-offset-0"
                />
                <span>Remember me</span>
              </label>

              <button
                type="button"
                className="text-xs font-medium text-cyan-300 hover:text-cyan-200 hover:underline"
              >
                Forgot password?
              </button>
            </div>

            {/* Error message */}
            {error && (
              <p className="text-xs text-red-300 bg-red-950/40 border border-red-500/40 rounded-md px-3 py-2">
                {error}
              </p>
            )}

            {/* Submit button */}
            <button
              type="submit"
              className="mt-1 inline-flex w-full items-center justify-center rounded-lg bg-cyan-500 px-4 py-2.5 text-sm font-medium text-slate-950 shadow-md hover:bg-cyan-400 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 transition"
            >
              Login
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;


