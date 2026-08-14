import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type {
  LinkedIssue,
  PipelineStage,
  ReviewFinding,
  SecurityFinding,
  ToolInvocation,
} from "@/lib/api";
import { PRIORITY_STYLE, SEVERITY_STYLE, STAGE_ICON, STAGE_TOOLS } from "./shared";

/**
 * What the agent actually did, step by step.
 *
 * Reads and writes are separated because they carry different weight: a
 * skipped read means thinner context, a skipped write means nothing changed
 * outside Locus.
 */
export const StageTimeline = ({ stages }: { stages: PipelineStage[] }) => {
  const reads = stages.filter((s) => s.kind === "read");
  const writes = stages.filter((s) => s.kind === "write");

  const group = (title: string, items: PipelineStage[]) =>
    items.length === 0 ? null : (
      <div>
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </p>
        <ul className="space-y-1">
          {items.map((stage) => {
            const icon = STAGE_ICON[stage.state] ?? STAGE_ICON.pending;
            return (
              <li key={stage.key} className="flex items-start gap-2 text-xs">
                <span className={`mt-0.5 shrink-0 font-mono ${icon.tone}`}>
                  {icon.glyph}
                </span>
                <span
                  className={
                    stage.state === "skipped"
                      ? "text-muted-foreground"
                      : "text-foreground"
                  }
                >
                  {stage.label}
                  {stage.detail && (
                    <span className="text-muted-foreground"> — {stage.detail}</span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    );

  return (
    <section className="space-y-3 rounded-lg border border-border bg-muted/20 p-3">
      {group("Gathered", reads)}
      {group("Actions taken", writes)}
    </section>
  );
};

/**
 * The pipeline steps for one run, shown on a collapsed row.
 *
 * Every step is listed even when skipped: a run that gathered nothing should
 * read as "Jira was not connected", not as an empty result.
 */
export const StageChecklist = ({
  stages,
  toolCalls = [],
}: {
  stages: PipelineStage[];
  toolCalls?: ToolInvocation[];
}) => {
  if (stages.length === 0) return null;

  const reads = stages.filter((s) => s.kind === "read");
  const writes = stages.filter((s) => s.kind === "write");

  const column = (title: string, items: PipelineStage[]) =>
    items.length === 0 ? null : (
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </p>
        <ul className="space-y-0.5">
          {items.map((stage) => {
            const icon = STAGE_ICON[stage.state] ?? STAGE_ICON.pending;
            // The searches behind this step, so "2 thread(s)" can be checked
            // against what was actually queried and found.
            const calls = toolCalls.filter((c) =>
              (STAGE_TOOLS[stage.key] ?? []).includes(c.tool)
            );
            return (
              <li key={stage.key} className="text-[11px]">
                <div className="flex items-start gap-1.5">
                  <span className={`mt-px shrink-0 font-mono ${icon.tone}`}>
                    {icon.glyph}
                  </span>
                  <span
                    className={
                      stage.state === "skipped"
                        ? "truncate text-muted-foreground line-through"
                        : "truncate text-foreground"
                    }
                  >
                    {stage.label}
                  </span>
                  {stage.detail && stage.state !== "skipped" && (
                    <span className="shrink-0 text-muted-foreground">
                      {stage.detail.length > 28
                        ? `${stage.detail.slice(0, 28)}…`
                        : stage.detail}
                    </span>
                  )}
                </div>
                {stage.state !== "skipped" &&
                  calls.map((call, i) => (
                    <div key={i} className="ml-4 mt-0.5">
                      {call.query && (
                        <p
                          className="truncate font-mono text-[10px] text-muted-foreground"
                          title={call.query}
                        >
                          ⌕ {call.query}
                        </p>
                      )}
                      {call.matches?.map((match, m) => (
                        <p
                          key={m}
                          className="truncate text-[10px] text-muted-foreground"
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
    <div className="flex gap-6 border-t border-border bg-muted/20 px-4 py-2.5">
      {column("Gathered", reads)}
      {column("Actions taken", writes)}
    </div>
  );
};

/**
 * One linked or mentioned GitHub issue, expandable to the text a human wrote.
 *
 * "Closes" and "Mentions" are labelled differently and deliberately: only a
 * formally closing issue is closed on merge, and rendering both identically
 * would overstate what the PR is claiming about a bare `#12`.
 */
export const IssueRow = ({ issue }: { issue: LinkedIssue }) => {
  const [open, setOpen] = useState(false);
  const hasBody = Boolean(issue.body?.trim());
  const closes = issue.relation === "closes";

  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
      <div className="flex items-start gap-1.5">
        {hasBody ? (
          <button
            onClick={() => setOpen(!open)}
            className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={open ? "Hide issue text" : "Show issue text"}
          >
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        ) : (
          <span className="mt-0.5 w-3 shrink-0" />
        )}

        <div className="min-w-0 flex-1">
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] ${
              closes
                ? "bg-purple-500/10 text-purple-600 dark:text-purple-400"
                : "bg-muted text-muted-foreground"
            }`}
            title={
              closes
                ? "Formally linked — closed automatically when this PR merges"
                : "Bare #N reference — left alone on merge"
            }
          >
            {closes ? "Closes" : "Mentions"}
          </span>{" "}
          <a
            href={issue.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-primary hover:underline"
          >
            #{issue.number}
          </a>
          <span className="text-foreground"> — {issue.title}</span>
          <span className="text-muted-foreground"> ({issue.state})</span>
          {issue.author && (
            <span className="text-muted-foreground"> · opened by {issue.author}</span>
          )}
        </div>
      </div>

      {open && hasBody && (
        <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-background/60 p-2 font-mono text-[11px] leading-relaxed text-foreground">
          {issue.body}
        </pre>
      )}
    </div>
  );
};

export const FindingRow = ({ finding }: { finding: SecurityFinding }) => (
  <div className={`rounded-lg border px-3 py-2 ${SEVERITY_STYLE[finding.severity]}`}>
    <div className="flex items-start justify-between gap-3">
      <span className="text-xs font-medium">{finding.title}</span>
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide opacity-70">
        {finding.severity}
      </span>
    </div>
    <code className="mt-1 block font-mono text-[11px] opacity-80">
      {finding.file_path}
      {finding.line ? `:${finding.line}` : ""}
    </code>
    {finding.description && (
      <p className="mt-1 text-[11px] leading-relaxed opacity-90">{finding.description}</p>
    )}
  </div>
);

export const ReviewRow = ({ finding }: { finding: ReviewFinding }) => (
  <div className={`rounded-lg border px-3 py-2 ${PRIORITY_STYLE[finding.priority]}`}>
    <div className="flex items-start justify-between gap-3">
      <span className="text-xs font-medium">{finding.title}</span>
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide opacity-70">
        {finding.priority} · {finding.category}
      </span>
    </div>
    <code className="mt-1 block font-mono text-[11px] opacity-80">
      {finding.file_path}
      {finding.line ? `:${finding.line}` : ""}
    </code>
    {finding.description && (
      <p className="mt-1 text-[11px] leading-relaxed opacity-90">{finding.description}</p>
    )}
  </div>
);
