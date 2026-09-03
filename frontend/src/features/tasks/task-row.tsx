"use client";

import { AlertTriangle, ChevronRight, GitBranch, GitPullRequest } from "lucide-react";
import type { TaskCard } from "@/lib/api";
import { Badge, Chip, Dot } from "@/components/ui/badge";
import { TaskProgress } from "./pipeline";
import { REVIEW_STATE, TASK_STAGE, ageLabel } from "./shared";
import { cn } from "@/lib/utils";

/**
 * One assigned task, as a row.
 *
 * Collapsed it answers two questions and no more: where is this, and is it
 * waiting on me. Everything else — the analysis, the review rounds, every
 * message searched and sent — moved into the sheet, because expanding it in
 * place pushed the rest of the queue off screen, and the queue is the reason
 * the board exists.
 *
 * The row is one button. The version this replaces nested links and mode
 * toggles inside a `<button>`, which is invalid markup and made the whole row
 * unusable with a keyboard: Tab landed on the outer button, and the controls
 * inside it were unreachable.
 */
export function TaskRow({
  card,
  onOpen,
}: {
  card: TaskCard;
  onOpen: () => void;
}) {
  const stage = TASK_STAGE[card.stage] ?? TASK_STAGE.assigned;
  const settled = card.stage === "done";

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Open ${card.key}: ${card.title}`}
      className={cn(
        "group relative block w-full rounded-lg border bg-surface p-5 text-left",
        "transition-[border-color,background-color,transform] duration-[--dur-fast] ease-[--ease]",
        "hover:border-line-strong hover:bg-surface-2/40",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        card.needs_you ? "border-accent/45" : "border-line",
        settled && "opacity-75 hover:opacity-100"
      )}
    >
      {/* A hairline down the leading edge rather than a full coloured border.
          Tinting the whole outline made a queue of things needing attention
          read as a wall of warnings; a 3px marker says the same thing without
          shouting it eight times. */}
      {card.needs_you && (
        <span
          aria-hidden
          className="absolute inset-y-4 left-0 w-[3px] rounded-pill bg-accent"
        />
      )}

      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          {/* Identity line */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-ink">
              {card.key}
            </span>
            <Badge tone={stage.tone}>{stage.label}</Badge>

            {card.needs_you && (
              <Badge tone="accent">
                <Dot tone="accent" pulse />
                Needs you
              </Badge>
            )}

            {/* Autonomy is a claim about who is writing the code, so it is
                stated on the row rather than only inside the sheet.
                "Handed back" is attention, not error — it is the bound
                working. */}
            {card.handed_back ? (
              <Badge tone="warning" title={card.handed_back_reason ?? undefined}>
                Handed back
              </Badge>
            ) : card.authoring_mode === "autonomous" ? (
              <Badge tone="info" title={`Set by: ${card.authoring_source}`}>
                Autonomous
              </Badge>
            ) : null}

            {card.round_number > 1 && (
              <Badge tone="neutral">round {card.round_number}</Badge>
            )}
          </div>

          {/* The title, at reading size. It was 14px on a row where the
              identifiers around it were 10px, which inverted the hierarchy —
              the ticket key is how you find it, the title is what it is. */}
          <p className="mt-2 text-body font-medium leading-snug text-ink">
            {card.title}
          </p>

          {/* Why it is stuck, in the words of whoever stuck it. */}
          {card.blocked_reason && (
            <p className="mt-2 flex items-start gap-2 text-sm text-warning">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              {card.blocked_reason}
            </p>
          )}

          {/* Handles onto the work. Linked branches are hidden once a pull
              request exists: the PR is the better handle on the same work, and
              showing both reads as two separate things happening. */}
          {(card.pull_requests.length > 0 || card.linked_branches.length > 0) && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {card.pull_requests.length > 0
                ? card.pull_requests.map((pr) => {
                    const review = pr.review_state
                      ? REVIEW_STATE[pr.review_state]
                      : null;
                    return (
                      <span
                        key={`${pr.repo}#${pr.pr_number}`}
                        className="flex items-center gap-1.5"
                      >
                        <Chip icon={<GitPullRequest />}>
                          {pr.repo}#{pr.pr_number}
                        </Chip>
                        {review && <Badge tone={review.tone}>{review.label}</Badge>}
                      </span>
                    );
                  })
                : card.linked_branches.map((branch) => (
                    <Chip key={branch.name} icon={<GitBranch />}>
                      {branch.name}
                    </Chip>
                  ))}
            </div>
          )}

          <TaskProgress stages={card.stages} className="mt-4" />
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          {card.age_hours > 0 && (
            <span className="tabular text-xs text-subtle">
              {ageLabel(card.age_hours)}
            </span>
          )}
          <ChevronRight
            className="size-4 text-subtle transition-transform duration-[--dur-fast] group-hover:translate-x-0.5 group-hover:text-ink"
            aria-hidden
          />
        </div>
      </div>
    </button>
  );
}
