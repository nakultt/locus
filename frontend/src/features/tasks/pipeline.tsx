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

export function TaskProgress({
  stages,
  className,
}: {
  stages: TaskStageStatus[];
  className?: string;
}) {
  if (stages.length === 0) return null;

  const completedCount = stages.filter((s) => s.state === "done").length;
  const runningStage = stages.find((s) => s.state === "running");
  const failedStage = stages.find((s) => s.state === "failed");
  const lastDoneStage = [...stages].reverse().find((s) => s.state === "done");
  const allDone =
    stages.length > 0 &&
    stages.every((s) => s.state === "done" || s.state === "skipped");

  return (
    <div className={cn("w-full", className)}>
      {/* ── Multi-line Wrapped Stepper (No scrollbar, wraps to second line) ── */}
      <ol
        className="flex flex-wrap items-center gap-x-2 gap-y-2 py-0.5"
        aria-label="Pipeline progress"
      >
        {stages.map((stage, i) => {
          const state = stage.state;
          const isLast = i === stages.length - 1;
          const isDone = state === "done";
          const isRunning = state === "running";
          const isFailed = state === "failed";
          const isSkipped = state === "skipped";

          return (
            <li
              key={stage.stage}
              className="flex items-center gap-2"
            >
              {/* Stage Chip with Node Icon and Visible Text */}
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-pill transition-colors",
                  isRunning
                    ? "border border-accent/40 bg-accent-soft px-2.5 py-1 text-ink shadow-xs"
                    : "py-0.5"
                )}
                title={`${String(i + 1).padStart(2, "0")}. ${stage.label} — ${state}${stage.detail ? ` (${stage.detail})` : ""}`}
              >
                {/* Node icon circle */}
                <span
                  className={cn(
                    "flex size-4.5 shrink-0 items-center justify-center rounded-pill border transition-all duration-200",
                    isDone && "border-success bg-success text-white",
                    isRunning && "border-accent bg-accent text-accent-fg",
                    isFailed && "border-danger bg-danger text-white",
                    isSkipped && "border-line bg-surface-2 text-subtle",
                    state === "pending" && "border-line bg-surface text-subtle/50"
                  )}
                >
                  {isDone ? (
                    <Check className="size-2.5 stroke-[3]" aria-hidden />
                  ) : isFailed ? (
                    <X className="size-2.5 stroke-[3]" aria-hidden />
                  ) : isSkipped ? (
                    <Minus className="size-2.5 stroke-[3]" aria-hidden />
                  ) : isRunning ? (
                    <span className="size-1.5 rounded-pill bg-current animate-pulse" />
                  ) : (
                    <span className="size-1 rounded-pill bg-current opacity-40" />
                  )}
                </span>

                {/* Visible Stage Text (Never clipped or hidden) */}
                <span
                  className={cn(
                    "whitespace-nowrap text-xs transition-colors",
                    isRunning
                      ? "font-medium text-ink"
                      : isDone
                        ? "text-muted"
                        : isFailed
                          ? "font-medium text-danger"
                          : "text-subtle"
                  )}
                >
                  {stage.label}
                </span>
              </span>

              {/* Directional chevron separator */}
              {!isLast && (
                <ChevronRight
                  className={cn(
                    "size-3 shrink-0 transition-colors",
                    isDone ? "text-success/50" : "text-subtle/40"
                  )}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>

      {/* ── Active Stage Summary Caption ─────────────────────────────────── */}
      <div className="mt-2 flex items-center justify-between gap-3 text-xs">
        <div className="min-w-0 flex items-center gap-1.5 truncate">
          {allDone ? (
            <span className="flex items-center gap-1.5 text-success font-medium">
              <Check className="size-3.5 stroke-[2.5]" aria-hidden />
              <span>Pipeline complete · All {stages.length} stages passed</span>
            </span>
          ) : runningStage ? (
            <span className="flex items-center gap-1.5 text-ink font-medium">
              <span className="size-1.5 rounded-pill bg-accent animate-pulse" aria-hidden />
              <span className="truncate">
                Current: {runningStage.label}
                {runningStage.detail ? (
                  <span className="font-normal text-muted"> — {runningStage.detail}</span>
                ) : null}
              </span>
            </span>
          ) : failedStage ? (
            <span className="flex items-center gap-1.5 text-danger font-medium">
              <X className="size-3.5 stroke-[2.5]" aria-hidden />
              <span className="truncate">
                Failed at {failedStage.label}
                {failedStage.detail ? (
                  <span className="font-normal text-danger/80"> — {failedStage.detail}</span>
                ) : null}
              </span>
            </span>
          ) : completedCount > 0 && lastDoneStage ? (
            <span className="flex items-center gap-1.5 text-muted">
              <Check className="size-3.5 text-success" aria-hidden />
              <span className="truncate">
                Completed: {lastDoneStage.label}
                {lastDoneStage.detail ? <span> — {lastDoneStage.detail}</span> : null}
              </span>
            </span>
          ) : (
            <span className="text-subtle">Ready to run</span>
          )}
        </div>

        <span className="shrink-0 font-mono text-[11px] text-subtle tabular">
          {completedCount}/{stages.length}
        </span>
      </div>
    </div>
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
