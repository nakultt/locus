"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion, useReducedMotion, useScroll, useSpring } from "framer-motion";
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
import { HeroScene } from "@/features/landing/hero-scene";
import { HeroDemo } from "@/features/landing/hero-demo";
import { ToolMarquee } from "@/features/landing/marquee";
import { Reveal, RevealGroup, RevealItem, RevealWords } from "@/features/landing/motion";
import { Button } from "@/components/ui/button";
import { LogoMark, Wordmark } from "@/components/ui/logo";
import { cn } from "@/lib/utils";

/**
 * The front door.
 *
 * Built to the reference material's proportions: a floating pill nav over the
 * content, an eyebrow chip, a display headline at a size the rest of the
 * product never uses, one primary action, and a soft horizon behind all of it.
 *
 * The motion is deliberately load-bearing rather than decorative. The hero runs
 * the actual pipeline — nine stages advancing on a timer, writing a log as they
 * go — because a page whose job is explaining what a product does should show
 * it doing that. Everything else (words rising into the headline, sections
 * arriving on scroll, the tool row travelling) is quiet by comparison, so the
 * one thing that moves for a *reason* is the thing you look at.
 *
 * Every animated component reads `useReducedMotion` and renders its final state
 * when it is set. There is no "reduced" variant that still moves.
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
    body: "Scanner rules produce confirmed findings. The model produces possible ones, labelled as such. A guess is never presented as a vulnerability, because one that is wrong costs a team's trust permanently.",
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
  const still = useReducedMotion();

  // A reading-progress hairline across the top. Springed rather than bound
  // straight to scroll, so a flick of the wheel does not make it twitch.
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, {
    stiffness: 180,
    damping: 30,
    restDelta: 0.001,
  });

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
      {!still && (
        <motion.div
          aria-hidden
          style={{ scaleX: progress }}
          className="fixed inset-x-0 top-0 z-50 h-0.5 origin-left bg-accent"
        />
      )}

      {/* ── Nav ─────────────────────────────────────────────────────────────
          Two states, because it sits over two different grounds. Unscrolled it
          floats on the hero painting and everything in it switches to the
          `on-art` pair; scrolled it is over the page and reverts to the ordinary
          tokens. Nothing here is a colour literal — a bar that hardcoded white
          would be unreadable the moment it left the image. */}
      <header
        className={cn(
          "sticky top-0 z-40 transition-colors duration-[--dur]",
          scrolled
            ? "border-b border-line bg-bg/85 backdrop-blur-xl"
            : "border-b border-transparent"
        )}
      >
        <div className="mx-auto flex h-18 max-w-[80rem] items-center gap-4 px-5 sm:px-8">
          <Link href="/" aria-label="Locus home" className="shrink-0">
            <Wordmark
              className={cn(
                "transition-colors duration-[--dur]",
                !scrolled && "text-on-art"
              )}
            />
          </Link>

          <nav
            aria-label="Sections"
            className={cn(
              "absolute left-1/2 hidden -translate-x-1/2 items-center gap-1 rounded-pill border p-1 backdrop-blur transition-colors duration-[--dur] md:flex",
              scrolled
                ? "border-line bg-surface/90 shadow-sm"
                : "border-on-art-line bg-on-art-fill"
            )}
          >
            {SECTIONS.map((s) => (
              <a
                key={s.href}
                href={s.href}
                className={cn(
                  "rounded-pill px-4 py-1.5 text-sm font-medium transition-colors",
                  scrolled
                    ? "text-muted hover:bg-surface-2 hover:text-ink"
                    : "text-on-art-muted hover:bg-on-art-fill hover:text-on-art"
                )}
              >
                {s.label}
              </a>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <Button
              asChild
              variant="ghost"
              size="md"
              className={cn(
                "hidden sm:inline-flex",
                !scrolled &&
                  "text-on-art-muted hover:bg-on-art-fill hover:text-on-art"
              )}
            >
              <Link href="/login">Sign in</Link>
            </Button>
            {/* `primary` needs no over-art variant: it is ink on cream in one
                theme and cream on ink in the other, and both carry against a
                mid-value sky. */}
            <Button asChild size="md" className="hidden sm:inline-flex">
              <Link href={primary.href}>{primary.label}</Link>
            </Button>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              className={cn(
                "flex size-9.5 items-center justify-center rounded-pill border backdrop-blur transition-colors md:hidden",
                scrolled || menuOpen
                  ? "border-line bg-surface text-ink"
                  : "border-on-art-line bg-on-art-fill text-on-art"
              )}
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

      {/* ── Hero ────────────────────────────────────────────────────────────
          `-mt-18` is the height of the bar above it. The painting has to run to
          the top of the window — a picture that starts below a strip of page
          colour reads as a banner someone dropped in, not as the ground the
          product is standing on — and the bar stays `sticky` for the whole
          document rather than being nested in here, where it would scroll away
          after the first screen. The padding puts back exactly what the negative
          margin took. */}
      <section className="relative -mt-18 overflow-hidden px-5 pb-24 pt-28 sm:px-8 sm:pt-36">
        <HeroScene />

        <div className="relative z-10 mx-auto max-w-4xl text-center">
          <motion.span
            className="eyebrow eyebrow-art"
            initial={still ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.32, 0.72, 0, 1] }}
          >
            <span className="size-1.5 rounded-pill bg-accent" aria-hidden />
            Ticket to sign-off, without the coordination
          </motion.span>

          {/* Set on the picture, so the type takes the `on-art` pair rather than
              `ink`/`muted`. The shadow is doing real work rather than styling:
              the sky behind the headline runs from deep blue to a bright band of
              sun across its width, and a light letterform crossing that boundary
              loses its edge exactly where the sun is. Two of them — a tight one
              for the edge and a wide one for separation — because a single wide
              shadow strong enough to separate reads as a glow. */}
          <h1 className="mt-7 text-balance text-[clamp(2.75rem,7.5vw,5rem)] font-normal leading-[1.02] tracking-[-0.035em] text-on-art [text-shadow:0_1px_2px_oklch(0.24_0.05_252/0.34),0_2px_28px_oklch(0.24_0.05_252/0.3)]">
            <RevealWords text="The work between" className="block text-on-art-muted" />
            <RevealWords
              text="writing it and shipping it"
              className="block"
              delay={0.18}
            />
          </h1>

          <motion.p
            className="mx-auto mt-6 max-w-xl text-pretty text-body leading-relaxed text-on-art-muted [text-shadow:0_1px_2px_oklch(0.24_0.05_252/0.4),0_1px_18px_oklch(0.24_0.05_252/0.42)] sm:text-lg"
            initial={still ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.5, ease: [0.32, 0.72, 0, 1] }}
          >
            A ticket lands on you. Somewhere after that come the context, the
            security pass, the review rounds, the QA thread and the board. Locus
            runs all of it, and shows you every step it took.
          </motion.p>

          <motion.div
            className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
            initial={still ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.62, ease: [0.32, 0.72, 0, 1] }}
          >
            {/* The reference CTA: a pill whose leading icon sits in its own
                filled circle. It gives the primary action a shape nothing else
                on the page shares, which is what makes it findable. */}
            <Link
              href={primary.href}
              className="group inline-flex h-14 items-center gap-3 rounded-pill bg-primary pl-2 pr-7 text-primary-fg shadow-pop transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span className="flex size-10 items-center justify-center rounded-pill bg-accent text-accent-fg transition-transform duration-[--dur] ease-[--ease] group-hover:translate-x-0.5">
                <ArrowRight className="size-4.5" aria-hidden />
              </span>
              <span className="text-body font-medium">{primary.label}</span>
            </Link>

            {/* Glass rather than the `secondary` pill. A filled surface here
                punches a page-coloured hole in the painting, which is the one
                thing that makes a hero image look pasted on. */}
            <a
              href="#pipeline"
              className="inline-flex h-14 w-full items-center justify-center rounded-pill border border-on-art-line bg-on-art-fill px-7 text-body font-medium text-on-art backdrop-blur-md transition-colors hover:bg-on-art-line focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring sm:w-auto"
            >
              See how it works
            </a>
          </motion.div>
        </div>

        {/* The product, running. Not a screenshot — the same nine stages the
            board renders, advancing on a timer. It overlaps the foreground of
            the painting deliberately: the panel is opaque and sharp where
            everything behind it is soft, which is what puts it in front. */}
        <motion.div
          className="relative z-10 mx-auto mt-16 max-w-4xl [&>*]:shadow-pop"
          initial={still ? false : { opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.85, delay: 0.75, ease: [0.32, 0.72, 0, 1] }}
        >
          <HeroDemo />
        </motion.div>
      </section>

      {/* ── Tools ─────────────────────────────────────────────────────────── */}
      <section className="border-y border-line bg-surface-2/40 py-10">
        <div className="mx-auto max-w-[80rem] px-5 sm:px-8">
          <p className="mb-6 text-center text-label uppercase text-subtle">
            Reads and writes through your own accounts
          </p>
          <ToolMarquee />
        </div>
      </section>

      {/* ── Pipeline ──────────────────────────────────────────────────────── */}
      <section id="pipeline" className="px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-[80rem]">
          <Reveal className="max-w-2xl">
            <span className="eyebrow">
              <Sparkles className="size-3.5 text-accent-strong" aria-hidden />
              What actually runs
            </span>
            <h2 className="mt-6 text-balance text-[clamp(2rem,4vw,3rem)] leading-[1.08] tracking-[-0.03em] text-ink">
              Four things happen on every push, whether or not anyone is watching
            </h2>
          </Reveal>

          <RevealGroup as="ol" className="mt-14 grid gap-x-10 gap-y-12 sm:grid-cols-2">
            {PIPELINE.map((step, i) => (
              <RevealItem as="li" key={step.title} className="flex gap-5">
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
              </RevealItem>
            ))}
          </RevealGroup>
        </div>
      </section>

      {/* ── Surfaces ──────────────────────────────────────────────────────── */}
      <section
        id="surfaces"
        className="border-t border-line bg-surface-2/50 px-5 py-24 sm:px-8"
      >
        <div className="mx-auto max-w-[80rem]">
          <Reveal className="max-w-2xl">
            <span className="eyebrow">Three surfaces</span>
            <h2 className="mt-6 text-balance text-[clamp(2rem,4vw,3rem)] leading-[1.08] tracking-[-0.03em] text-ink">
              A board, a conversation, and a record you can hand to someone
            </h2>
          </Reveal>

          <RevealGroup className="mt-14 grid gap-4 md:grid-cols-3">
            {SURFACES.map((s) => (
              <RevealItem key={s.title}>
                {/* A hover lift, small enough to read as responsiveness rather
                    than as the card trying to get your attention. */}
                <motion.div
                  whileHover={still ? undefined : { y: -4 }}
                  transition={{ duration: 0.25, ease: [0.32, 0.72, 0, 1] }}
                  className="h-full rounded-xl border border-line bg-surface p-7 transition-colors hover:border-line-strong"
                >
                  <span className="flex size-11 items-center justify-center rounded-pill bg-accent-soft">
                    <s.icon className="size-5 text-accent-strong" aria-hidden />
                  </span>
                  <h3 className="mt-5 text-h2 text-ink">{s.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
                </motion.div>
              </RevealItem>
            ))}
          </RevealGroup>
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
          <Reveal>
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
          </Reveal>

          <RevealGroup as="ul" className="space-y-3 self-center">
            {[
              "Credentials are Fernet-encrypted and held per request, never in module state",
              "The agent works in a throwaway git worktree, never your checkout",
              "A diff touching CI, secrets or the credential path is refused after the run",
              "A human commit on the branch ends autonomous mode for that work item",
              "Every message sent and received is recorded verbatim, not summarised",
            ].map((line) => (
              <RevealItem
                as="li"
                key={line}
                className="flex items-start gap-3 rounded-lg border border-line bg-surface px-5 py-4"
              >
                <CheckCircle2
                  className="mt-0.5 size-4 shrink-0 text-success"
                  aria-hidden
                />
                <span className="text-sm leading-relaxed text-ink">{line}</span>
              </RevealItem>
            ))}
          </RevealGroup>
        </div>
      </section>

      {/* ── Close ─────────────────────────────────────────────────────────── */}
      <section className="border-t border-line px-5 py-24 sm:px-8">
        <Reveal className="mx-auto max-w-2xl text-center">
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
        </Reveal>
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
