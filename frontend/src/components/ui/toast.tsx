"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Toasts.
 *
 * What this replaces: every view held its own `error` string in state and
 * rendered it as a red strip somewhere near the top, which meant a failure on
 * a control at the bottom of a long settings form reported itself off screen.
 * A toast is anchored to the viewport, so the report is where the person is.
 *
 * Two rules. Errors do not auto-dismiss — a message that disappears before it
 * is read is the same as no message, and a failure is exactly the case where
 * someone is looking at the thing that failed rather than the corner. And the
 * region is `aria-live="polite"`, so a screen reader hears the outcome without
 * being interrupted mid-sentence.
 */

export type ToastTone = "success" | "error" | "warning" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastApi {
  push: (t: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
  dismiss: (id: number) => void;
}

const Ctx = React.createContext<ToastApi | null>(null);

const ICON = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
} as const;

const TONE = {
  success: "text-success",
  error: "text-danger",
  warning: "text-warning",
  info: "text-info",
} as const;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const [mounted, setMounted] = React.useState(false);
  const seq = React.useRef(0);

  React.useEffect(() => setMounted(true), []);

  const dismiss = React.useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = React.useCallback(
    (t: Omit<Toast, "id">) => {
      const id = ++seq.current;
      // Bounded at four. A queue that grows without limit covers the thing it
      // is reporting on, and by the fifth simultaneous message nobody is
      // reading any of them.
      setToasts((prev) => [...prev.slice(-3), { ...t, id }]);
      if (t.tone !== "error") {
        setTimeout(() => dismiss(id), 5000);
      }
    },
    [dismiss]
  );

  const api = React.useMemo<ToastApi>(
    () => ({
      push,
      dismiss,
      success: (title, description) => push({ tone: "success", title, description }),
      error: (title, description) => push({ tone: "error", title, description }),
      info: (title, description) => push({ tone: "info", title, description }),
    }),
    [push, dismiss]
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      {mounted &&
        createPortal(
          <div
            aria-live="polite"
            aria-atomic="false"
            className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:right-0 sm:items-end sm:p-6"
          >
            <AnimatePresence initial={false}>
              {toasts.map((t) => {
                const Icon = ICON[t.tone];
                return (
                  <motion.div
                    key={t.id}
                    layout
                    initial={{ opacity: 0, y: 12, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, x: 24, scale: 0.97 }}
                    transition={{ duration: 0.24, ease: [0.32, 0.72, 0, 1] }}
                    className={cn(
                      "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border border-line bg-surface p-4 shadow-pop"
                    )}
                  >
                    <Icon className={cn("mt-px size-4 shrink-0", TONE[t.tone])} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink">{t.title}</p>
                      {t.description && (
                        <p className="mt-1 break-words text-xs leading-relaxed text-muted">
                          {t.description}
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => dismiss(t.id)}
                      aria-label="Dismiss"
                      className="-m-1 shrink-0 rounded-md p-1 text-subtle transition-colors hover:bg-surface-2 hover:text-ink"
                    >
                      <X className="size-3.5" />
                    </button>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>,
          document.body
        )}
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
