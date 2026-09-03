"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  History,
  Play,
  Plug,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import {
  getPRAgentSummary,
  getTaskBoard,
  listPRJobs,
  type PRAgentSummary,
  type PRJob,
  type TaskBoard,
  type TaskCard,
} from "@/lib/api";
import { PageHeader, PageShell } from "@/components/layout/app-shell";
import { Button, IconButton } from "@/components/ui/button";
import { Segmented } from "@/components/ui/nav";
import { Input } from "@/components/ui/form";
import {
  EmptyState,
  Notice,
  Section,
  SkeletonRows,
} from "@/components/ui/surface";
import { useToast } from "@/components/ui/toast";
import { TaskRow } from "./task-row";
import { TaskSheet } from "./task-sheet";
import { JobRow } from "./runs";

/**
 * The work board.
 *
 * Organised around the work item rather than the pull request, because that is
 * the unit a person is assigned. The pipeline Locus automates starts when a
 * ticket lands on someone and ends when the testing team signs off; only the
 * coding in the middle is manual. A ticket with no pull request yet is real
 * work, and it is invisible to every PR-shaped view.
 *
 * Two things changed here beyond the styling. The settings tab is gone — five
 * hundred lines of automation configuration lived behind a tab on the board,
 * which made the page read as a configuration screen that happened to list
 * some work; it is now a section of Settings, where someone looks for it. And
 * the three stacked sections became one list behind a filter: "Needs you", "In
 * flight" and "Completed" are states of the same thing, and rendering them as
 * three separately-headed lists meant the count you care about was three
 * scroll positions apart from the queue it describes.
 */

type Filter = "needs_you" | "in_flight" | "done" | "all";

export default function TasksView() {
  const { user } = useAuth();
  const toast = useToast();
  const userId = user?.id;

  const [board, setBoard] = useState<TaskBoard | null>(null);
  const [summary, setSummary] = useState<PRAgentSummary | null>(null);
  const [jobs, setJobs] = useState<PRJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<Filter>("needs_you");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<TaskCard | null>(null);
  const [showRuns, setShowRuns] = useState(false);

  const refresh = useCallback(
    async (forceAssigned = false) => {
      if (!userId) return;
      if (forceAssigned) setRefreshing(true);
      try {
        const [b, s, j] = await Promise.all([
          getTaskBoard(forceAssigned),
          getPRAgentSummary(),
          listPRJobs(),
        ]);
        setBoard(b);
        setSummary(s);
        setJobs(j);
      } catch (e) {
        toast.error(
          "Could not load your work",
          e instanceof Error ? e.message : undefined
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [userId, toast]
  );

  useEffect(() => {
    refresh();
    // Runs happen in the background, so poll while any are in flight. The
    // assigned half is cached server-side, so this does not re-query GitHub
    // and Jira every tick.
    const interval = setInterval(() => refresh(), 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  // The open sheet reads from the board, so a poll landing mid-read has to
  // hand it the fresh copy of the same card rather than a stale snapshot.
  useEffect(() => {
    if (!selected || !board) return;
    const fresh = [...board.needs_you, ...board.in_flight, ...(board.recently_done ?? [])].find(
      (c) => c.key === selected.key
    );
    if (fresh && fresh !== selected) setSelected(fresh);
  }, [board, selected]);

  const counts = useMemo(
    () => ({
      needs_you: board?.needs_you.length ?? 0,
      in_flight: board?.in_flight.length ?? 0,
      done: board?.recently_done?.length ?? 0,
      all:
        (board?.needs_you.length ?? 0) +
        (board?.in_flight.length ?? 0) +
        (board?.recently_done?.length ?? 0),
    }),
    [board]
  );

  const visible = useMemo(() => {
    if (!board) return [];
    const pool =
      filter === "needs_you"
        ? board.needs_you
        : filter === "in_flight"
          ? board.in_flight
          : filter === "done"
            ? (board.recently_done ?? [])
            : [
                ...board.needs_you,
                ...board.in_flight,
                ...(board.recently_done ?? []),
              ];

    const q = query.trim().toLowerCase();
    if (!q) return pool;
    return pool.filter(
      (c) =>
        c.key.toLowerCase().includes(q) ||
        c.title.toLowerCase().includes(q) ||
        c.pull_requests.some((pr) =>
          `${pr.repo}#${pr.pr_number}`.toLowerCase().includes(q)
        )
    );
  }, [board, filter, query]);

  const githubMissing = summary && !summary.github_connected;

  if (loading && !board) {
    return (
      <PageShell>
        <PageHeader
          title="Work"
          description="Everything assigned to you, from the ticket landing to the testing team signing off."
        />
        <div className="mt-8">
          <SkeletonRows />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Work"
        description="Everything assigned to you, from the ticket landing to the testing team signing off."
        actions={
          <>
            <Button asChild variant="secondary" size="md">
              <Link href="/settings?tab=automation">
                <SlidersHorizontal aria-hidden />
                Automation
              </Link>
            </Button>
            <IconButton
              label="Refresh"
              variant="secondary"
              onClick={() => refresh(true)}
            >
              <RefreshCw className={refreshing ? "animate-spin" : undefined} />
            </IconButton>
          </>
        }
      />

      {/* GitHub is the one connection the pipeline cannot run without, so its
          absence is stated here rather than only on the connections page. */}
      {githubMissing && (
        <Notice
          tone="warning"
          className="mt-6"
          icon={<Plug aria-hidden />}
          title="GitHub is not connected"
          action={
            <Button asChild size="sm" variant="secondary">
              <Link href="/integrations">Connect</Link>
            </Button>
          }
        >
          Nothing can be analysed until Locus can read your pull requests.
        </Notice>
      )}

      {/* A source that did not answer is said out loud. "Nothing assigned" and
          "Jira did not respond" mean very different things to someone deciding
          what to work on. */}
      {board && board.unavailable.length > 0 && (
        <Notice
          tone="warning"
          className="mt-4"
          icon={<AlertTriangle aria-hidden />}
          title={`Could not reach ${board.unavailable.join(" and ")}`}
        >
          What follows is everything the other sources returned. This is not an
          empty queue.
        </Notice>
      )}

      {/* ── Filter bar ─────────────────────────────────────────────────── */}
      <div className="mt-8 flex flex-wrap items-center gap-3">
        <Segmented
          ariaLabel="Filter work"
          value={filter}
          onChange={setFilter}
          items={[
            { value: "needs_you", label: "Needs you", count: counts.needs_you },
            { value: "in_flight", label: "In flight", count: counts.in_flight },
            { value: "done", label: "Completed", count: counts.done },
            { value: "all", label: "All", count: counts.all },
          ]}
        />
        <div className="ml-auto w-full sm:w-64">
          <Input
            type="search"
            inputSize="sm"
            icon={<Search aria-hidden />}
            placeholder="Filter by key, title or PR"
            aria-label="Filter work"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {/* ── The queue ──────────────────────────────────────────────────── */}
      <div className="mt-4">
        {visible.length === 0 ? (
          <BoardEmpty filter={filter} query={query} counts={counts} onClear={() => { setQuery(""); setFilter("all"); }} />
        ) : (
          <div className="space-y-2.5">
            {visible.map((card) => (
              <TaskRow
                key={card.key}
                card={card}
                onOpen={() => setSelected(card)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Runs ───────────────────────────────────────────────────────────
          Kept on this page but collapsed. A run is a record of the machine
          working, not a thing waiting on anyone, so it must not compete with
          the queue above — but it is also the first place to look when a card
          is not moving, so it does not belong on another page either. */}
      <Section
        className="mt-12"
        title="Recent analysis runs"
        description="What the pipeline actually did on each push."
        actions={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowRuns((v) => !v)}
            aria-expanded={showRuns}
          >
            <History aria-hidden />
            {showRuns ? "Hide" : `Show ${jobs.length || ""}`.trim()}
          </Button>
        }
      >
        {showRuns &&
          (jobs.length === 0 ? (
            <EmptyState
              compact
              icon={<Play aria-hidden />}
              title="No analyses yet"
              description="A run starts when a pull request is opened or pushed to on a registered repository."
              action={
                <Button asChild size="sm" variant="secondary">
                  <Link href="/settings?tab=automation">
                    <Settings2 aria-hidden />
                    Register a repository
                  </Link>
                </Button>
              }
            />
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </div>
          ))}
      </Section>

      <TaskSheet
        card={selected}
        open={!!selected}
        onClose={() => setSelected(null)}
        onChanged={() => refresh(true)}
      />
    </PageShell>
  );
}

/**
 * Empty, and why.
 *
 * Four different empties, because they mean four different things: nothing is
 * assigned at all, nothing is waiting on you right now (which is good news and
 * should read that way), nothing has finished this week, and your filter text
 * matches nothing.
 */
function BoardEmpty({
  filter,
  query,
  counts,
  onClear,
}: {
  filter: Filter;
  query: string;
  counts: Record<Filter, number>;
  onClear: () => void;
}) {
  if (query.trim()) {
    return (
      <EmptyState
        icon={<Search aria-hidden />}
        title={`Nothing matches “${query.trim()}”`}
        description="Try a ticket key, a word from the title, or a pull request like acme/api#412."
        action={
          <Button size="sm" variant="secondary" onClick={onClear}>
            Clear filter
          </Button>
        }
      />
    );
  }

  if (counts.all === 0) {
    return (
      <EmptyState
        icon={<ClipboardList aria-hidden />}
        title="Nothing is assigned to you"
        description="Open GitHub issues and Jira tickets assigned to the accounts you connected appear here automatically — there is nothing to configure."
        action={
          <Button asChild size="sm" variant="secondary">
            <Link href="/integrations">
              <Plug aria-hidden />
              Check your connections
            </Link>
          </Button>
        }
      />
    );
  }

  if (filter === "needs_you") {
    return (
      <EmptyState
        icon={<CheckCircle2 aria-hidden />}
        title="Nothing is waiting on you"
        description={
          counts.in_flight > 0
            ? `${counts.in_flight} ${counts.in_flight === 1 ? "task is" : "tasks are"} still moving — running, or waiting on someone else.`
            : "Every assigned task is settled."
        }
      />
    );
  }

  if (filter === "done") {
    return (
      <EmptyState
        compact
        icon={<CheckCircle2 aria-hidden />}
        title="Nothing signed off this week"
        description="Work appears here for seven days after the testing team signs it off."
      />
    );
  }

  return (
    <EmptyState
      compact
      icon={<ClipboardList aria-hidden />}
      title="Nothing in flight"
      description="Everything assigned to you is either waiting on you or already finished."
    />
  );
}
