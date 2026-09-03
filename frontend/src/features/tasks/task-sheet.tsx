"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  FileText,
  GitPullRequest,
  Play,
  RefreshCw,
  ShieldAlert,
  Ticket,
  UserRound,
} from "lucide-react";
import {
  analyzeTask,
  authorTask,
  getTaskAttempts,
  getTaskDetail,
  setTaskMode,
  type AuthoringAttempt,
  type CommLoop,
  type TaskCard,
  type TaskDetail,
} from "@/lib/api";
import { formatFull } from "@/lib/datetime";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/nav";
import { Sheet } from "@/components/ui/overlay";
import {
  EmptyState,
  Kicker,
  Notice,
  Panel,
  Section,
  Skeleton,
} from "@/components/ui/surface";
import { useToast } from "@/components/ui/toast";
import { AnalysisView } from "./analysis";
import { MessageRow, WorklistItemRow } from "./messages";
import { TaskProgress } from "./pipeline";
import { OUTCOME_LABEL, REVIEW_STATE, TASK_STAGE } from "./shared";

/**
 * Everything about one work item.
 *
 * A sheet rather than an inline accordion. The content is the same — the
 * pipeline, the review rounds, the analysis, every message across every pull
 * request on the ticket — but it now opens beside the queue instead of
 * displacing it, and it has room to render that content at a size a person can
 * read rather than at 10px.
 *
 * Four tabs, because the whole of it is far more than fits on a screen and
 * scrolling past two thousand words of message log to reach the mode switch is
 * not "everything in one place", it is everything in one column.
 */

type Tab = "overview" | "analysis" | "messages" | "agent";

const SOURCE_CAPTION: Record<string, string> = {
  work_item: "Set on this ticket, overriding the repository.",
  repo: "Inherited from this repository's settings.",
  defaults: "Inherited from your account defaults.",
  unset: "Nothing has been configured, so the safe default applies.",
  handed_back: "Handed back to you after the agent ran out of attempts.",
};

/**
 * Fill in any list the detail response left out.
 *
 * The same reasoning as the board's own normaliser: a dozen reads below call
 * `.length` or `.map` on these, and a response missing one key takes the sheet
 * down with a runtime error rather than rendering the parts that did arrive.
 */
const normalise = (detail: TaskDetail): TaskDetail => ({
  ...detail,
  events: detail.events ?? [],
  reviews: (detail.reviews ?? []).map((review) => ({
    ...review,
    rounds: review.rounds ?? [],
    pending_asks: review.pending_asks ?? [],
  })),
  reviewer_contacts: detail.reviewer_contacts ?? [],
  qa_recipients: detail.qa_recipients ?? [],
});

const TRIGGER_LABEL: Record<string, string> = {
  initial: "first attempt",
  changes_requested: "after a reviewer asked for changes",
  qa_rejected: "after the testing team rejected it",
};

export function TaskSheet({
  card,
  open,
  onClose,
  onChanged,
}: {
  card: TaskCard | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("overview");
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [attempts, setAttempts] = useState<AuthoringAttempt[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loopFilter, setLoopFilter] = useState<"all" | CommLoop>("all");

  const key = card?.key;

  const load = useCallback(async () => {
    if (!key) return;
    setLoading(true);
    try {
      setDetail(normalise(await getTaskDetail(key)));
    } catch (e) {
      toast.error(
        "Could not load this task",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setLoading(false);
    }
    // A failure here costs the history, never the task: the attempts are
    // context on the mode, and the pipeline is the point of the sheet.
    try {
      const rows = await getTaskAttempts(key);
      setAttempts(Array.isArray(rows) ? rows : []);
    } catch {
      setAttempts([]);
    }
  }, [key, toast]);

  // Reset to the first tab whenever a different task is opened — landing on
  // the message log of task B because that is where you left task A is
  // disorienting.
  useEffect(() => {
    if (!open || !key) return;
    setTab("overview");
    setDetail(null);
    setAttempts([]);
    load();
  }, [open, key, load]);

  if (!card) return null;

  const stage = TASK_STAGE[card.stage] ?? TASK_STAGE.assigned;

  const changeMode = async (mode: "assisted" | "autonomous" | null) => {
    setBusy(true);
    try {
      await setTaskMode(card.key, mode);
      toast.success(
        mode === null
          ? "Override cleared"
          : `${card.key} is now ${mode === "autonomous" ? "written by the agent" : "yours to write"}`
      );
      onChanged();
    } catch (e) {
      toast.error(
        "Could not change the mode",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setBusy(false);
    }
  };

  const runAuthoring = async () => {
    setBusy(true);
    try {
      const run = await authorTask(card.key);
      if (run.opened) {
        toast.success(`Opened pull request #${run.pr_number}`);
      } else {
        // Said plainly rather than swallowed. An attempt that opened nothing
        // has still been spent, and the person needs to know which.
        toast.error(
          "The agent opened no pull request",
          run.error ?? "That attempt is spent."
        );
      }
      const rows = await getTaskAttempts(card.key);
      setAttempts(Array.isArray(rows) ? rows : []);
      onChanged();
    } catch (e) {
      toast.error(
        "Could not start the agent",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setBusy(false);
    }
  };

  const runAnalysis = async () => {
    setBusy(true);
    try {
      await analyzeTask(card.key);
      toast.success("Analysis queued", "It will appear here when the run finishes.");
      onChanged();
    } catch (e) {
      toast.error(
        "Could not queue the analysis",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setBusy(false);
    }
  };

  const events =
    loopFilter === "all"
      ? (detail?.events ?? [])
      : (detail?.events ?? []).filter((e) => e.loop === loopFilter);

  const tabs = [
    { value: "overview" as const, label: "Overview" },
    { value: "analysis" as const, label: "Analysis" },
    {
      value: "messages" as const,
      label: "Messages",
      count: detail?.events.length ?? 0,
    },
    { value: "agent" as const, label: "Agent", count: attempts.length || undefined },
  ];

  return (
    <Sheet
      open={open}
      onClose={onClose}
      eyebrow={
        <div className="flex flex-wrap items-center gap-2">
          <Chip icon={card.source === "jira" ? <Ticket /> : <GitPullRequest />}>
            {card.key}
          </Chip>
          <Badge tone={stage.tone}>{stage.label}</Badge>
          {card.status && <Badge tone="neutral">{card.status}</Badge>}
          {card.issue_type && <Badge tone="neutral">{card.issue_type}</Badge>}
        </div>
      }
      title={card.title}
      footer={
        <>
          <Button asChild variant="secondary" size="sm">
            <a href={card.url} target="_blank" rel="noreferrer">
              Open in {card.source === "jira" ? "Jira" : "GitHub"}
              <ArrowUpRight aria-hidden />
            </a>
          </Button>
          {detail?.doc_url && (
            <Button asChild variant="secondary" size="sm">
              <a href={detail.doc_url} target="_blank" rel="noreferrer">
                <FileText aria-hidden />
                Report
              </a>
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={load}
            loading={loading}
            className="ml-auto"
          >
            {!loading && <RefreshCw aria-hidden />}
            Refresh
          </Button>
          {/* The board's writes are deliberate clicks. Everything that reaches
              other people stays driven by webhooks and the background loops —
              a dashboard refresh must never be able to notify a team twice. */}
          {card.pull_requests.length > 0 && (
            <Button size="sm" onClick={runAnalysis} loading={busy}>
              {!busy && <Play aria-hidden />}
              Re-run analysis
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-6">
        <TaskProgress stages={card.stages} />

        <div className="border-b border-line">
          <Segmented
            items={tabs}
            value={tab}
            onChange={setTab}
            ariaLabel="Task detail sections"
            className="mb-4"
          />
        </div>

        {loading && !detail ? (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <>
            {tab === "overview" && (
              <OverviewTab card={card} detail={detail} />
            )}

            {tab === "analysis" && (
              <>
                {detail?.job_status === "failed" && detail.job_error && (
                  <Notice
                    tone="danger"
                    icon={<AlertTriangle aria-hidden />}
                    title="The last run failed"
                    className="mb-4"
                  >
                    {detail.job_error}
                  </Notice>
                )}
                {detail?.analysis ? (
                  <AnalysisView result={detail.analysis} />
                ) : (
                  <EmptyState
                    icon={<ShieldAlert aria-hidden />}
                    title="No analysis yet"
                    description={
                      card.pull_requests.length === 0
                        ? "An analysis runs against a pull request. This work item does not have one open."
                        : "The next push to this pull request triggers a run, or start one now."
                    }
                    action={
                      card.pull_requests.length > 0 && (
                        <Button size="sm" onClick={runAnalysis} loading={busy}>
                          {!busy && <Play aria-hidden />}
                          Run analysis
                        </Button>
                      )
                    }
                  />
                )}
              </>
            )}

            {tab === "messages" && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <Kicker>
                    Every message on this work item, across every pull request
                  </Kicker>
                  <Segmented
                    size="sm"
                    ariaLabel="Filter messages by loop"
                    value={loopFilter}
                    onChange={setLoopFilter}
                    items={[
                      { value: "all", label: "All" },
                      { value: "review", label: "Review" },
                      { value: "qa", label: "Testing" },
                      { value: "context", label: "Context" },
                    ]}
                  />
                </div>

                {events.length === 0 ? (
                  <EmptyState
                    compact
                    title="Nothing recorded"
                    description={
                      loopFilter === "all"
                        ? "No searches, sends or replies have been logged against this work item yet."
                        : "No messages in this loop. Try All."
                    }
                  />
                ) : (
                  <div className="space-y-5">
                    {events.map((e) => (
                      <MessageRow key={e.id} event={e} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === "agent" && (
              <AgentTab
                card={card}
                attempts={attempts}
                busy={busy}
                onChangeMode={changeMode}
                onRun={runAuthoring}
              />
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}

/* ── Overview ─────────────────────────────────────────────────────────────── */

function OverviewTab({
  card,
  detail,
}: {
  card: TaskCard;
  detail: TaskDetail | null;
}) {
  return (
    <div className="space-y-6">
      {/* What is waiting on you, first. */}
      {(card.items ?? []).length > 0 && (
        <Panel tone="accent" className="p-4">
          <Kicker className="text-accent-strong">Needs you</Kicker>
          <div className="mt-3 space-y-4">
            {(card.items ?? []).map((item, i) => (
              <WorklistItemRow key={i} item={item} />
            ))}
          </div>
        </Panel>
      )}

      {/* The requirement, in the words of whoever filed it. Above the loops
          because a task with no pull request yet has nothing else describing
          what it actually is. */}
      {card.description && (
        <Section title="Description">
          <Panel tone="quiet" className="p-4">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
              {card.description.trim()}
            </p>
          </Panel>
        </Section>
      )}

      {/* Where each loop stands right now. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Panel tone="quiet" className="p-4">
          <Kicker>Senior dev review</Kicker>
          {!detail || detail.reviews.length === 0 ? (
            <p className="mt-2 text-sm text-muted">Not started</p>
          ) : (
            detail.reviews.map((review) => (
              <div key={review.id} className="mt-2">
                <p className="text-sm font-medium text-ink">
                  {REVIEW_STATE[review.state].label}
                  <span className="ml-1.5 font-normal text-muted">
                    round {review.round_number}
                  </span>
                </p>
                {review.pending_asks.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {review.pending_asks.map((ask, i) => (
                      <li key={i} className="flex gap-2 text-sm text-muted">
                        <span className="text-subtle" aria-hidden>
                          •
                        </span>
                        {ask}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))
          )}

          {detail && detail.reviewer_contacts.length > 0 && (
            <ul className="mt-3 space-y-1.5 border-t border-line pt-3">
              {detail.reviewer_contacts.map((c) => (
                <li key={c.login} className="text-xs">
                  <span className="font-mono text-ink">{c.login}</span>
                  {c.slack && <span className="text-muted"> · {c.slack}</span>}
                  {c.email && <span className="text-muted"> · {c.email}</span>}
                  {!c.slack && !c.email && (
                    <span className="text-subtle"> · no contact configured</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel tone="quiet" className="p-4">
          <Kicker>Testing team</Kicker>
          <p className="mt-2 text-sm font-medium text-ink">
            {!detail?.qa_notified
              ? "Not started"
              : detail.qa_resolved
                ? "Signed off"
                : "Awaiting tester"}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-muted">
            {detail?.qa_channel && <li>Slack · {detail.qa_channel}</li>}
            {detail?.qa_recipients.map((r) => (
              <li key={r}>Email · {r}</li>
            ))}
            {!detail?.qa_channel && !detail?.qa_recipients.length && (
              <li className="text-subtle">
                No QA channel or recipients configured
              </li>
            )}
          </ul>
        </Panel>
      </div>

      {/* Review rounds, oldest first. */}
      {detail?.reviews.some((r) => r.rounds.length > 0) && (
        <Section title="Review rounds">
          <ol className="space-y-3">
            {detail.reviews.flatMap((review) =>
              review.rounds.map((round, i) => (
                <li key={`${review.id}-${i}`} className="flex gap-3">
                  <span className="tabular mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-pill border border-line bg-surface-2 text-xs font-medium text-muted">
                    {round.round_number}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">
                      <span className="font-medium text-ink">
                        {OUTCOME_LABEL[round.outcome] ?? round.outcome}
                      </span>
                      {round.reviewer && (
                        <span className="text-muted"> — {round.reviewer}</span>
                      )}
                    </p>
                    {round.body && (
                      <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-muted">
                        {round.body}
                      </p>
                    )}
                  </div>
                </li>
              ))
            )}
          </ol>
        </Section>
      )}
    </div>
  );
}

/* ── Agent ────────────────────────────────────────────────────────────────── */

function AgentTab({
  card,
  attempts,
  busy,
  onChangeMode,
  onRun,
}: {
  card: TaskCard;
  attempts: AuthoringAttempt[];
  busy: boolean;
  onChangeMode: (mode: "assisted" | "autonomous" | null) => void;
  onRun: () => void;
}) {
  const autonomous = card.authoring_mode === "autonomous" && !card.handed_back;

  return (
    <div className="space-y-6">
      {/* Autonomy is a judgement about *this* work item — a dependency bump
          and a change to the credential path are not the same risk — so the
          switch lives on the task rather than only in settings. */}
      <Section
        title="Who writes this"
        description={
          card.handed_back
            ? `Handed back${card.handed_back_reason ? `: ${card.handed_back_reason}` : ""}. Choosing a mode puts it back in play.`
            : (SOURCE_CAPTION[card.authoring_source] ??
              `Set by: ${card.authoring_source}`)
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            ariaLabel="Who writes the code for this work item"
            value={card.handed_back ? ("none" as never) : card.authoring_mode}
            onChange={(v) => onChangeMode(v as "assisted" | "autonomous")}
            items={[
              { value: "assisted", label: "You write it", icon: <UserRound /> },
              { value: "autonomous", label: "Agent writes it", icon: <Bot /> },
            ]}
          />

          {card.authoring_source === "work_item" && (
            <Button
              variant="link"
              size="sm"
              disabled={busy}
              onClick={() => onChangeMode(null)}
            >
              Clear override
            </Button>
          )}

          {autonomous && (
            <Button size="sm" className="ml-auto" onClick={onRun} loading={busy}>
              {!busy && <Play aria-hidden />}
              Write it now
            </Button>
          )}
        </div>

        {autonomous && (
          <Notice
            tone="warning"
            icon={<AlertTriangle aria-hidden />}
            title="This brief leaves your machine"
            className="mt-4"
          >
            The ticket description, the Slack discussion and your source go to
            the model OpenCode is configured with, which is remote. Every model
            that reads your code <strong>automatically</strong> — the scanner,
            the reviewer, the QA classifier — still runs locally.
          </Notice>
        )}
      </Section>

      {/* Where a handed-back item explains itself. "The agent has tried three
          things" and "the agent tried once and a reviewer pushed back twice"
          are different situations, and only the trigger on each row tells them
          apart. */}
      <Section
        title={`${attempts.length} attempt${attempts.length === 1 ? "" : "s"}`}
      >
        {attempts.length === 0 ? (
          <EmptyState
            compact
            icon={<Bot aria-hidden />}
            title="The agent has not run on this"
            description="Every failure spends an attempt — a timeout, an oversized diff, a denylisted path or a failed test gate all count."
          />
        ) : (
          <ol className="space-y-2">
            {attempts.map((attempt) => (
              <Panel key={attempt.id} tone="quiet" className="p-4" as="li">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="tabular font-mono text-sm font-semibold text-ink">
                    #{attempt.attempt}
                  </span>
                  <Badge tone={attempt.opened ? "success" : "neutral"}>
                    {attempt.opened
                      ? `opened #${attempt.pr_number}`
                      : "opened nothing"}
                  </Badge>
                  <span className="text-sm text-muted">
                    {TRIGGER_LABEL[attempt.trigger] ?? attempt.trigger}
                  </span>
                  {attempt.created_at && (
                    <span className="ml-auto shrink-0 text-xs text-subtle">
                      {formatFull(attempt.created_at)}
                    </span>
                  )}
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {/* Recorded per attempt rather than read from config now:
                      "which model wrote this" is asked after the fact, when
                      the config value has already moved on. */}
                  {attempt.model && <Chip>{attempt.model}</Chip>}
                  {attempt.context_mode === "ticket_only" && (
                    <Chip
                      mono={false}
                      title="The internal discussion was withheld from this run"
                    >
                      ticket only
                    </Chip>
                  )}
                  {attempt.opened && (
                    <Chip mono={false}>
                      {attempt.files_changed} file
                      {attempt.files_changed === 1 ? "" : "s"} ·{" "}
                      {attempt.lines_changed} lines
                    </Chip>
                  )}
                </div>

                {attempt.error && (
                  <pre className="mt-2.5 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-warning-border bg-warning-soft p-3 font-mono text-xs leading-relaxed text-ink">
                    {attempt.error.slice(0, 2000)}
                  </pre>
                )}
              </Panel>
            ))}
          </ol>
        )}
      </Section>
    </div>
  );
}
