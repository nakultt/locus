"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Bot,
  CalendarClock,
  Check,
  Copy,
  FileText,
  GitPullRequest,
  Mail,
  Play,
  Plus,
  ShieldCheck,
  Terminal,
  Trash2,
  UserPlus,
  UserRound,
  Webhook,
  X,
} from "lucide-react";
import {
  analyzePR,
  getAgentRuntime,
  getAuthoringPresets,
  getPRAgentDefaults,
  getPRAgentSummary,
  listRepos,
  matchesPreset,
  registerRepo,
  savePRAgentDefaults,
  unregisterRepo,
  type AgentRuntimeResolved,
  type AuthoringPreset,
  type CapabilityStatus,
  type MergeMethod,
  type PRAgentDefaults,
  type PRAgentSummary,
  type RepoRegistration,
  type ServiceStatus,
} from "@/lib/api";
import { Badge, Chip } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import {
  CheckboxRow,
  Field,
  Input,
  Select,
  Textarea,
} from "@/components/ui/form";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import {
  EmptyState,
  Kicker,
  Notice,
  Panel,
  Section,
  Skeleton,
} from "@/components/ui/surface";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/**
 * Automation.
 *
 * This is the settings half of what used to be the second tab on the task
 * board — five hundred lines of configuration sitting behind a tab on a page
 * whose job is showing you what needs doing. It belongs in Settings, which is
 * where someone goes looking for it, and where it can be laid out as a form
 * rather than crammed under a queue.
 *
 * Three sections, in the order a person needs them: what the pipeline can
 * currently reach, what it does by default, and which repositories override
 * that. Registering a repo moved into a dialog — it is a one-off act, and it
 * was previously a `<details>` element containing twenty fields, most of which
 * duplicated the defaults immediately above it.
 */

/* ── Readiness ────────────────────────────────────────────────────────────── */

function Capability({ cap }: { cap: CapabilityStatus }) {
  return (
    <li className="flex items-start gap-2 text-sm" title={cap.hint}>
      {cap.available ? (
        <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
      ) : (
        <X className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
      )}
      <span className={cap.available ? "text-ink" : "text-subtle"}>
        {cap.label}
      </span>
    </li>
  );
}

/**
 * One service and the individual capabilities it provides.
 *
 * A flat "connected" pill is too coarse: Slack with only a bot token can post
 * but cannot search, and that is exactly the case that silently produces thin
 * results. Each capability is listed so the gap is visible.
 */
function ServicePanel({ service }: { service: ServiceStatus }) {
  const missing = service.capabilities.filter((c) => !c.available);
  // Amber means something a run needs is unavailable — not merely that an
  // optional capability is off. Toning every partially-configured service as a
  // warning turned the whole section yellow and made the one real problem
  // indistinguishable from two ordinary ones.
  const missingRequired = missing.some((c) => c.required);
  const tone = !service.connected
    ? service.required
      ? "danger"
      : "quiet"
    : missingRequired
      ? "warning"
      : "default";

  return (
    <Panel tone={tone} className="p-4">
      <div className="flex items-center gap-2">
        {!service.connected ? (
          <X
            className={cn(
              "size-4 shrink-0",
              service.required ? "text-danger" : "text-subtle"
            )}
            aria-hidden
          />
        ) : missingRequired ? (
          <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden />
        ) : (
          <Check className="size-4 shrink-0 text-success" aria-hidden />
        )}
        <h4 className="text-h3 text-ink">{service.label}</h4>
        {service.required && <Badge tone="outline">required</Badge>}
        {service.connected && missing.length > 0 && !missingRequired && (
          <span className="ml-auto text-xs text-subtle">
            {missing.length} optional off
          </span>
        )}
      </div>
      <ul className="mt-2.5 space-y-1.5">
        {service.capabilities.map((cap) => (
          <Capability key={cap.key} cap={cap} />
        ))}
      </ul>
    </Panel>
  );
}

/* ── Defaults ─────────────────────────────────────────────────────────────── */

const parseList = (raw: string) =>
  raw
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);

const parseLines = (raw: string) =>
  raw
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

/**
 * Account-wide settings applied to every repo that does not override them.
 *
 * Without these, a repo nobody registered silently skips the Google Doc and
 * the QA email — which reads as the feature being broken rather than
 * unconfigured.
 */
function Defaults({ docsConnected }: { docsConnected: boolean }) {
  const toast = useToast();
  const [values, setValues] = useState<PRAgentDefaults | null>(null);
  const [presets, setPresets] = useState<AuthoringPreset[]>([]);
  // What each blank runtime field currently resolves to. Rendered as the
  // placeholders, so "blank inherits" is checkable rather than a claim.
  const [resolved, setResolved] = useState<AgentRuntimeResolved | null>(null);
  const [emails, setEmails] = useState("");
  const [reviewers, setReviewers] = useState("");
  const [contacts, setContacts] = useState("");
  const [docs, setDocs] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getPRAgentDefaults()
      .then((d) => {
        setValues(d);
        setEmails(d.qa_emails.join(", "));
        setReviewers((d.reviewers ?? []).join(", "));
        setContacts(d.reviewer_contacts ?? "");
        setDocs((d.context_docs ?? []).join("\n"));
      })
      .catch(() => setValues(null))
      .finally(() => setLoaded(true));
    // A preset list that fails to load costs the shortcut, never the form.
    getAuthoringPresets()
      .then((rows) => setPresets(Array.isArray(rows) ? rows : []))
      .catch(() => setPresets([]));
    // Same rule: a failed resolve costs the placeholders, never the form.
    getAgentRuntime()
      .then(setResolved)
      .catch(() => setResolved(null));
  }, []);

  if (!loaded) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (!values) {
    return (
      <Notice tone="danger" title="Could not load your automation settings">
        The backend did not answer. Everything below is unavailable until it
        does.
      </Notice>
    );
  }

  const set = <K extends keyof PRAgentDefaults>(
    key: K,
    value: PRAgentDefaults[K]
  ) => setValues((v) => (v ? { ...v, [key]: value } : v));

  /**
   * Contact lines whose first field is not one of the configured reviewers.
   *
   * The parser reads that field as the GitHub login, so a line starting with
   * an address is stored against a "login" that matches nobody. Nothing
   * errors; the reviewer just silently shows as having no contact.
   */
  const reviewerLogins = new Set(
    parseList(reviewers).map((r) => r.replace(/^@/, "").toLowerCase())
  );
  const unmatched = contacts
    .split("\n")
    .map((line) => line.split(",")[0]?.trim().replace(/^@/, "") ?? "")
    .filter((login) => login && !reviewerLogins.has(login.toLowerCase()));

  const save = async () => {
    setSaving(true);
    try {
      const next = await savePRAgentDefaults({
        ...values,
        qa_emails: parseList(emails).filter((e) => e.includes("@")),
        reviewers: parseList(reviewers).map((r) => r.replace(/^@/, "")),
        reviewer_contacts: contacts.trim() || null,
        context_docs: parseLines(docs),
      });
      setValues(next);
      setEmails(next.qa_emails.join(", "));
      setReviewers((next.reviewers ?? []).join(", "));
      setContacts(next.reviewer_contacts ?? "");
      setDocs((next.context_docs ?? []).join("\n"));
      getAgentRuntime().then(setResolved).catch(() => {});
      toast.success("Automation settings saved");
    } catch (e) {
      toast.error(
        "Could not save",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setSaving(false);
    }
  };

  const autonomous = values.authoring_mode === "autonomous";

  return (
    <div className="space-y-8">
      {/* ── Who writes the code ─────────────────────────────────────────
          A preset writes these dials into the form and nothing else. Every
          one of them stays visible and editable below, and the backend
          resolver remains the only thing that decides what a run does — a
          preset expanded at read time would be a second resolution layer
          above it. */}
      {presets.length > 0 && (
        <Section
          title="Who writes the code"
          description="A starting point for the authoring dials. Any single ticket can be switched from its own card."
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {presets.map((preset) => {
              const active =
                values.authoring_mode === preset.values.authoring_mode;
              const modified = active && !matchesPreset(preset, values);
              return (
                <button
                  key={preset.name}
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    setValues({
                      ...values,
                      ...preset.values,
                      preset_label: preset.name,
                    })
                  }
                  className={cn(
                    "rounded-lg border p-4 text-left transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    active
                      ? "border-accent bg-accent-soft"
                      : "border-line bg-surface hover:border-line-strong"
                  )}
                >
                  <span className="flex items-center gap-2">
                    {preset.values.authoring_mode === "autonomous" ? (
                      <Bot className="size-4 shrink-0 text-accent-strong" aria-hidden />
                    ) : (
                      <UserRound className="size-4 shrink-0 text-subtle" aria-hidden />
                    )}
                    <span className="text-h3 text-ink">{preset.label}</span>
                    {modified && (
                      <span className="text-xs font-normal text-muted">
                        modified
                      </span>
                    )}
                  </span>
                  <span className="mt-1.5 block text-sm leading-relaxed text-muted">
                    {preset.description}
                  </span>
                </button>
              );
            })}
          </div>

          {autonomous && (
            <div className="space-y-4">
              {/* The one claim a user must not find in a changelog. */}
              <Notice
                tone="warning"
                icon={<AlertTriangle aria-hidden />}
                title="Autonomous briefs leave your machine"
              >
                The security scan, the code review and the QA classifier run on
                your local model server, on every push, without being asked.
                Authoring does not: a ticket you hand over sends its brief — the
                description, the Slack discussion and your source — to the model
                OpenCode is configured with, which is remote. Check that
                provider&apos;s retention and training terms before pointing this
                at a private repository.
              </Notice>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="Attempts before it comes back to you"
                  htmlFor="rounds"
                  hint={`The first attempt plus ${values.autonomous_max_rounds} rework${values.autonomous_max_rounds === 1 ? "" : "s"}. A timeout, an oversized diff or a failed test gate each spend one — otherwise a reliably-failing ticket retries forever.`}
                >
                  <Input
                    id="rounds"
                    type="number"
                    min={0}
                    max={10}
                    value={values.autonomous_max_rounds}
                    onChange={(e) =>
                      set("autonomous_max_rounds", Number(e.target.value))
                    }
                  />
                </Field>

                <div className="space-y-4">
                  <Field
                    label="Prepare command"
                    htmlFor="prepare"
                    hint="Run in the fresh worktree before the agent."
                  >
                    <Input
                      id="prepare"
                      className="font-mono text-xs"
                      placeholder="uv sync --extra security"
                      value={values.prepare_command ?? ""}
                      onChange={(e) =>
                        set("prepare_command", e.target.value || null)
                      }
                    />
                  </Field>
                  <Field
                    label="Test command"
                    htmlFor="test"
                    hint="The gate before a pull request opens. A fresh worktree has no node_modules and no .venv, so this cannot run without the prepare command. Blank means no gate."
                  >
                    <Input
                      id="test"
                      className="font-mono text-xs"
                      placeholder="uv run pytest tests/ -q"
                      value={values.test_command ?? ""}
                      onChange={(e) =>
                        set("test_command", e.target.value || null)
                      }
                    />
                  </Field>
                </div>
              </div>
            </div>
          )}
        </Section>
      )}

      {/* ── Agent runtime ────────────────────────────────────────────────
          How this account's agent runs, as opposed to which tickets it may
          write. Every one of these was an environment variable, which made it
          one operator's answer for every tenant — including the context mode,
          which decides whether your Slack discussion may be sent to a third
          party.

          Every field may be left blank, and blank inherits: the deployment's
          variable first, then the constant in the code. The placeholder under
          each one shows what it currently resolves to, because an empty box
          with no hint is where someone types a guess — and for the command
          template or the source root, that guess has a shell behind it. */}
      <Section
        title="Agent runtime"
        description={
          resolved?.configured
            ? "Your settings. Anything left blank inherits this deployment's default."
            : "Inheriting this deployment's defaults. Anything you set here applies to your account only."
        }
      >
        <Panel className="space-y-5 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Driver"
              htmlFor="rt-driver"
              hint="What actually writes the code. None is the safe answer: it reports that no driver is configured rather than running anything."
            >
              <Select
                id="rt-driver"
                value={values.authoring_driver ?? ""}
                onChange={(e) =>
                  set("authoring_driver", e.target.value || null)
                }
              >
                <option value="">
                  Inherit{resolved ? ` (${resolved.driver})` : ""}
                </option>
                <option value="opencode">OpenCode</option>
                <option value="none">None</option>
              </Select>
            </Field>

            <Field
              label="How much of the brief leaves the machine"
              htmlFor="rt-context"
              hint="ticket_only drops the Slack transcript and the issue bodies. It costs output quality — that discussion is where the requirement actually lives — and it is the setting for a team that cannot send internal discussion to a third party."
            >
              <Select
                id="rt-context"
                value={values.authoring_context ?? ""}
                onChange={(e) =>
                  set("authoring_context", e.target.value || null)
                }
              >
                <option value="">
                  Inherit{resolved ? ` (${resolved.context_mode})` : ""}
                </option>
                <option value="full">Full brief</option>
                <option value="ticket_only">Ticket only</option>
              </Select>
            </Field>
          </div>

          <Field
            label="Authoring model"
            htmlFor="rt-model"
            hint="Pins the model for reproducibility across attempts. Blank lets the driver use its own. This one is remote whatever you choose — it is the exception to everything else running locally."
          >
            <Input
              id="rt-model"
              className="font-mono text-xs"
              placeholder={resolved?.model || "the driver's own"}
              value={values.authoring_model ?? ""}
              onChange={(e) => set("authoring_model", e.target.value || null)}
              spellCheck={false}
            />
          </Field>

          <Field
            label="Invocation template"
            htmlFor="rt-command"
            hint="{prompt} and {workspace} are substituted. A template rather than fixed flags, because the CLI moves and a pinned flag breaks on an upgrade with a non-zero exit and no useful message."
          >
            <Input
              id="rt-command"
              className="font-mono text-xs"
              placeholder={resolved?.command || "opencode run --prompt-file {prompt}"}
              value={values.authoring_command ?? ""}
              onChange={(e) => set("authoring_command", e.target.value || null)}
              spellCheck={false}
            />
          </Field>

          {/* ── The bounds ──────────────────────────────────────────────
              Reviewer attention is the scarce resource this mode spends, and
              every one of these is a limit on how much of it one ticket can
              consume. A 4,000-line agent-authored diff is not reviewable. */}
          <div className="border-t border-line pt-5">
            <Kicker>Bounds</Kicker>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Reviewer attention is what this mode actually spends. A run over
              any of these is refused and recorded — it is not retried smaller,
              because the ticket was too big for the mode and that is something
              the human should hear.
            </p>

            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Timeout (seconds)" htmlFor="rt-timeout">
                <Input
                  id="rt-timeout"
                  type="number"
                  min={60}
                  max={7200}
                  placeholder={String(resolved?.timeout_seconds ?? "")}
                  value={values.authoring_timeout_seconds ?? ""}
                  onChange={(e) =>
                    set(
                      "authoring_timeout_seconds",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>

              <Field label="Max files" htmlFor="rt-files">
                <Input
                  id="rt-files"
                  type="number"
                  min={1}
                  max={500}
                  placeholder={String(resolved?.max_changed_files ?? "")}
                  value={values.max_changed_files ?? ""}
                  onChange={(e) =>
                    set(
                      "max_changed_files",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>

              <Field label="Max lines" htmlFor="rt-lines">
                <Input
                  id="rt-lines"
                  type="number"
                  min={1}
                  max={100000}
                  placeholder={String(resolved?.max_changed_lines ?? "")}
                  value={values.max_changed_lines ?? ""}
                  onChange={(e) =>
                    set(
                      "max_changed_lines",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>

              <Field
                label="Open PRs per repo"
                htmlFor="rt-open"
                hint="The rubber-stamping cap."
              >
                <Input
                  id="rt-open"
                  type="number"
                  min={0}
                  max={50}
                  placeholder={String(resolved?.max_open_prs ?? "")}
                  value={values.max_open_autonomous_prs ?? ""}
                  onChange={(e) =>
                    set(
                      "max_open_autonomous_prs",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>
            </div>
          </div>

          {/* ── Where the code is, and where the agent may write ─────────
              Two different questions. Conflating them is how an agent ends up
              editing Locus itself — which is refused whatever is typed here,
              in both directions, by the same check that has always guarded
              the environment variable. */}
          <div className="border-t border-line pt-5">
            <Kicker>Workspace</Kicker>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Where your repositories already sit, and where the agent is
              allowed to work. They are different questions: the agent always
              works in a <code className="font-mono text-xs">git worktree</code>{" "}
              cut from your checkout, so your branch, your uncommitted changes
              and your stashes are never touched. A path resolving to Locus&apos;s
              own tree, to something that is not a git repository, or to a repo
              whose <code className="font-mono text-xs">origin</code> does not
              match is refused as a configuration error.
            </p>

            <div className="mt-4 space-y-4">
              <Field
                label="Source root"
                htmlFor="rt-code-root"
                hint="A folder holding many repos. Used when a repository sets no path of its own."
              >
                <Input
                  id="rt-code-root"
                  className="font-mono text-xs"
                  placeholder={resolved?.code_root || "E:/Github"}
                  value={values.code_root ?? ""}
                  onChange={(e) => set("code_root", e.target.value || null)}
                  spellCheck={false}
                />
              </Field>

              <Field
                label="Workspace root"
                htmlFor="rt-ws-root"
                hint="Where the throwaway worktrees are cut. Blank uses the system temp directory."
              >
                <Input
                  id="rt-ws-root"
                  className="font-mono text-xs"
                  placeholder={resolved?.workspace_root || "system temp"}
                  value={values.workspace_root ?? ""}
                  onChange={(e) => set("workspace_root", e.target.value || null)}
                  spellCheck={false}
                />
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="Work in the checkout itself"
                  htmlFor="rt-in-place"
                  hint="Off unless a tree genuinely cannot be worktree'd. On, the agent shares a working tree with a person: git checkout becomes destructive and concurrent attempts become impossible."
                >
                  <Select
                    id="rt-in-place"
                    value={
                      values.allow_in_place == null
                        ? ""
                        : values.allow_in_place
                          ? "on"
                          : "off"
                    }
                    onChange={(e) =>
                      set(
                        "allow_in_place",
                        e.target.value === ""
                          ? null
                          : e.target.value === "on"
                      )
                    }
                  >
                    <option value="">
                      Inherit
                      {resolved ? ` (${resolved.allow_in_place ? "on" : "off"})` : ""}
                    </option>
                    <option value="off">Off — always use a worktree</option>
                    <option value="on">On — write in the checkout</option>
                  </Select>
                </Field>

                <Field
                  label="Keep failed worktrees for (days)"
                  htmlFor="rt-ttl"
                  hint="A failed run whose tree is gone is close to undebuggable, so they are kept and pruned on a timer."
                >
                  <Input
                    id="rt-ttl"
                    type="number"
                    min={0}
                    max={90}
                    placeholder={String(resolved?.workspace_ttl_days ?? "")}
                    value={values.workspace_ttl_days ?? ""}
                    onChange={(e) =>
                      set(
                        "workspace_ttl_days",
                        e.target.value ? Number(e.target.value) : null
                      )
                    }
                  />
                </Field>
              </div>
            </div>
          </div>

          {/* ── Commit identity ─────────────────────────────────────────
              Also the test for "did a human commit on this branch", which is
              what ends autonomous mode for a work item. Changing it while an
              attempt is open makes the agent's own commits read as a
              person's. */}
          <div className="border-t border-line pt-5">
            <Kicker>
              <Terminal className="mr-1.5 inline size-3.5" aria-hidden />
              Commit identity
            </Kicker>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Who the agent&apos;s commits are attributed to. This is also how a
              person&apos;s commits on a branch are told apart from a previous
              attempt&apos;s — a human commit hands the work item back — so
              changing it while an attempt is open makes the agent&apos;s own
              commits read as someone else&apos;s.
            </p>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="rt-agent-name">
                <Input
                  id="rt-agent-name"
                  placeholder={resolved?.agent_name}
                  value={values.agent_commit_name ?? ""}
                  onChange={(e) =>
                    set("agent_commit_name", e.target.value || null)
                  }
                />
              </Field>

              <Field label="Email" htmlFor="rt-agent-email">
                <Input
                  id="rt-agent-email"
                  className="font-mono text-xs"
                  placeholder={resolved?.agent_email}
                  value={values.agent_commit_email ?? ""}
                  onChange={(e) =>
                    set("agent_commit_email", e.target.value || null)
                  }
                  spellCheck={false}
                />
              </Field>
            </div>
          </div>

          {/* ── Review request ──────────────────────────────────────────
              Who GitHub asks to review the pull requests the agent opens.
              Deliberately not the reviewer list above: that one addresses the
              review loop's Slack pings, and turning it into a review request
              would start notifying people who only agreed to be mentioned in
              a channel. Blank requests nobody, which is what this mode did
              before the setting existed. */}
          <div className="border-t border-line pt-5">
            <Kicker>
              <UserPlus className="mr-1.5 inline size-3.5" aria-hidden />
              Review request
            </Kicker>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Who is asked to review the pull requests the agent opens, on
              GitHub itself. Requested once, on the pull request the agent
              actually creates — a rework pushes to the same branch, and
              re-requesting there would re-notify the reviewer on every round.
              The agent&apos;s own account is skipped: GitHub rejects a request
              naming the author, and it rejects the whole list with it.
            </p>

            <div className="mt-4">
              <Field
                label="Request a review from"
                htmlFor="rt-pr-reviewers"
                hint="One GitHub login per line. Blank opens the pull request without requesting anybody."
              >
                <Textarea
                  id="rt-pr-reviewers"
                  mono
                  rows={3}
                  placeholder={
                    resolved?.pr_reviewers?.length
                      ? resolved.pr_reviewers.join("\n")
                      : "senior-dev\ntech-lead"
                  }
                  value={values.autonomous_pr_reviewers ?? ""}
                  onChange={(e) =>
                    set("autonomous_pr_reviewers", e.target.value || null)
                  }
                  spellCheck={false}
                />
              </Field>
            </div>
          </div>

          {/* ── Calendar agent ──────────────────────────────────────────
              Per-user dials on a per-user agent. The loop still ticks on its
              own clock; a user is swept when their own interval has elapsed,
              which is what stops one aggressive setting from turning into a
              Google rate limit for everybody. */}
          <div className="border-t border-line pt-5">
            <Kicker>
              <CalendarClock className="mr-1.5 inline size-3.5" aria-hidden />
              Calendar agent
            </Kicker>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              How often your calendars are checked for conflicts, and how far
              ahead each sweep looks. Every sweep costs a Calendar call, and
              the ceiling on how fast a calendar changes is far below the
              ceiling on how fast Google rate-limits.
            </p>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label="Sweep every (minutes)" htmlFor="rt-sweep">
                <Input
                  id="rt-sweep"
                  type="number"
                  min={5}
                  max={1440}
                  placeholder={String(resolved?.calendar_sweep_minutes ?? "")}
                  value={values.calendar_sweep_minutes ?? ""}
                  onChange={(e) =>
                    set(
                      "calendar_sweep_minutes",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>

              <Field label="Look ahead (days)" htmlFor="rt-lookahead">
                <Input
                  id="rt-lookahead"
                  type="number"
                  min={1}
                  max={90}
                  placeholder={String(resolved?.calendar_lookahead_days ?? "")}
                  value={values.calendar_lookahead_days ?? ""}
                  onChange={(e) =>
                    set(
                      "calendar_lookahead_days",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>
            </div>
          </div>
        </Panel>
      </Section>

      {/* ── Routing ─────────────────────────────────────────────────────── */}
      <Section
        title="Where things go"
        description="Who reviews, who tests, and where each run is announced. A repository can override any of these."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Slack channel for summaries"
            htmlFor="slack-channel"
          >
            <Input
              id="slack-channel"
              placeholder="#dev-updates"
              value={values.slack_channel ?? ""}
              onChange={(e) => set("slack_channel", e.target.value)}
            />
          </Field>

          <Field
            label="Slack channel for review requests"
            htmlFor="review-channel"
            hint="Falls back to the summary channel when blank."
          >
            <Input
              id="review-channel"
              placeholder="#code-review"
              value={values.review_slack_channel ?? ""}
              onChange={(e) => set("review_slack_channel", e.target.value)}
            />
          </Field>

          <Field
            label="Senior dev reviewers"
            htmlFor="reviewers"
            hint="GitHub logins. This is who gets pinged, not who is allowed to review — a review from anyone else is still recorded."
          >
            <Input
              id="reviewers"
              placeholder="senior-dev, tech-lead"
              value={reviewers}
              onChange={(e) => setReviewers(e.target.value)}
            />
          </Field>

          <Field
            label="Testing team emails"
            htmlFor="qa-emails"
            hint="Notified on every merge."
          >
            <Input
              id="qa-emails"
              placeholder="qa@company.com, lead@company.com"
              value={emails}
              onChange={(e) => setEmails(e.target.value)}
            />
          </Field>
        </div>

        {/* A GitHub login is not a Slack handle and not an address. Without
            this the dashboard can say a review was requested but not who was
            actually reached. */}
        <Field
          label="Reviewer contacts"
          htmlFor="contacts"
          hint="One per line: login, @slack, email. The first field must be the GitHub login — that is what a contact is matched to."
        >
          <Textarea
            id="contacts"
            mono
            rows={3}
            placeholder={"senior-dev, @sr-dev, sr@company.com\ntech-lead, @lead, lead@company.com"}
            value={contacts}
            onChange={(e) => setContacts(e.target.value)}
          />
        </Field>

        {/* The mistake this catches is silent otherwise: the line is stored,
            no error is raised, and the dashboard simply says "no contact
            configured" against a reviewer who looks configured. */}
        {unmatched.length > 0 && (
          <Notice tone="warning" icon={<AlertTriangle aria-hidden />}>
            {unmatched.map((c) => `“${c}”`).join(", ")}{" "}
            {unmatched.length === 1 ? "is not a reviewer" : "are not reviewers"}{" "}
            listed above, so {unmatched.length === 1 ? "it" : "they"} will never
            be matched. Write it as{" "}
            <strong className="font-mono">
              {(parseList(reviewers)[0] || "login").trim()}, {unmatched[0]}
            </strong>
            .
          </Notice>
        )}
      </Section>

      {/* ── Context ─────────────────────────────────────────────────────── */}
      <Section
        title="Standing context"
        description="Read on every run, for every repository."
      >
        <Field
          label="Context documents"
          htmlFor="context-docs"
          hint={
            docsConnected
              ? "The standards that apply everywhere — a style guide, a security policy. A repository's own documents are read in addition to these, never instead of them."
              : "Connect Google Docs to use this."
          }
        >
          <Textarea
            id="context-docs"
            mono
            rows={3}
            disabled={!docsConnected}
            placeholder={"https://docs.google.com/document/d/.../edit\nOne per line"}
            value={docs}
            onChange={(e) => setDocs(e.target.value)}
          />
        </Field>
      </Section>

      {/* ── Behaviour ───────────────────────────────────────────────────── */}
      <Section
        title="What happens on merge"
        description="Each of these is off or on for every repository that does not say otherwise."
      >
        <Panel className="divide-y divide-line">
          <div className="p-5">
            <CheckboxRow
              id="export-docs"
              checked={values.export_to_docs}
              disabled={!docsConnected}
              onCheckedChange={(v) => set("export_to_docs", v)}
              label={
                <>
                  Write every analysis to a Google Doc
                  {!docsConnected && (
                    <span className="ml-1.5 font-normal text-subtle">
                      connect Google Docs first
                    </span>
                  )}
                </>
              }
              hint="The link is included in the review request and in both testing-team notifications, so whoever is asked to read the change can reach the full analysis behind the summary."
            />
          </div>

          <div className="p-5">
            <CheckboxRow
              id="close-issues"
              checked={values.close_issues_on_merge}
              onCheckedChange={(v) => set("close_issues_on_merge", v)}
              label="Close linked GitHub issues on merge"
              hint="Only issues the pull request formally closes are touched."
            />
          </div>

          <div className="p-5">
            <CheckboxRow
              id="qa-signoff"
              checked={values.close_on_qa_signoff}
              onCheckedChange={(v) => set("close_on_qa_signoff", v)}
              label="Wait for the testing team before closing the ticket"
              hint="The merge leaves the ticket and its issues alone; they close when a tester signs off. A thread nobody answers for three days shows up in Needs you, so nothing is left open silently."
            />
          </div>

          <div className="p-5">
            <CheckboxRow
              id="auto-merge"
              checked={values.auto_merge_on_approval}
              onCheckedChange={(v) => set("auto_merge_on_approval", v)}
              label="Merge automatically when a review approves"
              hint="Still gated on green CI, no merge conflict and no confirmed security finding. Review findings never block — the reviewer approving has already read them. Held merges are reported in Slack with the reason."
            >
              <Select
                selectSize="sm"
                aria-label="Merge method"
                value={values.merge_method}
                disabled={!values.auto_merge_on_approval}
                onChange={(e) =>
                  set("merge_method", e.target.value as MergeMethod)
                }
                className="w-28"
              >
                <option value="squash">squash</option>
                <option value="merge">merge</option>
                <option value="rebase">rebase</option>
              </Select>
            </CheckboxRow>
          </div>

          <div className="space-y-3 p-5">
            <CheckboxRow
              id="board-sync"
              checked={values.project_board_sync}
              onCheckedChange={(v) => set("project_board_sync", v)}
              label="Move GitHub Projects cards as the work moves"
              hint="GitHub's own project workflows only react to an issue closing, so a card otherwise sits in Todo through the entire review and QA round trip. Cards move forward only, except a QA rejection, which pulls the card back with the reopened ticket. Needs the project OAuth scope — repo does not include it."
            />
            <div className="pl-8">
              <Textarea
                aria-label="Stage to column map"
                mono
                rows={3}
                disabled={!values.project_board_sync}
                placeholder={"in_review: In review\ntesting: QA\ndone: Done"}
                value={values.project_column_map ?? ""}
                onChange={(e) =>
                  set("project_column_map", e.target.value || null)
                }
              />
              <p className="mt-1.5 text-xs leading-relaxed text-muted">
                Optional, one{" "}
                <span className="font-mono">stage: column</span> per line. Blank
                maps the branch through testing to &ldquo;In progress&rdquo; and
                only a QA sign-off to &ldquo;Done&rdquo; — merged is not done.
                Your own map replaces that entirely, and a stage you leave out
                moves no card.
              </p>
            </div>
          </div>

          <div className="p-5">
            <Field
              label="Jira status to move tickets to on merge"
              htmlFor="jira-status"
              hint="Transitions are forward-only — a ticket already past this status is left alone."
              className="max-w-xs"
            >
              <Input
                id="jira-status"
                placeholder="Done"
                value={values.jira_done_status}
                onChange={(e) => set("jira_done_status", e.target.value)}
              />
            </Field>
          </div>
        </Panel>
      </Section>

      {/* Sticky, because this form is long enough that the save button was
          previously below the fold from the moment the page loaded. */}
      <div className="sticky bottom-0 -mx-1 flex items-center gap-3 border-t border-line bg-bg/90 px-1 py-4 backdrop-blur">
        <Button onClick={save} loading={saving}>
          Save automation settings
        </Button>
        <p className="text-xs text-muted">
          Applies to every repository that does not override it.
        </p>
      </div>
    </div>
  );
}

/* ── Repositories ─────────────────────────────────────────────────────────── */

function RegisterDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (reg: RepoRegistration) => void;
}) {
  const toast = useToast();
  const [repo, setRepo] = useState("");
  const [channel, setChannel] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repo.trim()) return;
    setBusy(true);
    try {
      // Only the two fields that are genuinely per-repo. Everything else
      // inherits from the defaults above — the old form asked for all twenty
      // again here, which implied they had to be re-entered per repository.
      const reg = await registerRepo({
        repo: repo.trim(),
        slackChannel: channel.trim() || undefined,
      });
      onDone(reg);
      setRepo("");
      setChannel("");
    } catch (err) {
      toast.error(
        "Could not register",
        err instanceof Error ? err.message : undefined
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Register a repository"
      description="Registration is what lets GitHub notify Locus, so runs happen automatically on every push. Your automation settings already apply to it."
      footer={
        <>
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="register-repo"
            loading={busy}
            disabled={!repo.trim()}
          >
            Register
          </Button>
        </>
      }
    >
      <form id="register-repo" onSubmit={submit} className="space-y-4">
        <Field label="Repository" htmlFor="repo" required>
          <Input
            id="repo"
            data-autofocus
            placeholder="owner/repo"
            className="font-mono"
            spellCheck={false}
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            required
          />
        </Field>
        <Field
          label="Slack channel"
          htmlFor="repo-channel"
          hint="Overrides your default summary channel for this repository only."
        >
          <Input
            id="repo-channel"
            placeholder="#team-api"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          />
        </Field>
      </form>
    </Dialog>
  );
}

/**
 * The webhook credentials, shown once.
 *
 * A secret that is displayed once and then unavailable forever needs to be
 * unmissable, so it is a dialog rather than a strip that can be scrolled past.
 */
function WebhookDialog({
  registration,
  onClose,
}: {
  registration: RepoRegistration;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);

  const copy = (value: string, key: string) => {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  const rows: [string, string][] = [
    ["Payload URL", registration.webhook_url ?? ""],
    ["Secret", registration.webhook_secret ?? ""],
  ];

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title="Add this webhook in GitHub"
      description={`${registration.repo} is registered. The secret below is shown once and cannot be retrieved afterwards.`}
      footer={
        <Button data-autofocus onClick={onClose}>
          I have added it
        </Button>
      }
    >
      <div className="space-y-4">
        {rows.map(([label, value]) => (
          <div key={label}>
            <Kicker>{label}</Kicker>
            <div className="mt-1.5 flex gap-2">
              <code className="scroll-x flex-1 whitespace-nowrap rounded-md border border-line bg-surface-2 px-3 py-2.5 font-mono text-xs text-ink">
                {value}
              </code>
              <IconButton
                label={copied === label ? "Copied" : `Copy ${label.toLowerCase()}`}
                variant="secondary"
                onClick={() => copy(value, label)}
              >
                {copied === label ? (
                  <Check className="text-success" />
                ) : (
                  <Copy />
                )}
              </IconButton>
            </div>
          </div>
        ))}

        <Notice tone="info" icon={<Webhook aria-hidden />}>
          In GitHub: <strong>Settings → Webhooks → Add webhook</strong>. Content
          type <strong className="font-mono">application/json</strong>, and
          select the <strong>Pull requests</strong> and{" "}
          <strong>Pull request reviews</strong> events.
        </Notice>
      </div>
    </Dialog>
  );
}

function RepoRow({
  repo,
  onRemove,
}: {
  repo: RepoRegistration;
  onRemove: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3.5">
      <span className="font-mono text-sm font-medium text-ink">{repo.repo}</span>

      <div className="flex flex-wrap items-center gap-1.5">
        {repo.slack_channel && <Chip>{repo.slack_channel}</Chip>}
        {(repo.qa_emails?.length ?? 0) > 0 && (
          <Chip mono={false} icon={<Mail />}>
            {repo.qa_emails?.length} QA
          </Chip>
        )}
        {(repo.context_docs?.length ?? 0) > 0 && (
          <Chip mono={false} icon={<FileText />}>
            {repo.context_docs?.length} doc
            {(repo.context_docs?.length ?? 0) === 1 ? "" : "s"}
          </Chip>
        )}
        {repo.export_to_docs && (
          <Chip mono={false} icon={<FileText />}>
            exports
          </Chip>
        )}
        {repo.auto_merge_on_approval && (
          <Badge tone="warning">auto-merge</Badge>
        )}
        {repo.authoring_mode === "autonomous" && (
          <Badge tone="info">autonomous</Badge>
        )}
      </div>

      <IconButton
        label={`Unregister ${repo.repo}`}
        variant="danger-ghost"
        size="sm"
        className="ml-auto"
        onClick={onRemove}
      >
        <Trash2 />
      </IconButton>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export function AutomationSettings() {
  const toast = useToast();
  const [summary, setSummary] = useState<PRAgentSummary | null>(null);
  const [repos, setRepos] = useState<RepoRegistration[]>([]);
  const [loading, setLoading] = useState(true);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [justRegistered, setJustRegistered] = useState<RepoRegistration | null>(
    null
  );
  const [removing, setRemoving] = useState<RepoRegistration | null>(null);

  const [manualRepo, setManualRepo] = useState("");
  const [manualPr, setManualPr] = useState("");
  const [analysing, setAnalysing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([getPRAgentSummary(), listRepos()]);
      setSummary(s);
      setRepos(r?.repos ?? []);
    } catch {
      // The sections below degrade to their own empty states; a toast for a
      // background refresh would fire on every transient blip.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const runManual = async () => {
    if (!manualRepo.trim() || !manualPr.trim()) return;
    setAnalysing(true);
    try {
      await analyzePR(manualRepo.trim(), Number(manualPr.trim()));
      toast.success(
        "Analysis queued",
        `${manualRepo.trim()}#${manualPr.trim()} will appear under Work when it finishes.`
      );
      setManualPr("");
    } catch (e) {
      toast.error(
        "Could not queue the analysis",
        e instanceof Error ? e.message : undefined
      );
    } finally {
      setAnalysing(false);
    }
  };

  const confirmRemove = async () => {
    if (!removing) return;
    const target = removing;
    setRemoving(null);
    try {
      await unregisterRepo(target.repo);
      toast.success(`${target.repo} unregistered`);
      refresh();
    } catch (e) {
      toast.error(
        "Could not unregister",
        e instanceof Error ? e.message : undefined
      );
    }
  };

  return (
    <div className="space-y-12">
      {/* ── Readiness ───────────────────────────────────────────────────── */}
      <Section
        title="Pipeline readiness"
        description="What a run can currently reach. A capability that is missing does not fail a run — it quietly makes its results thinner."
      >
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(summary?.services ?? []).map((service) => (
                <ServicePanel key={service.key} service={service} />
              ))}
            </div>
            {summary && !summary.github_connected && (
              <Notice
                tone="danger"
                icon={<AlertTriangle aria-hidden />}
                action={
                  <Button asChild size="sm" variant="secondary">
                    <Link href="/integrations">Connect</Link>
                  </Button>
                }
              >
                The pipeline cannot run without GitHub.
              </Notice>
            )}
          </>
        )}
      </Section>

      {/* ── Defaults ────────────────────────────────────────────────────── */}
      <Defaults docsConnected={!!summary?.docs_connected} />

      {/* ── Repositories ────────────────────────────────────────────────── */}
      <Section
        title="Registered repositories"
        description="Registration is what lets GitHub notify Locus. The settings above already apply to every repository — this is about webhooks."
        actions={
          <Button size="sm" onClick={() => setRegisterOpen(true)}>
            <Plus aria-hidden />
            Register
          </Button>
        }
      >
        {loading ? (
          <Skeleton className="h-24 w-full" />
        ) : repos.length === 0 ? (
          <EmptyState
            compact
            icon={<GitPullRequest aria-hidden />}
            title="No repositories registered"
            description="Without a webhook, nothing runs automatically. You can still analyse a specific pull request below."
            action={
              <Button size="sm" onClick={() => setRegisterOpen(true)}>
                <Plus aria-hidden />
                Register a repository
              </Button>
            }
          />
        ) : (
          <Panel className="divide-y divide-line">
            {repos.map((repo) => (
              <RepoRow
                key={repo.id}
                repo={repo}
                onRemove={() => setRemoving(repo)}
              />
            ))}
          </Panel>
        )}
      </Section>

      {/* ── One-off run ─────────────────────────────────────────────────── */}
      <Section
        title="Analyse a single pull request"
        description="Works whether or not the repository is registered. Useful for checking a configuration change without waiting for a push."
      >
        <Panel className="p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Field label="Repository" htmlFor="manual-repo" className="flex-1">
              <Input
                id="manual-repo"
                placeholder="owner/repo"
                className="font-mono"
                spellCheck={false}
                value={manualRepo}
                onChange={(e) => setManualRepo(e.target.value)}
              />
            </Field>
            <Field label="PR number" htmlFor="manual-pr" className="sm:w-32">
              <Input
                id="manual-pr"
                type="number"
                inputMode="numeric"
                placeholder="412"
                value={manualPr}
                onChange={(e) => setManualPr(e.target.value)}
              />
            </Field>
            <Button
              onClick={runManual}
              loading={analysing}
              disabled={!manualRepo.trim() || !manualPr.trim()}
            >
              {!analysing && <Play aria-hidden />}
              Analyse
            </Button>
          </div>
        </Panel>
      </Section>

      {/* ── Where the models run ────────────────────────────────────────── */}
      <Notice
        tone="info"
        icon={<ShieldCheck aria-hidden />}
        title="Where the models run"
      >
        The security scanner, the code reviewer, the QA classifier and the
        review summariser all run on your local model server, over loopback, and
        none of them has a tool bound. Autonomous authoring is the only exception
        and is off until you hand over a specific ticket.
      </Notice>

      <RegisterDialog
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        onDone={(reg) => {
          setRegisterOpen(false);
          setJustRegistered(reg);
          refresh();
        }}
      />

      {justRegistered?.webhook_secret && (
        <WebhookDialog
          registration={justRegistered}
          onClose={() => setJustRegistered(null)}
        />
      )}

      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        onConfirm={confirmRemove}
        title={`Unregister ${removing?.repo ?? ""}?`}
        description="GitHub will keep sending webhooks until you remove the hook there too, but Locus will stop acting on them. Analyses already run are kept."
        confirmLabel="Unregister"
      />
    </div>
  );
}
