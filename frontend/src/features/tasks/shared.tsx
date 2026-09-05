import type {
  CommChannel,
  CommDirection,
  CommLoop,
  ReviewPriority,
  ReviewState,
  SecuritySeverity,
  StageState,
  TaskStage,
  WorklistKind,
} from "@/lib/api";
import { formatDateTime, parseInstant } from "@/lib/datetime";
import type { DotTone } from "@/components/ui/badge";

/**
 * The style vocabulary shared across the work surface.
 *
 * Kept in one module so a severity, a priority and a loop mean the same thing
 * everywhere. A finding that reads red on one panel and orange on another
 * trains people to stop reading the colour at all.
 *
 * Everything here resolves to a semantic token rather than a Tailwind palette
 * colour. The version this replaces wrote `bg-red-500/10 text-red-600
 * dark:text-red-400 border-red-500/30` inline at each site, which is four
 * chances to get one state wrong and no way to change the danger colour once.
 */

/* ── Tones ────────────────────────────────────────────────────────────────
   `Tone` is the single vocabulary the badges, dots and panels all speak. */

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

export const SEVERITY_TONE: Record<SecuritySeverity, Tone> = {
  critical: "danger",
  high: "danger",
  medium: "warning",
  low: "info",
  info: "neutral",
};

// P1 shares the tone of a critical finding: both mean "do not merge".
export const PRIORITY_TONE: Record<ReviewPriority, Tone> = {
  p1: "danger",
  p2: "warning",
  p3: "info",
};

export const JOB_STATUS: Record<string, { label: string; tone: Tone; pulse?: boolean }> = {
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  running: { label: "Running", tone: "info", pulse: true },
  queued: { label: "Queued", tone: "neutral" },
};

export const REVIEW_STATE: Record<ReviewState, { label: string; tone: Tone }> = {
  awaiting_review: { label: "Awaiting review", tone: "warning" },
  changes_requested: { label: "Changes requested", tone: "danger" },
  approved: { label: "Approved", tone: "success" },
  merged: { label: "Merged", tone: "accent" },
  closed: { label: "Closed", tone: "neutral" },
};

export const LOOP: Record<CommLoop, { label: string; tone: Tone }> = {
  context: { label: "Context", tone: "neutral" },
  review: { label: "Review", tone: "info" },
  qa: { label: "Testing", tone: "success" },
};

export const KIND: Record<WorklistKind, { label: string; tone: Tone }> = {
  changes_requested: { label: "Changes requested", tone: "danger" },
  qa_rejected: { label: "Testing failed", tone: "danger" },
  qa_unanswered: { label: "No word from testing", tone: "warning" },
  approved_not_merged: { label: "Approved, not merged", tone: "success" },
  delivery_failed: { label: "Message not delivered", tone: "warning" },
  awaiting_review: { label: "Waiting on review", tone: "neutral" },
};

/**
 * The stage a task has reached, in words and in a tone.
 *
 * `merged` is deliberately not a "done" tone. Merged and done are different
 * claims, and the whole reason the QA loop exists is that a human still
 * confirms the second one.
 */
export const TASK_STAGE: Record<TaskStage, { label: string; tone: Tone }> = {
  assigned: { label: "Assigned", tone: "neutral" },
  authoring: { label: "Being written", tone: "accent" },
  branch_created: { label: "Branch open", tone: "neutral" },
  in_progress: { label: "In progress", tone: "info" },
  analyzed: { label: "Analysed", tone: "info" },
  in_review: { label: "In review", tone: "info" },
  changes_requested: { label: "Changes requested", tone: "danger" },
  approved: { label: "Approved", tone: "success" },
  merged: { label: "Merged", tone: "accent" },
  testing: { label: "Testing", tone: "accent" },
  done: { label: "Done", tone: "success" },
};

export const OUTCOME_LABEL: Record<string, string> = {
  review_requested: "Review requested",
  approved: "Approved",
  changes_requested: "Changes requested",
  commented: "Commented",
  resubmitted: "Author pushed changes",
};

export const CHANNEL_LABEL: Record<CommChannel, string> = {
  slack: "Slack",
  email: "Email",
  github: "GitHub",
};

export const DIRECTION_LABEL: Record<CommDirection, string> = {
  searched: "Searched",
  sent: "Sent",
  received: "Received",
};

/** A pipeline step's state, as a dot tone. */
export const STAGE_TONE: Record<StageState, DotTone> = {
  done: "success",
  failed: "danger",
  skipped: "neutral",
  running: "info",
  pending: "neutral",
};

/** Which tool calls belong under which pipeline stage. */
export const STAGE_TOOLS: Record<string, string[]> = {
  slack_search: ["search_messages"],
  jira: ["issue_lookup", "search"],
  docs_read: ["find_related_documents"],
  issues: ["get_linked_issues"],
  scan: ["semgrep", "gitleaks", "llm_review"],
  review: ["code_review"],
};

/** "3d", "4h", "just now" — staleness is the ranking signal, so it is prominent. */
export const ageLabel = (hours: number) => {
  if (hours >= 48) return `${Math.floor(hours / 24)}d`;
  if (hours >= 1) return `${Math.floor(hours)}h`;
  return "just now";
};

/**
 * An absolute timestamp, always in IST.
 *
 * Not the viewer's zone: these are shared events people discuss with each
 * other, so the wall clock has to be the same for everyone reading it.
 */
export const timeOf = (iso?: string | null) => formatDateTime(iso);

/**
 * How long ago an instant was, in the shortest honest form.
 *
 * Used for a run that is still going, so it counts up rather than describing
 * an age. Seconds matter for the first minute — a run that has just started
 * showing "0m" reads as stalled.
 */
export const elapsedLabel = (iso: string | null | undefined) => {
  if (!iso) return "";
  const started = parseInstant(iso);
  if (!started) return "";
  const seconds = Math.max(0, (Date.now() - started.getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
};
