"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useRouter } from "next/navigation";
import {
  CornerDownLeft,
  LogOut,
  MessageSquarePlus,
  Search,
  Settings,
  SunMoon,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import { NAV_ITEMS } from "@/components/layout/nav-config";
import { cn } from "@/lib/utils";

/**
 * ⌘K.
 *
 * Five destinations do not need a search box; what they need is a way to reach
 * any of them without moving the pointer to the top of the window. This also
 * carries the actions that have no home in the navigation — start a new chat,
 * flip the theme, sign out — which is what keeps them out of the top bar and
 * off the settings page.
 *
 * Deliberately not fuzzy. Substring matching over a fixed list of five things
 * is predictable; a fuzzy matcher over five things mostly produces surprises.
 */
interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  run: () => void;
  group: "Go to" | "Actions";
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const router = useRouter();
  const { logout } = useAuth();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [mounted, setMounted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  const close = useCallback(() => {
    onOpenChange(false);
    setQuery("");
    setActive(0);
  }, [onOpenChange]);

  const commands = useMemo<Command[]>(() => {
    const go: Command[] = NAV_ITEMS.map((item) => ({
      id: item.href,
      label: item.label,
      hint: item.hint,
      icon: item.icon,
      group: "Go to",
      run: () => router.push(item.href),
    }));

    return [
      ...go,
      {
        id: "settings",
        label: "Settings",
        hint: "Profile, appearance, automation and system",
        icon: Settings,
        group: "Go to",
        run: () => router.push("/settings"),
      },
      {
        id: "new-chat",
        label: "New chat",
        hint: "Start a fresh conversation",
        icon: MessageSquarePlus,
        group: "Actions",
        run: () => router.push("/chatbot"),
      },
      {
        id: "theme",
        label: "Toggle dark mode",
        icon: SunMoon,
        group: "Actions",
        run: () => {
          const root = document.documentElement;
          const next = root.classList.contains("dark") ? "light" : "dark";
          root.classList.toggle("dark", next === "dark");
          localStorage.setItem("theme", next);
        },
      },
      {
        id: "logout",
        label: "Sign out",
        icon: LogOut,
        group: "Actions",
        run: () => {
          logout();
          router.push("/login");
        },
      },
    ];
  }, [router, logout]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) || c.hint?.toLowerCase().includes(q)
    );
  }, [commands, query]);

  // Clamp rather than reset: typing narrows the list, and an index left past
  // the end selects nothing on Enter.
  useEffect(() => {
    setActive((i) => Math.min(i, Math.max(results.length - 1, 0)));
  }, [results.length]);

  useEffect(() => {
    if (!open) return;
    const raf = requestAnimationFrame(() => inputRef.current?.focus());
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(raf);
      document.body.style.overflow = prev;
    };
  }, [open]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % Math.max(results.length, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % Math.max(results.length, 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = results[active];
      if (cmd) {
        close();
        cmd.run();
      }
    }
  };

  if (!mounted) return null;

  let lastGroup = "";

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={close}
            className="fixed inset-0 z-[70] bg-ink/40 backdrop-blur-[2px]"
          />
          <div className="fixed inset-0 z-[70] flex items-start justify-center p-4 pt-[12vh]">
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-label="Command palette"
              initial={{ opacity: 0, y: -12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
              onKeyDown={onKeyDown}
              className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface shadow-pop"
            >
              <div className="flex items-center gap-3 border-b border-line px-4">
                <Search className="size-4 shrink-0 text-subtle" aria-hidden />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search pages and actions…"
                  aria-label="Search pages and actions"
                  className="h-12 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-subtle"
                />
                <kbd className="rounded-sm border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-subtle">
                  esc
                </kbd>
              </div>

              <div role="listbox" className="max-h-80 overflow-y-auto p-2">
                {results.length === 0 ? (
                  <p className="px-3 py-8 text-center text-sm text-muted">
                    Nothing matches “{query}”.
                  </p>
                ) : (
                  results.map((cmd, i) => {
                    const header = cmd.group !== lastGroup ? cmd.group : null;
                    lastGroup = cmd.group;
                    const Icon = cmd.icon;
                    return (
                      <div key={cmd.id}>
                        {header && (
                          <p className="px-3 pb-1.5 pt-3 text-label uppercase text-subtle first:pt-1">
                            {header}
                          </p>
                        )}
                        <button
                          type="button"
                          role="option"
                          aria-selected={i === active}
                          onMouseMove={() => setActive(i)}
                          onClick={() => {
                            close();
                            cmd.run();
                          }}
                          className={cn(
                            "flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors",
                            i === active ? "bg-surface-2" : "hover:bg-surface-2/60"
                          )}
                        >
                          <Icon className="size-4 shrink-0 text-subtle" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm text-ink">
                              {cmd.label}
                            </span>
                            {cmd.hint && (
                              <span className="block truncate text-xs text-muted">
                                {cmd.hint}
                              </span>
                            )}
                          </span>
                          {i === active && (
                            <CornerDownLeft
                              className="size-3.5 shrink-0 text-subtle"
                              aria-hidden
                            />
                          )}
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}

/** Registers ⌘K / Ctrl-K globally and reports whether the palette is open. */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return { open, setOpen };
}
