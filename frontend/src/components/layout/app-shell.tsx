"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { LogOut, Menu, Search, Settings, User } from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import { NAV_ITEMS, isActivePath } from "@/components/layout/nav-config";
import {
  CommandPalette,
  useCommandPalette,
} from "@/components/layout/command-palette";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Avatar } from "@/components/ui/avatar";
import { IconButton } from "@/components/ui/button";
import { LogoMark, Wordmark } from "@/components/ui/logo";
import { Menu as MenuRoot, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Sheet } from "@/components/ui/overlay";
import { cn } from "@/lib/utils";

/**
 * The signed-in chrome.
 *
 * A floating top bar, not a sidebar. The sidebar this replaces was carrying
 * three unrelated jobs at once — the brand, the global navigation, and the
 * chat conversation list — which meant every page in the product reserved
 * 256px for a chat history that only one of them could use, and the four
 * destinations that were not chat got a narrower canvas to pay for it.
 *
 * Splitting them puts the navigation where it costs nothing (a 56px bar, the
 * width of the window) and moves the conversation list inside chat, where it
 * is context rather than chrome. Every other page gained the full width, which
 * is what the analysis tables and message logs actually needed.
 *
 * The bar is `sticky`, not `fixed`: it participates in the document flow, so
 * the page below does not need a compensating top padding that has to be kept
 * in sync by hand.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPalette();

  // A tap on a nav item in the drawer navigates; the drawer must not still be
  // over the page it navigated to.
  useEffect(() => setMobileNavOpen(false), [pathname]);

  const signOut = () => {
    logout();
    router.push("/login");
  };

  return (
    /* `h-dvh`, not `min-h-dvh`.
       Every page here scrolls its own content — `PageShell` and the chat
       transcript both own an `overflow-y-auto` region — and that only works if
       something above them is actually bounded. With a *minimum* height the
       shell grew past the viewport instead, so the document scrolled: in chat
       the conversation rail and its header slid up under the application bar
       while the transcript sat still. An exact viewport height gives `flex-1`
       a real size to divide. */
    <div className="flex h-dvh flex-col overflow-hidden bg-bg">
      <header className="sticky top-0 z-30 border-b border-line/80 bg-bg/85 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[92rem] items-center gap-3 px-4 sm:px-6 lg:px-8">
          {/* Brand. Links to Work rather than to `/`: for someone signed in,
              `/` is the marketing page, and a home button that leaves the
              product is a trapdoor. */}
          <Link
            href="/tasks"
            prefetch={true}
            className="shrink-0 rounded-md transition-opacity hover:opacity-80"
            aria-label="Locus — go to Work"
          >
            <Wordmark className="hidden sm:inline-flex" />
            <LogoMark className="size-7 text-ink sm:hidden" />
          </Link>

          {/* The pill nav, centred. Absolutely positioned so it is centred on
              the *window* rather than on whatever space the brand and the
              account controls happen to leave — otherwise it drifts sideways
              as a longer name appears in the account button. */}
          <nav
            aria-label="Primary"
            className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-0.5 rounded-pill border border-line bg-surface p-1 shadow-sm lg:flex"
          >
            {NAV_ITEMS.map((item) => {
              const active = isActivePath(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "relative rounded-pill px-3.5 py-1.5 text-sm font-medium transition-colors",
                    active ? "text-ink" : "text-muted hover:text-ink"
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="nav-pill"
                      transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                      className="absolute inset-0 rounded-pill bg-surface-2"
                    />
                  )}
                  <span className="relative">{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {/* Search is a button that opens ⌘K, not an input. There is nothing
                to type into on most of these pages, and a dead search field is
                worse than none. */}
            <button
              type="button"
              onClick={() => setPaletteOpen(true)}
              className="hidden items-center gap-2 rounded-pill border border-line bg-surface py-1.5 pl-3 pr-1.5 text-sm text-muted transition-colors hover:border-line-strong hover:text-ink sm:flex"
            >
              <Search className="size-4" aria-hidden />
              <span>Search</span>
              <kbd className="rounded-pill border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-subtle">
                ⌘K
              </kbd>
            </button>

            <ThemeToggle className="hidden md:inline-flex" />

            <MenuRoot>
              <MenuTrigger
                label="Account menu"
                className="rounded-pill transition-opacity hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <Avatar name={user?.name} email={user?.email} />
              </MenuTrigger>
              <MenuContent width="w-60">
                <div className="px-2.5 pb-2 pt-1.5">
                  <p className="truncate text-sm font-medium text-ink">
                    {user?.name || "Your account"}
                  </p>
                  <p className="truncate text-xs text-muted">{user?.email}</p>
                </div>
                <MenuSeparator />
                <MenuItem icon={<User />} onSelect={() => router.push("/settings")}>
                  Profile
                </MenuItem>
                <MenuItem
                  icon={<Settings />}
                  onSelect={() => router.push("/settings?tab=automation")}
                >
                  Automation
                </MenuItem>
                <MenuSeparator />
                <MenuLabel>Theme</MenuLabel>
                <div className="px-2.5 pb-1.5 pt-0.5">
                  <ThemeToggle />
                </div>
                <MenuSeparator />
                <MenuItem icon={<LogOut />} tone="danger" onSelect={signOut}>
                  Sign out
                </MenuItem>
              </MenuContent>
            </MenuRoot>

            <IconButton
              label="Open navigation"
              className="lg:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              <Menu />
            </IconButton>
          </div>
        </div>
      </header>

      {/* `min-h-0` so a page that wants to own its own scrolling — chat — can
          actually do so inside a flex column. */}
      <main className="flex min-h-0 flex-1 flex-col">{children}</main>

      {/* On a phone the navigation is a drawer, not a shrunken bar. Five 44px
          targets in a row do not fit across 390px without becoming unhittable. */}
      <Sheet
        open={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        title="Navigate"
        width="narrow"
        side="right"
      >
        <nav aria-label="Primary (mobile)" className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const active = isActivePath(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                prefetch={true}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-start gap-3 rounded-md px-3 py-3 transition-colors",
                  active ? "bg-surface-2" : "hover:bg-surface-2/60"
                )}
              >
                <Icon
                  className={cn(
                    "mt-0.5 size-4.5 shrink-0",
                    active ? "text-accent-strong" : "text-subtle"
                  )}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">
                    {item.label}
                  </span>
                  <span className="block text-xs text-muted">{item.hint}</span>
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-6 space-y-1 border-t border-line pt-6">
          <Link
            href="/settings"
            className="flex items-center gap-3 rounded-md px-3 py-3 text-sm text-ink transition-colors hover:bg-surface-2/60"
          >
            <Settings className="size-4.5 shrink-0 text-subtle" />
            Settings
          </Link>
          <button
            type="button"
            onClick={signOut}
            className="flex w-full items-center gap-3 rounded-md px-3 py-3 text-left text-sm text-danger transition-colors hover:bg-danger-soft"
          >
            <LogOut className="size-4.5 shrink-0" />
            Sign out
          </button>
        </div>

        <div className="mt-6 flex items-center justify-between border-t border-line pt-6">
          <span className="text-sm text-muted">Theme</span>
          <ThemeToggle />
        </div>
      </Sheet>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}

/**
 * The top of a page: a title, one line saying what the page answers, and the
 * page-level actions.
 *
 * Every surface used to invent its own — different sizes, different margins,
 * a refresh button floated right on two of them and absent on the rest. One
 * component is what makes five pages read as one product.
 */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-6 gap-y-4",
        className
      )}
    >
      <div className="min-w-0 space-y-2">
        {eyebrow}
        <h1 className="text-title text-ink">{title}</h1>
        {description && (
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

/**
 * The page canvas.
 *
 * `wide` is the default and suits the board, the analysis tables and the
 * connection list. `narrow` is for reading and forms — settings, the calendar
 * composer — where a full-width line of text is tiring to scan.
 */
export function PageShell({
  children,
  width = "wide",
  className,
}: {
  children: React.ReactNode;
  width?: "wide" | "narrow";
  className?: string;
}) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div
        className={cn(
          "mx-auto px-4 py-8 sm:px-6 sm:py-10 lg:px-8",
          width === "wide" ? "max-w-[80rem]" : "max-w-3xl",
          className
        )}
      >
        {children}
      </div>
    </div>
  );
}

export { AppShell as default };
