import React, { useState, FormEvent } from "react";

type Role = "admin" | "manager" | "user";

interface LoginPageProps {
  /**
   * Optional callback fired on successful submit.
   * You can plug in API calls here.
   */
  onSubmit?: (payload: {
    email: string;
    password: string;
    rememberMe: boolean;
    role: Role;
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
  const [role, setRole] = useState<Role>("user");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError("Please fill in both email and password.");
      return;
    }

    onSubmit?.({ email, password, rememberMe, role });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <div className="w-full max-w-md">
        <div className="bg-white border border-gray-200 shadow-xl rounded-2xl px-6 py-8 sm:px-8 sm:py-10">
          {/* Heading */}
          <div className="mb-6 text-center">
            <h1 className="text-2xl sm:text-3xl font-semibold text-gray-900 tracking-tight">
              Integration Store
            </h1>
            <p className="mt-1 text-sm text-gray-600">
              Secure Enterprise Sign-In
            </p>
          </div>

          {/* Form */}
          <form className="space-y-5" onSubmit={handleSubmit} noValidate>
            {/* Email */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="block text-xs font-medium text-gray-700"
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
                className="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 shadow-sm outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
              />
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="block text-xs font-medium text-gray-700"
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
                className="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 shadow-sm outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
              />
            </div>

            {/* Remember + Forgot */}
            <div className="flex items-center justify-between text-xs text-gray-600">
              <label className="inline-flex items-center gap-2">
                <input
                  id="rememberMe"
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-gray-300 bg-white text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                />
                <span>Remember me</span>
              </label>

              <button
                type="button"
                className="text-xs font-medium text-cyan-600 hover:text-cyan-700 hover:underline"
              >
                Forgot password?
              </button>
            </div>

            {/* Error message */}
            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                {error}
              </p>
            )}

            {/* Submit button */}
            <button
              type="submit"
              className="mt-1 inline-flex w-full items-center justify-center rounded-lg bg-cyan-500 px-4 py-2.5 text-sm font-medium text-white shadow-md hover:bg-cyan-600 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white transition"
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


