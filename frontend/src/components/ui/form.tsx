"use client";

import * as React from "react";
import { Check, ChevronDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Form primitives.
 *
 * One control shape, one focus treatment, one way of attaching a label, a hint
 * and an error. The surface this replaces had inputs written inline in six
 * files with six different border/ring/padding combinations, and a `Checkbox`
 * that held its own state and so could not be controlled at all.
 */

/* ── Field ────────────────────────────────────────────────────────────────
   The label/hint/error wrapper. `htmlFor` is threaded through by the caller
   rather than generated, because most of these inputs already have ids that
   other code depends on. The hint is wired with `aria-describedby` at the
   call site via the `describedBy` helper below. */

export function Field({
  label,
  hint,
  error,
  htmlFor,
  required,
  className,
  children,
}: {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  htmlFor?: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <label
          htmlFor={htmlFor}
          className="block text-sm font-medium text-ink"
        >
          {label}
          {required && (
            <span className="ml-1 text-danger" aria-hidden>
              *
            </span>
          )}
        </label>
      )}
      {children}
      {/* The error replaces the hint rather than stacking beneath it: two
          lines of guidance under one input is where forms start to feel
          cluttered, and the error is always the more urgent of the two. */}
      {error ? (
        <p id={htmlFor ? `${htmlFor}-msg` : undefined} className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={htmlFor ? `${htmlFor}-msg` : undefined} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** The id a Field's hint or error is published under, for `aria-describedby`. */
export const describedBy = (id?: string) => (id ? `${id}-msg` : undefined);

/* ── Text inputs ─────────────────────────────────────────────────────────── */

const controlBase = [
  "w-full rounded-md border bg-surface text-ink",
  "placeholder:text-subtle",
  "transition-[border-color,box-shadow] duration-[--dur-fast] ease-[--ease]",
  "hover:border-line-strong",
  "focus-visible:outline-none focus-visible:border-accent",
  "focus-visible:ring-[3px] focus-visible:ring-accent/25",
  "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-surface-2",
].join(" ");

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  /** Rendered inside the control on the leading edge, e.g. a search glyph. */
  icon?: React.ReactNode;
  inputSize?: "sm" | "md" | "lg";
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, invalid, icon, inputSize = "md", ...props }, ref) => {
    const height =
      inputSize === "sm" ? "h-8 text-xs" : inputSize === "lg" ? "h-12 text-body" : "h-9.5 text-sm";

    const control = (
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          controlBase,
          height,
          "px-3",
          icon && "pl-9",
          invalid && "border-danger focus-visible:border-danger focus-visible:ring-danger/25",
          className
        )}
        {...props}
      />
    );

    if (!icon) return control;

    return (
      <div className="relative">
        <span
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle [&_svg]:size-4"
          aria-hidden
        >
          {icon}
        </span>
        {control}
      </div>
    );
  }
);
Input.displayName = "Input";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
  /** Monospace, for the line-oriented config fields (doc urls, column maps). */
  mono?: boolean;
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid, mono, ...props }, ref) => (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        controlBase,
        "min-h-20 resize-y px-3 py-2.5",
        mono ? "font-mono text-xs leading-relaxed" : "text-sm",
        invalid && "border-danger focus-visible:border-danger focus-visible:ring-danger/25",
        className
      )}
      {...props}
    />
  )
);
Textarea.displayName = "Textarea";

/* ── Select ───────────────────────────────────────────────────────────────
   A styled native <select>. A custom listbox would need focus trapping, type-
   ahead and touch handling to match what the platform already does correctly;
   the only thing wrong with the native control is its chrome, so only the
   chrome is replaced. */

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  selectSize?: "sm" | "md";
}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, selectSize = "md", ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          controlBase,
          "cursor-pointer appearance-none pr-9",
          selectSize === "sm" ? "h-8 px-2.5 text-xs" : "h-9.5 px-3 text-sm",
          className
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle"
        aria-hidden
      />
    </div>
  )
);
Select.displayName = "Select";

/* ── Checkbox ─────────────────────────────────────────────────────────────
   Fully controlled. The version this replaces kept `checked` in its own
   `useState` and ignored the prop entirely, so the "remember me" box on the
   login page could be ticked visually while the form read `false`. */

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  onCheckedChange?: (checked: boolean) => void;
  indeterminate?: boolean;
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, onCheckedChange, onChange, indeterminate, checked, ...props }, ref) => (
    <span className="relative inline-flex size-[18px] shrink-0 items-center justify-center">
      <input
        ref={ref}
        type="checkbox"
        checked={checked}
        onChange={(e) => {
          onChange?.(e);
          onCheckedChange?.(e.target.checked);
        }}
        className="peer absolute inset-0 z-10 m-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        {...props}
      />
      <span
        aria-hidden
        className={cn(
          "pointer-events-none flex size-[18px] items-center justify-center rounded-[6px] border border-line-strong bg-surface text-primary-fg",
          "transition-colors duration-[--dur-fast]",
          "peer-hover:border-accent",
          "peer-checked:border-primary peer-checked:bg-primary",
          "peer-focus-visible:ring-[3px] peer-focus-visible:ring-accent/30",
          "peer-disabled:opacity-50",
          // The glyph is a descendant of this span, not a sibling of the
          // input, so `peer-checked:` has to be applied here and reach down
          // into it. Writing it on the icon itself silently does nothing.
          "[&>svg]:scale-50 [&>svg]:opacity-0 [&>svg]:transition",
          "peer-checked:[&>svg]:scale-100 peer-checked:[&>svg]:opacity-100",
          // Indeterminate is a third state, not "unchecked": it has to paint
          // whatever the input's own checked value happens to be.
          indeterminate &&
            "border-primary bg-primary [&>svg]:scale-100 [&>svg]:opacity-100",
          className
        )}
      >
        {indeterminate ? (
          <Minus className="size-3" strokeWidth={3} />
        ) : (
          <Check className="size-3" strokeWidth={3.5} />
        )}
      </span>
    </span>
  )
);
Checkbox.displayName = "Checkbox";

/**
 * A checkbox with its label and explanation, as one clickable row.
 *
 * Most of the settings in this product are a boolean plus a paragraph saying
 * what it costs. Writing that inline every time is how the settings form ended
 * up with four different arrangements of the same two elements.
 */
export function CheckboxRow({
  id,
  label,
  hint,
  checked,
  onCheckedChange,
  disabled,
  children,
}: {
  id: string;
  label: React.ReactNode;
  hint?: React.ReactNode;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
  /** Trailing control on the label row, e.g. the merge-method select. */
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("flex gap-3", disabled && "opacity-60")}>
      <span className="mt-0.5">
        <Checkbox
          id={id}
          checked={checked}
          disabled={disabled}
          aria-describedby={hint ? `${id}-hint` : undefined}
          onCheckedChange={onCheckedChange}
        />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor={id}
            className={cn(
              "text-sm font-medium text-ink",
              !disabled && "cursor-pointer"
            )}
          >
            {label}
          </label>
          {children}
        </div>
        {hint && (
          <p id={`${id}-hint`} className="mt-1 text-xs leading-relaxed text-muted">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Switch ───────────────────────────────────────────────────────────────
   For settings that take effect immediately. A checkbox is for something you
   confirm with a Save; a switch is for something already done by the time you
   let go — the theme toggle, not a form field. */

export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
  id,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-pill border transition-colors duration-[--dur] ease-[--ease]",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "border-primary bg-primary" : "border-line-strong bg-surface-2"
      )}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none block size-4.5 rounded-pill bg-surface shadow-sm transition-transform duration-[--dur] ease-[--ease]",
          checked ? "translate-x-[22px]" : "translate-x-[3px]"
        )}
      />
    </button>
  );
}

export { Input, Textarea, Select, Checkbox };
