"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  Check,
  FileSearch,
  GitMerge,
  GitPullRequest,
  MessagesSquare,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The pipeline, running.
 *
 * The hero animation is the product doing its job rather than a decoration
 * beside it. A ticket arrives, context is gathered, the diff is scanned, a
 * reviewer answers, the testing team signs off — the same nine stages the board
 * renders, advancing on a timer, with each step writing a line into the log
 * beside it.
 *
 * Three rules hold it together:
 *
 * It only runs when it is on screen. An `IntersectionObserver` pauses the timer
 * once the hero scrolls away, so a landing page left open in a background tab
 * is not animating a component nobody is looking at.
 *
 * It stops entirely for `prefers-reduced-motion`, showing the finished state.
 * A "calmer" version that still moved would be answering a request not to move
 * with a smaller amount of moving.
 *
 * And nothing here is a number. A hero that counts up to "12,000 pull requests
 * reviewed" is inventing a metric; this shows the mechanism, which is true.
 *
 * **The panel's height never changes, and that is the fourth rule.** The log
 * used to mount each line as the step landed and unmount all seven when the
 * cycle wrapped, which grew and collapsed the panel by ~540px every twenty
 * seconds. The hero section is sized by this panel, and `HeroScene` is
 * `absolute inset-0` inside it drawing with `preserveAspectRatio="slice"` — so
 * a panel that changes height rescales and re-crops the painting behind it,
 * which is what read as the background zooming and jumping on its own. Every
 * step is therefore always in the DOM and reserves its space; the unreached
 * ones are drawn at `opacity: 0`. Nothing animates layout, so nothing above or
 * behind it reflows.
 */

interface Step {
  label: string;
  detail: string;
  icon: typeof Check;
  /** Milliseconds to hold on this step before moving to the next. */
  hold: number;
}

const STEPS: Step[] = [
  {
    label: "Ticket assigned",
    detail: "PROJ-1183 landed on you",
    icon: GitPullRequest,
    hold: 1400,
  },
  {
    label: "Context gathered",
    detail: "1 issue · 1 ticket · 1 Slack thread",
    icon: FileSearch,
    hold: 2000,
  },
  {
    label: "Scanned and reviewed",
    detail: "1 confirmed · 1 possible · 2 review notes",
    icon: ShieldCheck,
    hold: 2200,
  },
  {
    label: "Review requested",
    detail: "@priya pinged in #code-review",
    icon: UserCheck,
    hold: 1800,
  },
  {
    label: "Changes requested",
    detail: "round 2 — the sweep needs a ceiling",
    icon: MessagesSquare,
    hold: 2000,
  },
  {
    label: "Merged",
    detail: "squashed into main, CI green",
    icon: GitMerge,
    hold: 1600,
  },
  {
    label: "Testing signed off",
    detail: "qa@acme.com replied: works",
    icon: Check,
    hold: 2600,
  },
];

const EASE = [0.32, 0.72, 0, 1] as const;

export function HeroDemo() {
  const still = useReducedMotion();
  const [active, setActive] = useState(still ? STEPS.length - 1 : 0);
  const [visible, setVisible] = useState(true);
  const hostRef = useRef<HTMLDivElement>(null);

  // Off screen, the timer stops. Left running, this would keep re-rendering a
  // component nobody can see for as long as the tab is open.
  useEffect(() => {
    const node = hostRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { threshold: 0.15 }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (still || !visible) return;
    const timer = setTimeout(
      () => setActive((i) => (i + 1) % STEPS.length),
      STEPS[active].hold
    );
    return () => clearTimeout(timer);
  }, [active, still, visible]);

  return (
    <div ref={hostRef} className="relative">
      {/* The glow tracks the panel rather than the page, so the whole thing
          reads as one object sitting slightly above the ground. */}
      <div
        aria-hidden
        className="absolute -inset-x-8 -bottom-8 -top-4 -z-10 rounded-[2rem] bg-[radial-gradient(60%_60%_at_50%_40%,var(--accent-soft),transparent_75%)] blur-2xl"
      />

      <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-md">
        {/* ── Chrome ─────────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2.5 border-b border-line bg-surface-2/60 px-4 py-3 sm:px-5">
          <span className="flex gap-1.5" aria-hidden>
            <span className="size-2.5 rounded-pill bg-line-strong" />
            <span className="size-2.5 rounded-pill bg-line-strong" />
            <span className="size-2.5 rounded-pill bg-line-strong" />
          </span>
          <span className="ml-1.5 font-mono text-xs font-medium text-ink">
            PROJ-1183
          </span>
          <span className="hidden truncate text-xs text-muted sm:inline">
            Retry the merge gate when GitHub reports mergeable: null
          </span>

          <span className="ml-auto flex items-center gap-2">
            <span
              className={cn(
                "size-1.5 rounded-pill",
                active === STEPS.length - 1 ? "bg-success" : "bg-accent",
                !still && "animate-pulse"
              )}
              aria-hidden
            />
            <span className="text-xs font-medium text-muted">
              {active === STEPS.length - 1 ? "Done" : "Running"}
            </span>
          </span>
        </div>

        <div className="grid gap-0 md:grid-cols-[1fr_minmax(0,20rem)]">
          {/* ── The log ─────────────────────────────────────────────────── */}
          <div
            className="border-b border-line p-4 sm:p-5 md:border-b-0 md:border-r"
            // The list rewrites itself on a timer; a screen reader announcing
            // each line as it lands would talk over the page indefinitely.
            aria-hidden
          >
            <ol className="space-y-2.5">
              {STEPS.map((step, i) => {
                const Icon = step.icon;
                const current = i === active;
                const reached = i <= active;
                return (
                  <motion.li
                    key={step.label}
                    // Opacity and a transform only. A line that has not landed
                    // yet still occupies its row, so the panel — and with it
                    // the hero and the painting behind it — never resizes.
                    initial={false}
                    animate={
                      still
                        ? { opacity: 1, x: 0 }
                        : { opacity: reached ? 1 : 0, x: reached ? 0 : -12 }
                    }
                    transition={{ duration: 0.45, ease: EASE }}
                    className={cn(
                      "flex items-start gap-3 rounded-md border px-3 py-2.5 transition-colors",
                      current
                        ? "border-accent/40 bg-accent-soft"
                        : "border-transparent bg-surface-2/50"
                    )}
                  >
                    <span
                      className={cn(
                        "mt-px flex size-6 shrink-0 items-center justify-center rounded-pill",
                        current
                          ? "bg-accent text-accent-fg"
                          : "bg-success/15 text-success"
                      )}
                    >
                      {current ? (
                        <Icon className="size-3.5" />
                      ) : (
                        <Check className="size-3.5" strokeWidth={3} />
                      )}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-ink">
                        {step.label}
                      </span>
                      <span className="block truncate text-xs text-muted">
                        {step.detail}
                      </span>
                    </span>
                  </motion.li>
                );
              })}
            </ol>
          </div>

          {/* ── The rail ────────────────────────────────────────────────── */}
          <div className="p-4 sm:p-5">
            <p className="text-label uppercase text-subtle">Pipeline</p>
            <ol className="mt-3 space-y-0" aria-hidden>
              {STEPS.map((step, i) => {
                const reached = i <= active;
                const current = i === active;
                const isLast = i === STEPS.length - 1;
                return (
                  <li key={step.label} className="flex gap-3">
                    <span className="flex flex-col items-center">
                      <motion.span
                        animate={{ scale: current && !still ? [1, 1.18, 1] : 1 }}
                        transition={{ duration: 0.5, ease: EASE }}
                        className={cn(
                          "flex size-4 shrink-0 items-center justify-center rounded-pill border transition-colors duration-300",
                          reached
                            ? current
                              ? "border-accent bg-accent"
                              : "border-success bg-success"
                            : "border-line bg-surface"
                        )}
                      >
                        {reached && !current && (
                          <Check
                            className="size-2.5 text-white"
                            strokeWidth={4}
                          />
                        )}
                      </motion.span>
                      {!isLast && (
                        <span className="relative my-0.5 h-6 w-px bg-line">
                          {/* The connector fills as the step completes, so the
                              rail reads as a level rather than a row of dots
                              turning on independently. */}
                          <motion.span
                            className="absolute inset-x-0 top-0 bg-success"
                            initial={false}
                            animate={{ height: i < active ? "100%" : "0%" }}
                            transition={{ duration: 0.4, ease: EASE }}
                          />
                        </span>
                      )}
                    </span>
                    <span
                      className={cn(
                        "pb-1 text-xs transition-colors duration-300",
                        current
                          ? "font-medium text-ink"
                          : reached
                            ? "text-muted"
                            : "text-subtle"
                      )}
                    >
                      {step.label}
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
