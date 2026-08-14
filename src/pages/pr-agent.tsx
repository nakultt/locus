import { Fragment, useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Copy,
  Eye,
  ExternalLink,
  FileText,
  GitMerge,
  GitPullRequest,
  Loader2,
  Mail,
  MessageSquare,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import {
  analyzePR,
  getPRAgentDefaults,
  getPRAgentSummary,
  savePRAgentDefaults,
  getPRActivity,
  getPRJob,
  getReview,
  listPRJobs,
  listRepos,
  listReviews,
  registerRepo,
  unregisterRepo,
  type PRAgentDefaults,
  type PRAgentSummary,
  type PRJob,
  type PRJobDetail,
  type PRReviewDetail,
  type PRReviewSummary,
  type RepoRegistration,
  type LinkedIssue,
  type PipelineStage,
  type ReviewFinding,
  type ReviewPriority,
  type ReviewState,
  type MergeMethod,
  type CommLoop,
  type CommDirection,
  type CommChannel,
  type CommunicationEvent,
  type PRActivity,
  type SecurityFinding,
  type ToolInvocation,
  type ServiceStatus,
  type StageState,
  type SecuritySeverity,
} from "@/lib/api";

/** Dashboard for the PR Context Agent: setup, runs, and findings. */

const SEVERITY_STYLE: Record<SecuritySeverity, string> = {
  critical: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30",
  high: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/30",
  medium: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400 border-yellow-500/30",
  low: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
  info: "bg-muted text-muted-foreground border-border",
};

// P1 shares the red of a critical finding: both mean "do not merge".
const PRIORITY_STYLE: Record<ReviewPriority, string> = {
  p1: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30",
  p2: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/30",
  p3: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
};

const STATUS_STYLE: Record<string, string> = {
  completed: "bg-green-500/10 text-green-600 dark:text-green-400",
  failed: "bg-red-500/10 text-red-600 dark:text-red-400",
  running: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  queued: "bg-muted text-muted-foreground",
};

const Stat = ({ label, value, tone }: { label: string; value: number; tone?: string }) => (
  <div className="rounded-xl border border-border bg-card p-4">
    <p className={`text-2xl font-semibold ${tone ?? "text-foreground"}`}>{value}</p>
    <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
  </div>
);

/**
 * One service and the individual capabilities it provides.
 *
 * A flat "connected" pill is too coarse: Slack with only a bot token can post
 * but cannot search, and that is exactly the case that silently produces thin
 * results. Each capability is listed so the gap is visible.
 */
const ServiceCard = ({ service }: { service: ServiceStatus }) => {
  const missing = service.capabilities.filter((c) => !c.available);
  const tone = service.connected
    ? missing.length === 0
      ? "border-green-500/30 bg-green-500/5"
      : "border-yellow-500/30 bg-yellow-500/5"
    : service.required
      ? "border-red-500/30 bg-red-500/5"
      : "border-border bg-muted/30";

  return (
    <div className={`rounded-lg border p-3 ${tone}`}>
      <div className="mb-2 flex items-center gap-1.5">
        {service.connected && missing.length === 0 ? (
          <Check size={13} className="text-green-500" />
        ) : service.required && !service.connected ? (
          <X size={13} className="text-red-500" />
        ) : (
          <AlertTriangle size={13} className="text-yellow-500" />
        )}
        <span className="text-xs font-semibold text-foreground">{service.label}</span>
        {service.required && (
          <span className="rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground">
            required
          </span>
        )}
      </div>
      <ul className="space-y-1">
        {service.capabilities.map((cap) => (
          <li key={cap.key} title={cap.hint} className="flex items-center gap-1.5 text-xs">
            {cap.available ? (
              <Check size={11} className="shrink-0 text-green-500" />
            ) : (
              <X size={11} className="shrink-0 text-muted-foreground" />
            )}
            <span className={cap.available ? "text-foreground" : "text-muted-foreground"}>
              {cap.label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};

/** One line of the "what will happen" preview. */
const PlanItem = ({ on, label }: { on: boolean; label: string }) => (
  <li className="flex items-start gap-1.5">
    {on ? (
      <Check size={11} className="mt-0.5 shrink-0 text-green-500" />
    ) : (
      <X size={11} className="mt-0.5 shrink-0 text-muted-foreground" />
    )}
    <span className={on ? "text-foreground" : "text-muted-foreground line-through"}>
      {label}
    </span>
  </li>
);

const STAGE_ICON: Record<StageState, { glyph: string; tone: string }> = {
  done: { glyph: "✓", tone: "text-green-500" },
  failed: { glyph: "✕", tone: "text-red-500" },
  skipped: { glyph: "—", tone: "text-muted-foreground" },
  running: { glyph: "●", tone: "text-blue-500 animate-pulse" },
  pending: { glyph: "○", tone: "text-muted-foreground" },
};

/**
 * What the agent actually did, step by step.
 *
 * Reads and writes are separated because they carry different weight: a
 * skipped read means thinner context, a skipped write means nothing changed
 * outside Locus.
 */
const StageTimeline = ({ stages }: { stages: PipelineStage[] }) => {
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
 * One linked or mentioned GitHub issue, expandable to the text a human wrote.
 *
 * "Closes" and "Mentions" are labelled differently and deliberately: only a
 * formally closing issue is closed on merge, and rendering both identically
 * would overstate what the PR is claiming about a bare `#12`.
 *
 * The body is collapsed by default. It is fetched and fed to the reviewer
 * either way, so hiding it entirely means the dashboard shows less than the
 * model was given -- but a wall of issue text above the findings buries them.
 */
const IssueRow = ({ issue }: { issue: LinkedIssue }) => {
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

const FindingRow = ({ finding }: { finding: SecurityFinding }) => (
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

const ReviewRow = ({ finding }: { finding: ReviewFinding }) => (
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

const JobDetail = ({ detail }: { detail: PRJobDetail }) => {
  const result = detail.result;

  if (detail.status === "failed") {
    return (
      <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
        {detail.error || "The run failed without recording a reason."}
      </div>
    );
  }
  if (!result) {
    return (
      <p className="text-xs text-muted-foreground">
        {detail.status === "queued" || detail.status === "running"
          ? "Analysis in progress..."
          : "No result recorded."}
      </p>
    );
  }

  const ctx = result.context;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <a
          href={ctx.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-primary hover:underline"
        >
          {ctx.repo}#{ctx.pr_number} <ExternalLink size={11} />
        </a>
        <span>by {ctx.author}</span>
        <span className="text-green-600 dark:text-green-400">+{ctx.additions}</span>
        <span className="text-red-500">-{ctx.deletions}</span>
        <span>{ctx.files_changed} files</span>
      </div>

      {result.stages.length > 0 && <StageTimeline stages={result.stages} />}

      {ctx.linked_issues.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs font-medium text-foreground">Linked issues</h4>
          <div className="space-y-1">
            {ctx.linked_issues.map((issue) => (
              <IssueRow key={issue.number} issue={issue} />
            ))}
          </div>
        </section>
      )}

      {ctx.tickets.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs font-medium text-foreground">Related tickets</h4>
          <div className="space-y-1">
            {ctx.tickets.map((t) => (
              <div key={t.key} className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
                <a
                  href={t.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-primary hover:underline"
                >
                  {t.key}
                </a>
                {t.summary && <span className="text-foreground"> — {t.summary}</span>}
                {(t.status || t.assignee) && (
                  <span className="text-muted-foreground">
                    {" "}
                    ({[t.status, t.assignee].filter(Boolean).join(" · ")})
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {ctx.documents.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs font-medium text-foreground">
            Related documents
            <span className="ml-1 font-normal text-muted-foreground">
              — given to the reviewer as context
            </span>
          </h4>
          <div className="space-y-1">
            {ctx.documents.map((doc, i) => (
              <a
                key={i}
                href={doc.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs hover:bg-muted/60"
              >
                <FileText size={12} className="text-muted-foreground" />
                <span className="font-medium text-primary">{doc.title}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      {ctx.slack_threads.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs font-medium text-foreground">Prior discussion</h4>
          <div className="space-y-1">
            {ctx.slack_threads.slice(0, 5).map((thread, i) => (
              <a
                key={i}
                href={thread.permalink}
                target="_blank"
                rel="noopener noreferrer"
                className="block rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs hover:bg-muted/60"
              >
                <span className="font-medium text-primary">#{thread.channel}</span>
                {thread.summary && (
                  <span className="text-muted-foreground"> — {thread.summary}</span>
                )}
              </a>
            ))}
          </div>
        </section>
      )}

      {/* Confirmed and unverified stay visually distinct. Presenting a
          model-generated guess as a confirmed vulnerability is how a review
          bot loses a team's trust permanently. */}
      {result.confirmed_findings.length > 0 && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-foreground">
            <ShieldAlert size={13} className="text-red-500" />
            Confirmed findings
            <span className="font-normal text-muted-foreground">— matched by scanner rules</span>
          </h4>
          <div className="space-y-1.5">
            {result.confirmed_findings.map((f, i) => (
              <FindingRow key={i} finding={f} />
            ))}
          </div>
        </section>
      )}

      {result.unverified_findings.length > 0 && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-foreground">
            <AlertTriangle size={13} className="text-yellow-500" />
            Possible issues
            <span className="font-normal text-muted-foreground">
              — model-generated, <strong>not</strong> confirmed
            </span>
          </h4>
          <div className="space-y-1.5">
            {result.unverified_findings.map((f, i) => (
              <FindingRow key={i} finding={f} />
            ))}
          </div>
        </section>
      )}

      {result.confirmed_findings.length === 0 && result.unverified_findings.length === 0 && (
        <div className="flex items-center gap-1.5 rounded-lg bg-green-500/10 px-3 py-2 text-xs text-green-600 dark:text-green-400">
          <ShieldCheck size={13} /> No security issues detected
        </div>
      )}

      {/* Code review, kept visually apart from security: a clean scan on a
          change that ignores the agreed requirement is not an approval. */}
      {result.review_findings?.length > 0 ? (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-foreground">
            <ClipboardList size={13} className="text-muted-foreground" />
            Code review
            <span className="font-normal text-muted-foreground">
              — reviewer's judgement, not a scanner result
            </span>
          </h4>
          <div className="space-y-1.5">
            {result.review_findings.map((f, i) => (
              <ReviewRow key={i} finding={f} />
            ))}
          </div>
        </section>
      ) : (
        <div className="flex items-center gap-1.5 rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
          <ClipboardList size={13} /> Code review raised no issues
        </div>
      )}

      {/* What ran. Distinguishes "searched and found nothing" from
          "never searched" -- indistinguishable in the output otherwise. */}
      {result.tool_calls.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-xs font-medium text-foreground">Tools used</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1 pr-3 text-left font-medium">Service</th>
                  <th className="py-1 pr-3 text-left font-medium">Tool</th>
                  <th className="py-1 pr-3 text-left font-medium">Query</th>
                  <th className="py-1 text-right font-medium">Results</th>
                </tr>
              </thead>
              <tbody>
                {result.tool_calls.map((call, i) => (
                  <Fragment key={i}>
                    <tr className="border-t border-border">
                      <td className="py-1 pr-3 text-muted-foreground">{call.service}</td>
                      <td className="py-1 pr-3 font-mono text-foreground">{call.tool}</td>
                      <td className="py-1 pr-3 font-mono text-muted-foreground">
                        {call.succeeded ? (
                          <span title={call.query ?? ""}>
                            {(call.query ?? "—").slice(0, 60)}
                            {(call.query?.length ?? 0) > 60 ? "…" : ""}
                          </span>
                        ) : (
                          <span className="text-yellow-600 dark:text-yellow-400">
                            {call.detail ?? "skipped"}
                          </span>
                        )}
                      </td>
                      <td className="py-1 text-right text-foreground">
                        {call.succeeded ? call.result_count : "—"}
                      </td>
                    </tr>
                    {/* What the query actually matched. A bare count cannot be
                        sanity-checked -- "1 thread" could be the wrong thread. */}
                    {call.matches?.length > 0 && (
                      <tr>
                        <td />
                        <td colSpan={3} className="pb-1.5 pl-0 pr-3">
                          <ul className="space-y-0.5">
                            {call.matches.map((match, m) => (
                              <li
                                key={m}
                                className="truncate text-[10px] text-muted-foreground"
                                title={match}
                              >
                                ↳ {match}
                              </li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Post-merge outcomes */}
      {result.merge_actions && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-foreground">
            <GitMerge size={13} className="text-purple-500" />
            Merge actions
          </h4>
          <div className="space-y-1 text-xs">
            {result.merge_actions.jira_transitioned.map((line, i) => (
              <div key={`j${i}`} className="flex items-center gap-1.5 text-green-600 dark:text-green-400">
                <Check size={11} /> {line}
              </div>
            ))}
            {result.merge_actions.issues_closed.map((line, i) => (
              <div key={`i${i}`} className="flex items-center gap-1.5 text-green-600 dark:text-green-400">
                <Check size={11} /> {line}
              </div>
            ))}
            {result.merge_actions.qa_notified && (
              <div className="flex items-center gap-1.5 text-green-600 dark:text-green-400">
                <Mail size={11} /> Test team notified
              </div>
            )}
            {result.merge_actions.errors.map((line, i) => (
              <div key={`e${i}`} className="flex items-center gap-1.5 text-yellow-600 dark:text-yellow-400">
                <AlertTriangle size={11} /> {line}
              </div>
            ))}
          </div>
          {result.merge_actions.qa_brief && (
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                Test brief sent to QA
              </summary>
              <pre className="mt-1 whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-2 text-[11px] text-foreground">
                {result.merge_actions.qa_brief}
              </pre>
            </details>
          )}
        </section>
      )}

      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>{result.pr_comment_posted ? "✓ Commented on PR" : "PR comment not posted"}</span>
        <span>{result.slack_posted ? "✓ Posted to Slack" : "No Slack summary"}</span>
        {result.doc_url && (
          <a
            href={result.doc_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-primary hover:underline"
          >
            <FileText size={11} /> Google Doc
          </a>
        )}
      </div>

      {result.errors.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            Pipeline notes ({result.errors.length})
          </summary>
          <ul className="mt-1.5 space-y-0.5 pl-4 text-muted-foreground">
            {result.errors.map((e, i) => (
              <li key={i} className="list-disc">{e}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
};

/**
 * The pipeline steps for one run, shown on the collapsed row.
 *
 * Every step is listed even when skipped: a run that gathered nothing should
 * read as "Jira was not connected", not as an empty result.
 */
/** Which tool calls belong under which pipeline stage. */
const STAGE_TOOLS: Record<string, string[]> = {
  slack_search: ["search_messages"],
  jira: ["issue_lookup", "search"],
  docs_read: ["find_related_documents"],
  issues: ["get_linked_issues"],
  scan: ["semgrep", "gitleaks", "llm_review"],
  review: ["code_review"],
};

const StageChecklist = ({
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
 * Account-wide settings applied to every repo that does not override them.
 *
 * Without these, a repo nobody registered silently skips the Google Doc and
 * the QA email -- which reads as the feature being broken rather than
 * unconfigured.
 */
const GlobalDefaults = ({ docsConnected }: { docsConnected: boolean }) => {
  const [values, setValues] = useState<PRAgentDefaults | null>(null);
  const [emailsInput, setEmailsInput] = useState("");
  const [reviewersInput, setReviewersInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPRAgentDefaults()
      .then((d) => {
        setValues(d);
        setEmailsInput(d.qa_emails.join(", "));
        setReviewersInput((d.reviewers ?? []).join(", "));
      })
      .catch(() => setValues(null));
  }, []);

  if (!values) return null;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const next = await savePRAgentDefaults({
        ...values,
        qa_emails: emailsInput
          .split(/[,\n]/)
          .map((e) => e.trim())
          .filter((e) => e.includes("@")),
        reviewers: reviewersInput
          .split(/[,\n]/)
          .map((r) => r.trim().replace(/^@/, ""))
          .filter(Boolean),
      });
      setValues(next);
      setEmailsInput(next.qa_emails.join(", "));
      setReviewersInput((next.reviewers ?? []).join(", "));
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-6 rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-semibold text-foreground">Default settings</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Applied to every repository that does not set its own. A repo's own
        settings always win.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">
            Slack channel for summaries
          </label>
          <input
            value={values.slack_channel ?? ""}
            onChange={(e) =>
              setValues({ ...values, slack_channel: e.target.value })
            }
            placeholder="#dev-updates"
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">
            Test team emails, notified on every merge
          </label>
          <input
            value={emailsInput}
            onChange={(e) => setEmailsInput(e.target.value)}
            placeholder="qa@company.com, lead@company.com"
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">
            Senior dev reviewers (GitHub logins)
          </label>
          <input
            value={reviewersInput}
            onChange={(e) => setReviewersInput(e.target.value)}
            placeholder="senior-dev, tech-lead"
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">
            Slack channel for review requests
          </label>
          <input
            value={values.review_slack_channel ?? ""}
            onChange={(e) =>
              setValues({ ...values, review_slack_channel: e.target.value })
            }
            placeholder="#code-review"
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
      </div>

      <div className="mt-3 space-y-2">
        <label className="flex items-center gap-2 text-xs text-foreground">
          <input
            type="checkbox"
            checked={values.export_to_docs}
            onChange={(e) =>
              setValues({ ...values, export_to_docs: e.target.checked })
            }
            disabled={!docsConnected}
            className="rounded border-border"
          />
          Write every analysis to a Google Doc
          {!docsConnected && " (connect Google Docs first)"}
        </label>
        <label className="flex items-center gap-2 text-xs text-foreground">
          <input
            type="checkbox"
            checked={values.close_issues_on_merge}
            onChange={(e) =>
              setValues({ ...values, close_issues_on_merge: e.target.checked })
            }
            className="rounded border-border"
          />
          Close linked GitHub issues on merge
        </label>
        <label className="flex items-center gap-2 text-xs text-foreground">
          <input
            type="checkbox"
            checked={values.auto_merge_on_approval}
            onChange={(e) =>
              setValues({ ...values, auto_merge_on_approval: e.target.checked })
            }
            className="rounded border-border"
          />
          Merge automatically when a review approves
          <select
            value={values.merge_method}
            onChange={(e) =>
              setValues({
                ...values,
                merge_method: e.target.value as PRAgentDefaults["merge_method"],
              })
            }
            disabled={!values.auto_merge_on_approval}
            className="rounded border border-border bg-background px-1.5 py-0.5 text-xs disabled:opacity-50"
          >
            <option value="squash">squash</option>
            <option value="merge">merge</option>
            <option value="rebase">rebase</option>
          </select>
        </label>
        <p className="text-xs text-muted-foreground">
          Still gated on green CI, no conflict, no confirmed security finding, and no
          P1 review finding. Held merges are reported in Slack with the reason.
        </p>
      </div>

      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? <Loader2 className="animate-spin" size={13} /> : null}
          Save defaults
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
            <Check size={12} /> Saved
          </span>
        )}
      </div>
    </div>
  );
};

const JobRow = ({ job }: { job: PRJob }) => {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<PRJobDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      setLoading(true);
      try {
        setDetail(await getPRJob(job.id));
      } catch {
        setDetail(null);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        onClick={toggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40"
      >
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <GitPullRequest size={15} className="text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">
          {job.repo}#{job.pr_number}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLE[job.status]}`}>
          {job.status}
        </span>
        {job.action === "manual" && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
            manual
          </span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {new Date(job.created_at).toLocaleString()}
        </span>
      </button>

      {!open && (
        <StageChecklist stages={job.stages ?? []} toolCalls={job.tool_calls ?? []} />
      )}

      {open && (
        <div className="border-t border-border px-4 py-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> Loading...
            </div>
          ) : detail ? (
            <JobDetail detail={detail} />
          ) : (
            <p className="text-xs text-muted-foreground">Could not load this run.</p>
          )}
        </div>
      )}
    </div>
  );
};

const LOOP_STYLE: Record<CommLoop, { label: string; className: string }> = {
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

const DIRECTION_GLYPH: Record<CommDirection, { glyph: string; tone: string }> = {
  searched: { glyph: "🔍", tone: "text-muted-foreground" },
  sent: { glyph: "↗", tone: "text-blue-500" },
  received: { glyph: "↙", tone: "text-green-600 dark:text-green-400" },
};

const CHANNEL_LABEL: Record<CommChannel, string> = {
  slack: "Slack",
  email: "Email",
  github: "GitHub",
};

const timeOf = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }) : "";

/**
 * One message, shown with its actual text.
 *
 * The body is rendered verbatim in a monospace block rather than summarized.
 * A summary answers the easy questions; "what exactly did the bot say to my
 * team" is the one people actually ask, and only the real text answers it.
 */
const MessageRow = ({ event }: { event: CommunicationEvent }) => {
  const dir = DIRECTION_GLYPH[event.direction];
  const loop = LOOP_STYLE[event.loop];

  return (
    <div className="flex gap-2.5">
      <span className={`mt-0.5 shrink-0 text-sm ${dir.tone}`} title={event.direction}>
        {dir.glyph}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`rounded px-1.5 py-0.5 text-[10px] ${loop.className}`}>
            {loop.label}
          </span>
          <span className="text-[11px] font-medium text-foreground">
            {event.direction === "searched"
              ? `Searched ${CHANNEL_LABEL[event.channel]}`
              : event.direction === "sent"
                ? `Sent via ${CHANNEL_LABEL[event.channel]}`
                : `From ${CHANNEL_LABEL[event.channel]}`}
          </span>
          {event.participant && (
            <span className="text-[11px] text-muted-foreground">
              {event.direction === "sent" ? "to" : ""} {event.participant}
            </span>
          )}
          {event.target && event.target !== event.participant && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {event.target}
            </span>
          )}
          {event.outcome && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {event.outcome}
            </span>
          )}
          {!event.succeeded && (
            <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-600 dark:text-red-400">
              not delivered
            </span>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
            {timeOf(event.created_at)}
          </span>
        </div>

        {event.query && (
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            query: {event.query}
          </p>
        )}

        {event.subject && (
          <p className="mt-1 text-[11px] font-medium text-foreground">
            {event.subject}
          </p>
        )}

        {event.body && (
          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-2 font-mono text-[11px] leading-relaxed text-foreground">
            {event.body}
          </pre>
        )}

        {event.permalink && (
          <a
            href={event.permalink}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline dark:text-blue-400"
          >
            Open in {CHANNEL_LABEL[event.channel]} <ExternalLink size={10} />
          </a>
        )}
      </div>
    </div>
  );
};

/**
 * Both loops for one PR: where it stands now, and everything said along the way.
 *
 * Review and testing are shown as two columns of state over one shared
 * timeline. They are genuinely sequential -- testing only begins once the
 * review ends in a merge -- so a single ordered log reads correctly, while
 * two separate ones would hide the handoff between them.
 */
const ActivityPanel = ({ repo, prNumber }: { repo: string; prNumber: number }) => {
  const [data, setData] = useState<PRActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<CommLoop | "all">("all");

  useEffect(() => {
    let live = true;
    setLoading(true);
    getPRActivity(repo, prNumber)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e instanceof Error ? e.message : "Failed"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [repo, prNumber]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-xs text-muted-foreground">
        <Loader2 size={13} className="animate-spin" /> Loading activity…
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="p-4 text-xs text-muted-foreground">
        {error ?? "Nothing recorded for this pull request yet."}
      </p>
    );
  }

  const shown =
    filter === "all" ? data.events : data.events.filter((e) => e.loop === filter);

  const reviewState = data.review?.state;
  const qaState = !data.qa_notified
    ? "not started"
    : data.qa_resolved
      ? "signed off"
      : "awaiting tester";

  return (
    <div className="space-y-4 p-3">
      {/* What is happening now, per loop */}
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-indigo-500/30 bg-indigo-500/5 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600 dark:text-indigo-400">
            Senior dev review
          </p>
          <p className="mt-1 text-sm font-medium text-foreground">
            {reviewState ? REVIEW_STATE_STYLE[reviewState].label : "Not started"}
            {data.review && (
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                · round {data.review.round_number}
              </span>
            )}
          </p>

          {data.reviewer_contacts.length > 0 && (
            <ul className="mt-2 space-y-1">
              {data.reviewer_contacts.map((c) => (
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

          {data.review?.pending_asks?.length ? (
            <div className="mt-2">
              <p className="text-[11px] font-medium text-foreground">
                Outstanding asks
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {data.review.pending_asks.map((a, i) => (
                  <li key={i} className="text-[11px] text-muted-foreground">
                    • {a}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <div className="rounded-lg border border-teal-500/30 bg-teal-500/5 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-teal-600 dark:text-teal-400">
            Testing team
          </p>
          <p className="mt-1 text-sm font-medium text-foreground">{qaState}</p>
          <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
            {data.qa_channel && <li>Slack · {data.qa_channel}</li>}
            {data.qa_recipients.map((r) => (
              <li key={r}>Email · {r}</li>
            ))}
            {!data.qa_channel && data.qa_recipients.length === 0 && (
              <li className="italic">No QA channel or recipients configured</li>
            )}
          </ul>
        </div>
      </div>

      {/* The message log */}
      <div>
        <div className="mb-2 flex items-center gap-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Messages ({data.events.length})
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
                {f === "all" ? "All" : LOOP_STYLE[f].label}
              </button>
            ))}
          </div>
        </div>

        {shown.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border p-4 text-center text-[11px] text-muted-foreground">
            No messages recorded{filter !== "all" && " for this loop"}. Runs from
            before message logging existed show nothing here — there is no record
            to recover.
          </p>
        ) : (
          <div className="space-y-3">
            {shown.map((e) => (
              <MessageRow key={e.id} event={e} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const REVIEW_STATE_STYLE: Record<ReviewState, { label: string; className: string }> = {
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

const OUTCOME_LABEL: Record<string, string> = {
  review_requested: "Review requested",
  approved: "Approved",
  changes_requested: "Changes requested",
  commented: "Commented",
  resubmitted: "Author pushed changes",
};

/**
 * One PR in the review queue, expandable to its full round history.
 *
 * The round count is shown even at one, so a PR that has been round-tripping
 * five times is visibly different from one waiting on its first look.
 */
const ReviewQueueRow = ({ review }: { review: PRReviewSummary }) => {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<PRReviewDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"history" | "activity">("history");

  const style = REVIEW_STATE_STYLE[review.state];

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      setLoading(true);
      try {
        setDetail(await getReview(review.repo, review.pr_number));
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="rounded-xl border border-border">
      <button
        onClick={toggle}
        className="flex w-full items-center gap-3 p-3 text-left hover:bg-muted/50"
      >
        {open ? (
          <ChevronDown size={15} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={15} className="shrink-0 text-muted-foreground" />
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-foreground">
              {review.repo}#{review.pr_number}
            </span>
            <span className={`rounded px-1.5 py-0.5 text-[11px] ${style.className}`}>
              {style.label}
            </span>
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
              round {review.round_number}
            </span>
          </div>
          {review.pr_title && (
            <p className="truncate text-xs text-muted-foreground">{review.pr_title}</p>
          )}
        </div>

        <div className="shrink-0 text-right text-[11px] text-muted-foreground">
          {review.author && <div>by {review.author}</div>}
          {review.last_reviewer && <div>reviewed by {review.last_reviewer}</div>}
        </div>
      </button>

      {open && (
        <div className="border-t border-border">
          <div className="flex gap-1 border-b border-border px-3 pt-2">
            {(["history", "activity"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-t px-2.5 py-1 text-[11px] ${
                  tab === t
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t === "history" ? "Review rounds" : "Messages & loops"}
              </button>
            ))}
          </div>

          {tab === "activity" ? (
            <ActivityPanel repo={review.repo} prNumber={review.pr_number} />
          ) : (
          <div className="p-3">
          {loading && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> Loading history…
            </div>
          )}

          {detail && (
            <div className="space-y-3">
              {detail.pending_asks.length > 0 && (
                <div className="rounded-lg bg-orange-500/5 p-3">
                  <p className="mb-1 text-xs font-semibold text-foreground">
                    Outstanding asks
                  </p>
                  <ul className="space-y-1">
                    {detail.pending_asks.map((ask, i) => (
                      <li key={i} className="text-xs text-muted-foreground">
                        • {ask}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[10px] text-muted-foreground">
                    Summarized from the review. The reviewer's own words below are
                    canonical.
                  </p>
                </div>
              )}

              <div className="space-y-2">
                {detail.rounds.map((round, i) => (
                  <div key={i} className="flex gap-2 text-xs">
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                      {round.round_number}
                    </span>
                    <div className="min-w-0 flex-1">
                      <span className="font-medium text-foreground">
                        {OUTCOME_LABEL[round.outcome] ?? round.outcome}
                      </span>
                      {round.reviewer && (
                        <span className="text-muted-foreground"> — {round.reviewer}</span>
                      )}
                      {round.body && (
                        <p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">
                          {round.body}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {detail.pr_url && (
                <a
                  href={detail.pr_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
                >
                  Open on GitHub <ExternalLink size={11} />
                </a>
              )}
            </div>
          )}
          </div>
          )}
        </div>
      )}
    </div>
  );
};

export default function PRAgentDashboard() {
  const { user } = useAuth();
  const userId = user?.id;

  const [summary, setSummary] = useState<PRAgentSummary | null>(null);
  const [jobs, setJobs] = useState<PRJob[]>([]);
  const [repos, setRepos] = useState<RepoRegistration[]>([]);
  const [reviews, setReviews] = useState<PRReviewSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const [repoInput, setRepoInput] = useState("");
  const [channelInput, setChannelInput] = useState("");
  const [prInput, setPrInput] = useState("");
  const [exportDocs, setExportDocs] = useState(false);
  const [contextDocsInput, setContextDocsInput] = useState("");
  const [qaEmailsInput, setQaEmailsInput] = useState("");
  const [jiraDoneStatus, setJiraDoneStatus] = useState("Done");
  const [closeIssues, setCloseIssues] = useState(true);
  const [reviewersInput, setReviewersInput] = useState("");
  const [reviewChannelInput, setReviewChannelInput] = useState("");
  const [reviewerContactsInput, setReviewerContactsInput] = useState("");
  const [autoMerge, setAutoMerge] = useState(false);
  const [mergeMethod, setMergeMethod] = useState<MergeMethod>("squash");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justRegistered, setJustRegistered] = useState<RepoRegistration | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  /**
   * The saved registration for whatever repo is typed, if there is one.
   *
   * Without this the form shows unsaved local state: a ticked "export to
   * Docs" box on a repo registered before it was ticked reads as configured
   * when the merge run will not do it.
   */
  const savedForInput = repos.find(
    (r) => r.repo.toLowerCase() === repoInput.trim().toLowerCase()
  );

  const settingsDiffer = Boolean(
    savedForInput &&
      (savedForInput.export_to_docs !== exportDocs ||
        (savedForInput.qa_emails ?? []).join(",") !==
          qaEmailsInput
            .split(/[,\n]/)
            .map((e) => e.trim())
            .filter((e) => e.includes("@"))
            .join(",") ||
        (savedForInput.slack_channel ?? "") !== channelInput.trim() ||
        (savedForInput.close_issues_on_merge ?? true) !== closeIssues)
  );

  /** Load a registered repo's real settings into the form. */
  const loadSaved = useCallback((reg: RepoRegistration) => {
    setRepoInput(reg.repo);
    setChannelInput(reg.slack_channel ?? "");
    setExportDocs(reg.export_to_docs ?? false);
    setContextDocsInput((reg.context_docs ?? []).join("\n"));
    setQaEmailsInput((reg.qa_emails ?? []).join(", "));
    setJiraDoneStatus(reg.jira_done_status ?? "Done");
    setCloseIssues(reg.close_issues_on_merge ?? true);
    setReviewersInput((reg.reviewers ?? []).join(", "));
    setReviewChannelInput(reg.review_slack_channel ?? "");
    setReviewerContactsInput(reg.reviewer_contacts ?? "");
    setAutoMerge(reg.auto_merge_on_approval ?? false);
    setMergeMethod(reg.merge_method ?? "squash");
  }, []);

  const refresh = useCallback(async () => {
    if (!userId) return;
    try {
      const [s, j, r, rv] = await Promise.all([
        getPRAgentSummary(),
        listPRJobs(),
        listRepos(),
        listReviews(),
      ]);
      setSummary(s);
      setJobs(j);
      setRepos(r.repos);
      setReviews(rv.reviews);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load dashboard");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    refresh();
    // Jobs run in the background, so poll while any are in flight.
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  const handleRegister = async () => {
    if (!userId || !repoInput.trim()) return;
    setBusy(true);
    setError(null);
    try {
      // One doc per line; the backend accepts full URLs or bare ids.
      const contextDocs = contextDocsInput
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

      // Accept comma- or newline-separated addresses.
      const qaEmails = qaEmailsInput
        .split(/[,\n]/)
        .map((e) => e.trim())
        .filter((e) => e.includes("@"));

      // Accept comma- or newline-separated logins, with or without a leading @.
      const reviewers = reviewersInput
        .split(/[,\n]/)
        .map((r) => r.trim().replace(/^@/, ""))
        .filter(Boolean);

      const reg = await registerRepo(
        repoInput.trim(),
        channelInput.trim() || undefined,
        exportDocs,
        contextDocs,
        qaEmails,
        jiraDoneStatus.trim() || "Done",
        closeIssues,
        reviewers,
        reviewChannelInput.trim() || undefined,
        reviewerContactsInput.trim() || undefined,
        autoMerge,
        mergeMethod
      );
      setJustRegistered(reg);
      setRepoInput("");
      setChannelInput("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  const handleAnalyze = async () => {
    if (!userId || !repoInput.trim() || !prInput.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await analyzePR(repoInput.trim(), Number(prInput.trim()));
      setPrInput("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not queue analysis");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl p-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">PR Context Agent</h1>
            <p className="text-sm text-muted-foreground">
              Gathers Jira and Slack context on every pull request, scans the diff, and
              comments back.
            </p>
          </div>
          <button
            onClick={refresh}
            className="rounded-lg border border-border p-2 hover:bg-muted"
            aria-label="Refresh"
          >
            <RefreshCw size={15} className="text-muted-foreground" />
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {summary && (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Runs" value={summary.total_jobs} />
              <Stat
                label="Completed"
                value={summary.completed}
                tone="text-green-600 dark:text-green-400"
              />
              <Stat
                label="Confirmed findings"
                value={summary.confirmed_findings}
                tone={summary.confirmed_findings > 0 ? "text-red-500" : undefined}
              />
              <Stat
                label="Unverified"
                value={summary.unverified_findings}
                tone={summary.unverified_findings > 0 ? "text-yellow-600" : undefined}
              />
            </div>

            <div className="mb-6 rounded-xl border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-foreground">
                Pipeline readiness
              </h2>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {(summary.services ?? []).map((service) => (
                  <ServiceCard key={service.key} service={service} />
                ))}
              </div>
              {!summary.github_connected && (
                <p className="mt-3 text-xs text-red-600 dark:text-red-400">
                  Connect GitHub in Integrations — the pipeline cannot run without it.
                </p>
              )}
            </div>
          </>
        )}

        {/* Setup */}
        <div className="mb-6 rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold text-foreground">Run an analysis</h2>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={repoInput}
              onChange={(e) => setRepoInput(e.target.value)}
              placeholder="owner/repo"
              className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <input
              value={prInput}
              onChange={(e) => setPrInput(e.target.value)}
              placeholder="PR #"
              className="w-24 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <button
              onClick={handleAnalyze}
              disabled={busy || !repoInput.trim() || !prInput.trim()}
              className="flex items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Analyze now
            </button>
          </div>

          <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3 sm:flex-row">
            <input
              value={channelInput}
              onChange={(e) => setChannelInput(e.target.value)}
              placeholder="#slack-channel (optional)"
              className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <button
              onClick={handleRegister}
              disabled={busy || !repoInput.trim()}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
            >
              Register for webhooks
            </button>
          </div>

          <div className="mt-3">
            <label className="mb-1 block text-xs font-medium text-foreground">
              Context documents
              <span className="ml-1 font-normal text-muted-foreground">
                — Google Docs the reviewer should always read
              </span>
            </label>
            <textarea
              value={contextDocsInput}
              onChange={(e) => setContextDocsInput(e.target.value)}
              placeholder={"https://docs.google.com/document/d/.../edit\nOne per line"}
              rows={2}
              disabled={!summary?.docs_connected}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {summary?.docs_connected
                ? "Their text is given to the reviewer so it can flag changes that contradict the spec. Saved when you register."
                : "Connect Google Docs in Integrations to use this."}
            </p>
          </div>

          <div className="mt-3 border-t border-border pt-3">
            <p className="mb-2 text-xs font-medium text-foreground">
              Senior dev review
              <span className="ml-1 font-normal text-muted-foreground">
                — who reviews, and where the loop is announced
              </span>
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={reviewersInput}
                onChange={(e) => setReviewersInput(e.target.value)}
                placeholder="senior-dev, tech-lead"
                className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
              <input
                value={reviewChannelInput}
                onChange={(e) => setReviewChannelInput(e.target.value)}
                placeholder="#code-review"
                className="w-40 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              GitHub logins. This is who gets pinged, not who is allowed to review —
              GitHub does not restrict that, and a review from anyone else is still
              recorded. Falls back to the summary channel when no review channel is
              set.
            </p>

            <textarea
              value={reviewerContactsInput}
              onChange={(e) => setReviewerContactsInput(e.target.value)}
              placeholder={"senior-dev, @sr-dev, sr@company.com\ntech-lead, @lead, lead@company.com"}
              rows={2}
              className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Optional, one reviewer per line:{" "}
              <span className="font-mono">login, @slack, email</span>. A GitHub login
              is not a Slack handle and not an address — without this the dashboard
              can say a review was requested but not who was actually reached.
            </p>

            <label className="mt-2 flex items-center gap-2 text-xs text-foreground">
              <input
                type="checkbox"
                checked={autoMerge}
                onChange={(e) => setAutoMerge(e.target.checked)}
                className="rounded border-border"
              />
              Merge automatically when approved
              <select
                value={mergeMethod}
                onChange={(e) => setMergeMethod(e.target.value as MergeMethod)}
                disabled={!autoMerge}
                className="rounded border border-border bg-background px-1.5 py-0.5 text-xs disabled:opacity-50"
              >
                <option value="squash">squash</option>
                <option value="merge">merge</option>
                <option value="rebase">rebase</option>
              </select>
            </label>
            <p className="mt-1 text-xs text-muted-foreground">
              Off unless you turn it on — this is the only thing that writes to your
              default branch with no human in the loop. An approval alone is not
              enough: the merge also needs green CI, no merge conflict, no confirmed
              security finding, and no P1 review finding. Anything held is reported in
              Slack with the reason.
            </p>
          </div>

          <div className="mt-3 border-t border-border pt-3">
            <p className="mb-2 text-xs font-medium text-foreground">
              On merge
              <span className="ml-1 font-normal text-muted-foreground">
                — applied automatically when the PR merges
              </span>
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={qaEmailsInput}
                onChange={(e) => setQaEmailsInput(e.target.value)}
                placeholder="qa@company.com, tester@company.com"
                className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
              <input
                value={jiraDoneStatus}
                onChange={(e) => setJiraDoneStatus(e.target.value)}
                placeholder="Jira status"
                className="w-36 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            <label className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={closeIssues}
                onChange={(e) => setCloseIssues(e.target.checked)}
                className="rounded border-border"
              />
              Close linked GitHub issues on merge
            </label>
            <p className="mt-1 text-xs text-muted-foreground">
              Transitions are forward-only — a ticket already past this status is
              left alone. Only issues the PR formally closes are touched.
            </p>
          </div>

          <label className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={exportDocs}
              onChange={(e) => setExportDocs(e.target.checked)}
              disabled={!summary?.docs_connected}
              className="rounded border-border"
            />
            Also write each analysis to a Google Doc
            {!summary?.docs_connected && " (connect Google Docs first)"}
          </label>
          <p className="mt-2 text-xs text-muted-foreground">
            Registering enables automatic analysis on every PR. "Analyze now" works without it.
          </p>

          {/* Automatic runs read the saved registration, not this form. Say so
              when they disagree, rather than letting the preview below imply
              settings that a merge will not actually apply. */}
          {settingsDiffer && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-yellow-500/40 bg-yellow-500/5 px-3 py-2">
              <AlertTriangle size={13} className="mt-0.5 shrink-0 text-yellow-600" />
              <div className="text-xs">
                <p className="text-foreground">
                  These settings are not saved for{" "}
                  <span className="font-medium">{savedForInput?.repo}</span>.
                  Automatic runs on merge use the saved ones.
                </p>
                <div className="mt-1 flex gap-3">
                  <button
                    onClick={() => savedForInput && loadSaved(savedForInput)}
                    className="text-muted-foreground underline hover:text-foreground"
                  >
                    Show saved settings
                  </button>
                  <span className="text-muted-foreground">
                    or press Register to save these
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* What this configuration will actually do, so the effect of each
              toggle is visible before a run rather than after. */}
          <div className="mt-3 grid gap-3 rounded-lg border border-border bg-muted/20 p-3 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                On every PR
              </p>
              <ul className="space-y-0.5 text-xs">
                <PlanItem on label="Read PR, diff and changed files" />
                <PlanItem on={!!summary?.jira_connected} label="Read Jira tickets" />
                <PlanItem on={!!summary?.github_connected} label="Read linked GitHub issues" />
                <PlanItem on={!!summary?.slack_search_enabled} label="Search Slack history" />
                <PlanItem on={!!summary?.docs_connected} label="Read Google Docs as context" />
                <PlanItem
                  on={!!summary?.semgrep_available || !!summary?.gitleaks_available}
                  label="Scan for vulnerabilities"
                />
                <PlanItem on label="Comment on the PR" />
                <PlanItem on={!!channelInput.trim()} label="Post summary to Slack" />
                <PlanItem on={exportDocs} label="Write report to Google Docs" />
              </ul>
            </div>
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                On merge
              </p>
              <ul className="space-y-0.5 text-xs">
                <PlanItem
                  on={!!summary?.jira_connected}
                  label={`Move Jira ticket to "${jiraDoneStatus || "Done"}"`}
                />
                <PlanItem on={closeIssues} label="Close linked GitHub issues" />
                <PlanItem
                  on={!!channelInput.trim() || !!qaEmailsInput.trim()}
                  label="Notify test team"
                />
                <PlanItem
                  on={!!channelInput.trim() || !!qaEmailsInput.trim()}
                  label="Reopen if QA reports a failure"
                />
              </ul>
            </div>
          </div>
        </div>

        {/* Secret shown once */}
        {justRegistered?.webhook_secret && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-6 rounded-xl border border-yellow-500/40 bg-yellow-500/5 p-4"
          >
            <div className="mb-2 flex items-center gap-2">
              <AlertTriangle size={15} className="text-yellow-600" />
              <h3 className="text-sm font-semibold text-foreground">
                Add this webhook in GitHub — the secret is shown only once
              </h3>
            </div>
            {(
              [
                ["Payload URL", justRegistered.webhook_url ?? ""],
                ["Secret", justRegistered.webhook_secret],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="mb-2">
                <p className="mb-1 text-xs text-muted-foreground">{label}</p>
                <div className="flex gap-2">
                  <code className="flex-1 overflow-x-auto rounded-lg border border-border bg-background px-2 py-1.5 font-mono text-xs">
                    {value}
                  </code>
                  <button
                    onClick={() => copy(value, label)}
                    className="rounded-lg border border-border p-1.5 hover:bg-muted"
                    aria-label={`Copy ${label}`}
                  >
                    {copied === label ? (
                      <Check size={13} className="text-green-500" />
                    ) : (
                      <Copy size={13} className="text-muted-foreground" />
                    )}
                  </button>
                </div>
              </div>
            ))}
            <p className="text-xs text-muted-foreground">
              In GitHub: Settings → Webhooks → Add webhook. Content type{" "}
              <code className="text-[11px]">application/json</code>, events ={" "}
              <strong>Pull requests</strong> only.
            </p>
            <button
              onClick={() => setJustRegistered(null)}
              className="mt-2 text-xs text-primary hover:underline"
            >
              I've added it — dismiss
            </button>
          </motion.div>
        )}

        {/* Account-wide fallbacks */}
        <GlobalDefaults docsConnected={!!summary?.docs_connected} />

        {/* Registered repos */}
        {repos.length > 0 && (
          <div className="mb-6">
            <h2 className="mb-2 text-sm font-semibold text-foreground">Registered repositories</h2>
            <div className="space-y-2">
              {repos.map((repo) => (
                <div
                  key={repo.id}
                  className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-2.5"
                >
                  <button
                    onClick={() => loadSaved(repo)}
                    className="text-sm text-foreground underline-offset-2 hover:underline"
                    title="Load these saved settings into the form"
                  >
                    {repo.repo}
                  </button>
                  {repo.slack_channel && (
                    <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {repo.slack_channel}
                    </span>
                  )}
                  {(repo.qa_emails?.length ?? 0) > 0 && (
                    <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      <Mail size={10} />
                      {repo.qa_emails?.length} QA
                    </span>
                  )}
                  {(repo.context_docs?.length ?? 0) > 0 && (
                    <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      <FileText size={10} />
                      {repo.context_docs?.length} doc
                      {(repo.context_docs?.length ?? 0) > 1 ? "s" : ""}
                    </span>
                  )}
                  {repo.export_to_docs && (
                    <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      <FileText size={10} />
                      exports
                    </span>
                  )}
                  <button
                    onClick={async () => {
                      if (!userId) return;
                      await unregisterRepo(repo.repo);
                      refresh();
                    }}
                    className="ml-auto rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-red-500"
                    aria-label={`Unregister ${repo.repo}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Review queue */}
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">Review queue</h2>
          {reviews.length > 0 && (
            <div className="flex gap-2 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Eye size={11} />
                {reviews.filter((r) => r.state === "awaiting_review").length} awaiting
              </span>
              <span className="inline-flex items-center gap-1">
                <MessageSquare size={11} />
                {reviews.filter((r) => r.state === "changes_requested").length} need
                changes
              </span>
              <span className="inline-flex items-center gap-1">
                <Check size={11} />
                {reviews.filter((r) => r.state === "approved").length} approved
              </span>
            </div>
          )}
        </div>
        {reviews.length === 0 ? (
          <div className="mb-6 rounded-xl border border-dashed border-border p-8 text-center">
            <Eye size={24} className="mx-auto mb-2 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No pull requests in review.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Add the <span className="font-mono">Pull request reviews</span> event to
              your GitHub webhook, then request a review — the loop appears here as it
              runs.
            </p>
          </div>
        ) : (
          <div className="mb-6 space-y-2">
            {reviews.map((review) => (
              <ReviewQueueRow key={review.id} review={review} />
            ))}
          </div>
        )}

        {/* Runs */}
        <h2 className="mb-2 text-sm font-semibold text-foreground">Recent runs</h2>
        {jobs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-8 text-center">
            <GitPullRequest size={24} className="mx-auto mb-2 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No analyses yet. Enter a repo and PR number above to run one.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
