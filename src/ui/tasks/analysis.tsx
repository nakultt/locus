import { Fragment } from "react";
import {
  AlertTriangle,
  Check,
  ClipboardList,
  ExternalLink,
  FileText,
  GitMerge,
  Mail,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { PRAnalysisResult } from "@/lib/api";
import { FindingRow, IssueRow, ReviewRow, StageTimeline } from "./pipeline";

/**
 * One analysis run, rendered in full.
 *
 * Extracted from the old per-job view so the task card and the settings-tab
 * run list show the same thing. The order is deliberate: what was gathered,
 * then what was found, then what was done about it.
 */
export const AnalysisView = ({ result }: { result: PRAnalysisResult }) => {
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
              <div
                key={t.key}
                className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs"
              >
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
            <span className="font-normal text-muted-foreground">
              — matched by scanner rules
            </span>
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

      {result.confirmed_findings.length === 0 &&
        result.unverified_findings.length === 0 && (
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
              <div
                key={`j${i}`}
                className="flex items-center gap-1.5 text-green-600 dark:text-green-400"
              >
                <Check size={11} /> {line}
              </div>
            ))}
            {result.merge_actions.issues_closed.map((line, i) => (
              <div
                key={`i${i}`}
                className="flex items-center gap-1.5 text-green-600 dark:text-green-400"
              >
                <Check size={11} /> {line}
              </div>
            ))}
            {(result.merge_actions.board_moves ?? []).map((line, i) => (
              <div
                key={`b${i}`}
                className="flex items-center gap-1.5 text-green-600 dark:text-green-400"
              >
                <Check size={11} /> {line}
              </div>
            ))}
            {result.merge_actions.qa_notified && (
              <div className="flex items-center gap-1.5 text-green-600 dark:text-green-400">
                <Mail size={11} /> Test team notified
              </div>
            )}
            {result.merge_actions.errors.map((line, i) => (
              <div
                key={`e${i}`}
                className="flex items-center gap-1.5 text-yellow-600 dark:text-yellow-400"
              >
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
              <li key={i} className="list-disc">
                {e}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
};
