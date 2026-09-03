import type { Metadata, Viewport } from "next";
import { Inter, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import { AuthProvider } from "@/features/auth/auth-context";
import { ToastProvider } from "@/components/ui/toast";
import "./globals.css";

/**
 * Three families, each with one job.
 *
 * Inter carries the interface and the display sizes both — at 300–400 weight
 * with the negative tracking the type scale applies, it gives the tight
 * grotesque headline the design is built around without a fourth download.
 * Instrument Serif is the wordmark and nothing else, which is what stops the
 * brand from looking like the UI. JetBrains Mono is reserved for things that
 * are literally code: repo names, branches, queries, model ids.
 *
 * `display: "swap"` on all three: a blocked font must never blank the page.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-instrument-serif",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-jb",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Locus — the work between the ticket and the sign-off",
    template: "%s · Locus",
  },
  description:
    "Locus runs the pipeline from a ticket landing on you to the testing team signing off: context, review, security, QA and the board, without the coordination.",
  icons: { icon: "/locus_logo.png" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf8" },
    { media: "(prefers-color-scheme: dark)", color: "#1c1a18" },
  ],
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
 *
 * "system" is stored as the absence of a value rather than as a literal, so a
 * user who never chose follows their OS and one who chose explicitly does not.
 */
const THEME_INIT = `
try {
  var saved = localStorage.getItem("theme");
  var dark = saved === "dark" || (!saved && window.matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) document.documentElement.classList.add("dark");
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <AuthProvider>
          <ToastProvider>{children}</ToastProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
