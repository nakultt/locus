import type {
  CommChannel,
  CommDirection,
  CommLoop,
  ReviewPriority,
  ReviewState,
  SecuritySeverity,
  StageState,
  WorklistKind,
} from "@/lib/api";

/**
 * Style vocabulary shared by the task board and the settings view.
 *
 * Kept in one module so a severity, a priority and a loop mean the same
 * colour everywhere. A finding that reads red on one panel and orange on
 * another trains people to stop reading the colour at all.
 */

export const SEVERITY_STYLE: Record<SecuritySeverity, string> = {
  critical: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30",
  high: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/30",
  medium: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400 border-yellow-500/30",
  low: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
  info: "bg-muted text-muted-foreground border-border",
};

// P1 shares the red of a critical finding: both mean "do not merge".
export const PRIORITY_STYLE: Record<ReviewPriority, string> = {
  p1: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30",
  p2: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/30",
  p3: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
};

export const STATUS_STYLE: Record<string, string> = {
  completed: "bg-green-500/10 text-green-600 dark:text-green-400",
  failed: "bg-red-500/10 text-red-600 dark:text-red-400",
  running: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  queued: "bg-muted text-muted-foreground",
};

export const STAGE_ICON: Record<StageState, { glyph: string; tone: string }> = {
  done: { glyph: "✓", tone: "text-green-500" },
  failed: { glyph: "✕", tone: "text-red-500" },
  skipped: { glyph: "—", tone: "text-muted-foreground" },
  running: { glyph: "●", tone: "text-blue-500 animate-pulse" },
  pending: { glyph: "○", tone: "text-muted-foreground" },
};

export const REVIEW_STATE_STYLE: Record<
  ReviewState,
  { label: string; className: string }
> = {
  awaiting_review: {
    label: "Awaiting review",
    className: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  },
  changes_requested: {
    label: "Changes requested",
    className: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  },
  approved: {
    label: "Approved",
    className: "bg-green-500/10 text-green-600 dark:text-green-400",
  },
  merged: {
    label: "Merged",
    className: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
  },
};

export const OUTCOME_LABEL: Record<string, string> = {
  review_requested: "Review requested",
  approved: "Approved",
  changes_requested: "Changes requested",
  commented: "Commented",
  resubmitted: "Author pushed changes",
};

export const KIND_STYLE: Record<
  WorklistKind,
  { label: string; className: string; dot: string }
> = {
  changes_requested: {
    label: "Changes requested",
    className: "text-orange-600 dark:text-orange-400",
    dot: "bg-orange-500",
  },
  qa_rejected: {
    label: "Testing failed",
    className: "text-red-600 dark:text-red-400",
    dot: "bg-red-500",
  },
  approved_not_merged: {
    label: "Approved, not merged",
    className: "text-green-600 dark:text-green-400",
    dot: "bg-green-500",
  },
  delivery_failed: {
    label: "Message not delivered",
    className: "text-yellow-600 dark:text-yellow-400",
    dot: "bg-yellow-500",
  },
  awaiting_review: {
    label: "Waiting on review",
    className: "text-muted-foreground",
    dot: "bg-muted-foreground",
  },
};

export const LOOP_STYLE: Record<CommLoop, { label: string; className: string }> = {
  context: {
    label: "Context",
    className: "bg-slate-500/10 text-slate-600 dark:text-slate-300",
  },
  review: {
    label: "Review loop",
    className: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  },
  qa: {
    label: "Testing loop",
    className: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
  },
};

export const DIRECTION_GLYPH: Record<CommDirection, { glyph: string; tone: string }> = {
  searched: { glyph: "🔍", tone: "text-muted-foreground" },
  sent: { glyph: "↗", tone: "text-blue-500" },
  received: { glyph: "↙", tone: "text-green-600 dark:text-green-400" },
};

export const CHANNEL_LABEL: Record<CommChannel, string> = {
  slack: "Slack",
  email: "Email",
  github: "GitHub",
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

export const timeOf = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
