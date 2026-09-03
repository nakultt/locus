"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  Check,
  Cpu,
  LogOut,
  Plug,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import {
  checkLLMStatus,
  fetchIntegrationHealth,
  type IntegrationHealthEntry,
  type LLMStatus,
} from "@/lib/api";
import { timeAgo } from "@/lib/datetime";
import { AutomationSettings } from "@/features/settings/automation";
import { PageHeader, PageShell } from "@/components/layout/app-shell";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Avatar } from "@/components/ui/avatar";
import { Badge, Dot } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Tabs } from "@/components/ui/nav";
import { ConfirmDialog } from "@/components/ui/overlay";
import {
  Kicker,
  Notice,
  Panel,
  PanelHeader,
  Section,
  Skeleton,
} from "@/components/ui/surface";
import { useToast } from "@/components/ui/toast";

/**
 * Settings.
 *
 * Four tabs, because this page absorbed the automation configuration that used
 * to live behind a tab on the task board and would otherwise be a single column
 * of a dozen unrelated panels — appearance, then a profile modal, then five
 * hundred lines of pipeline dials, then the model server's health.
 *
 * The tab is in the URL (`?tab=automation`) so it can be linked to. The
 * top-bar account menu and the Work page both point straight at Automation,
 * which is only useful if that address exists.
 */

type Tab = "profile" | "automation" | "system";

const TABS = [
  { value: "profile" as const, label: "Profile", icon: <UserRound /> },
  { value: "automation" as const, label: "Automation", icon: <SlidersHorizontal /> },
  { value: "system" as const, label: "System", icon: <Cpu /> },
];

export default function SettingsView() {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const [tab, setTab] = useState<Tab>(
    requested === "automation" || requested === "system" ? requested : "profile"
  );

  const changeTab = (next: Tab) => {
    setTab(next);
    // `replace`, not `push`: flicking between tabs should not fill the back
    // stack with settings pages someone has to press Back through.
    router.replace(next === "profile" ? "/settings" : `/settings?tab=${next}`, {
      scroll: false,
    });
  };

  return (
    <PageShell width={tab === "automation" ? "wide" : "narrow"}>
      <PageHeader
        title="Settings"
        description="Your account, what the pipeline does on your behalf, and whether the machinery behind it is reachable."
      />

      <Tabs
        className="mt-8"
        ariaLabel="Settings sections"
        items={TABS}
        value={tab}
        onChange={changeTab}
      />

      <div className="mt-8">
        {tab === "profile" && <ProfileTab />}
        {tab === "automation" && <AutomationSettings />}
        {tab === "system" && <SystemTab />}
      </div>
    </PageShell>
  );
}

/* ── Profile ──────────────────────────────────────────────────────────────── */

function ProfileTab() {
  const router = useRouter();
  const toast = useToast();
  const { user, updateProfile, logout } = useAuth();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [signOutOpen, setSignOutOpen] = useState(false);

  // Seeded from the account once it is known. Editing in place rather than in
  // a modal: there are three fields, and a dialog to change your own name is
  // ceremony around nothing.
  useEffect(() => {
    if (!user) return;
    setName(user.name ?? "");
    setEmail(user.email ?? "");
  }, [user]);

  const dirty =
    name !== (user?.name ?? "") ||
    email !== (user?.email ?? "") ||
    password.length > 0;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await updateProfile({
        name,
        email,
        // Only sent when set — an empty string would be a password change to
        // nothing.
        password: password || undefined,
      });
      setPassword("");
      toast.success("Profile updated");
    } catch (err) {
      toast.error(
        "Could not update your profile",
        err instanceof Error ? err.message : undefined
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-10">
      <Section title="Your account">
        <Panel className="p-5">
          <div className="flex items-center gap-4">
            <Avatar name={user?.name} email={user?.email} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-h2 text-ink">
                {user?.name || "Unnamed account"}
              </p>
              <p className="truncate text-sm text-muted">{user?.email}</p>
            </div>
          </div>

          <form onSubmit={save} className="mt-6 space-y-4 border-t border-line pt-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="profile-name">
                <Input
                  id="profile-name"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label="Email" htmlFor="profile-email">
                <Input
                  id="profile-email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
            </div>

            <Field
              label="New password"
              htmlFor="profile-password"
              hint="Leave blank to keep your current password."
            >
              <Input
                id="profile-password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            <div className="flex items-center gap-3">
              <Button type="submit" loading={saving} disabled={!dirty}>
                Save changes
              </Button>
              {dirty && (
                <span className="text-xs text-muted">
                  You have unsaved changes.
                </span>
              )}
            </div>
          </form>
        </Panel>
      </Section>

      <Section
        title="Appearance"
        description="Applied immediately and remembered on this device. System follows your operating system as it changes."
      >
        <Panel className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <p className="text-h3 text-ink">Colour theme</p>
            <p className="mt-0.5 text-sm text-muted">
              Light, dark, or whatever your machine is doing.
            </p>
          </div>
          <ThemeToggle />
        </Panel>
      </Section>

      <Section
        title="Connections"
        description="Locus reads and writes through your own credentials."
      >
        <Panel className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md bg-surface-2">
              <Plug className="size-4 text-subtle" aria-hidden />
            </span>
            <div>
              <p className="text-h3 text-ink">Connected services</p>
              <p className="mt-0.5 text-sm text-muted">
                GitHub, Jira, Slack, Linear and Google Workspace.
              </p>
            </div>
          </div>
          <Button asChild variant="secondary" size="sm">
            {/* The old button here pointed at `/integrations/integrations-page`,
                which is not a route — it 404'd. */}
            <Link href="/integrations">Manage</Link>
          </Button>
        </Panel>
      </Section>

      <Section title="Session">
        <Panel tone="quiet" className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <p className="text-h3 text-ink">Sign out</p>
            <p className="mt-0.5 text-sm text-muted">
              Ends this session on this device. Your connections stay
              configured.
            </p>
          </div>
          <Button variant="danger-ghost" onClick={() => setSignOutOpen(true)}>
            <LogOut aria-hidden />
            Sign out
          </Button>
        </Panel>
      </Section>

      <ConfirmDialog
        open={signOutOpen}
        onClose={() => setSignOutOpen(false)}
        onConfirm={() => {
          logout();
          router.push("/login");
        }}
        title="Sign out of Locus?"
        description="Background loops keep running on the server. You will need to sign in again on this device."
        confirmLabel="Sign out"
      />
    </div>
  );
}

/**
 * The provider's own label, so the panel names OpenAI rather than "moe-local"
 * when a hosted backend is configured.
 */
function providerLabel(llm: LLMStatus): string {
  const active = llm.providers?.find((p) => p.active);
  return active?.label ?? llm.provider ?? "—";
}

/* ── System ───────────────────────────────────────────────────────────────── */

function SystemTab() {
  const [llm, setLlm] = useState<LLMStatus | null>(null);
  const [health, setHealth] = useState<IntegrationHealthEntry[]>([]);
  const [loadingLlm, setLoadingLlm] = useState(true);

  const refreshLlm = useCallback(async () => {
    try {
      setLlm(await checkLLMStatus());
    } catch {
      setLlm({
        available: false,
        message: "Cannot reach the Locus backend.",
      });
    } finally {
      setLoadingLlm(false);
    }
  }, []);

  // Health changes on the poller's schedule (minutes), not the model's, so it
  // is fetched once rather than on the 15s model-status interval.
  const refreshHealth = useCallback(async () => {
    try {
      const rows = await fetchIntegrationHealth();
      setHealth(Array.isArray(rows) ? rows : []);
    } catch {
      // A failure here must not blank the page; the section stays empty.
    }
  }, []);

  useEffect(() => {
    refreshLlm();
    refreshHealth();
    const interval = setInterval(refreshLlm, 15000);
    return () => clearInterval(interval);
  }, [refreshLlm, refreshHealth]);

  return (
    <div className="space-y-10">
      {/* ── Local model ─────────────────────────────────────────────────── */}
      <Section title="Model backend">
        <Panel>
          <PanelHeader
            icon={<Cpu aria-hidden />}
            title="Inference"
            description={
              llm && llm.is_local === false
                ? "Analysis runs on a hosted provider — diffs and discussion leave this machine."
                : "Every model that reads your code automatically runs here, over loopback."
            }
            actions={
              <IconButton
                label="Check again"
                variant="ghost"
                size="sm"
                onClick={refreshLlm}
              >
                <RefreshCw className={loadingLlm ? "animate-spin" : undefined} />
              </IconButton>
            }
          />

          <div className="p-5">
            {loadingLlm && !llm ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <Notice
                  tone={llm?.available ? "success" : "warning"}
                  icon={
                    llm?.available ? (
                      <Check aria-hidden />
                    ) : (
                      <AlertTriangle aria-hidden />
                    )
                  }
                >
                  {llm?.message}
                </Notice>

                {llm?.base_url && (
                  <dl className="mt-4 divide-y divide-line border-t border-line">
                    {[
                      ["Provider", providerLabel(llm)],
                      ["Endpoint", llm.base_url],
                      ["Fast model", llm.fast_model],
                      ["Smart model", llm.smart_model],
                      ...(llm.api_key_env
                        ? [
                            [
                              "API key",
                              `${llm.api_key_env} ${
                                llm.api_key_configured ? "(set)" : "(missing)"
                              }`,
                            ] as [string, string],
                          ]
                        : []),
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className="flex items-baseline justify-between gap-4 py-2.5"
                      >
                        <dt className="shrink-0 text-sm text-muted">{label}</dt>
                        <dd className="min-w-0 truncate font-mono text-xs text-ink">
                          {value || "—"}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}

                {!llm?.available &&
                  (llm?.is_local === false ? (
                    <p className="mt-4 text-sm leading-relaxed text-muted">
                      Set {llm.api_key_env ?? "the provider's API key"} in{" "}
                      <code className="font-mono text-xs">backend/.env</code> and
                      restart the backend, or set{" "}
                      <code className="font-mono text-xs">LLM_PROVIDER=local</code>{" "}
                      to go back to MoE Model Manager.
                    </p>
                  ) : (
                    <p className="mt-4 text-sm leading-relaxed text-muted">
                      Open MoE Model Manager and load a text model. No API key is
                      required — the server holds one model at a time, and chat
                      reports this rather than failing with a connection error.
                    </p>
                  ))}

                {llm?.providers && llm.providers.length > 0 && (
                  <div className="mt-6 border-t border-line pt-4">
                    <p className="text-sm text-muted">
                      Set <code className="font-mono text-xs">LLM_PROVIDER</code> in{" "}
                      <code className="font-mono text-xs">backend/.env</code> to switch.
                      A hosted provider sends every diff, Slack thread and ticket the
                      analysis reads to a third party, on every push.
                    </p>
                    <ul className="mt-3 space-y-2">
                      {llm.providers.map((p) => (
                        <li
                          key={p.id}
                          className="flex items-baseline justify-between gap-4"
                        >
                          <span className="flex min-w-0 items-baseline gap-2">
                            <code className="font-mono text-xs text-ink">{p.id}</code>
                            <span className="truncate text-sm text-muted">
                              {p.label}
                            </span>
                          </span>
                          <span className="shrink-0 text-xs text-muted">
                            {p.active
                              ? "active"
                              : p.is_local
                                ? "available"
                                : p.api_key_configured
                                  ? `${p.api_key_env} set`
                                  : `needs ${p.api_key_env}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        </Panel>
      </Section>

      {/* ── Integration health ──────────────────────────────────────────────
          The background loops swallow their own failures so one dead
          integration cannot stop the others. This is where that silence
          surfaces — a Gmail token that expired days ago otherwise shows up
          only as QA replies no longer arriving.

          Rendered only when there is something to report: a service is listed
          once it has been attempted, and "never attempted" is not a state
          worth a row. */}
      <Section
        title="Integration health"
        description="What the background loops last saw. A service that has never been attempted is absent rather than reported healthy."
        actions={
          <IconButton
            label="Refresh health"
            variant="ghost"
            size="sm"
            onClick={refreshHealth}
          >
            <RefreshCw />
          </IconButton>
        }
      >
        {health.length === 0 ? (
          <Panel tone="quiet" className="px-5 py-8 text-center">
            <Activity
              className="mx-auto mb-2 size-5 text-subtle"
              aria-hidden
            />
            <p className="text-sm text-muted">
              Nothing has been attempted yet. Rows appear here after the loops
              have tried to reach a service at least once.
            </p>
          </Panel>
        ) : (
          <Panel className="divide-y divide-line">
            {health.map((entry) => (
              <div key={entry.service} className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  <span className="flex items-center gap-2.5">
                    <Dot tone={entry.healthy ? "success" : "warning"} />
                    <span className="text-h3 capitalize text-ink">
                      {entry.service}
                    </span>
                    {!entry.healthy && (
                      <Badge tone="warning">
                        {entry.consecutive_failures} failed
                      </Badge>
                    )}
                  </span>
                  <span className="text-xs text-subtle">
                    last worked {timeAgo(entry.last_success_at)}
                  </span>
                </div>

                {/* The error is shown only while it is the current state. A
                    message from a failure that has since recovered would read
                    as a live problem. */}
                {!entry.healthy && (
                  <div className="mt-3 rounded-md border border-warning-border bg-warning-soft px-4 py-3">
                    <p className="text-sm text-ink">
                      {entry.consecutive_failures} failed attempt
                      {entry.consecutive_failures === 1 ? "" : "s"} in a row,
                      most recently {timeAgo(entry.last_failure_at)}.
                    </p>
                    {entry.last_error && (
                      <p className="mt-1.5 break-words font-mono text-xs text-muted">
                        {entry.last_error}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </Panel>
        )}
      </Section>

      <Section title="About">
        <Panel tone="quiet" className="p-5">
          <Kicker>Where the models run</Kicker>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            The security scanner, the code reviewer, the QA classifier and the
            review summariser read text that anyone who can open a pull request
            controls. None of them has a tool bound, and all of them run on the
            local endpoint above. Autonomous authoring is the one exception, is
            off by default, and says so before its first attempt.
          </p>
          <p className="mt-4 flex items-center gap-2 text-xs text-subtle">
            <ShieldCheck className="size-3.5" aria-hidden />
            Locus · credentials encrypted at rest, bound per request
          </p>
        </Panel>
      </Section>
    </div>
  );
}
