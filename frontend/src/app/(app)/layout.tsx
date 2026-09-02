"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/auth-context";
import { AppShell } from "@/components/layout/app-shell";

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
  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
