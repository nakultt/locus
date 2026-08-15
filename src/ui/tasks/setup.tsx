import { useEffect, useState } from "react";
import { AlertTriangle, Check, ChevronDown, ChevronRight, GitPullRequest, Loader2, X } from "lucide-react";
import {
  getPRAgentDefaults,
  getPRJob,
  savePRAgentDefaults,
  type PRAgentDefaults,
  type PRJob,
  type PRJobDetail,
  type ServiceStatus,
} from "@/lib/api";
import { formatFull } from "@/lib/datetime";
import { STATUS_STYLE } from "./shared";
import { StageChecklist } from "./pipeline";
import { AnalysisView } from "./analysis";

/**
 * One service and the individual capabilities it provides.
 *
 * A flat "connected" pill is too coarse: Slack with only a bot token can post
 * but cannot search, and that is exactly the case that silently produces thin
 * results. Each capability is listed so the gap is visible.
 */
export const ServiceCard = ({ service }: { service: ServiceStatus }) => {
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
export const PlanItem = ({ on, label }: { on: boolean; label: string }) => (
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

/**
 * Account-wide settings applied to every repo that does not override them.
 *
 * Without these, a repo nobody registered silently skips the Google Doc and
 * the QA email -- which reads as the feature being broken rather than
 * unconfigured.
 */
export const GlobalDefaults = ({ docsConnected }: { docsConnected: boolean }) => {
  const [values, setValues] = useState<PRAgentDefaults | null>(null);
  const [emailsInput, setEmailsInput] = useState("");
  const [reviewersInput, setReviewersInput] = useState("");
  const [contactsInput, setContactsInput] = useState("");
  const [docsInput, setDocsInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPRAgentDefaults()
      .then((d) => {
        setValues(d);
        setEmailsInput(d.qa_emails.join(", "));
        setReviewersInput((d.reviewers ?? []).join(", "));
        setContactsInput(d.reviewer_contacts ?? "");
        setDocsInput((d.context_docs ?? []).join("\n"));
      })
      .catch(() => setValues(null));
  }, []);

  if (!values) return null;

  /**
   * Contact lines whose first field is not one of the configured reviewers.
   *
   * The parser reads that field as the GitHub login, so a line starting with
   * an address is stored against a "login" that matches nobody. Nothing
   * errors; the reviewer just silently shows as having no contact.
   */
  const reviewerLogins = new Set(
    reviewersInput
      .split(/[,\n]/)
      .map((r) => r.trim().replace(/^@/, "").toLowerCase())
      .filter(Boolean)
  );
  const unmatchedContacts = contactsInput
    .split("\n")
    .map((line) => line.split(",")[0]?.trim().replace(/^@/, "") ?? "")
    .filter((login) => login && !reviewerLogins.has(login.toLowerCase()));

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
        reviewer_contacts: contactsInput.trim() || null,
        context_docs: docsInput
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
      });
      setValues(next);
      setEmailsInput(next.qa_emails.join(", "));
      setReviewersInput((next.reviewers ?? []).join(", "));
      setContactsInput(next.reviewer_contacts ?? "");
      setDocsInput((next.context_docs ?? []).join("\n"));
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
      <h2 className="text-sm font-semibold text-foreground">
        Automation settings
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        These drive every pull request on every repository — who reviews, who tests,
        where it is announced, and what happens on merge. A repository can override
        any of them, but nothing here needs a repository to be registered first.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">
            Slack channel for summaries
          </label>
          <input
            value={values.slack_channel ?? ""}
            onChange={(e) => setValues({ ...values, slack_channel: e.target.value })}
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
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">
            Jira status to move tickets to on merge
          </label>
          <input
            value={values.jira_done_status}
            onChange={(e) =>
              setValues({ ...values, jira_done_status: e.target.value })
            }
            placeholder="Done"
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
      </div>

      {/* A GitHub login is not a Slack handle and not an address. Without
          this the dashboard can say a review was requested but not who was
          actually reached. */}
      <div className="mt-3">
        <label className="mb-1 block text-xs text-muted-foreground">
          Reviewer contacts — one per line:{" "}
          <span className="font-mono">login, @slack, email</span>
        </label>
        <textarea
          value={contactsInput}
          onChange={(e) => setContactsInput(e.target.value)}
          placeholder={
            "senior-dev, @sr-dev, sr@company.com\ntech-lead, @lead, lead@company.com"
          }
          rows={2}
          aria-describedby="reviewer-contacts-help"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <p id="reviewer-contacts-help" className="mt-1 text-xs text-muted-foreground">
          The first field must be the GitHub login — that is what a contact is
          matched to. An address on its own cannot be matched to anyone.
        </p>

        {/* The mistake this catches is silent otherwise: the line is stored,
            no error is raised, and the dashboard simply says "no contact
            configured" against a reviewer who looks configured. */}
        {unmatchedContacts.length > 0 && (
          <div className="mt-1.5 flex items-start gap-1.5 rounded-lg border border-yellow-500/40 bg-yellow-500/5 px-2.5 py-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0 text-yellow-600" />
            <p className="text-xs text-foreground">
              {unmatchedContacts.map((c) => `"${c}"`).join(", ")}{" "}
              {unmatchedContacts.length === 1 ? "is not a" : "are not"} reviewer
              login{unmatchedContacts.length === 1 ? "" : "s"} listed above, so{" "}
              {unmatchedContacts.length === 1 ? "it" : "they"} will never be
              matched. Write it as{" "}
              <span className="font-mono">
                {(reviewersInput.split(/[,\n]/)[0] || "login").trim() || "login"},{" "}
                {unmatchedContacts[0]}
              </span>
              .
            </p>
          </div>
        )}
      </div>

      <div className="mt-3">
        <label className="mb-1 block text-xs text-muted-foreground">
          Context documents — read on every run, for every repository
        </label>
        <textarea
          value={docsInput}
          onChange={(e) => setDocsInput(e.target.value)}
          placeholder={"https://docs.google.com/document/d/.../edit\nOne per line"}
          rows={2}
          disabled={!docsConnected}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          {docsConnected
            ? "The standards that apply everywhere — a style guide, a security policy. A repository's own documents are read in addition to these, never instead of them."
            : "Connect Google Docs in Integrations to use this."}
        </p>
      </div>

      <div className="mt-3 space-y-2">
        <label className="flex items-center gap-2 text-xs text-foreground">
          <input
            type="checkbox"
            checked={values.export_to_docs}
            onChange={(e) => setValues({ ...values, export_to_docs: e.target.checked })}
            disabled={!docsConnected}
            className="rounded border-border"
          />
          Write every analysis to a Google Doc
          {!docsConnected && " (connect Google Docs first)"}
        </label>
        <p className="-mt-1 pl-5 text-xs text-muted-foreground">
          The link is included in the review request and in both testing-team
          notifications, so whoever is asked to read the change can reach the full
          analysis behind the summary.
        </p>
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
            checked={values.close_on_qa_signoff}
            onChange={(e) =>
              setValues({ ...values, close_on_qa_signoff: e.target.checked })
            }
            className="rounded border-border"
          />
          Wait for the testing team before closing the ticket
        </label>
        <p className="-mt-1 pl-5 text-xs text-muted-foreground">
          The merge leaves the ticket and its issues alone; they close when a
          tester signs off. A thread nobody answers for three days shows up in
          Needs you, so nothing is left open silently.
        </p>
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
          Still gated on green CI, no conflict, no confirmed security finding, and no P1
          review finding. Held merges are reported in Slack with the reason.
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

/** One analysis run, collapsed to its stage checklist until expanded. */
export const JobRow = ({ job }: { job: PRJob }) => {
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
          {formatFull(job.created_at)}
        </span>
      </button>

      {!open && <StageChecklist stages={job.stages ?? []} toolCalls={job.tool_calls ?? []} />}

      {open && (
        <div className="border-t border-border px-4 py-3">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> Loading...
            </div>
          ) : detail?.status === "failed" ? (
            <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
              {detail.error || "The run failed without recording a reason."}
            </div>
          ) : detail?.result ? (
            <AnalysisView result={detail.result} />
          ) : detail ? (
            <p className="text-xs text-muted-foreground">
              {detail.status === "queued" || detail.status === "running"
                ? "Analysis in progress..."
                : "No result recorded."}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">Could not load this run.</p>
          )}
        </div>
      )}
    </div>
  );
};
