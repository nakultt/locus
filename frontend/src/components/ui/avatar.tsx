"use client";

import { cn } from "@/lib/utils";

/**
 * An identity mark.
 *
 * No image: this product has no avatar upload, and a generic silhouette says
 * nothing a person's own initials do not say better. The tint is derived from
 * the name so the same person is the same colour on every screen — it is
 * recognisable at a glance in a way a uniform grey circle is not.
 */

const TINTS = [
  "bg-accent-soft text-accent-strong",
  "bg-info-soft text-info",
  "bg-success-soft text-success",
  "bg-warning-soft text-warning",
  "bg-danger-soft text-danger",
] as const;

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Stable across reloads and across machines — a hash, not a random pick. */
function tintFor(seed: string) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return TINTS[Math.abs(h) % TINTS.length];
}

export function Avatar({
  name,
  email,
  size = "md",
  className,
}: {
  name?: string | null;
  email?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const label = name?.trim() || email?.split("@")[0] || "Account";
  const dims = {
    sm: "size-7 text-xs",
    md: "size-8.5 text-xs",
    lg: "size-12 text-sm",
  }[size];

  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-pill font-semibold",
        tintFor(email || label),
        dims,
        className
      )}
    >
      {initials(label)}
    </span>
  );
}
