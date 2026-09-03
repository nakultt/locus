"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import {
  ArrowUpRight,
  Check,
  Link2,
  Plug,
  ShieldCheck,
  Unlink,
} from "lucide-react";
import { useAuth } from "@/features/auth/auth-context";
import {
  connectIntegration,
  disconnectIntegration,
  listIntegrations,
  type Integration,
} from "@/lib/api";
import {
  ALL_ENTRIES,
  CATALOG,
  type CatalogEntry,
  type CatalogGroup,
} from "@/features/integrations/catalog";
import { PageHeader, PageShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Field, Input } from "@/components/ui/form";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { Notice, Panel, Skeleton } from "@/components/ui/surface";
import { useToast } from "@/components/ui/toast";

/**
 * Connections.
 *
 * A list, not a grid of thirteen cards. The grid gave a Google Slides tile the
 * same visual weight as GitHub — which the pipeline cannot run without — and
 * spread eight Google services that share a single consent screen across three
 * rows as though each were a separate decision.
 *
 * Grouped instead, with the Google group carrying one action for all eight,
 * and GitHub marked as required. Scanning a list of names down the left edge is
 * also simply faster than scanning tiles, which is what someone is doing here.
 */

/* ── One service ──────────────────────────────────────────────────────────── */

function ConnectionRow({
  entry,
  connected,
  busy,
  onConnect,
  onDisconnect,
}: {
  entry: CatalogEntry;
  connected: boolean;
  busy: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3 px-5 py-4 transition-colors hover:bg-surface-2/50">
      {/* The logo sits on a neutral plate. Several of these SVGs are near-white
          and vanish against the surface in dark mode without one. */}
      <span className="flex size-10 shrink-0 items-center justify-center rounded-md border border-line bg-surface">
        <Image
          src={entry.logo}
          alt=""
          width={22}
          height={22}
          // Straight from /public, not through the optimizer: these are our own
          // SVGs, and the image route refuses SVG unless `dangerouslyAllowSVG`
          // is set — which would relax it for every image, to optimize files
          // that are already a few hundred bytes.
          unoptimized
          className="size-[22px] object-contain"
        />
      </span>

      <div className="min-w-0 flex-1 basis-64">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-h3 text-ink">{entry.title}</h3>
          {entry.required && (
            <Badge tone="outline">Required</Badge>
          )}
          {connected && (
            <Badge tone="success">
              <Check aria-hidden />
              Connected
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          {entry.description}
        </p>
      </div>

      <div className="ml-auto shrink-0">
        {connected ? (
          <Button
            variant="danger-ghost"
            size="sm"
            onClick={onDisconnect}
            loading={busy}
          >
            {!busy && <Unlink aria-hidden />}
            Disconnect
          </Button>
        ) : (
          <Button variant="secondary" size="sm" onClick={onConnect} loading={busy}>
            {!busy && <Link2 aria-hidden />}
            Connect
          </Button>
        )}
      </div>
    </div>
  );
}

/* ── A group ──────────────────────────────────────────────────────────────── */

function ConnectionGroup({
  group,
  connectedServices,
  busyService,
  onConnect,
  onDisconnect,
  onConnectGoogle,
}: {
  group: CatalogGroup;
  connectedServices: Set<string>;
  busyService: string | null;
  onConnect: (entry: CatalogEntry) => void;
  onDisconnect: (entry: CatalogEntry) => void;
  onConnectGoogle: () => void;
}) {
  const connectedCount = group.entries.filter((e) =>
    connectedServices.has(e.id)
  ).length;
  const allConnected = connectedCount === group.entries.length;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h2 className="text-h2 text-ink">{group.title}</h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
            {group.description}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <span className="tabular text-xs text-subtle">
            {connectedCount} of {group.entries.length}
          </span>
          {/* One consent grants every Google scope, so the action belongs to
              the group. Offering it per service implied eight separate round
              trips through Google's screen. */}
          {group.sharedOAuth === "google" && !allConnected && (
            <Button size="sm" onClick={onConnectGoogle}>
              <ShieldCheck aria-hidden />
              {connectedCount > 0 ? "Reconnect Google" : "Connect all"}
            </Button>
          )}
        </div>
      </div>

      <Panel className="divide-y divide-line overflow-hidden">
        {group.entries.map((entry) => (
          <ConnectionRow
            key={entry.id}
            entry={entry}
            connected={connectedServices.has(entry.id)}
            busy={busyService === entry.id}
            onConnect={() => onConnect(entry)}
            onDisconnect={() => onDisconnect(entry)}
          />
        ))}
      </Panel>
    </section>
  );
}

/* ── Credential dialog ────────────────────────────────────────────────────── */

function CredentialDialog({
  entry,
  onClose,
  onSubmit,
}: {
  entry: CatalogEntry;
  onClose: () => void;
  onSubmit: (apiKey: string, credentials?: Record<string, string>) => Promise<void>;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);

    const apiKey = values["api_key"] ?? "";
    const credentials: Record<string, string> = {};
    for (const field of entry.fields) {
      if (field.isCredential && values[field.name]) {
        credentials[field.name] = values[field.name];
      }
    }

    // Slack needs both tokens side by side: the bot token posts messages, the
    // user token searches history. Mirror the api_key in so services read one
    // consistent shape instead of guessing which field holds which token.
    if (entry.id === "slack" && apiKey) credentials["bot_token"] = apiKey;

    try {
      await onSubmit(
        apiKey,
        Object.keys(credentials).length > 0 ? credentials : undefined
      );
    } finally {
      setBusy(false);
    }
  };

  const missingRequired = entry.fields.some(
    (f) => !f.optional && !values[f.name]?.trim()
  );

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Connect ${entry.title}`}
      description={entry.description}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            type="submit"
            form="connect-form"
            loading={busy}
            disabled={missingRequired}
          >
            Connect
          </Button>
        </>
      }
    >
      <form id="connect-form" onSubmit={submit} className="space-y-4">
        {entry.fields.map((field, i) => (
          <Field
            key={field.name}
            htmlFor={`f-${field.name}`}
            label={
              <>
                {field.label}
                {field.optional && (
                  <span className="ml-1.5 font-normal text-subtle">optional</span>
                )}
              </>
            }
            hint={field.help}
            required={!field.optional}
          >
            <Input
              id={`f-${field.name}`}
              data-autofocus={i === 0 ? "" : undefined}
              // Tokens are passwords. Pasting one into a plain text field
              // leaves it legible on screen for as long as the dialog is open.
              type={field.secret ? "password" : "text"}
              autoComplete="off"
              spellCheck={false}
              placeholder={field.placeholder}
              value={values[field.name] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.name]: e.target.value }))
              }
              required={!field.optional}
            />
          </Field>
        ))}

        <Notice tone="info" icon={<ShieldCheck aria-hidden />}>
          Credentials are encrypted at rest and bound to your account for the
          duration of a single request — never held in shared module state.
        </Notice>
      </form>
    </Dialog>
  );
}

/* ── OAuth dialog ─────────────────────────────────────────────────────────── */

function OAuthDialog({
  title,
  provider,
  scopeNote,
  onClose,
  onConfirm,
}: {
  title: string;
  provider: "google" | "linear";
  scopeNote?: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const name = provider === "linear" ? "Linear" : "Google";
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Connect ${title}`}
      description={`You will be taken to ${name} to approve access, then returned here.`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button data-autofocus onClick={onConfirm}>
            Continue to {name}
            <ArrowUpRight aria-hidden />
          </Button>
        </>
      }
    >
      {scopeNote && (
        <Notice tone="info" icon={<ShieldCheck aria-hidden />}>
          {scopeNote}
        </Notice>
      )}
    </Dialog>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function IntegrationsView() {
  const { user } = useAuth();
  const toast = useToast();

  const [connected, setConnected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busyService, setBusyService] = useState<string | null>(null);
  const [credentialFor, setCredentialFor] = useState<CatalogEntry | null>(null);
  const [oauthFor, setOauthFor] = useState<
    { title: string; provider: "google" | "linear"; note?: string } | null
  >(null);
  const [disconnectFor, setDisconnectFor] = useState<CatalogEntry | null>(null);

  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const refresh = useCallback(async () => {
    if (!user?.id) {
      setLoading(false);
      return;
    }
    try {
      const result = await listIntegrations();
      setConnected(
        new Set(result.integrations.map((i: Integration) => i.service_name))
      );
    } catch (err) {
      toast.error(
        "Could not load your connections",
        err instanceof Error ? err.message : undefined
      );
    } finally {
      setLoading(false);
    }
  }, [user?.id, toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // The OAuth round trip returns here with its outcome in the query string.
  // Reported as a toast and then stripped from the URL, so a refresh does not
  // re-announce a connection made ten minutes ago.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const success = params.get("success");
    const error = params.get("error");
    const service = params.get("service");
    if (!success && !error) return;

    if (success) {
      toast.success(
        `${service || (success === "linear_connected" ? "Linear" : "Google")} connected`,
        success === "google_connected"
          ? "Every Google service below is now available."
          : undefined
      );
      refresh();
    } else if (error) {
      toast.error("Could not complete the connection", error.replace(/_/g, " "));
    }
    window.history.replaceState({}, "", window.location.pathname);
  }, [toast, refresh]);

  const startOAuth = (provider: "google" | "linear") => {
    if (!user?.id) return;
    const target =
      provider === "linear"
        ? `${apiBaseUrl}/auth/linear?user_id=${user.id}`
        : // "google" rather than the individual card id: one consent screen
          // grants every Google scope anyway, so connecting Gmail should light
          // up Calendar, Docs, Drive and the rest instead of leaving them
          // greyed out.
          `${apiBaseUrl}/auth/google?user_id=${user.id}&service=google`;

    /* A full document navigation, not a client-side one: `apiBaseUrl` is the
     * FastAPI backend, a different origin in every deployment. It answers with
     * a 302 to Google or Linear, and the consent screen returns to the
     * backend's callback, which finally redirects back here. `router.push`
     * cannot start that chain — it would look for a Next route of this name.
     */
    window.location.href = target;
  };

  const handleConnect = (entry: CatalogEntry) => {
    if (entry.authType === "oauth") {
      setOauthFor({
        title: entry.title,
        provider: entry.oauthProvider ?? "google",
        note:
          entry.oauthProvider === "google"
            ? "One consent grants every Google service — Gmail, Calendar, Docs, Drive, Sheets, Slides, Forms and Meet."
            : undefined,
      });
      return;
    }
    setCredentialFor(entry);
  };

  const submitCredentials = async (
    apiKey: string,
    credentials?: Record<string, string>
  ) => {
    if (!user?.id || !credentialFor) return;
    setBusyService(credentialFor.id);
    try {
      await connectIntegration(credentialFor.id, apiKey, credentials);
      setConnected((prev) => new Set([...prev, credentialFor.id]));
      toast.success(`${credentialFor.title} connected`);
      setCredentialFor(null);
    } catch (err) {
      toast.error(
        `Could not connect ${credentialFor.title}`,
        err instanceof Error ? err.message : undefined
      );
    } finally {
      setBusyService(null);
    }
  };

  const confirmDisconnect = async () => {
    if (!user?.id || !disconnectFor) return;
    const entry = disconnectFor;
    setDisconnectFor(null);
    setBusyService(entry.id);
    try {
      await disconnectIntegration(entry.id);
      setConnected((prev) => {
        const next = new Set(prev);
        next.delete(entry.id);
        return next;
      });
      toast.success(`${entry.title} disconnected`);
    } catch (err) {
      toast.error(
        `Could not disconnect ${entry.title}`,
        err instanceof Error ? err.message : undefined
      );
    } finally {
      setBusyService(null);
    }
  };

  const total = ALL_ENTRIES.length;
  const githubConnected = connected.has("github");

  return (
    <PageShell>
      <PageHeader
        title="Connections"
        description="Locus reads and writes through your own credentials. Nothing here is required except GitHub — every other connection widens what a run can see or say."
        actions={
          !loading && (
            <span className="tabular inline-flex items-center gap-2 rounded-pill border border-line bg-surface px-3.5 py-1.5 text-sm text-muted">
              <Plug className="size-4 text-subtle" aria-hidden />
              {connected.size} of {total} connected
            </span>
          )
        }
      />

      {!loading && !githubConnected && (
        <Notice
          tone="warning"
          className="mt-6"
          title="GitHub is not connected"
          icon={<Plug aria-hidden />}
        >
          The pipeline reads pull requests and posts its analysis through
          GitHub. Until it is connected, nothing else on this page has anything
          to act on.
        </Notice>
      )}

      <div className="mt-8 space-y-10">
        {loading
          ? CATALOG.map((group) => (
              <div key={group.id} className="space-y-3">
                <Skeleton className="h-6 w-40" />
                <Panel className="divide-y divide-line">
                  {group.entries.slice(0, 3).map((e) => (
                    <div key={e.id} className="flex items-center gap-4 px-5 py-4">
                      <Skeleton className="size-10 shrink-0" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-32" />
                        <Skeleton className="h-3 w-full max-w-md" />
                      </div>
                      <Skeleton className="h-8 w-24 rounded-pill" />
                    </div>
                  ))}
                </Panel>
              </div>
            ))
          : CATALOG.map((group) => (
              <ConnectionGroup
                key={group.id}
                group={group}
                connectedServices={connected}
                busyService={busyService}
                onConnect={handleConnect}
                onDisconnect={setDisconnectFor}
                onConnectGoogle={() =>
                  setOauthFor({
                    title: "Google Workspace",
                    provider: "google",
                    note: "One consent grants every Google service — Gmail, Calendar, Docs, Drive, Sheets, Slides, Forms and Meet.",
                  })
                }
              />
            ))}
      </div>

      {credentialFor && (
        <CredentialDialog
          entry={credentialFor}
          onClose={() => setCredentialFor(null)}
          onSubmit={submitCredentials}
        />
      )}

      {oauthFor && (
        <OAuthDialog
          title={oauthFor.title}
          provider={oauthFor.provider}
          scopeNote={oauthFor.note}
          onClose={() => setOauthFor(null)}
          onConfirm={() => startOAuth(oauthFor.provider)}
        />
      )}

      {/* Names the service rather than saying "this integration". Disconnecting
          the wrong one is silent until a loop stops working days later. */}
      <ConfirmDialog
        open={!!disconnectFor}
        onClose={() => setDisconnectFor(null)}
        onConfirm={confirmDisconnect}
        title={`Disconnect ${disconnectFor?.title ?? ""}?`}
        description={
          disconnectFor
            ? `Locus will stop using your ${disconnectFor.title} credentials immediately. Anything in the pipeline that depends on it is skipped until you reconnect.`
            : undefined
        }
        confirmLabel="Disconnect"
      />
    </PageShell>
  );
}
