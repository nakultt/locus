import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ClipboardList,
  Copy,
  FileText,
  GitPullRequest,
  Loader2,
  Mail,
  Play,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import {
  analyzePR,
  getPRAgentSummary,
  getTaskBoard,
  listPRJobs,
  listRepos,
  registerRepo,
  unregisterRepo,
  type MergeMethod,
  type PRAgentSummary,
  type PRJob,
  type RepoRegistration,
  type TaskBoard,
} from "@/lib/api";
import { TaskCard } from "@/ui/tasks/task-card";
import { GlobalDefaults, JobRow, PlanItem, ServiceCard } from "@/ui/tasks/setup";

/**
 * The task board.
 *
 * Organized around the work item rather than the pull request, because that
 * is the unit a person is assigned. The pipeline Locus automates starts when
 * a ticket lands on someone and ends when the testing team signs off; only
 * the coding in the middle is manual. A ticket with no pull request yet is
 * real work, and it is invisible to every PR-shaped view.
 *
 * Setup lives behind a second tab. It is necessary but consulted rarely, and
 * putting it first made the page read as a configuration screen that happened
 * to list some runs.
 */

const Stat = ({ label, value, tone }: { label: string; value: number; tone?: string }) => (
  <div className="rounded-xl border border-border bg-card p-4">
    <p className={`text-2xl font-semibold ${tone ?? "text-foreground"}`}>{value}</p>
    <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
  </div>
);

/** The board: what is assigned, and how far each piece has travelled. */
const BoardTab = ({
  board,
  loading,
  onChanged,
}: {
  board: TaskBoard | null;
  loading: boolean;
  onChanged: () => void;
}) => {
  if (loading && !board) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 size={15} className="animate-spin" /> Loading your tasks…
      </div>
    );
  }

  if (!board) return null;

  return (
    <div className="space-y-6">
      {/* A source that did not answer is said out loud. "Nothing assigned"
          and "Jira did not respond" mean very different things to someone
          deciding what to work on. */}
      {board.unavailable.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-yellow-500/40 bg-yellow-500/5 px-3 py-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-yellow-600" />
          <p className="text-xs text-foreground">
            Could not reach {board.unavailable.join(" and ")}. The tasks below are
            everything the other sources returned — this is not an empty queue.
          </p>
        </div>
      )}

      {board.total === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <ClipboardList size={24} className="mx-auto mb-2 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Nothing is assigned to you.</p>
          <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
            Open GitHub issues and Jira tickets assigned to the accounts you connected
            in Integrations appear here automatically — no configuration needed.
          </p>
        </div>
      ) : (
        <>
          <section>
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">Needs you</h2>
              {board.needs_you.length > 0 && (
                <span className="rounded-full bg-orange-500/10 px-2 py-0.5 text-[11px] font-medium text-orange-600 dark:text-orange-400">
                  {board.needs_you.length}
                </span>
              )}
            </div>

            {board.needs_you.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border p-6 text-center">
                <Check size={20} className="mx-auto mb-1.5 text-green-500" />
                <p className="text-sm text-muted-foreground">
                  Nothing is waiting on you.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {board.needs_you.map((card) => (
                  <TaskCard key={card.key} card={card} onChanged={onChanged} />
                ))}
              </div>
            )}
          </section>

          {board.in_flight.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold text-foreground">
                In flight
                <span className="ml-1.5 font-normal text-xs text-muted-foreground">
                  — running, or waiting on someone else
                </span>
              </h2>
              <div className="space-y-2">
                {board.in_flight.map((card) => (
                  <TaskCard key={card.key} card={card} onChanged={onChanged} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
};

export default function TasksPage() {
  const { user } = useAuth();
  const userId = user?.id;

  const [tab, setTab] = useState<"board" | "settings">("board");
  const [board, setBoard] = useState<TaskBoard | null>(null);
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

  const refresh = useCallback(
    async (forceAssigned = false) => {
      if (!userId) return;
      try {
        const [b, s, j, r] = await Promise.all([
          getTaskBoard(forceAssigned),
          getPRAgentSummary(),
          listPRJobs(),
          listRepos(),
        ]);
        setBoard(b);
        setSummary(s);
        setJobs(j);
        setRepos(r.repos);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load your tasks");
      } finally {
        setLoading(false);
      }
    },
    [userId]
  );

  useEffect(() => {
    refresh();
    // Runs happen in the background, so poll while any are in flight. The
    // assigned half is cached server-side, so this does not re-query GitHub
    // and Jira every tick.
    const interval = setInterval(() => refresh(), 10000);
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
      await refresh(true);
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
      await refresh(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not queue analysis");
    } finally {
      setBusy(false);
    }
  };

  if (loading && !board) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Tasks</h1>
            <p className="text-sm text-muted-foreground">
              Everything assigned to you, from the ticket landing to the testing team
              signing off.
            </p>
          </div>
          <button
            onClick={() => refresh(true)}
            className="rounded-lg border border-border p-2 hover:bg-muted"
            aria-label="Refresh"
          >
            <RefreshCw size={15} className="text-muted-foreground" />
          </button>
        </div>

        <div className="mb-6 flex gap-1 border-b border-border">
          {(["board", "settings"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                tab === t
                  ? "border-primary font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t === "board" ? "My tasks" : "Settings"}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {tab === "board" ? (
          <BoardTab board={board} loading={loading} onChanged={() => refresh(true)} />
        ) : (
          <>
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

            {/* The settings that drive every run, before anything repo-specific. */}
            <GlobalDefaults docsConnected={!!summary?.docs_connected} />

            {/* Registering a repo is about webhooks, not configuration: the
                automation above already applies to it. The per-repo fields are
                an override, so they stay collapsed rather than reading as the
                place settings are supposed to live. */}
            <details className="mb-6 rounded-xl border border-border bg-card p-4">
              <summary className="cursor-pointer text-sm font-semibold text-foreground">
                Register a repository, or override the settings above for one repo
              </summary>
              <p className="mt-1 text-xs text-muted-foreground">
                Registration is what lets GitHub notify Locus, so runs happen
                automatically. Every field here is optional — anything left blank uses
                the automation settings above.
              </p>

              <h3 className="mb-3 mt-4 text-sm font-semibold text-foreground">
                Run an analysis
              </h3>
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
                  {busy ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Play size={14} />
                  )}
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
                    — specific to this repo, read in addition to the global ones
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
                    — override for this repo only; blank uses the settings above
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
                  placeholder={
                    "senior-dev, @sr-dev, sr@company.com\ntech-lead, @lead, lead@company.com"
                  }
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
                    — override for this repo only; blank uses the settings above
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
                  Transitions are forward-only — a ticket already past this status is left
                  alone. Only issues the PR formally closes are touched.
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
                Registering enables automatic analysis on every PR. "Analyze now" works
                without it.
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
                    <PlanItem
                      on={!!summary?.github_connected}
                      label="Read linked GitHub issues"
                    />
                    <PlanItem
                      on={!!summary?.slack_search_enabled}
                      label="Search Slack history"
                    />
                    <PlanItem
                      on={!!summary?.docs_connected}
                      label="Read Google Docs as context"
                    />
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
            </details>

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
                  <strong>Pull requests</strong> and{" "}
                  <strong>Pull request reviews</strong>.
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
                <h2 className="mb-2 text-sm font-semibold text-foreground">
                  Registered repositories
                </h2>
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
                          refresh(true);
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
                  <JobRow key={job.id} job={job} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
