"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Buttons.
 *
 * Every control in the product is a pill. That is the one shape decision the
 * reference material makes most consistently, and it only reads as intentional
 * if nothing opts out — a single `rounded-md` button next to pills looks like
 * a bug rather than a variant.
 *
 * `primary` is ink (cream in dark), not the accent. A dense screen with six
 * sand-coloured buttons has no primary action at all; spending the accent on
 * identity and state instead leaves the loudest control unambiguous.
 */
const buttonVariants = cva(
  [
    "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap",
    "rounded-pill font-medium",
    "transition-[background-color,border-color,color,box-shadow,transform] duration-[--dur-fast] ease-[--ease]",
    "active:scale-[0.98]",
    "disabled:pointer-events-none disabled:opacity-45",
    // The ring is defined once in globals.css and reached through
    // :focus-visible, so a pointer click never paints it and a tab always does.
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    "[&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-fg hover:bg-primary-hover",
        accent: "bg-accent text-accent-fg hover:bg-accent-hover",
        secondary:
          "bg-surface text-ink border border-line hover:bg-surface-2 hover:border-line-strong",
        ghost: "text-muted hover:bg-surface-2 hover:text-ink",
        danger: "bg-danger text-white hover:opacity-90",
        // Quiet destructive: reads as available, not as a dare. The loud
        // `danger` fill is reserved for the confirm inside a dialog.
        "danger-ghost":
          "text-muted hover:bg-danger-soft hover:text-danger",
        link: "text-accent-strong underline-offset-4 hover:underline px-0 h-auto rounded-xs",
      },
      size: {
        sm: "h-8 px-3 text-xs [&_svg]:size-[15px]",
        md: "h-9.5 px-4 text-sm [&_svg]:size-4",
        lg: "h-11 px-6 text-body [&_svg]:size-[18px]",
        xl: "h-13 px-7 text-body [&_svg]:size-5",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Swaps the leading icon for a spinner and blocks input. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, loading, children, disabled, ...props },
    ref
  ) => {
    // `asChild` merges these props onto the caller's own element — a `<Link>`,
    // an `<a>` — and Radix's Slot requires exactly one child to merge onto.
    // Injecting a spinner beside `children` gives it two, which fails at
    // render with "Slot failed to slot onto its children". Nothing in the
    // product renders a loading anchor, so the spinner is simply not offered
    // in that mode rather than reached for with `Slottable`.
    if (asChild) {
      return (
        <Slot
          className={cn(buttonVariants({ variant, size }), className)}
          ref={ref}
          {...props}
        >
          {children}
        </Slot>
      );
    }

    // A spinner *appended* to the label would reflow it mid-click. Rendering
    // it in the leading slot keeps the button the same width and the label in
    // the same place, so a slow save does not move the thing being clicked.
    return (
      <button
        className={cn(buttonVariants({ variant, size }), className)}
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? <Loader2 className="animate-spin" aria-hidden /> : null}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

export interface IconButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Required: an icon alone tells a screen reader nothing. */
  label: string;
}

/**
 * A square control carrying one icon.
 *
 * The label is a required prop rather than an optional `aria-label`, because
 * the version of this that was optional shipped six unlabelled buttons.
 */
const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, variant = "ghost", size = "md", label, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        buttonVariants({ variant, size }),
        "px-0",
        size === "sm" ? "size-8" : size === "lg" ? "size-11" : "size-9.5",
        className
      )}
      {...props}
    />
  )
);
IconButton.displayName = "IconButton";

export { Button, IconButton, buttonVariants };
