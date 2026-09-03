"use client";

import Link from "next/link";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { Wordmark } from "@/components/ui/logo";

/**
 * The chrome around signing in and signing up.
 *
 * A split, with the form on the left and one concrete claim on the right. What
 * it replaces was ~500 lines of cartoon characters that tracked the cursor,
 * blinked on a timer, leaned toward the pointer and covered their eyes while
 * you typed a password — measuring their own DOM nodes during render to do it,
 * which the file already carried an eslint suppression for.
 *
 * The right panel is hidden below `lg` rather than stacked. On a phone the
 * only thing anyone wants from this screen is the form; scrolling past a
 * marketing panel to reach it is a tax on the person who already decided.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_minmax(0,34rem)]">
      {/* ── Form ────────────────────────────────────────────────────────── */}
      <div className="flex flex-col px-5 py-8 sm:px-10">
        <div className="flex items-center justify-between">
          <Link href="/" aria-label="Locus home">
            <Wordmark />
          </Link>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-sm text-muted transition-colors hover:text-ink"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            Back
          </Link>
        </div>

        <div className="flex flex-1 items-center justify-center py-12">
          <div className="w-full max-w-sm">
            <h1 className="text-balance text-[2rem] leading-[1.1] tracking-[-0.028em] text-ink">
              {title}
            </h1>
            <p className="mt-2.5 text-sm leading-relaxed text-muted">{subtitle}</p>

            <div className="mt-8">{children}</div>

            <div className="mt-8 text-center text-sm text-muted">{footer}</div>
          </div>
        </div>
      </div>

      {/* ── Proof ───────────────────────────────────────────────────────── */}
      <aside className="relative hidden overflow-hidden border-l border-line bg-surface-2 lg:block">
        <div
          className="grain pointer-events-none absolute inset-0"
          aria-hidden
        >
          <div className="absolute -right-32 top-[-10rem] size-[36rem] rounded-pill bg-[radial-gradient(circle,var(--accent-soft),transparent_68%)]" />
          <div className="absolute -left-24 bottom-[-8rem] size-[32rem] rounded-pill bg-[radial-gradient(circle,var(--info-soft),transparent_70%)] opacity-80" />
        </div>

        <div className="relative flex h-full flex-col justify-center px-14 py-16">
          <p className="text-label uppercase text-subtle">What happens next</p>
          <p className="mt-6 text-balance text-[2rem] leading-[1.14] tracking-[-0.028em] text-ink">
            Connect one repository. The next pull request opened against it is
            read, scanned, reviewed and routed.
          </p>

          <ul className="mt-10 space-y-4">
            {[
              "Context gathered from the ticket, the issues and the Slack thread",
              "Scanner findings and model findings kept visibly separate",
              "Review rounds tracked across pushes, approvals revoked when the diff moves",
              "The testing team briefed with what the reviewer actually asked for",
            ].map((line) => (
              <li key={line} className="flex items-start gap-3">
                <CheckCircle2
                  className="mt-0.5 size-4 shrink-0 text-accent-strong"
                  aria-hidden
                />
                <span className="text-sm leading-relaxed text-muted">{line}</span>
              </li>
            ))}
          </ul>

          <p className="mt-12 max-w-sm border-t border-line pt-6 text-xs leading-relaxed text-subtle">
            Every model that reads your code automatically runs on your own
            machine. Autonomous authoring is the one exception and stays off
            until you hand over a specific ticket.
          </p>
        </div>
      </aside>
    </div>
  );
}
