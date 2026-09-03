"use client";

import { Fragment } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  ClipboardList,
  FileText,
  GitMerge,
  Mail,
  MessagesSquare,
  ShieldAlert,
  ShieldCheck,
  Ticket,
} from "lucide-react";
import type { PRAnalysisResult } from "@/lib/api";
import { Badge, Chip } from "@/components/ui/badge";
import { Notice, Panel } from "@/components/ui/surface";
import { FindingRow, IssueRow, ReviewRow, StageTimeline } from "./pipeline";

/**
 * One analysis run, rendered in full.
 *
 * The order is deliberate and unchanged: what was gathered, then what was
 * found, then what was done about it. What changed is the density — this used
 * to be nine sections of 10px text with `<h4>` headings that were the same
 * size as the body beneath them, so nothing separated a heading from its
 * content except a 6px margin.
 */

function Group({
  title,
  note,
  icon,
  children,
}: {
  title: string;
  note?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h4 className="flex items-center gap-2 text-h3 text-ink [&_svg]:size-4">
          {icon}
          {title}
        </h4>
        {note && <span className="text-xs text-muted">{note}</span>}
      </div>
      {children}
    </section>
  );
}

export function AnalysisView({ result }: { result: PRAnalysisResult }) {
  const ctx = result.context;
  const clean =
    result.confirmed_findings.length === 0 &&
    result.unverified_findings.length === 0;

  return (
    <div className="space-y-7">
      {/* ── The change itself ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-line bg-surface-2/60 px-4 py-3">
        <a
          href={ctx.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 font-mono text-sm font-medium text-accent-strong underline-offset-2 hover:underline"
        >
          {ctx.repo}#{ctx.pr_number}
          <ArrowUpRight className="size-3.5" aria-hidden />
        </a>
        <span className="text-sm text-muted">by {ctx.author}</span>
        <span className="tabular ml-auto flex items-center gap-3 font-mono text-xs">
          <span className="text-success">+{ctx.additions}</span>
          <span className="text-danger">−{ctx.deletions}</span>
          <span className="text-subtle">
            {ctx.files_changed} file{ctx.files_changed === 1 ? "" : "s"}
          </span>
        </span>
      </div>

      {result.stages.length > 0 && <StageTimeline stages={result.stages} />}

      {/* ── Context gathered ───────────────────────────────────────────── */}
      {ctx.linked_issues.length > 0 && (
        <Group title="Linked issues">
          <div className="space-y-2">
            {ctx.linked_issues.map((issue) => (
              <IssueRow key={issue.number} issue={issue} />
            ))}
          </div>
        </Group>
      )}

      {ctx.tickets.length > 0 && (
        <Group title="Related tickets" icon={<Ticket aria-hidden />}>
          <div className="space-y-2">
            {ctx.tickets.map((t) => (
              <div
                key={t.key}
                className="rounded-md border border-line bg-surface-2/60 px-4 py-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <a
                    href={t.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-sm font-medium text-accent-strong underline-offset-2 hover:underline"
                  >
                    {t.key}
                  </a>
                  {t.status && <Badge tone="neutral">{t.status}</Badge>}
                  {t.assignee && (
                    <span className="text-xs text-subtle">{t.assignee}</span>
                  )}
                </div>
                {t.summary && <p className="mt-1 text-sm text-ink">{t.summary}</p>}
              </div>
            ))}
          </div>
        </Group>
      )}

      {ctx.documents.length > 0 && (
        <Group
          title="Related documents"
          note="given to the reviewer as context"
          icon={<FileText aria-hidden />}
        >
          <div className="space-y-2">
            {ctx.documents.map((doc, i) => (
              <a
                key={i}
                href={doc.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2.5 rounded-md border border-line bg-surface-2/60 px-4 py-3 text-sm text-ink transition-colors hover:border-line-strong hover:bg-surface-2"
              >
                <FileText className="size-4 shrink-0 text-subtle" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{doc.title}</span>
                <ArrowUpRight className="size-3.5 shrink-0 text-subtle" aria-hidden />
              </a>
            ))}
          </div>
        </Group>
      )}

      {ctx.slack_threads.length > 0 && (
        <Group
          title="Prior discussion"
          note="where the requirement was agreed"
          icon={<MessagesSquare aria-hidden />}
        >
          <div className="space-y-2">
            {ctx.slack_threads.slice(0, 5).map((thread, i) => (
              <a
                key={i}
                href={thread.permalink}
                target="_blank"
                rel="noopener noreferrer"
                className="block rounded-md border border-line bg-surface-2/60 px-4 py-3 transition-colors hover:border-line-strong hover:bg-surface-2"
              >
                <span className="font-mono text-sm font-medium text-accent-strong">
                  #{thread.channel}
                </span>
                {thread.summary && (
                  <p className="mt-1 text-sm text-muted">{thread.summary}</p>
                )}
              </a>
            ))}
          </div>
        </Group>
      )}

      {/* ── Security ───────────────────────────────────────────────────────
          Confirmed and unverified stay visually distinct. Presenting a
          model-generated guess as a confirmed vulnerability is how a review
          bot loses a team's trust permanently. */}
      {result.confirmed_findings.length > 0 && (
        <Group
          title="Confirmed findings"
          note="matched by scanner rules"
          icon={<ShieldAlert className="text-danger" aria-hidden />}
        >
          <div className="space-y-2">
            {result.confirmed_findings.map((f, i) => (
              <FindingRow key={i} finding={f} />
            ))}
          </div>
        </Group>
      )}

      {result.unverified_findings.length > 0 && (
        <Group
          title="Possible issues"
          note="model-generated, not confirmed"
          icon={<AlertTriangle className="text-warning" aria-hidden />}
        >
          <div className="space-y-2">
            {result.unverified_findings.map((f, i) => (
              <FindingRow key={i} finding={f} />
            ))}
          </div>
        </Group>
      )}

      {clean && (
        <Notice tone="success" icon={<ShieldCheck aria-hidden />}>
          No security issues detected.
        </Notice>
      )}

      {/* ── Code review ────────────────────────────────────────────────────
          Kept visually apart from security: a clean scan on a change that
          ignores the agreed requirement is not an approval. */}
      {result.review_findings?.length > 0 ? (
        <Group
          title="Code review"
          note="the reviewer's judgement, not a scanner result"
          icon={<ClipboardList aria-hidden />}
        >
          <div className="space-y-2">
            {result.review_findings.map((f, i) => (
              <ReviewRow key={i} finding={f} />
            ))}
          </div>
        </Group>
      ) : (
        <Notice tone="info" icon={<ClipboardList aria-hidden />}>
          Code review raised no issues.
        </Notice>
      )}

      {/* ── Tools ──────────────────────────────────────────────────────────
          Distinguishes "searched and found nothing" from "never searched" —
          indistinguishable in the output otherwise. */}
      {result.tool_calls.length > 0 && (
        <Group title="Tools used">
          <Panel tone="quiet" className="scroll-x">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="border-b border-line">
                  <th className="px-4 py-2.5 text-left text-label uppercase text-subtle">
                    Service
                  </th>
                  <th className="px-4 py-2.5 text-left text-label uppercase text-subtle">
                    Tool
                  </th>
                  <th className="px-4 py-2.5 text-left text-label uppercase text-subtle">
                    Query
                  </th>
                  <th className="px-4 py-2.5 text-right text-label uppercase text-subtle">
                    Results
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.tool_calls.map((call, i) => (
                  <Fragment key={i}>
                    <tr className="border-b border-line/60 last:border-0">
                      <td className="px-4 py-2.5 text-muted">{call.service}</td>
                      <td className="px-4 py-2.5 font-mono text-xs text-ink">
                        {call.tool}
                      </td>
                      <td className="max-w-xs px-4 py-2.5">
                        {call.succeeded ? (
                          <span
                            className="block truncate font-mono text-xs text-muted"
                            title={call.query ?? ""}
                          >
                            {call.query ?? "—"}
                          </span>
                        ) : (
                          <span className="text-xs text-warning">
                            {call.detail ?? "skipped"}
                          </span>
                        )}
                      </td>
                      <td className="tabular px-4 py-2.5 text-right text-ink">
                        {call.succeeded ? call.result_count : "—"}
                      </td>
                    </tr>
                    {/* What the query actually matched. A bare count cannot be
                        sanity-checked — "1 thread" could be the wrong thread. */}
                    {call.matches?.length > 0 && (
                      <tr className="border-b border-line/60 last:border-0">
                        <td />
                        <td colSpan={3} className="px-4 pb-2.5">
                          <ul className="space-y-0.5">
                            {call.matches.map((match, m) => (
                              <li
                                key={m}
                                className="truncate text-xs text-subtle"
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
          </Panel>
        </Group>
      )}

      {/* ── Merge outcomes ─────────────────────────────────────────────── */}
      {result.merge_actions && (
        <Group title="Merge actions" icon={<GitMerge aria-hidden />}>
          <ul className="space-y-1.5">
            {[
              ...result.merge_actions.jira_transitioned,
              ...result.merge_actions.issues_closed,
              ...(result.merge_actions.board_moves ?? []),
            ].map((line, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-ink">
                <Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
                {line}
              </li>
            ))}
            {result.merge_actions.qa_notified && (
              <li className="flex items-start gap-2 text-sm text-ink">
                <Mail className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
                Testing team notified
              </li>
            )}
            {result.merge_actions.errors.map((line, i) => (
              <li key={`e${i}`} className="flex items-start gap-2 text-sm text-ink">
                <AlertTriangle
                  className="mt-0.5 size-4 shrink-0 text-warning"
                  aria-hidden
                />
                {line}
              </li>
            ))}
          </ul>

          {result.merge_actions.qa_brief && (
            <details className="group mt-2">
              <summary className="cursor-pointer list-none text-sm text-muted transition-colors hover:text-ink">
                <span className="underline underline-offset-4 decoration-line">
                  Show the brief sent to QA
                </span>
              </summary>
              <pre className="mt-2 whitespace-pre-wrap rounded-md border border-line bg-surface-2 p-4 font-mono text-xs leading-relaxed text-ink">
                {result.merge_actions.qa_brief}
              </pre>
            </details>
          )}
        </Group>
      )}

      {/* ── Where it went ──────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-5">
        <Chip mono={false} icon={result.pr_comment_posted ? <Check /> : undefined}>
          {result.pr_comment_posted ? "Commented on PR" : "No PR comment"}
        </Chip>
        <Chip mono={false} icon={result.slack_posted ? <Check /> : undefined}>
          {result.slack_posted ? "Posted to Slack" : "No Slack summary"}
        </Chip>
        {result.doc_url && (
          <a
            href={result.doc_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-pill border border-line bg-surface px-3 py-1 text-xs text-accent-strong transition-colors hover:border-line-strong"
          >
            <FileText className="size-3.5" aria-hidden />
            Full report
            <ArrowUpRight className="size-3" aria-hidden />
          </a>
        )}
      </div>

      {result.errors.length > 0 && (
        <details>
          <summary className="cursor-pointer list-none text-sm text-muted transition-colors hover:text-ink">
            <span className="underline underline-offset-4 decoration-line">
              Pipeline notes ({result.errors.length})
            </span>
          </summary>
          <ul className="mt-2 space-y-1">
            {result.errors.map((e, i) => (
              <li key={i} className="text-xs leading-relaxed text-muted">
                • {e}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
