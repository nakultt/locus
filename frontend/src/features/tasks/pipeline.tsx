"use client";

import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Minus, X } from "lucide-react";
import type {
  LinkedIssue,
  PipelineStage,
  ReviewFinding,
  SecurityFinding,
  TaskStageStatus,
  ToolInvocation,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Kicker, Panel } from "@/components/ui/surface";
import { PRIORITY_TONE, SEVERITY_TONE, STAGE_TOOLS } from "./shared";
import { cn } from "@/lib/utils";

/**
 * The pipeline, in its three renderings.
 *
 * All three answer a different question and so look different on purpose:
 * `TaskProgress` is "how far has this got and what happens next", shown on a
 * board row; `StageChecklist` is "what did this run gather and do", shown on a
 * job row; `StageTimeline` is the same list at reading size inside the sheet.
 */

/* ── Task progress ────────────────────────────────────────────────────────── */

const NODE = {
  done: "border-success bg-success text-white",
  running: "border-accent bg-accent text-accent-fg",
  failed: "border-danger bg-danger text-white",
  skipped: "border-line bg-surface-2 text-subtle",
  pending: "border-line bg-surface text-subtle",
} as const;

/**
 * Where the work has got to, as a rail.
 *
 * Every stage is rendered, including the ones not yet reached, because the
 * point of the card is to show the whole automated run — from the ticket
 * landing on someone to the testing team signing off. A stepper that only
 * showed the stages already visited would answer "what happened" but not
 * "what happens next", which is the question someone opening the board has.
 *
 * The connector between two nodes is filled only when the *earlier* one is
 * done, so the rail reads as a level rather than as a row of disconnected
 * chips. That is the whole difference between this and the pill strip it
 * replaces, which wrapped onto three lines on a narrow window and lost its
 * order entirely.
 */
export function TaskProgress({
  stages,
  className,
}: {
  stages: TaskStageStatus[];
  className?: string;
}) {
  if (stages.length === 0) return null;

  // A *container* query, not a viewport one. This rail renders both across a
  // full-width board row and inside a 736px sheet on the same screen, so a
  // `lg:` breakpoint showed nine labels in both and overflowed the narrower of
  // them. Measuring the box it is actually in is the only thing that answers
  // the question being asked. It scrolls rather than truncating when even that
  // is not enough, because a rail with its tail cut off silently misreports
  // how far the work has got.
  return (
    <ol
      className={cn("@container scroll-x flex items-center pb-0.5", className)}
      aria-label="Pipeline progress"
    >
      {stages.map((stage, i) => {
        const state = stage.state;
        const isLast = i === stages.length - 1;
        const filled = state === "done";

        return (
          <li key={stage.stage} className="flex min-w-0 items-center">
            <span
              className="group/node relative flex shrink-0 items-center"
              title={
                stage.detail ? `${stage.label} — ${stage.detail}` : stage.label
              }
            >
              <span
                className={cn(
                  "flex size-5 items-center justify-center rounded-pill border transition-colors",
                  NODE[state] ?? NODE.pending
                )}
              >
                {state === "done" ? (
                  <Check className="size-3" strokeWidth={3} aria-hidden />
                ) : state === "failed" ? (
                  <X className="size-3" strokeWidth={3} aria-hidden />
                ) : state === "skipped" ? (
                  <Minus className="size-3" strokeWidth={3} aria-hidden />
                ) : state === "running" ? (
                  <span className="size-1.5 animate-pulse rounded-pill bg-current" />
                ) : (
                  <span className="size-1.5 rounded-pill bg-current opacity-40" />
                )}
              </span>

              {/* The label rides under its node on wide screens and is dropped
                  on narrow ones, where the rail alone still carries progress
                  and the stage name is available on hover and to the label
                  below the rail. */}
              <span
                className={cn(
                  "ml-2 hidden whitespace-nowrap text-xs @3xl:inline",
                  state === "running"
                    ? "font-medium text-ink"
                    : filled
                      ? "text-muted"
                      : "text-subtle"
                )}
              >
                {stage.label}
              </span>
            </span>

            {!isLast && (
              <span
                aria-hidden
                className={cn(
                  "mx-1 h-px w-2 shrink-0 @sm:mx-2 @sm:w-4 @3xl:w-6",
                  filled ? "bg-success/50" : "bg-line"
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

/* ── Stage lists ──────────────────────────────────────────────────────────── */

const StageGlyph = ({ state }: { state: PipelineStage["state"] }) => {
  const map = {
    done: { icon: Check, tone: "text-success" },
    failed: { icon: X, tone: "text-danger" },
    skipped: { icon: Minus, tone: "text-subtle" },
    running: { icon: null, tone: "text-info" },
    pending: { icon: null, tone: "text-subtle" },
  } as const;

  const entry = map[state] ?? map.pending;
  const Icon = entry.icon;

  return (
    <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center", entry.tone)} aria-hidden>
      {Icon ? (
        <Icon className="size-3.5" strokeWidth={2.75} />
      ) : (
        <span
          className={cn(
            "size-1.5 rounded-pill bg-current",
            state === "running" && "animate-pulse"
          )}
        />
      )}
    </span>
  );
};

/**
 * What the agent gathered and what it did about it.
 *
 * Reads and writes are separated because they carry different weight: a
 * skipped read means thinner context, a skipped write means nothing changed
 * outside Locus. Every step is listed even when skipped — a run that gathered
 * nothing should read as "Jira was not connected", not as an empty result.
 */
export function StageTimeline({ stages }: { stages: PipelineStage[] }) {
  const reads = stages.filter((s) => s.kind === "read");
  const writes = stages.filter((s) => s.kind === "write");

  const group = (title: string, items: PipelineStage[]) =>
    items.length === 0 ? null : (
      <div>
        <Kicker>{title}</Kicker>
        <ul className="mt-2 space-y-1.5">
          {items.map((stage) => (
            <li key={stage.key} className="flex items-start gap-2.5 text-sm">
              <StageGlyph state={stage.state} />
              <span
                className={
                  stage.state === "skipped" ? "text-subtle" : "text-ink"
                }
              >
                {stage.label}
                {stage.detail && (
                  <span className="text-muted"> — {stage.detail}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>
    );

  return (
    <Panel tone="quiet" className="grid gap-5 p-4 sm:grid-cols-2">
      {group("Gathered", reads)}
      {group("Actions taken", writes)}
    </Panel>
  );
}

/** The compact variant, on a collapsed run row. */
export function StageChecklist({
  stages,
  toolCalls = [],
}: {
  stages: PipelineStage[];
  toolCalls?: ToolInvocation[];
}) {
  if (stages.length === 0) return null;

  const reads = stages.filter((s) => s.kind === "read");
  const writes = stages.filter((s) => s.kind === "write");

  const column = (title: string, items: PipelineStage[]) =>
    items.length === 0 ? null : (
      <div className="min-w-0 flex-1">
        <Kicker>{title}</Kicker>
        <ul className="mt-1.5 space-y-1">
          {items.map((stage) => {
            // The searches behind this step, so "2 threads" can be checked
            // against what was actually queried and found.
            const calls = toolCalls.filter((c) =>
              (STAGE_TOOLS[stage.key] ?? []).includes(c.tool)
            );
            return (
              <li key={stage.key} className="text-xs">
                <div className="flex items-start gap-2">
                  <StageGlyph state={stage.state} />
                  <span
                    className={cn(
                      "min-w-0 truncate",
                      stage.state === "skipped" ? "text-subtle" : "text-ink"
                    )}
                  >
                    {stage.label}
                  </span>
                  {stage.detail && stage.state !== "skipped" && (
                    <span className="shrink-0 text-muted">{stage.detail}</span>
                  )}
                </div>
                {stage.state !== "skipped" &&
                  calls.map((call, i) => (
                    <div key={i} className="ml-6 mt-1 space-y-0.5">
                      {call.query && (
                        <p
                          className="truncate font-mono text-xs text-subtle"
                          title={call.query}
                        >
                          {call.query}
                        </p>
                      )}
                      {call.matches?.map((match, m) => (
                        <p
                          key={m}
                          className="truncate text-xs text-subtle"
                          title={match}
                        >
                          ↳ {match}
                        </p>
                      ))}
                    </div>
                  ))}
              </li>
            );
          })}
        </ul>
      </div>
    );

  return (
    <div className="flex flex-col gap-4 border-t border-line bg-surface-2/40 px-5 py-3.5 sm:flex-row sm:gap-8">
      {column("Gathered", reads)}
      {column("Actions taken", writes)}
    </div>
  );
}

/* ── Findings ─────────────────────────────────────────────────────────────── */

const FINDING_TONE = {
  neutral: "border-line bg-surface-2",
  accent: "border-accent/35 bg-accent-soft",
  success: "border-success-border bg-success-soft",
  warning: "border-warning-border bg-warning-soft",
  danger: "border-danger-border bg-danger-soft",
  info: "border-info-border bg-info-soft",
} as const;

/**
 * One finding.
 *
 * The severity is a badge rather than the panel's whole colour: a page of
 * solid red blocks is unreadable, and the file path — which is what someone
 * acts on — has to stay legible. The tint is a hint; the badge is the claim.
 */
function Finding({
  title,
  tone,
  tag,
  file,
  line,
  description,
}: {
  title: string;
  tone: keyof typeof FINDING_TONE;
  tag: string;
  file: string;
  line?: number | null;
  description?: string | null;
}) {
  return (
    <div className={cn("rounded-md border px-4 py-3", FINDING_TONE[tone])}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
        <p className="min-w-0 flex-1 text-sm font-medium text-ink">{title}</p>
        <Badge tone={tone}>{tag}</Badge>
      </div>
      <code className="mt-1.5 block break-all font-mono text-xs text-muted">
        {file}
        {line ? `:${line}` : ""}
      </code>
      {description && (
        <p className="mt-2 text-sm leading-relaxed text-muted">{description}</p>
      )}
    </div>
  );
}

export const FindingRow = ({ finding }: { finding: SecurityFinding }) => (
  <Finding
    title={finding.title}
    tone={SEVERITY_TONE[finding.severity]}
    tag={finding.severity}
    file={finding.file_path}
    line={finding.line}
    description={finding.description}
  />
);

export const ReviewRow = ({ finding }: { finding: ReviewFinding }) => (
  <Finding
    title={finding.title}
    tone={PRIORITY_TONE[finding.priority]}
    tag={`${finding.priority} · ${finding.category}`}
    file={finding.file_path}
    line={finding.line}
    description={finding.description}
  />
);

/* ── Linked issue ─────────────────────────────────────────────────────────── */

/**
 * One linked or mentioned GitHub issue, expandable to the text a human wrote.
 *
 * "Closes" and "Mentions" are labelled differently and deliberately: only a
 * formally closing issue is closed on merge, and rendering both identically
 * would overstate what the PR is claiming about a bare `#12`.
 */
export function IssueRow({ issue }: { issue: LinkedIssue }) {
  const [open, setOpen] = useState(false);
  const hasBody = Boolean(issue.body?.trim());
  const closes = issue.relation === "closes";

  return (
    <div className="rounded-md border border-line bg-surface-2/60 px-4 py-3">
      <div className="flex items-start gap-2.5">
        {hasBody ? (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="mt-0.5 shrink-0 rounded-xs text-subtle transition-colors hover:text-ink"
            aria-label={open ? "Hide issue text" : "Show issue text"}
          >
            {open ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        ) : (
          <span className="mt-0.5 w-4 shrink-0" aria-hidden />
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              tone={closes ? "accent" : "neutral"}
              title={
                closes
                  ? "Formally linked — closed automatically when this PR merges"
                  : "Bare #N reference — left alone on merge"
              }
            >
              {closes ? "Closes" : "Mentions"}
            </Badge>
            <a
              href={issue.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-sm font-medium text-accent-strong underline-offset-2 hover:underline"
            >
              #{issue.number}
            </a>
            <span className="text-xs text-subtle">{issue.state}</span>
          </div>
          <p className="mt-1 text-sm text-ink">{issue.title}</p>
          {issue.author && (
            <p className="mt-0.5 text-xs text-subtle">opened by {issue.author}</p>
          )}
        </div>
      </div>

      {open && hasBody && (
        <pre className="scroll-x mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-sm bg-surface p-3 font-mono text-xs leading-relaxed text-ink">
          {issue.body}
        </pre>
      )}
    </div>
  );
}
