"use client";

import Link from "next/link";
import { ArrowRight, Check, Plug, Play, Webhook } from "lucide-react";
import type { PRAgentSummary, TaskBoard } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/surface";
import { cn } from "@/lib/utils";

/**
 * What to do first.
 *
 * A new account lands on an empty board and is told "Nothing is assigned to
 * you" — true, unhelpful, and indistinguishable from something being broken.
 * Nothing on the page said that GitHub has to be connected before any of this
 * works, or that a repository has to be registered before it works
 * *automatically*.
 *
 * Three steps, in the order they have to happen, each showing whether it is
 * already done. It disappears entirely once the account is set up: a checklist
 * that stays after you have finished it is clutter on the page you look at
 * most.
 */
export function GettingStarted({
  summary,
  board,
}: {
  summary: PRAgentSummary | null;
  board: TaskBoard | null;
}) {
  if (!summary) return null;

  const connected = summary.github_connected;
  const registered = (summary.repos_registered ?? 0) > 0;
  const analysed = (summary.total_jobs ?? 0) > 0;

  // Only while something is still missing. Someone whose account works does not
  // need to be told how to set it up every time they open the board.
  if (connected && registered && analysed) return null;

  // ...and not on top of a board that already has work on it. A person with
  // eight assigned tickets is using the product; a setup panel above them
  // reads as the product not noticing.
  const hasWork = (board?.needs_you.length ?? 0) + (board?.in_flight.length ?? 0) > 0;
  if (hasWork && connected) return null;

  const steps = [
    {
      done: connected,
      icon: Plug,
      title: "Connect GitHub",
      body: "Locus reads your pull requests and posts its analysis through your own account. Nothing runs without it.",
      action: (
        <Button asChild size="sm" variant={connected ? "secondary" : "primary"}>
          <Link href="/integrations">
            {connected ? "Manage connections" : "Connect GitHub"}
            {!connected && <ArrowRight aria-hidden />}
          </Link>
        </Button>
      ),
    },
    {
      done: registered,
      icon: Webhook,
      title: "Register a repository",
      body: "Registration is what lets GitHub notify Locus, so every pull request is analysed without you asking. Your automation settings already apply to it.",
      action: (
        <Button
          asChild
          size="sm"
          variant={registered || !connected ? "secondary" : "primary"}
        >
          <Link href="/settings?tab=automation">
            {registered ? "Manage repositories" : "Register a repo"}
            {!registered && connected && <ArrowRight aria-hidden />}
          </Link>
        </Button>
      ),
    },
    {
      done: analysed,
      icon: Play,
      title: "Watch the first run",
      body: "Open a pull request on that repository, or analyse an existing one by number. Everything the pipeline did shows up here.",
      action: (
        <Button asChild size="sm" variant="secondary">
          <Link href="/settings?tab=automation">Analyse a pull request</Link>
        </Button>
      ),
    },
  ];

  const complete = steps.filter((s) => s.done).length;

  return (
    <Panel className="mt-6 overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-h2 text-ink">Get set up</h2>
          <p className="mt-0.5 text-sm text-muted">
            Three steps, once. Everything after this happens on its own.
          </p>
        </div>
        <span className="tabular shrink-0 text-sm text-muted">
          {complete} of {steps.length} done
        </span>
      </div>

      <ol className="divide-y divide-line">
        {steps.map((step, i) => (
          <li
            key={step.title}
            className="flex flex-wrap items-start gap-x-4 gap-y-3 px-5 py-4"
          >
            <span
              className={cn(
                "flex size-7 shrink-0 items-center justify-center rounded-pill text-xs font-semibold",
                step.done
                  ? "bg-success-soft text-success"
                  : "bg-surface-2 text-muted"
              )}
              aria-hidden
            >
              {step.done ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
            </span>

            <div className="min-w-0 flex-1 basis-64">
              <p
                className={cn(
                  "text-h3",
                  step.done ? "text-muted line-through" : "text-ink"
                )}
              >
                {step.title}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-muted">
                {step.body}
              </p>
            </div>

            <div className="ml-auto shrink-0">{step.action}</div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
