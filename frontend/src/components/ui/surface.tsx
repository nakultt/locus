"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Containers, and the states a container can be in.
 *
 * The rule this file exists to enforce: a panel is a *surface*, not a
 * decoration. Wrapping a paragraph in a bordered box does not group it with
 * anything — it just draws a line. So `Section` (a heading and its content,
 * flat on the page) is the default, and `Panel` is reserved for content that
 * genuinely needs to be lifted off the ground: a form, a list of rows, a
 * summary. Nesting a Panel inside a Panel is not supported, deliberately.
 */

/* ── Section ─────────────────────────────────────────────────────────────── */

export function Section({
  title,
  description,
  actions,
  children,
  className,
  id,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn("space-y-4", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 space-y-1">
            {title && <h2 className="text-h2 text-ink">{title}</h2>}
            {description && (
              <p className="max-w-prose text-sm text-muted">{description}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** A small all-caps kicker over a group. Replaces the ad-hoc uppercase spans. */
export function Kicker({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p className={cn("text-label uppercase text-subtle", className)}>{children}</p>
  );
}

/* ── Panel ───────────────────────────────────────────────────────────────── */

export function Panel({
  children,
  className,
  tone = "default",
  as: Tag = "div",
  ...rest
}: {
  children: React.ReactNode;
  className?: string;
  /** A tinted panel states its own severity without needing an icon to say it. */
  tone?: "default" | "quiet" | "accent" | "success" | "warning" | "danger" | "info";
  as?: React.ElementType;
} & React.HTMLAttributes<HTMLElement>) {
  const tones = {
    default: "border-line bg-surface",
    quiet: "border-line bg-surface-2",
    accent: "border-accent/35 bg-accent-soft",
    success: "border-success-border bg-success-soft",
    warning: "border-warning-border bg-warning-soft",
    danger: "border-danger-border bg-danger-soft",
    info: "border-info-border bg-info-soft",
  } as const;

  return (
    <Tag className={cn("rounded-lg border", tones[tone], className)} {...rest}>
      {children}
    </Tag>
  );
}

/** A padded panel header with a bottom rule. For panels containing a list. */
export function PanelHeader({
  title,
  description,
  icon,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-5 py-4",
        className
      )}
    >
      {icon && (
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-surface-2 text-muted [&_svg]:size-4">
          {icon}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h3 className="text-h3 text-ink">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ── Empty state ─────────────────────────────────────────────────────────── */

/**
 * What an empty surface says.
 *
 * Never just "no results". Every empty state here has to answer two questions —
 * why is this empty, and what would fill it — because the alternative reads as
 * a failed fetch. The dashed border is what distinguishes "nothing here yet"
 * from "here is a thing".
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  compact,
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-line-strong bg-surface-2/40 text-center",
        compact ? "px-6 py-8" : "px-6 py-14",
        className
      )}
    >
      {icon && (
        <span
          className="mb-3 flex size-11 items-center justify-center rounded-pill border border-line bg-surface text-subtle [&_svg]:size-5"
          aria-hidden
        >
          {icon}
        </span>
      )}
      <p className="text-h3 text-ink">{title}</p>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ── Loading ─────────────────────────────────────────────────────────────── */

/**
 * A skeleton, not a spinner.
 *
 * A spinner says "wait"; a skeleton says "wait, and here is the shape of what
 * is coming", which stops the layout jumping when it arrives. Spinners are
 * kept for actions in progress inside a button, where the shape is known.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface-3", className)}
    />
  );
}

/** The board's loading shape: a stack of task rows. */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="rounded-lg border border-line bg-surface p-5">
          <div className="flex items-center gap-2">
            <Skeleton className="h-5 w-16 rounded-pill" />
            <Skeleton className="h-5 w-24 rounded-pill" />
          </div>
          <Skeleton className="mt-3 h-4 w-2/3" />
          <Skeleton className="mt-3 h-6 w-full max-w-md rounded-pill" />
        </div>
      ))}
    </div>
  );
}

/* ── Separator ───────────────────────────────────────────────────────────── */

export function Separator({
  className,
  label,
}: {
  className?: string;
  label?: string;
}) {
  if (label) {
    return (
      <div className={cn("flex items-center gap-3", className)} role="separator">
        <span className="h-px flex-1 bg-line" />
        <span className="text-label uppercase text-subtle">{label}</span>
        <span className="h-px flex-1 bg-line" />
      </div>
    );
  }
  return <div role="separator" className={cn("h-px w-full bg-line", className)} />;
}

/* ── Inline notice ───────────────────────────────────────────────────────── */

/**
 * A message about the state of the page, not about an action.
 *
 * Distinct from a toast: a toast is transient and reports what just happened;
 * a notice is persistent and reports a condition — "Jira did not answer", "the
 * settings on screen are not the settings that will run".
 */
export function Notice({
  tone = "info",
  icon,
  title,
  children,
  action,
  className,
}: {
  tone?: "info" | "success" | "warning" | "danger" | "accent";
  icon?: React.ReactNode;
  title?: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-info-border bg-info-soft [&_.notice-icon]:text-info",
    success: "border-success-border bg-success-soft [&_.notice-icon]:text-success",
    warning: "border-warning-border bg-warning-soft [&_.notice-icon]:text-warning",
    danger: "border-danger-border bg-danger-soft [&_.notice-icon]:text-danger",
    accent: "border-accent/35 bg-accent-soft [&_.notice-icon]:text-accent-strong",
  } as const;

  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-md border px-4 py-3",
        tones[tone],
        className
      )}
    >
      {icon && (
        <span className="notice-icon mt-px shrink-0 [&_svg]:size-4" aria-hidden>
          {icon}
        </span>
      )}
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="text-sm font-medium text-ink">{title}</p>}
        {children && (
          <div className="text-xs leading-relaxed text-muted [&_strong]:text-ink">
            {children}
          </div>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
