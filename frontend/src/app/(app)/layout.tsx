"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import { LogoMark } from "@/components/ui/logo";

/**
 * The signed-in half of the application.
 *
 * A route group rather than a path segment: `(app)` shapes the component tree
 * without appearing in any URL, so `/tasks` stays `/tasks`. This replaces both
 * `ProtectedRoute` and `WithLayout` from the old `App.tsx`, and the guard now
 * runs once for the group instead of being repeated per route.
 */
export default function AppLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  // Navigation is a side effect in the App Router — rendering `<Navigate />`
  // has no equivalent, and calling `router.replace` during render warns about
  // updating another component while rendering this one.
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  // Covers both "still reading storage" and the frame after the redirect is
  // queued but before it lands. Rendering the shell there would flash the
  // signed-in chrome at someone who is not signed in.
  //
  // The mark rather than the word "Loading…": this frame is measured in
  // milliseconds on a warm load, and a word appearing and vanishing that fast
  // reads as a flicker where a held brand mark reads as the app opening.
  if (isLoading || !isAuthenticated) {
    return (
      <div
        className="flex min-h-dvh items-center justify-center bg-bg"
        role="status"
        aria-label="Loading Locus"
      >
        <LogoMark className="size-9 animate-pulse text-subtle" />
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
