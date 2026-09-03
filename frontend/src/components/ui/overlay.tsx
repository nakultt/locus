"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { IconButton } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Dialogs and sheets, built by hand.
 *
 * Only `@radix-ui/react-slot` is a dependency here, and the repo maintains its
 * primitives by hand deliberately — so the behaviour a real dialog needs is
 * implemented rather than assumed: a portal so it escapes any `overflow:
 * hidden` ancestor, Escape to dismiss, a click on the scrim to dismiss, the
 * page held still underneath, focus moved in on open and returned on close,
 * and Tab kept inside while it is open.
 *
 * The last two are the ones that get skipped. A dialog you can Tab out of
 * leaves a keyboard user typing into a form they cannot see.
 */

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

function useOverlayBehaviour(open: boolean, onClose: () => void) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const restoreTo = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    if (!open) return;

    restoreTo.current = document.activeElement as HTMLElement | null;

    // Hold the page still. Padding compensates for the scrollbar that
    // `overflow: hidden` removes — without it the whole layout shifts sideways
    // the moment any dialog opens, which reads as the page jumping.
    const { body } = document;
    const prevOverflow = body.style.overflow;
    const prevPad = body.style.paddingRight;
    const gap = window.innerWidth - document.documentElement.clientWidth;
    body.style.overflow = "hidden";
    if (gap > 0) body.style.paddingRight = `${gap}px`;

    // Move focus in. Preference order: whatever asked for it, then the first
    // real control, then the panel itself — never leave it on the trigger
    // behind the scrim.
    const raf = requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const target =
        panel.querySelector<HTMLElement>("[data-autofocus]") ??
        panel.querySelector<HTMLElement>(FOCUSABLE) ??
        panel;
      target.focus();
    });

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      const panel = panelRef.current;
      if (!panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null
      );
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKeyDown, true);
      body.style.overflow = prevOverflow;
      body.style.paddingRight = prevPad;
      restoreTo.current?.focus?.();
    };
  }, [open, onClose]);

  return panelRef;
}

/** Portals only once mounted — `document` does not exist during SSR. */
function Portal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return createPortal(children, document.body);
}

const Scrim = ({ onClick }: { onClick: () => void }) => (
  <motion.div
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0 }}
    transition={{ duration: 0.18 }}
    onClick={onClick}
    className="fixed inset-0 z-50 bg-ink/35 backdrop-blur-[2px]"
  />
);

/* ── Dialog ──────────────────────────────────────────────────────────────── */

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  const panelRef = useOverlayBehaviour(open, onClose);
  const titleId = React.useId();
  const descId = React.useId();

  const width = { sm: "max-w-sm", md: "max-w-md", lg: "max-w-2xl" }[size];

  return (
    <Portal>
      <AnimatePresence>
        {open && (
          <>
            <Scrim onClick={onClose} />
            <div className="fixed inset-0 z-50 flex items-end justify-center overflow-y-auto p-0 sm:items-center sm:p-6">
              <motion.div
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-describedby={description ? descId : undefined}
                tabIndex={-1}
                initial={{ opacity: 0, y: 16, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.985 }}
                transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
                className={cn(
                  "relative w-full rounded-t-xl bg-surface shadow-pop outline-none sm:rounded-xl",
                  "border border-line",
                  width
                )}
              >
                <div className="flex items-start gap-4 px-6 pt-6">
                  <div className="min-w-0 flex-1">
                    <h2 id={titleId} className="text-h1 text-ink">
                      {title}
                    </h2>
                    {description && (
                      <p id={descId} className="mt-1.5 text-sm leading-relaxed text-muted">
                        {description}
                      </p>
                    )}
                  </div>
                  <IconButton
                    label="Close"
                    size="sm"
                    onClick={onClose}
                    className="-mr-1.5 -mt-1.5"
                  >
                    <X />
                  </IconButton>
                </div>

                {children && <div className="px-6 py-5">{children}</div>}

                {footer && (
                  <div className="flex flex-col-reverse gap-2 border-t border-line px-6 py-4 sm:flex-row sm:justify-end">
                    {footer}
                  </div>
                )}
              </motion.div>
            </div>
          </>
        )}
      </AnimatePresence>
    </Portal>
  );
}

/* ── Sheet ───────────────────────────────────────────────────────────────── */

/**
 * A side panel for detail without losing the list.
 *
 * This is what replaces the accordion the task board used to expand inline.
 * Expanding a row in place pushed every row below it off screen, so reading one
 * task's history meant losing the queue it belongs to — and the queue is the
 * reason the board exists. A sheet keeps both.
 *
 * Full width on mobile: a 520px panel on a 390px screen is a dialog with extra
 * steps.
 */
export function Sheet({
  open,
  onClose,
  title,
  eyebrow,
  children,
  footer,
  side = "right",
  width = "wide",
}: {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  eyebrow?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  side?: "right" | "left";
  width?: "narrow" | "wide";
}) {
  const panelRef = useOverlayBehaviour(open, onClose);
  const titleId = React.useId();

  const from = side === "right" ? "100%" : "-100%";

  return (
    <Portal>
      <AnimatePresence>
        {open && (
          <>
            <Scrim onClick={onClose} />
            <motion.div
              ref={panelRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby={title ? titleId : undefined}
              tabIndex={-1}
              initial={{ x: from }}
              animate={{ x: 0 }}
              exit={{ x: from }}
              transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
              className={cn(
                "fixed inset-y-0 z-50 flex w-full flex-col bg-surface shadow-pop outline-none",
                side === "right"
                  ? "right-0 border-l border-line"
                  : "left-0 border-r border-line",
                width === "wide" ? "sm:max-w-[46rem]" : "sm:max-w-md"
              )}
            >
              <div className="flex items-start gap-4 border-b border-line px-5 py-4 sm:px-6">
                <div className="min-w-0 flex-1">
                  {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
                  {title && (
                    <h2 id={titleId} className="text-h1 text-ink">
                      {title}
                    </h2>
                  )}
                </div>
                <IconButton label="Close" size="sm" onClick={onClose} className="-mr-1.5">
                  <X />
                </IconButton>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 sm:px-6">
                {children}
              </div>

              {footer && (
                <div className="flex items-center gap-2 border-t border-line bg-surface px-5 py-3.5 sm:px-6">
                  {footer}
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </Portal>
  );
}

/* ── Confirm ─────────────────────────────────────────────────────────────── */

/**
 * A destructive action, confirmed.
 *
 * Names the specific thing in the body rather than saying "this item", because
 * "Are you sure?" is answered yes by reflex and the only real safeguard is
 * seeing which repository is about to be unregistered.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Delete",
  busy,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  confirmLabel?: string;
  busy?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9.5 items-center justify-center rounded-pill border border-line px-4 text-sm font-medium text-ink transition-colors hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            data-autofocus
            onClick={onConfirm}
            disabled={busy}
            className="inline-flex h-9.5 items-center justify-center rounded-pill bg-danger px-4 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {confirmLabel}
          </button>
        </>
      }
    />
  );
}
