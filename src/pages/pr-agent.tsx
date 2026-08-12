import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  GitMerge,
  GitPullRequest,
  Loader2,
  Mail,
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
  getPRAgentSummary,
  getPRJob,
  listPRJobs,
  listRepos,
  registerRepo,
  unregisterRepo,
  type PRAgentSummary,
  type PRJob,
  type PRJobDetail,
  type RepoRegistration,
  type PipelineStage,
  type SecurityFinding,
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
              <div
                key={issue.number}
                className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs"
              >
                <span className="text-muted-foreground">
                  {issue.relation === "closes" ? "Closes" : "Mentions"}{" "}
                </span>
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
              </div>
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
                  <tr key={i} className="border-t border-border">
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
const StageChecklist = ({ stages }: { stages: PipelineStage[] }) => {
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
            return (
              <li
                key={stage.key}
                title={stage.detail ?? ""}
                className="flex items-start gap-1.5 text-[11px]"
              >
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

const JobRow = ({ job, userId }: { job: PRJob; userId: number }) => {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<PRJobDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      setLoading(true);
      try {
        setDetail(await getPRJob(userId, job.id));
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

      {!open && <StageChecklist stages={job.stages ?? []} />}

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

export default function PRAgentDashboard() {
  const { user } = useAuth();
  const userId = user?.id;

  const [summary, setSummary] = useState<PRAgentSummary | null>(null);
  const [jobs, setJobs] = useState<PRJob[]>([]);
  const [repos, setRepos] = useState<RepoRegistration[]>([]);
  const [loading, setLoading] = useState(true);

  const [repoInput, setRepoInput] = useState("");
  const [channelInput, setChannelInput] = useState("");
  const [prInput, setPrInput] = useState("");
  const [exportDocs, setExportDocs] = useState(false);
  const [contextDocsInput, setContextDocsInput] = useState("");
  const [qaEmailsInput, setQaEmailsInput] = useState("");
  const [jiraDoneStatus, setJiraDoneStatus] = useState("Done");
  const [closeIssues, setCloseIssues] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justRegistered, setJustRegistered] = useState<RepoRegistration | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!userId) return;
    try {
      const [s, j, r] = await Promise.all([
        getPRAgentSummary(userId),
        listPRJobs(userId),
        listRepos(userId),
      ]);
      setSummary(s);
      setJobs(j);
      setRepos(r.repos);
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

      const reg = await registerRepo(
        userId,
        repoInput.trim(),
        channelInput.trim() || undefined,
        exportDocs,
        contextDocs,
        qaEmails,
        jiraDoneStatus.trim() || "Done",
        closeIssues
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
      await analyzePR(userId, repoInput.trim(), Number(prInput.trim()));
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
                  <span className="text-sm text-foreground">{repo.repo}</span>
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
                  <button
                    onClick={async () => {
                      if (!userId) return;
                      await unregisterRepo(userId, repo.repo);
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
              <JobRow key={job.id} job={job} userId={userId!} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
