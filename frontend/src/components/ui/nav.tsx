"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * Tabs and segmented controls.
 *
 * They look similar and mean different things, so both exist:
 *
 *   Tabs      — switch between views of *different* content. Underline, sits on
 *               a rule, reads as navigation.
 *   Segmented — filter or change the shape of the *same* content. A pill inside
 *               a track, reads as a control.
 *
 * Both move a shared `layoutId` indicator rather than toggling a border, so the
 * active marker travels between options instead of blinking out and in. It is a
 * small thing that does a lot of the work of making an interface feel built.
 */

export interface TabItem<T extends string> {
  value: T;
  label: React.ReactNode;
  count?: number;
  icon?: React.ReactNode;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
  ariaLabel,
}: {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
  ariaLabel: string;
}) {
  const id = React.useId();

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn("scroll-x flex gap-1 border-b border-line", className)}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              "relative flex shrink-0 items-center gap-2 px-3.5 py-2.5 text-sm font-medium transition-colors",
              "[&_svg]:size-4",
              active ? "text-ink" : "text-muted hover:text-ink"
            )}
          >
            {item.icon}
            {item.label}
            {typeof item.count === "number" && item.count > 0 && (
              <span
                className={cn(
                  "tabular rounded-pill px-1.5 py-0.5 text-xs",
                  active ? "bg-accent-soft text-accent-strong" : "bg-surface-2 text-muted"
                )}
              >
                {item.count}
              </span>
            )}
            {active && (
              <motion.span
                layoutId={`tab-${id}`}
                transition={{ duration: 0.24, ease: [0.32, 0.72, 0, 1] }}
                className="absolute inset-x-1 -bottom-px h-0.5 rounded-pill bg-primary"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

export function Segmented<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  size = "md",
  className,
}: {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const id = React.useId();

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        // `max-w-full` + `scroll-x` rather than wrapping: a segmented control
        // that breaks a label onto two lines stops reading as one track, and
        // four options genuinely do not fit across a 390px screen.
        "scroll-x inline-flex max-w-full items-center gap-0.5 rounded-pill border border-line bg-surface-2 p-1",
        className
      )}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(item.value)}
            className={cn(
              "relative flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-pill font-medium transition-colors",
              "[&_svg]:size-3.5",
              size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm",
              active ? "text-ink" : "text-muted hover:text-ink"
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                transition={{ duration: 0.24, ease: [0.32, 0.72, 0, 1] }}
                className="absolute inset-0 rounded-pill bg-surface shadow-sm"
              />
            )}
            <span className="relative flex items-center gap-1.5">
              {item.icon}
              {item.label}
              {typeof item.count === "number" && (
                <span className="tabular text-subtle">{item.count}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
