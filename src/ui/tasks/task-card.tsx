import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
} from "lucide-react";
import {
  analyzeTask,
  getTaskDetail,
  type TaskCard as TaskCardData,
  type TaskDetail,
  type TaskStage,
} from "@/lib/api";
import { OUTCOME_LABEL, REVIEW_STATE_STYLE, ageLabel } from "./shared";
import { MessageRow, WorklistItemRow } from "./messages";
import { AnalysisView } from "./analysis";

/**
 * The pipeline, as a horizontal stepper.
 *
 * Every stage is rendered, including the ones not yet reached, because the
 * point of the card is to show the whole automated run -- from the ticket
 * landing on someone to the testing team signing off. A stepper that only
 * showed the stages already visited would answer "what happened" but not
 * "what happens next", which is the question someone opening the board has.
 */
const StageStepper = ({ stages }: { stages: TaskCardData["stages"] }) => (
  <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
    {stages.map((stage, i) => {
      const done = stage.state === "done";
      const current = stage.state === "running";

      return (
        <li key={stage.stage} className="flex items-center gap-1">
          <div
            className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${
              current
                ? "border-primary bg-primary/10 text-primary"
                : done
                  ? "border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400"
                  : "border-border bg-muted/40 text-muted-foreground"
            }`}
            title={stage.detail ?? undefined}
          >
            <span className="font-mono text-[10px] leading-none">
              {done ? "✓" : current ? "●" : "○"}
            </span>
            <span className="whitespace-nowrap text-[10px] font-medium">
              {stage.label}
            </span>
            {stage.detail && (
              <span className="whitespace-nowrap text-[10px] opacity-70">
                {stage.detail}
              </span>
            )}
          </div>
          {i < stages.length - 1 && (
            <span className="text-[10px] text-muted-foreground/50">→</span>
          )}
        </li>
      );
    })}
  </ol>
);

const SOURCE_STYLE: Record<string, string> = {
  github: "bg-slate-500/10 text-slate-600 dark:text-slate-300",
  jira: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
};

/** Stages that mean the work is finished, for the muted card treatment. */
const SETTLED: TaskStage[] = ["done"];

/**
 * One assigned task, expandable to its whole pipeline.
 *
 * Collapsed, it answers "where is this and is it waiting on me". Expanded, it
 * carries everything the old per-PR views showed -- the analysis, the review
 * rounds, and every message searched, sent and received -- keyed by work item
 * rather than by pull request, so the second PR on a ticket shows the first
 * one's discussion instead of starting from nothing.
 */
export const TaskCard = ({
  card,
  onChanged,
}: {
  card: TaskCardData;
  onChanged: () => void;
}) => {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "review" | "qa" | "context">("all");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await getTaskDetail(card.key));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load this task");
    } finally {
      setLoading(false);
    }
  };

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) await load();
  };

  const runAnalysis = async () => {
    setBusy(true);
    setError(null);
    try {
      await analyzeTask(card.key);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not queue the analysis");
    } finally {
      setBusy(false);
    }
  };

  const settled = SETTLED.includes(card.stage);
  const events =
    filter === "all"
      ? (detail?.events ?? [])
      : (detail?.events ?? []).filter((e) => e.loop === filter);

  return (
    <div
      className={`rounded-xl border ${
        card.needs_you
          ? "border-orange-500/40 bg-card"
          : settled
            ? "border-border/60 bg-muted/20"
            : "border-border bg-card"
      }`}
    >
      <button
        onClick={toggle}
        className="flex w-full items-start gap-2.5 p-4 text-left hover:bg-muted/40"
      >
        <span className="mt-0.5 shrink-0 text-muted-foreground">
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                SOURCE_STYLE[card.source]
              }`}
            >
              {card.source}
            </span>
            <span className="font-mono text-xs font-semibold text-foreground">
              {card.key}
            </span>
            {card.status && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {card.status}
              </span>
            )}
            {card.issue_type && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {card.issue_type}
              </span>
            )}
            {card.round_number > 1 && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                round {card.round_number}
              </span>
            )}
            {card.age_hours > 0 && (
              <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                {ageLabel(card.age_hours)}
              </span>
            )}
          </div>

          <p className="mt-1 text-sm font-medium text-foreground">{card.title}</p>

          {/* Why it is stuck, in the words of whoever stuck it. */}
          {card.blocked_reason && (
            <p className="mt-1 flex items-center gap-1.5 text-xs text-orange-600 dark:text-orange-400">
              <AlertTriangle size={11} className="shrink-0" />
              {card.blocked_reason}
            </p>
          )}

          <div className="mt-2.5">
            <StageStepper stages={card.stages} />
          </div>

          {card.pull_requests.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {card.pull_requests.map((pr) => (
                <span
                  key={`${pr.repo}#${pr.pr_number}`}
                  className="flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {pr.repo}#{pr.pr_number}
                  {pr.review_state && (
                    <span
                      className={`rounded px-1 ${REVIEW_STATE_STYLE[pr.review_state].className}`}
                    >
                      {REVIEW_STATE_STYLE[pr.review_state].label}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>
      </button>

      {open && (
        <div className="space-y-4 border-t border-border p-4">
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={card.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Open in {card.source === "jira" ? "Jira" : "GitHub"}{" "}
              <ExternalLink size={11} />
            </a>
            {card.pull_requests.map((pr) =>
              pr.url ? (
                <a
                  key={pr.pr_number}
                  href={pr.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  {pr.repo}#{pr.pr_number} <ExternalLink size={11} />
                </a>
              ) : null
            )}

            <div className="ml-auto flex gap-2">
              <button
                onClick={load}
                disabled={loading}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[11px] hover:bg-muted disabled:opacity-50"
              >
                <RefreshCw size={11} /> Refresh
              </button>
              {/* The only write the board offers. Everything that reaches
                  other people stays driven by the webhooks and the loops. */}
              {card.pull_requests.length > 0 && (
                <button
                  onClick={runAnalysis}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {busy ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <Play size={11} />
                  )}
                  Re-run analysis
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-400">
              {error}
            </div>
          )}

          {loading && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> Loading pipeline…
            </div>
          )}

          {detail && (
            <>
              {/* What is waiting on you, first. */}
              {detail.card.items.length > 0 && (
                <section className="rounded-lg border border-orange-500/30 bg-orange-500/5 p-3">
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-orange-600 dark:text-orange-400">
                    Needs you
                  </p>
                  <div className="space-y-2.5">
                    {detail.card.items.map((item, i) => (
                      <WorklistItemRow key={i} item={item} />
                    ))}
                  </div>
                </section>
              )}

              {/* Where each loop stands right now. */}
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-indigo-500/30 bg-indigo-500/5 p-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600 dark:text-indigo-400">
                    Senior dev review
                  </p>
                  {detail.reviews.length === 0 ? (
                    <p className="mt-1 text-sm text-muted-foreground">Not started</p>
                  ) : (
                    detail.reviews.map((review) => (
                      <div key={review.id} className="mt-1">
                        <p className="text-sm font-medium text-foreground">
                          {REVIEW_STATE_STYLE[review.state].label}
                          <span className="ml-1 text-xs font-normal text-muted-foreground">
                            · round {review.round_number}
                          </span>
                        </p>
                        {review.pending_asks.length > 0 && (
                          <ul className="mt-1 space-y-0.5">
                            {review.pending_asks.map((ask, i) => (
                              <li key={i} className="text-[11px] text-muted-foreground">
                                • {ask}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))
                  )}

                  {detail.reviewer_contacts.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {detail.reviewer_contacts.map((c) => (
                        <li key={c.login} className="text-[11px] text-muted-foreground">
                          <span className="text-foreground">{c.login}</span>
                          {c.slack && <span> · {c.slack}</span>}
                          {c.email && <span> · {c.email}</span>}
                          {!c.slack && !c.email && (
                            <span className="italic"> · no contact configured</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="rounded-lg border border-teal-500/30 bg-teal-500/5 p-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-teal-600 dark:text-teal-400">
                    Testing team
                  </p>
                  <p className="mt-1 text-sm font-medium text-foreground">
                    {!detail.qa_notified
                      ? "not started"
                      : detail.qa_resolved
                        ? "signed off"
                        : "awaiting tester"}
                  </p>
                  <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                    {detail.qa_channel && <li>Slack · {detail.qa_channel}</li>}
                    {detail.qa_recipients.map((r) => (
                      <li key={r}>Email · {r}</li>
                    ))}
                    {!detail.qa_channel && detail.qa_recipients.length === 0 && (
                      <li className="italic">No QA channel or recipients configured</li>
                    )}
                  </ul>
                </div>
              </div>

              {/* Review rounds, oldest first. */}
              {detail.reviews.some((r) => r.rounds.length > 0) && (
                <section>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Review rounds
                  </p>
                  <div className="space-y-2">
                    {detail.reviews.flatMap((review) =>
                      review.rounds.map((round, i) => (
                        <div key={`${review.id}-${i}`} className="flex gap-2 text-xs">
                          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                            {round.round_number}
                          </span>
                          <div className="min-w-0 flex-1">
                            <span className="font-medium text-foreground">
                              {OUTCOME_LABEL[round.outcome] ?? round.outcome}
                            </span>
                            {round.reviewer && (
                              <span className="text-muted-foreground">
                                {" "}
                                — {round.reviewer}
                              </span>
                            )}
                            {round.body && (
                              <p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">
                                {round.body}
                              </p>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              )}

              {/* The analysis of the newest PR. Findings never carry across
                  rounds, so this is what the latest run actually produced. */}
              {detail.job_status === "failed" && detail.job_error && (
                <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
                  {detail.job_error}
                </div>
              )}
              {detail.analysis && (
                <section>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Latest analysis
                  </p>
                  <AnalysisView result={detail.analysis} />
                </section>
              )}

              {/* Every message, across every PR on this work item. */}
              <section>
                <div className="mb-2 flex items-center gap-1.5">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Messages ({detail.events.length})
                  </p>
                  <div className="ml-auto flex gap-1">
                    {(["all", "review", "qa", "context"] as const).map((f) => (
                      <button
                        key={f}
                        onClick={() => setFilter(f)}
                        className={`rounded px-1.5 py-0.5 text-[10px] ${
                          filter === f
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-muted-foreground hover:bg-muted/70"
                        }`}
                      >
                        {f === "all"
                          ? "All"
                          : f === "qa"
                            ? "Testing"
                            : f === "review"
                              ? "Review"
                              : "Context"}
                      </button>
                    ))}
                  </div>
                </div>

                {events.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-border p-4 text-center text-[11px] text-muted-foreground">
                    No messages recorded{filter !== "all" && " for this loop"}.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {events.map((e) => (
                      <MessageRow key={e.id} event={e} />
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </div>
  );
};
