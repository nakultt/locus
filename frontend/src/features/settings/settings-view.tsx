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
  KeyRound,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import {
  checkLLMStatus,
  fetchIntegrationHealth,
  fetchLLMConfig,
  resetLLMConfig,
  saveLLMConfig,
  testLLMConfig,
  type IntegrationHealthEntry,
  type LLMConfig,
  type LLMConfigUpdate,
  type LLMStatus,
} from "@/lib/api";
import { timeAgo } from "@/lib/datetime";
import { AutomationSettings } from "@/features/settings/automation";
import { PageHeader, PageShell } from "@/components/layout/app-shell";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Avatar } from "@/components/ui/avatar";
import { Badge, Dot } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
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

/* ── Model backend ────────────────────────────────────────────────────────
   The provider, the endpoint, the model ids and the API key are settings,
   not deployment constants. They used to live in `backend/.env`, which meant
   changing a model id required a restart and a shell on the server — fine for
   one machine, wrong for a product.

   Two rules shape the form. The key is write-only: the API returns whether one
   is stored and never the value, so the field stays empty and is sent only
   when somebody types in it — a form that always submitted its empty box would
   erase the key on every unrelated save, invisibly, until the next analysis
   failed with a 401. And every field may be left blank, which inherits the
   deployment default rather than overriding with nothing; the placeholder
   shows what blank resolves to, because an empty box with no hint is where
   someone types a guess. */

function ModelBackendPanel({
  llm,
  loading,
  onRefresh,
}: {
  llm: LLMStatus | null;
  loading: boolean;
  onRefresh: () => Promise<void> | void;
}) {
  const toast = useToast();

  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [provider, setProvider] = useState("local");
  const [baseUrl, setBaseUrl] = useState("");
  const [fastModel, setFastModel] = useState("");
  const [smartModel, setSmartModel] = useState("");
  const [timeout, setTimeoutSeconds] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [keyStored, setKeyStored] = useState(false);

  const [busy, setBusy] = useState<"save" | "test" | "reset" | null>(null);
  const [probe, setProbe] = useState<LLMStatus | null>(null);

  const apply = useCallback((next: LLMConfig) => {
    setConfig(next);
    setProvider(next.provider ?? next.providers.find((p) => p.active)?.id ?? "local");
    setBaseUrl(next.base_url ?? "");
    setFastModel(next.fast_model ?? "");
    setSmartModel(next.smart_model ?? "");
    setTimeoutSeconds(
      next.timeout_seconds == null ? "" : String(next.timeout_seconds)
    );
    setKeyStored(next.api_key_configured);
    setApiKey("");
  }, []);

  useEffect(() => {
    fetchLLMConfig()
      .then(apply)
      .catch(() => {
        // The status notice above already reports an unreachable backend;
        // a second error here would say the same thing twice.
      });
  }, [apply]);

  const selected = config?.providers.find((p) => p.id === provider);
  const isLocal = selected?.is_local ?? provider === "local";

  /** What the form is about to send. Blank fields are sent as null: they mean
      "inherit", and sending "" would store an override of nothing. */
  const payload = (): LLMConfigUpdate => {
    const trimmed = timeout.trim();
    const seconds = trimmed ? Number(trimmed) : null;

    return {
      provider,
      base_url: baseUrl.trim() || null,
      fast_model: fastModel.trim() || null,
      smart_model: smartModel.trim() || null,
      timeout_seconds:
        seconds != null && Number.isFinite(seconds) && seconds > 0 ? seconds : null,
      // Omitted entirely unless typed, which is what keeps the stored key.
      ...(apiKey ? { api_key: apiKey } : {}),
    };
  };

  const run = async (
    kind: "save" | "test" | "reset",
    action: () => Promise<void>
  ) => {
    setBusy(kind);
    try {
      await action();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  };

  const onSave = () =>
    run("save", async () => {
      apply(await saveLLMConfig(payload()));
      setProbe(null);
      await onRefresh();
      toast.success("Model backend saved.");
    });

  const onTest = () =>
    run("test", async () => {
      const result = await testLLMConfig(payload());
      setProbe(result);
      if (!result.available) toast.error(result.message);
    });

  const onReset = () =>
    run("reset", async () => {
      apply(await resetLLMConfig());
      setProbe(null);
      await onRefresh();
      toast.success("Back to this deployment's default.");
    });

  const onClearKey = () =>
    run("save", async () => {
      // An explicit empty string, which is the only thing that clears it.
      apply(await saveLLMConfig({ ...payload(), api_key: "" }));
      await onRefresh();
      toast.success("API key removed.");
    });

  return (
    <Section title="Model backend">
      <Panel>
        <PanelHeader
          icon={<Cpu aria-hidden />}
          title="Inference"
          description={
            llm && llm.is_local === false
              ? "Analysis runs on a hosted provider — diffs and discussion leave this machine."
              : "Every model that reads your code automatically runs on the endpoint below."
          }
          actions={
            <IconButton
              label="Check again"
              variant="ghost"
              size="sm"
              onClick={onRefresh}
            >
              <RefreshCw className={loading ? "animate-spin" : undefined} />
            </IconButton>
          }
        />

        <div className="space-y-6 p-5">
          {loading && !llm ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <>
              <Notice
                tone={llm?.available ? "success" : "warning"}
                icon={llm?.available ? <Check aria-hidden /> : <AlertTriangle aria-hidden />}
              >
                {llm?.message}
              </Notice>

              {llm?.base_url && (
                <dl className="divide-y divide-line border-t border-line">
                  {[
                    ["Provider", providerLabel(llm)],
                    ["Endpoint", llm.base_url],
                    ["Fast model", llm.fast_model],
                    ["Smart model", llm.smart_model],
                    [
                      "Configured by",
                      // Named as a state, not just a source. "this deployment"
                      // alone reads as a choice somebody made, when what it
                      // actually means is that this account has saved nothing
                      // and the form below is showing inherited placeholders.
                      llm.source === "settings"
                        ? "your settings"
                        : "backend/.env — nothing saved for your account",
                    ],
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
            </>
          )}

          {/* ── The form ───────────────────────────────────────────────── */}
          {config === null ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <div className="space-y-5 border-t border-line pt-6">
              <Field
                label="Provider"
                htmlFor="llm-provider"
                hint={
                  isLocal
                    ? "Any OpenAI-compatible server you run — Ollama, LM Studio, etc. Nothing leaves the machine it runs on."
                    : "A hosted provider receives every diff, Slack thread and ticket the analysis reads, on every push."
                }
              >
                <Select
                  id="llm-provider"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                >
                  {config.providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field
                label="Endpoint"
                htmlFor="llm-base-url"
                hint="Blank uses the default shown. Point this at your own gateway — LiteLLM, OpenRouter, an Azure deployment — when you have one."
              >
                <Input
                  id="llm-base-url"
                  value={baseUrl}
                  placeholder={selected?.default_base_url}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className="font-mono text-xs"
                  spellCheck={false}
                />
              </Field>

              <div className="grid gap-5 sm:grid-cols-2">
                <Field
                  label="Fast model"
                  htmlFor="llm-fast"
                  hint="Classifiers and short answers."
                >
                  <Input
                    id="llm-fast"
                    value={fastModel}
                    placeholder={selected?.fast_model}
                    onChange={(e) => setFastModel(e.target.value)}
                    className="font-mono text-xs"
                    spellCheck={false}
                  />
                </Field>

                <Field
                  label="Smart model"
                  htmlFor="llm-smart"
                  hint="The security scan and the code review."
                >
                  <Input
                    id="llm-smart"
                    value={smartModel}
                    placeholder={selected?.smart_model}
                    onChange={(e) => setSmartModel(e.target.value)}
                    className="font-mono text-xs"
                    spellCheck={false}
                  />
                </Field>
              </div>

              {/* Local servers take no key. Rendering the field anyway invites
                  someone to paste a real one into a box nothing will use. */}
              {selected?.needs_key !== false && (
                <Field
                  label="API key"
                  htmlFor="llm-key"
                  hint={
                    keyStored
                      ? "A key is stored, encrypted. Leave this blank to keep it — it is never sent back to the browser."
                      : `Stored encrypted. Falls back to ${
                          selected?.api_key_env || "the environment"
                        } in backend/.env when blank.`
                  }
                >
                  <div className="flex gap-2">
                    <Input
                      id="llm-key"
                      type="password"
                      value={apiKey}
                      autoComplete="off"
                      placeholder={keyStored ? "•••••••••••••• (stored)" : "sk-…"}
                      onChange={(e) => setApiKey(e.target.value)}
                      icon={<KeyRound />}
                      className="font-mono text-xs"
                    />
                    {keyStored && (
                      <Button
                        variant="ghost"
                        onClick={onClearKey}
                        disabled={busy !== null}
                      >
                        Remove
                      </Button>
                    )}
                  </div>
                </Field>
              )}

              <Field
                label="Request timeout"
                htmlFor="llm-timeout"
                hint="Seconds. Local generation is slow and agent loops chain several calls; the default is 600."
              >
                <Input
                  id="llm-timeout"
                  value={timeout}
                  inputMode="numeric"
                  placeholder="600"
                  onChange={(e) => setTimeoutSeconds(e.target.value)}
                  className="max-w-32 font-mono text-xs"
                />
              </Field>

              {/* The probe result, from Test. Deliberately separate from the
                  status notice above, which describes what is *saved* — a test
                  that overwrote it would claim settings are live before they
                  have been saved. */}
              {probe && (
                <Notice
                  tone={probe.available ? "success" : "warning"}
                  icon={probe.available ? <Check aria-hidden /> : <AlertTriangle aria-hidden />}
                >
                  {probe.message}
                </Notice>
              )}

              <div className="flex flex-wrap items-center gap-2 border-t border-line pt-5">
                <Button onClick={onSave} disabled={busy !== null}>
                  {busy === "save" ? "Saving…" : "Save"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={onTest}
                  disabled={busy !== null}
                >
                  {busy === "test" ? "Testing…" : "Test connection"}
                </Button>
                {config.configured && (
                  <Button
                    variant="ghost"
                    onClick={onReset}
                    disabled={busy !== null}
                    className="ml-auto"
                  >
                    Use deployment default
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </Panel>
    </Section>
  );
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

  // A local server's readiness changes while you watch — a model finishes
  // loading — so it is worth polling closely. A hosted provider's check is a
  // request to a third party on a metered key, and polling that every fifteen
  // seconds for as long as a settings tab is left open is a cost with no
  // corresponding signal.
  const interval = llm?.is_local === false ? 60000 : 15000;

  useEffect(() => {
    refreshLlm();
    refreshHealth();
  }, [refreshLlm, refreshHealth]);

  useEffect(() => {
    const timer = setInterval(refreshLlm, interval);
    return () => clearInterval(timer);
  }, [refreshLlm, interval]);

  return (
    <div className="space-y-10">
      <ModelBackendPanel
        llm={llm}
        loading={loadingLlm}
        onRefresh={refreshLlm}
      />

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
            endpoint configured above — on a local server that is your own
            machine, and on a hosted provider it is not. Autonomous authoring
            runs on its own model regardless, is off by default, and says so
            before its first attempt.
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
