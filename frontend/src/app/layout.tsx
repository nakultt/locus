import type { Metadata } from "next";
import { AuthProvider } from "@/features/auth/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "locus",
  description: "Cross-tool context for IT work.",
  icons: { icon: "/locus_logo.png" },
};

/**
 * Resolve the theme before the first paint.
 *
 * Vite ran this as a top-level statement in `main.tsx`, which executed before
 * React mounted. Next has no equivalent seam: a `useEffect` in a client
 * component runs *after* hydration, so the page would paint light and then
 * snap to dark on every load for anyone using the dark theme. Inlining it in
 * `<head>` restores the original ordering — the class is on `<html>` before
 * any pixels are drawn.
 *
 * `suppressHydrationWarning` on <html> is required because this script edits
 * the element the server rendered, which React would otherwise flag as a
 * mismatch.
 */
const THEME_INIT = `
try {
  var saved = localStorage.getItem("theme");
  if (saved === "dark" || (!saved && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
    document.documentElement.classList.add("dark");
  }
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
