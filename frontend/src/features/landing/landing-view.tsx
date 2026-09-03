"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircuitBoard,
  FileText,
  GitPullRequest,
  Menu,
  MessagesSquare,
  Radar,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import { Button } from "@/components/ui/button";
import { LogoMark, Wordmark } from "@/components/ui/logo";
import { cn } from "@/lib/utils";

/**
 * The front door.
 *
 * Built to the reference material's proportions rather than to a template: a
 * floating pill nav over the content, an eyebrow chip, a display headline at a
 * size the rest of the product never uses, one primary action, and a soft
 * horizon behind all of it. What it replaces was an animated grid, three blurred
 * colour blobs and a headline that said "Your AI-Powered Productivity Hub",
 * which describes nothing and could sit on any product.
 *
 * The copy here is the same claim the repository's own documentation makes:
 * this runs the stretch between a ticket landing on someone and the testing
 * team signing off. That is specific, and it is what the product does.
 */

const SECTIONS = [
  { href: "#pipeline", label: "Pipeline" },
  { href: "#surfaces", label: "Product" },
  { href: "#trust", label: "Where it runs" },
];

const PIPELINE = [
  {
    icon: Radar,
    title: "It reads the context first",
    body: "The ticket, the linked issues, the Slack thread where the requirement was actually agreed, and your team's standards documents — gathered before a single line of the diff is judged.",
  },
  {
    icon: ShieldCheck,
    title: "Two passes, never conflated",
    body: "Scanner rules produce confirmed findings. The model produces possible ones, labelled as such. A guess has never been presented as a vulnerability, because one that is wrong costs the team's trust permanently.",
  },
  {
    icon: GitPullRequest,
    title: "It runs the review round trip",
    body: "GitHub reports each review as an isolated event. Locus keeps the thread — which round this is, what was asked for last time, and whether a push has quietly invalidated an approval.",
  },
  {
    icon: CheckCircle2,
    title: "It closes the loop with QA",
    body: "The brief that reaches your testers carries what the reviewer asked for in their own words. A rejection reopens the ticket. Merged and done stay different claims.",
  },
];

const SURFACES = [
  {
    icon: CircuitBoard,
    title: "Work",
    body: "Every assigned ticket and how far it has travelled — including the ones with no pull request yet, which every PR-shaped dashboard renders as nothing at all.",
  },
  {
    icon: MessagesSquare,
    title: "Chat",
    body: "One place to ask across GitHub, Jira, Slack, Linear and Google. Tool calls stream as they run, so a slow answer is legible rather than silent.",
  },
  {
    icon: FileText,
    title: "The written record",
    body: "One document per work item, rewritten in place. Every search, every message sent and received, every skipped step. Nothing in it is model-written, so nothing in it can be wrong the way a summary can.",
  },
];

export default function LandingView() {
  const { isAuthenticated, isLoading } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  // The bar earns its border only once there is something behind it. Over the
  // hero it floats; on the page it separates.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Held until the stored session has been read, so the primary action does not
  // say "Get started" for a beat to somebody who is already signed in.
  const primary = isLoading
    ? { href: "/login", label: "Get started" }
    : isAuthenticated
      ? { href: "/tasks", label: "Open your board" }
      : { href: "/signup", label: "Get started" };

  return (
    <div className="min-h-dvh bg-bg">
      {/* ── Nav ───────────────────────────────────────────────────────────── */}
      <header
        className={cn(
          "sticky top-0 z-40 transition-colors duration-[--dur]",
          scrolled ? "border-b border-line bg-bg/85 backdrop-blur-xl" : "border-b border-transparent"
        )}
      >
        <div className="mx-auto flex h-18 max-w-[80rem] items-center gap-4 px-5 sm:px-8">
          <Link href="/" aria-label="Locus home" className="shrink-0">
            <Wordmark />
          </Link>

          <nav
            aria-label="Sections"
            className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-1 rounded-pill border border-line bg-surface/90 p-1 shadow-sm backdrop-blur md:flex"
          >
            {SECTIONS.map((s) => (
              <a
                key={s.href}
                href={s.href}
                className="rounded-pill px-4 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink"
              >
                {s.label}
              </a>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <Button asChild variant="ghost" size="md" className="hidden sm:inline-flex">
              <Link href="/login">Sign in</Link>
            </Button>
            <Button asChild size="md" className="hidden sm:inline-flex">
              <Link href={primary.href}>{primary.label}</Link>
            </Button>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              className="flex size-9.5 items-center justify-center rounded-pill border border-line bg-surface text-ink md:hidden"
            >
              {menuOpen ? <X className="size-4" /> : <Menu className="size-4" />}
            </button>
          </div>
        </div>

        {menuOpen && (
          <div className="border-t border-line bg-surface px-5 py-4 md:hidden">
            <nav className="space-y-1">
              {SECTIONS.map((s) => (
                <a
                  key={s.href}
                  href={s.href}
                  onClick={() => setMenuOpen(false)}
                  className="block rounded-md px-3 py-2.5 text-sm text-ink hover:bg-surface-2"
                >
                  {s.label}
                </a>
              ))}
            </nav>
            <div className="mt-3 flex gap-2 border-t border-line pt-3">
              <Button asChild variant="secondary" size="md" className="flex-1">
                <Link href="/login">Sign in</Link>
              </Button>
              <Button asChild size="md" className="flex-1">
                <Link href={primary.href}>{primary.label}</Link>
              </Button>
            </div>
          </div>
        )}
      </header>

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden px-5 pb-24 pt-10 sm:px-8 sm:pb-32 sm:pt-16">
        <Horizon />

        <div className="relative mx-auto max-w-4xl text-center">
          <span className="eyebrow animate-in-up">
            <span className="size-1.5 rounded-pill bg-accent" aria-hidden />
            Ticket to sign-off, without the coordination
          </span>

          <h1
            className="mt-7 text-balance text-[clamp(2.75rem,7.5vw,5rem)] font-normal leading-[1.02] tracking-[-0.035em] text-ink animate-in-up"
            style={{ animationDelay: "60ms" }}
          >
            The work between
            <br className="hidden sm:block" />{" "}
            <span className="text-muted">writing it</span> and{" "}
            <span className="text-muted">shipping it</span>
          </h1>

          <p
            className="mx-auto mt-6 max-w-xl text-pretty text-body leading-relaxed text-muted animate-in-up sm:text-lg"
            style={{ animationDelay: "120ms" }}
          >
            A ticket lands on you. Somewhere after that come the context, the
            security pass, the review rounds, the QA thread and the board. Locus
            runs all of it, and shows you every step it took.
          </p>

          <div
            className="mt-9 flex flex-col items-center justify-center gap-3 animate-in-up sm:flex-row"
            style={{ animationDelay: "180ms" }}
          >
            {/* The reference CTA: a pill whose leading icon sits in its own
                filled circle. It gives the primary action a shape nothing else
                on the page shares, which is what makes it findable. */}
            <Link
              href={primary.href}
              className="group inline-flex h-14 items-center gap-3 rounded-pill bg-primary pl-2 pr-7 text-primary-fg transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span className="flex size-10 items-center justify-center rounded-pill bg-accent text-accent-fg transition-transform duration-[--dur] ease-[--ease] group-hover:translate-x-0.5">
                <ArrowRight className="size-4.5" aria-hidden />
              </span>
              <span className="text-body font-medium">{primary.label}</span>
            </Link>

            <Button asChild variant="secondary" size="xl" className="w-full sm:w-auto">
              <a href="#pipeline">See how it works</a>
            </Button>
          </div>

          <p
            className="mt-7 text-xs text-subtle animate-in-up"
            style={{ animationDelay: "240ms" }}
          >
            Connects GitHub · Jira · Slack · Linear · Google Workspace
          </p>
        </div>

        {/* The product itself, cropped. A screenshot of the board says more
            about what this is than any illustration would. */}
        <div
          className="relative mx-auto mt-16 max-w-5xl animate-in-up"
          style={{ animationDelay: "300ms" }}
        >
          <BoardPreview />
        </div>
      </section>

      {/* ── Pipeline ──────────────────────────────────────────────────────── */}
      <section id="pipeline" className="border-t border-line px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-[80rem]">
          <div className="max-w-2xl">
            <span className="eyebrow">
              <Sparkles className="size-3.5 text-accent-strong" aria-hidden />
              What actually runs
            </span>
            <h2 className="mt-6 text-balance text-[clamp(2rem,4vw,3rem)] leading-[1.08] tracking-[-0.03em] text-ink">
              Four things happen on every push, whether or not anyone is watching
            </h2>
          </div>

          <ol className="mt-14 grid gap-x-10 gap-y-12 sm:grid-cols-2">
            {PIPELINE.map((step, i) => (
              <li key={step.title} className="flex gap-5">
                <span className="flex size-11 shrink-0 items-center justify-center rounded-pill border border-line bg-surface">
                  <step.icon className="size-5 text-accent-strong" aria-hidden />
                </span>
                <div className="min-w-0 pt-1">
                  <span className="tabular text-label uppercase text-subtle">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3 className="mt-1.5 text-h2 text-ink">{step.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── Surfaces ──────────────────────────────────────────────────────── */}
      <section id="surfaces" className="border-t border-line bg-surface-2/50 px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-[80rem]">
          <div className="max-w-2xl">
            <span className="eyebrow">Three surfaces</span>
            <h2 className="mt-6 text-balance text-[clamp(2rem,4vw,3rem)] leading-[1.08] tracking-[-0.03em] text-ink">
              A board, a conversation, and a record you can hand to someone
            </h2>
          </div>

          <div className="mt-14 grid gap-4 md:grid-cols-3">
            {SURFACES.map((s) => (
              <div
                key={s.title}
                className="rounded-xl border border-line bg-surface p-7 transition-colors hover:border-line-strong"
              >
                <span className="flex size-11 items-center justify-center rounded-pill bg-accent-soft">
                  <s.icon className="size-5 text-accent-strong" aria-hidden />
                </span>
                <h3 className="mt-5 text-h2 text-ink">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Trust ─────────────────────────────────────────────────────────
          The honest version of the claim. Every model that reads your code
          without being asked runs on your own machine; the one exception is
          authoring, which is opt-in per ticket. Saying so plainly on the
          marketing page is the only place it is worth anything — nobody reads
          a changelog to find out where their code went. */}
      <section id="trust" className="border-t border-line px-5 py-24 sm:px-8">
        <div className="mx-auto grid max-w-[80rem] gap-12 lg:grid-cols-2 lg:gap-20">
          <div>
            <span className="eyebrow">
              <ShieldCheck className="size-3.5 text-accent-strong" aria-hidden />
              Where the models run
            </span>
            <h2 className="mt-6 text-balance text-[clamp(2rem,4vw,3rem)] leading-[1.08] tracking-[-0.03em] text-ink">
              Everything automatic runs on your machine
            </h2>
            <p className="mt-5 max-w-xl text-body leading-relaxed text-muted">
              The security scanner, the code reviewer, the QA classifier and the
              review summariser all talk to a local model server over loopback.
              They read diffs, Slack messages and review bodies — text anyone who
              can open a pull request controls — and none of them has a single
              tool bound. They return findings and nothing else.
            </p>
            <p className="mt-4 max-w-xl text-body leading-relaxed text-muted">
              Autonomous authoring is the one exception, and it is off until you
              hand over a specific ticket. It says so before the first attempt,
              records which model ran, and can withhold your internal discussion
              entirely.
            </p>
          </div>

          <ul className="space-y-3 self-center">
            {[
              "Credentials are Fernet-encrypted and held per request, never in module state",
              "The agent works in a throwaway git worktree, never your checkout",
              "A diff touching CI, secrets or the credential path is refused after the run",
              "A human commit on the branch ends autonomous mode for that work item",
              "Every message sent and received is recorded verbatim, not summarised",
            ].map((line) => (
              <li
                key={line}
                className="flex items-start gap-3 rounded-lg border border-line bg-surface px-5 py-4"
              >
                <CheckCircle2
                  className="mt-0.5 size-4 shrink-0 text-success"
                  aria-hidden
                />
                <span className="text-sm leading-relaxed text-ink">{line}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── Close ─────────────────────────────────────────────────────────── */}
      <section className="border-t border-line px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-balance text-[clamp(2rem,4.5vw,3.25rem)] leading-[1.06] tracking-[-0.032em] text-ink">
            Start with one repository
          </h2>
          <p className="mx-auto mt-5 max-w-lg text-body leading-relaxed text-muted">
            Connect GitHub, register a repo, and the next pull request opened
            against it is analysed. Nothing else needs configuring first.
          </p>
          <div className="mt-9 flex justify-center">
            <Link
              href={primary.href}
              className="group inline-flex h-14 items-center gap-3 rounded-pill bg-primary pl-2 pr-7 text-primary-fg transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span className="flex size-10 items-center justify-center rounded-pill bg-accent text-accent-fg transition-transform duration-[--dur] ease-[--ease] group-hover:translate-x-0.5">
                <ArrowRight className="size-4.5" aria-hidden />
              </span>
              <span className="text-body font-medium">{primary.label}</span>
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-line px-5 py-10 sm:px-8">
        <div className="mx-auto flex max-w-[80rem] flex-col items-center justify-between gap-4 sm:flex-row">
          <div className="flex items-center gap-2 text-sm text-muted">
            <LogoMark className="size-5 text-subtle" />
            <span>Locus</span>
          </div>
          <p className="text-xs text-subtle">
            Cross-tool context for the work around the code.
          </p>
        </div>
      </footer>
    </div>
  );
}

/**
 * The soft horizon behind the hero.
 *
 * Two very wide, very diffuse radial fields in the accent and a cool
 * counterpoint, plus the shared grain overlay. Flat colour at this scale reads
 * as an unstyled page; a gradient this soft reads as depth without becoming the
 * blurred-blob background it replaces.
 */
function Horizon() {
  return (
    <div className="grain pointer-events-none absolute inset-x-0 top-0 -z-0 h-[42rem] overflow-hidden" aria-hidden>
      <div className="absolute left-1/2 top-[-18rem] size-[46rem] -translate-x-1/2 rounded-pill bg-[radial-gradient(circle,var(--accent-soft),transparent_68%)]" />
      <div className="absolute left-[8%] top-[6rem] size-[30rem] rounded-pill bg-[radial-gradient(circle,var(--info-soft),transparent_70%)] opacity-70" />
      <div className="absolute right-[4%] top-[2rem] size-[26rem] rounded-pill bg-[radial-gradient(circle,var(--success-soft),transparent_70%)] opacity-60" />
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-bg" />
    </div>
  );
}

/**
 * A cropped, non-interactive rendering of the board.
 *
 * Drawn in the real design tokens rather than shipped as a PNG: it stays sharp,
 * it follows the theme, and it cannot go stale the way a screenshot of an
 * earlier version does.
 */
function BoardPreview() {
  const rows = [
    {
      key: "PROJ-1183",
      title: "Retry the merge gate when GitHub reports mergeable: null",
      stage: "In review",
      tone: "info" as const,
      needs: true,
      meta: "round 2 · acme/api#412",
    },
    {
      key: "PROJ-1179",
      title: "Rotate the Gmail refresh token before the QA sweep",
      stage: "Testing",
      tone: "accent" as const,
      needs: false,
      meta: "acme/api#409",
    },
    {
      key: "#284",
      title: "Board card sits in Todo through the whole review round trip",
      stage: "Branch",
      tone: "neutral" as const,
      needs: false,
      meta: "feat/project-card-sync",
    },
  ];

  const toneClass = {
    info: "border-info-border bg-info-soft text-info",
    accent: "border-accent/35 bg-accent-soft text-accent-strong",
    neutral: "border-line bg-surface-2 text-muted",
  };

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-md">
      <div className="flex items-center gap-2 border-b border-line bg-surface-2/60 px-5 py-3.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-pill bg-line-strong" />
          <span className="size-2.5 rounded-pill bg-line-strong" />
          <span className="size-2.5 rounded-pill bg-line-strong" />
        </span>
        <span className="ml-2 text-xs font-medium text-muted">Work</span>
        <span className="ml-auto rounded-pill bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent-strong">
          1 needs you
        </span>
      </div>

      <div className="divide-y divide-line">
        {rows.map((row) => (
          <div key={row.key} className="flex items-start gap-4 px-5 py-4">
            <span
              className={cn(
                "mt-1 size-2 shrink-0 rounded-pill",
                row.needs ? "bg-accent" : "bg-line-strong"
              )}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-medium text-ink">
                  {row.key}
                </span>
                <span
                  className={cn(
                    "rounded-pill border px-2 py-0.5 text-xs font-medium",
                    toneClass[row.tone]
                  )}
                >
                  {row.stage}
                </span>
                {row.needs && (
                  <span className="rounded-pill bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-strong">
                    Needs you
                  </span>
                )}
              </div>
              <p className="mt-1.5 truncate text-sm text-ink">{row.title}</p>
              <p className="mt-1 truncate font-mono text-xs text-subtle">
                {row.meta}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
