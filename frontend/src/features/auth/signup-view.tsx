"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import { AuthLayout } from "@/features/auth/auth-layout";
import { Button, IconButton } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Notice } from "@/components/ui/surface";
import { cn } from "@/lib/utils";

/**
 * Create an account.
 *
 * This page did not work. It validated the two passwords, waited a second on a
 * `setTimeout` standing in for a request, logged "Signup successful!" and sent
 * the browser to `/login` — no account was ever created. The only working path
 * was a hidden mode toggle on the login form. It now calls `signup` from the
 * auth context, the same one that toggle used, and lands the new user on their
 * board rather than bouncing them back to a sign-in screen.
 */

const MIN_LENGTH = 6;

/** Strength as a count of satisfied rules, so the meter can say *why*. */
function assess(password: string) {
  const rules = [
    { label: `${MIN_LENGTH} characters or more`, ok: password.length >= MIN_LENGTH },
    { label: "a number", ok: /\d/.test(password) },
    { label: "a letter", ok: /[a-zA-Z]/.test(password) },
    { label: "a symbol", ok: /[^a-zA-Z0-9]/.test(password) },
  ];
  return { rules, score: rules.filter((r) => r.ok).length };
}

export default function SignupView() {
  const router = useRouter();
  const { signup } = useAuth();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { rules, score } = useMemo(() => assess(password), [password]);

  // Only after something has been typed in the field: an inline "passwords do
  // not match" the instant the first character lands is scolding, not helping.
  const mismatch = confirm.length > 0 && confirm !== password;
  const tooShort = password.length > 0 && password.length < MIN_LENGTH;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < MIN_LENGTH) {
      setError(`Your password needs at least ${MIN_LENGTH} characters.`);
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }

    setBusy(true);
    try {
      await signup(email, password, name.trim() || undefined);
      router.push("/tasks");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create your account."
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Connect a repository and the next pull request is analysed automatically."
      footer={
        <>
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-medium text-ink underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-5" noValidate>
        {error && <Notice tone="danger">{error}</Notice>}

        <Field label="Name" htmlFor="name" hint="Optional — used to address you.">
          <Input
            id="name"
            name="name"
            autoComplete="name"
            inputSize="lg"
            placeholder="Priya Raman"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

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
          />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          error={tooShort ? `At least ${MIN_LENGTH} characters.` : undefined}
        >
          <div className="relative">
            <Input
              id="password"
              name="password"
              type={reveal ? "text" : "password"}
              autoComplete="new-password"
              inputSize="lg"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              invalid={tooShort}
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

          {/* Four segments naming four rules. A bare "weak/strong" word tells
              someone their password is wrong without telling them what to do
              about it, which is the whole job of the meter. */}
          {password.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="flex gap-1.5" aria-hidden>
                {rules.map((rule, i) => (
                  <span
                    key={rule.label}
                    className={cn(
                      "h-1 flex-1 rounded-pill transition-colors",
                      i < score
                        ? score <= 1
                          ? "bg-danger"
                          : score <= 2
                            ? "bg-warning"
                            : "bg-success"
                        : "bg-surface-3"
                    )}
                  />
                ))}
              </div>
              <p className="text-xs text-muted" aria-live="polite">
                {score === rules.length
                  ? "Strong password."
                  : `Add ${rules
                      .filter((r) => !r.ok)
                      .map((r) => r.label)
                      .join(", ")}.`}
              </p>
            </div>
          )}
        </Field>

        <Field
          label="Confirm password"
          htmlFor="confirm"
          error={mismatch ? "These do not match." : undefined}
        >
          <Input
            id="confirm"
            name="confirm"
            type={reveal ? "text" : "password"}
            autoComplete="new-password"
            inputSize="lg"
            placeholder="••••••••"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            invalid={mismatch}
          />
        </Field>

        <Button type="submit" size="lg" className="w-full" loading={busy}>
          {busy ? "Creating your account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
