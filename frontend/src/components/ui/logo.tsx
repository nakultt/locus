import { cn } from "@/lib/utils";

/**
 * The mark and the wordmark.
 *
 * Drawn rather than served from `/public`. The old header loaded a PNG at 24px,
 * which was soft on every retina screen and could not follow the theme — it was
 * a dark glyph on a dark surface the moment anyone switched. This is a few
 * paths, it is sharp at any size, and `currentColor` means it is correct in
 * both themes for free.
 *
 * The shape: a locus is the set of points satisfying a condition — a ring, and
 * the one point on it that the work has reached.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className={cn("size-6", className)}
    >
      <circle
        cx="12"
        cy="12"
        r="8.25"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeDasharray="3.4 3.6"
        opacity="0.45"
      />
      <circle cx="12" cy="12" r="3.4" stroke="currentColor" strokeWidth="1.75" />
      <circle cx="18.6" cy="6" r="2.6" fill="var(--accent)" />
    </svg>
  );
}

export function Wordmark({
  className,
  markClassName,
}: {
  className?: string;
  markClassName?: string;
}) {
  return (
    // The colour is set once, on the wrapper, and both halves inherit it —
    // `LogoMark` strokes in `currentColor`. Pinning `text-ink` on the children
    // instead made the wordmark unusable anywhere the ground is not the page:
    // a caller's `text-on-art` landed on the wrapper and lost to the child's
    // own class, so the brand stayed near-black over the hero artwork.
    <span className={cn("inline-flex items-center gap-2 text-ink", className)}>
      <LogoMark className={cn("size-6", markClassName)} />
      {/* Serif, and the only serif in the product. It is what keeps the brand
          from reading as another label in the interface. */}
      <span className="font-serif text-[1.375rem] leading-none tracking-tight">
        Locus
      </span>
    </span>
  );
}
