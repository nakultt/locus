"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, GitPullRequest } from "lucide-react";
import { getPRJob, type PRJob, type PRJobDetail } from "@/lib/api";
import { formatFull } from "@/lib/datetime";
import { Badge, Dot } from "@/components/ui/badge";
import { Notice, Panel, Skeleton } from "@/components/ui/surface";
import { AnalysisView } from "./analysis";
import { StageChecklist } from "./pipeline";
import { JOB_STATUS } from "./shared";

/**
 * One analysis run.
 *
 * Collapsed it shows its stage checklist, because "what did this run actually
 * gather" is the question a list of runs is scanned for — a row saying only
 * `completed` is a row nobody reads twice.
 *
 * The detail is fetched on expand rather than with the list: a page of twenty
 * runs would otherwise pull twenty full analyses, each carrying its findings,
 * its tool calls and its whole message history.
 */
export function JobRow({ job }: { job: PRJob }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<PRJobDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const status = JOB_STATUS[job.status] ?? JOB_STATUS.queued;

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || detail) return;

    setLoading(true);
    setFailed(false);
    try {
      setDetail(await getPRJob(job.id));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel className="overflow-hidden">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors hover:bg-surface-2/50"
      >
        <span className="shrink-0 text-subtle" aria-hidden>
          {open ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
        </span>
        <GitPullRequest className="size-4 shrink-0 text-subtle" aria-hidden />
        <span className="min-w-0 truncate font-mono text-sm font-medium text-ink">
          {job.repo}#{job.pr_number}
        </span>
        <Badge tone={status.tone}>
          {status.pulse && <Dot tone={status.tone} pulse />}
          {status.label}
        </Badge>
        {job.action === "manual" && <Badge tone="outline">manual</Badge>}
        <span className="ml-auto shrink-0 text-xs text-subtle">
          {formatFull(job.created_at)}
        </span>
      </button>

      {!open && (
        <StageChecklist stages={job.stages ?? []} toolCalls={job.tool_calls ?? []} />
      )}

      {open && (
        <div className="border-t border-line px-5 py-5">
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : failed ? (
            <Notice tone="danger">Could not load this run.</Notice>
          ) : detail?.status === "failed" ? (
            <Notice tone="danger" title="The run failed">
              {detail.error || "It failed without recording a reason."}
            </Notice>
          ) : detail?.result ? (
            <AnalysisView result={detail.result} />
          ) : (
            <p className="text-sm text-muted">
              {detail?.status === "queued" || detail?.status === "running"
                ? "Analysis in progress…"
                : "No result recorded."}
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
