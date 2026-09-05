"use client";

import Link from "next/link";
import { ArrowRight, Plug } from "lucide-react";
import type { PRAgentSummary, TaskBoard } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/surface";

/**
 * What to do first.
 *
 * Prompts the user to connect GitHub if it is not yet connected.
 * Once GitHub is connected, setup is complete and this disappears
 * so it does not clutter the active work board.
 */
export function GettingStarted({
  summary,
  board: _board,
}: {
  summary: PRAgentSummary | null;
  board?: TaskBoard | null;
}) {
  if (!summary) return null;

  const connected = summary.github_connected;

  // Once GitHub is connected, setup is complete.
  if (connected) return null;

  return (
    <Panel className="mt-6 overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-h2 text-ink">Get set up</h2>
          <p className="mt-0.5 text-sm text-muted">
            Connect your GitHub account to get started. Everything after this happens on its own.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-x-4 gap-y-3 px-5 py-4">
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-pill bg-surface-2 text-xs font-semibold text-muted"
          aria-hidden
        >
          <Plug className="size-3.5" />
        </span>

        <div className="min-w-0 flex-1 basis-64">
          <p className="text-h3 text-ink">Connect GitHub</p>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Locus reads your pull requests and posts its analysis through your own account. Nothing runs without it.
          </p>
        </div>

        <div className="ml-auto shrink-0">
          <Button asChild size="sm" variant="primary">
            <Link href="/integrations">
              Connect GitHub
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        </div>
      </div>
    </Panel>
  );
}
