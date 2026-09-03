"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * A dropdown menu.
 *
 * Anchored rather than portalled: every use of it in this product sits in the
 * top bar or a panel header, neither of which clips, and keeping it in the tree
 * means it inherits the theme and needs no position measurement on scroll.
 *
 * Keyboard: Escape closes and returns focus to the trigger; ArrowDown/Up walk
 * the items; Home/End jump. A menu you can only click is a menu half the
 * product cannot use.
 */

interface MenuContext {
  open: boolean;
  setOpen: (v: boolean) => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

const Ctx = React.createContext<MenuContext | null>(null);

export function Menu({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const rootRef = React.useRef<HTMLDivElement>(null);

  // A click anywhere else closes it. `mousedown` rather than `click`, so the
  // menu is gone before the thing underneath receives the press — otherwise a
  // click on a button behind the menu both closes it and fires the button.
  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <Ctx.Provider value={{ open, setOpen, triggerRef }}>
      <div ref={rootRef} className="relative">
        {children}
      </div>
    </Ctx.Provider>
  );
}

function useMenu() {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("Menu parts must be used inside <Menu>");
  return ctx;
}

export function MenuTrigger({
  children,
  className,
  label,
}: {
  children: React.ReactNode;
  className?: string;
  label: string;
}) {
  const { open, setOpen, triggerRef } = useMenu();
  return (
    <button
      ref={triggerRef}
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={label}
      onClick={() => setOpen(!open)}
      className={className}
    >
      {children}
    </button>
  );
}

export function MenuContent({
  children,
  align = "end",
  className,
  width = "w-56",
}: {
  children: React.ReactNode;
  align?: "start" | "end";
  className?: string;
  width?: string;
}) {
  const { open, setOpen, triggerRef } = useMenu();
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;

    const items = () =>
      Array.from(
        listRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ??
          []
      );

    const onKey = (e: KeyboardEvent) => {
      const list = items();
      if (list.length === 0) return;
      const i = list.indexOf(document.activeElement as HTMLElement);

      switch (e.key) {
        case "Escape":
          e.preventDefault();
          setOpen(false);
          triggerRef.current?.focus();
          break;
        case "ArrowDown":
          e.preventDefault();
          list[(i + 1) % list.length]?.focus();
          break;
        case "ArrowUp":
          e.preventDefault();
          list[i <= 0 ? list.length - 1 : i - 1]?.focus();
          break;
        case "Home":
          e.preventDefault();
          list[0]?.focus();
          break;
        case "End":
          e.preventDefault();
          list[list.length - 1]?.focus();
          break;
      }
    };

    const raf = requestAnimationFrame(() => items()[0]?.focus());
    document.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, setOpen, triggerRef]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={listRef}
          role="menu"
          initial={{ opacity: 0, y: -4, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -4, scale: 0.98 }}
          transition={{ duration: 0.14, ease: [0.32, 0.72, 0, 1] }}
          className={cn(
            "absolute top-[calc(100%+8px)] z-40 overflow-hidden rounded-lg border border-line bg-surface p-1.5 shadow-pop",
            align === "end" ? "right-0" : "left-0",
            width,
            className
          )}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function MenuItem({
  children,
  onSelect,
  icon,
  tone = "default",
  disabled,
  shortcut,
}: {
  children: React.ReactNode;
  onSelect: () => void;
  icon?: React.ReactNode;
  tone?: "default" | "danger";
  disabled?: boolean;
  shortcut?: string;
}) {
  const { setOpen } = useMenu();
  return (
    <button
      role="menuitem"
      type="button"
      disabled={disabled}
      onClick={() => {
        setOpen(false);
        onSelect();
      }}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors",
        "[&_svg]:size-4 [&_svg]:shrink-0",
        "disabled:pointer-events-none disabled:opacity-45",
        tone === "danger"
          ? "text-danger hover:bg-danger-soft"
          : "text-ink hover:bg-surface-2"
      )}
    >
      {icon && <span className="text-subtle">{icon}</span>}
      <span className="flex-1 truncate">{children}</span>
      {shortcut && <span className="font-mono text-xs text-subtle">{shortcut}</span>}
    </button>
  );
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pb-1.5 pt-2 text-label uppercase text-subtle">{children}</p>
  );
}

export function MenuSeparator() {
  return <div role="separator" className="my-1.5 h-px bg-line" />;
}
