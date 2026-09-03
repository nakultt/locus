"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import { AuthLayout } from "@/features/auth/auth-layout";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Input } from "@/components/ui/form";
import { Notice } from "@/components/ui/surface";

/**
 * Sign in.
 *
 * One job. The version this replaces held a `isSignupMode` flag and switched
 * between logging in and registering inside the same component at the same URL
 * — while a separate `/signup` route existed alongside it, rendering a *third*
 * form that never called the API at all. Two routes, two components, one
 * behaviour each.
 */
export default function LoginView() {
  const router = useRouter();
  const { login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password, remember);
      router.push("/tasks");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign you in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Pick up wherever the pipeline left your work."
      footer={
        <>
          New here?{" "}
          <Link
            href="/signup"
            className="font-medium text-ink underline-offset-4 hover:underline"
          >
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-5" noValidate>
        {error && <Notice tone="danger">{error}</Notice>}

        <Field label="Email" htmlFor="email">
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            inputSize="lg"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            invalid={!!error}
          />
        </Field>

        <Field label="Password" htmlFor="password">
          <div className="relative">
            <Input
              id="password"
              name="password"
              type={reveal ? "text" : "password"}
              autoComplete="current-password"
              inputSize="lg"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              invalid={!!error}
              className="pr-12"
            />
            <IconButton
              label={reveal ? "Hide password" : "Show password"}
              size="sm"
              onClick={() => setReveal((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2"
              tabIndex={-1}
            >
              {reveal ? <EyeOff /> : <Eye />}
            </IconButton>
          </div>
        </Field>

        <div className="flex items-center justify-between">
          <label
            htmlFor="remember"
            className="flex cursor-pointer items-center gap-2.5 text-sm text-muted"
          >
            {/* Controlled, and now actually so — the old checkbox kept its own
                state and ignored the prop, so this could look ticked while the
                request went out with `remember: false`. */}
            <Checkbox
              id="remember"
              checked={remember}
              onCheckedChange={setRemember}
            />
            Stay signed in
          </label>
        </div>

        <Button type="submit" size="lg" className="w-full" loading={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
