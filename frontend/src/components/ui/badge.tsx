"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Badges, chips and status dots.
 *
 * Three shapes, and the distinction is what they are *for* — not how they look:
 *
 *   Badge  — a state the system is reporting. "Approved", "critical", "p1".
 *   Chip   — a fact attached to a thing. A repo name, a branch, a doc count.
 *   Dot    — a state small enough to sit inside a sentence or before a label.
 *
 * The surface this replaces had all three rendered as `rounded bg-muted px-1.5
 * text-[10px]`, which meant a severity, a repository name and a round counter
 * were visually identical and none of them were readable.
 */

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-pill border font-medium whitespace-nowrap [&_svg]:size-3.5 [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "border-line bg-surface-2 text-muted",
        solid: "border-transparent bg-primary text-primary-fg",
        accent: "border-accent/35 bg-accent-soft text-accent-strong",
        success: "border-success-border bg-success-soft text-success",
        warning: "border-warning-border bg-warning-soft text-warning",
        danger: "border-danger-border bg-danger-soft text-danger",
        info: "border-info-border bg-info-soft text-info",
        outline: "border-line-strong bg-transparent text-muted",
      },
      size: {
        sm: "px-2 py-0.5 text-xs",
        md: "px-2.5 py-1 text-xs",
      },
    },
    defaultVariants: { tone: "neutral", size: "sm" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone, size }), className)} {...props} />;
}

/**
 * A fact attached to a thing.
 *
 * Monospace by default, because nearly every one of these is an identifier a
 * person may need to copy or match by eye: `acme/api#412`, `feat/retry-gate`,
 * `PROJ-1183`.
 */
export function Chip({
  children,
  icon,
  className,
  mono = true,
  title,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-pill border border-line bg-surface-2 px-2.5 py-0.5 text-xs text-muted",
        "[&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-subtle",
        mono && "font-mono",
        className
      )}
    >
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}

const DOT_TONE = {
  neutral: "bg-subtle",
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
} as const;

export type DotTone = keyof typeof DOT_TONE;

/**
 * A state, as a dot.
 *
 * `pulse` is reserved for something genuinely in motion right now — a running
 * job, a live connection. A decorative pulse on a static state is how an
 * interface teaches people to ignore movement.
 */
export function Dot({
  tone = "neutral",
  pulse,
  className,
}: {
  tone?: DotTone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("relative flex size-2 shrink-0", className)} aria-hidden>
      {pulse && (
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-pill opacity-60",
            DOT_TONE[tone]
          )}
        />
      )}
      <span
        className={cn("relative inline-flex size-2 rounded-pill", DOT_TONE[tone])}
      />
    </span>
  );
}

/** A dot and a label, as one unit. The common case for a connection status. */
export function StatusDot({
  tone = "neutral",
  pulse,
  children,
  className,
}: {
  tone?: DotTone;
  pulse?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs text-muted", className)}>
      <Dot tone={tone} pulse={pulse} />
      {children}
    </span>
  );
}

export { badgeVariants };
