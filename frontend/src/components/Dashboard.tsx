import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";

type Role = "admin" | "manager" | "user";

const cardVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
};

const sectionTitleClass =
  "flex items-center justify-between text-xs font-semibold uppercase tracking-[0.18em] text-slate-400";

interface DashboardProps {
  initialRole?: Role;
}

export const Dashboard: React.FC<DashboardProps> = ({ initialRole = "user" }) => {
  const [role, setRole] = useState<Role>(initialRole);
  const [isSimulationOpen, setIsSimulationOpen] = useState(false);

  const roleDescription = useMemo(() => {
    switch (role) {
      case "admin":
        return "System health, integration posture, and permission integrity across the DewDrop fabric.";
      case "manager":
        return "Workflow performance, productivity gains, and business impact of your automation programs.";
      case "user":
        return "Your recent commands, safe previews, and AI‑recommended shortcuts to work faster.";
      default:
        return "";
    }
  }, [role]);

  const integrations = [
    {
      id: "jira",
      name: "Jira",
      icon: "🧩",
      status: "active" as const,
      lastSync: "2 mins ago",
      permissions: "Scoped project access",
    },
    {
      id: "slack",
      name: "Slack",
      icon: "💬",
      status: "active" as const,
      lastSync: "Just now",
      permissions: "Workspace approved",
    },
    {
      id: "salesforce",
      name: "Salesforce",
      icon: "📈",
      status: "error" as const,
      lastSync: "12 mins ago",
      permissions: "Re‑auth required",
    },
    {
      id: "servicenow",
      name: "ServiceNow",
      icon: "⚙️",
      status: "active" as const,
      lastSync: "5 mins ago",
      permissions: "ITSM admin scope",
    },
  ];

  const activities = [
    {
      id: 1,
      tool: "Jira",
      icon: "🧩",
      message: "Ticket DEV‑214 created from Slack command.",
      timestamp: "09:42",
      status: "success" as const,
    },
    {
      id: 2,
      tool: "Slack",
      icon: "💬",
      message: "Message sent to #dev‑platform: deployment rollback notice.",
      timestamp: "09:39",
      status: "success" as const,
    },
    {
      id: 3,
      tool: "Workflow",
      icon: "🔁",
      message: "Workflow “Bug → Notify → Escalate” executed.",
      timestamp: "09:31",
      status: "success" as const,
    },
    {
      id: 4,
      tool: "Salesforce",
      icon: "📈",
      message: "Opportunity sync failed (permission issue).",
      timestamp: "09:27",
      status: "error" as const,
    },
  ];

  const recommendations = [
    {
      id: 1,
      title: "Automate Jira + Slack triage",
      description:
        "You often create Jira tickets and follow up in Slack. Convert this into a reusable triage workflow.",
      confidence: 0.87,
      reason: "Detected 42 related command patterns in the last 7 days.",
    },
    {
      id: 2,
      title: "Stabilize Salesforce sync",
      description:
        "Salesforce updates are failing intermittently. Add a retry + notification workflow before sales reviews.",
      confidence: 0.81,
      reason: "High error rate in the last 3 nightly sync windows.",
    },
  ];

  const alerts = [
    {
      id: 1,
      severity: "high" as const,
      title: "Salesforce token expired",
      description: "Reconnect Salesforce to restore opportunity and account sync.",
      cta: "Reconnect",
    },
    {
      id: 2,
      severity: "medium" as const,
      title: "Workflow “Incident → Major Incident” failing",
      description: "5 failures in the last hour. Slack channel permission mismatch.",
      cta: "View run log",
    },
    {
      id: 3,
      severity: "low" as const,
      title: "New integration available: Notion",
      description: "Connect Notion to sync runbooks and incident timelines.",
      cta: "Explore",
    },
  ];

  const isAdmin = role === "admin";
  const isManager = role === "manager";
  const isUser = role === "user";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50">
      {/* Global shell header */}
      <header className="border-b border-slate-800/70 bg-slate-950/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-400 via-sky-500 to-violet-500 text-xs font-semibold text-slate-950 shadow-lg shadow-cyan-500/30">
              DD
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-semibold tracking-tight">
                DewDrop Integration Store
              </span>
              <span className="text-[11px] text-slate-400">
                AI‑powered mission control for enterprise automations
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* System pulse */}
            <div className="hidden items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-[11px] text-emerald-200 shadow-sm shadow-emerald-500/20 sm:flex">
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(52,211,153,0.35)]" />
              <span>All systems operational</span>
            </div>

            {/* Role selector */}
            <div className="flex items-center gap-1 rounded-full bg-slate-900/80 p-1 text-[11px] border border-slate-700/80 shadow-inner shadow-slate-950/60">
              {[
                { id: "admin", label: "Admin" },
                { id: "manager", label: "Manager" },
                { id: "user", label: "User" },
              ].map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setRole(r.id as Role)}
                  className={`rounded-full px-2.5 py-1 transition text-xs ${
                    role === r.id
                      ? "bg-cyan-500 text-slate-950 shadow-sm shadow-cyan-400/40"
                      : "text-slate-400 hover:text-slate-100 hover:bg-slate-800/80"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* Main layout */}
      <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        {/* Role description & simulation entry */}
        <section className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.22em] text-slate-500">
              {role === "admin"
                ? "System Health • Security • Governance"
                : role === "manager"
                ? "Automation Performance • Business Impact"
                : "Personal Command Center • AI Guidance"}
            </p>
            <p className="mt-1 text-sm text-slate-300">{roleDescription}</p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setIsSimulationOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-medium text-cyan-200 shadow-sm hover:bg-cyan-500/20 hover:border-cyan-400/70 transition"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
              <span>Open Workflow Simulation</span>
            </button>
            <span className="hidden text-[11px] text-slate-500 md:inline">
              Run a dry‑run of complex automations before deploying live.
            </span>
          </div>
        </section>

        {/* System overview metrics */}
        <section>
          <div className={sectionTitleClass}>
            <span>System Overview</span>
            <span className="text-[11px] text-slate-500">
              Real‑time visibility into your DewDrop fabric
            </span>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              {
                label: "Active Integrations",
                value: "6",
                icon: "🔌",
                subLabel: "All systems operational",
                trend: "+2 this week",
                tone: "primary",
              },
              {
                label: "Commands Executed Today",
                value: "128",
                icon: "⚡",
                subLabel: "Avg latency 420ms",
                trend: "+18% vs yesterday",
                tone: "neutral",
              },
              {
                label: "Active Workflows",
                value: "12",
                icon: "🔁",
                subLabel: "3 with AI‑driven routing",
                trend: "4 in draft",
                tone: "neutral",
              },
              {
                label: "Success Rate",
                value: "98.4%",
                icon: "✅",
                subLabel: "Last 24h execution health",
                trend: "0.6% error rate",
                tone: "success",
              },
            ].map((card, idx) => (
              <motion.div
                key={card.label}
                variants={cardVariants}
                initial="hidden"
                animate="visible"
                transition={{ delay: 0.03 * idx, duration: 0.25 }}
                className={`group relative overflow-hidden rounded-2xl border border-slate-800/80 bg-gradient-to-br from-slate-950 via-slate-950 to-slate-900/90 px-4 py-4 shadow-[0_18px_45px_rgba(15,23,42,0.9)] transition
                hover:-translate-y-0.5 hover:border-cyan-400/60 hover:shadow-[0_22px_65px_rgba(8,47,73,0.75)]`}
              >
                <div
                  className={`pointer-events-none absolute inset-px rounded-2xl opacity-0 blur-2xl transition
                  group-hover:opacity-100 ${
                    card.tone === "primary"
                      ? "bg-gradient-to-br from-cyan-500/25 via-sky-500/10 to-transparent"
                      : card.tone === "success"
                      ? "bg-gradient-to-br from-emerald-500/20 via-sky-500/10 to-transparent"
                      : "bg-gradient-to-br from-slate-500/10 to-transparent"
                  }`}
                />
                <div className="relative flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-medium text-slate-400">
                      {card.label}
                    </p>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="text-2xl font-semibold tracking-tight text-slate-50">
                        {card.value}
                      </span>
                      <span className="text-[11px] text-slate-500">
                        {card.subLabel}
                      </span>
                    </div>
                    <p
                      className={`mt-2 text-[11px] ${
                        card.tone === "success"
                          ? "text-emerald-300"
                          : "text-sky-300"
                      }`}
                    >
                      {card.trend}
                    </p>
                  </div>
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900/80 text-lg shadow-inner shadow-slate-900/80 ring-1 ring-slate-700/80">
                    <span>{card.icon}</span>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </section>

        {/* Second row: integrations + activity + command insights */}
        <section className="grid gap-4 lg:grid-cols-3">
          {/* Connected Integrations */}
          {(isAdmin || isManager) && (
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              transition={{ duration: 0.25, delay: 0.05 }}
              className="rounded-2xl border border-slate-800/80 bg-slate-950/90 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.9)]"
            >
              <div className={sectionTitleClass}>
                <span>Connected Integrations</span>
                <span className="text-[11px] text-slate-500">
                  Health across Jira, Slack, Salesforce, ServiceNow
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {integrations.map((integration) => (
                  <div
                    key={integration.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5 text-xs hover:border-cyan-500/40 hover:bg-slate-900 transition"
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-800/80 text-base">
                        <span>{integration.icon}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[13px] font-medium text-slate-100">
                          {integration.name}
                        </span>
                        <span className="text-[11px] text-slate-500">
                          Last sync: {integration.lastSync}
                        </span>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          integration.status === "active"
                            ? "bg-emerald-500/10 text-emerald-300"
                            : "bg-rose-500/10 text-rose-300"
                        }`}
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            integration.status === "active"
                              ? "bg-emerald-400"
                              : "bg-rose-400"
                          }`}
                        />
                        <span className="capitalize">
                          {integration.status === "active" ? "Active" : "Error"}
                        </span>
                      </span>
                      <span className="text-[11px] text-slate-500">
                        {integration.permissions}
                      </span>
                      {isAdmin && (
                        <button
                          type="button"
                          className="text-[11px] font-medium text-cyan-300 hover:text-cyan-200"
                        >
                          Manage
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {/* Activity Feed */}
          <motion.div
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.25, delay: 0.08 }}
            className="rounded-2xl border border-slate-800/80 bg-slate-950/90 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.9)]"
          >
            <div className={sectionTitleClass}>
              <span>Recent Activity</span>
              <span className="text-[11px] text-slate-500">
                Live orchestration feed
              </span>
            </div>
            <div className="mt-3 max-h-64 space-y-3 overflow-y-auto pr-1 text-xs">
              <div className="relative">
                <div className="absolute left-[10px] top-1 bottom-1 w-px bg-slate-800" />
                <div className="space-y-3">
                  {activities.map((item) => (
                    <div key={item.id} className="relative flex gap-3">
                      <div className="z-10 mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-[11px] ring-1 ring-slate-700">
                        <span>{item.icon}</span>
                      </div>
                      <div className="flex-1 rounded-xl bg-slate-900/80 px-3 py-2.5 border border-slate-800/80">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-[11px] font-medium text-slate-200">
                            {item.tool}
                          </span>
                          <span
                            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] ${
                              item.status === "success"
                                ? "bg-emerald-500/10 text-emerald-300"
                                : "bg-rose-500/10 text-rose-300"
                            }`}
                          >
                            <span
                              className={`h-1.5 w-1.5 rounded-full ${
                                item.status === "success"
                                  ? "bg-emerald-400"
                                  : "bg-rose-400"
                              }`}
                            />
                            <span className="capitalize">{item.status}</span>
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-300">
                          {item.message}
                        </p>
                        <p className="mt-1 text-[10px] text-slate-500">
                          {item.timestamp} • Simulated log
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </motion.div>

          {/* Command Usage Insights */}
          {(isManager || isUser) && (
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              transition={{ duration: 0.25, delay: 0.11 }}
              className="rounded-2xl border border-slate-800/80 bg-slate-950/90 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.9)]"
            >
              <div className={sectionTitleClass}>
                <span>Command Usage Insights</span>
                <span className="text-[11px] text-slate-500">
                  How your teams talk to DewDrop
                </span>
              </div>
              <div className="mt-3 space-y-3 text-xs">
                <div>
                  <p className="text-[11px] text-slate-400">Most common command</p>
                  <p className="mt-1 text-sm font-medium text-slate-100">
                    “Create Jira ticket”
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Used 83 times today • Peak 10:00–12:00
                  </p>
                </div>
                <div>
                  <p className="text-[11px] text-slate-400">Power user band</p>
                  <div className="mt-1 flex items-center justify-between">
                    <div className="h-1.5 w-40 rounded-full bg-slate-800">
                      <div className="h-1.5 w-2/3 rounded-full bg-gradient-to-r from-cyan-400 via-sky-500 to-violet-500" />
                    </div>
                    <span className="text-[11px] text-slate-400">
                      Top 12% of org
                    </span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 text-[11px]">
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 px-3 py-2">
                    <p className="text-slate-400">Peak load window</p>
                    <p className="mt-1 text-sm text-slate-100">09:00–13:00</p>
                    <p className="mt-0.5 text-slate-500">
                      Ideal for scaling concurrency.
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/70 px-3 py-2">
                    <p className="text-slate-400">Natural language usage</p>
                    <p className="mt-1 text-sm text-slate-100">92%</p>
                    <p className="mt-0.5 text-slate-500">
                      High reliance on AI interpretation.
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </section>

        {/* Third row: workflow performance + AI recommendations + alerts */}
        <section className="grid gap-4 lg:grid-cols-3">
          {/* Workflow Performance */}
          {(isManager || isAdmin) && (
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              transition={{ duration: 0.25, delay: 0.05 }}
              className="rounded-2xl border border-slate-800/80 bg-slate-950/90 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.9)]"
            >
              <div className={sectionTitleClass}>
                <span>Workflow Performance</span>
                <span className="text-[11px] text-slate-500">
                  Automation insights & business impact
                </span>
              </div>
              <div className="mt-3 space-y-3 text-xs">
                <div className="rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5">
                  <p className="text-[11px] text-slate-400">Top Workflow</p>
                  <p className="mt-1 text-sm font-medium text-slate-100">
                    “Create Jira → Notify Slack”
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Used 47 times today • Median run: 3.2s
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5">
                    <p className="text-[11px] text-slate-400">
                      Success vs failure
                    </p>
                    <div className="mt-1 flex items-end justify-between">
                      <p className="text-xl font-semibold text-emerald-300">
                        96.8%
                      </p>
                      <p className="text-[11px] text-slate-500">Last 7 days</p>
                    </div>
                    <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-slate-800">
                      <div className="h-1.5 w-[92%] bg-gradient-to-r from-emerald-400 to-cyan-500" />
                      <div className="h-1.5 flex-1 bg-rose-500/60" />
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5">
                    <p className="text-[11px] text-slate-400">Workflows with errors</p>
                    <p className="mt-1 text-xl font-semibold text-amber-300">3</p>
                    <p className="mt-0.5 text-[11px] text-slate-500">
                      Mostly permissions or throttling.
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 text-[11px]">
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5">
                    <p className="text-slate-400">Time Saved</p>
                    <p className="mt-1 text-sm text-slate-100">2.5 hrs/week</p>
                    <p className="mt-0.5 text-slate-500">Modeled vs manual flows.</p>
                  </div>
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5">
                    <p className="text-slate-400">Manual Steps Reduced</p>
                    <p className="mt-1 text-sm text-slate-100">5 per run</p>
                    <p className="mt-0.5 text-slate-500">Cross‑tool hand‑offs removed.</p>
                  </div>
                  <div className="rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5">
                    <p className="text-slate-400">Estimated Cost Saved</p>
                    <p className="mt-1 text-sm text-emerald-300">$18.7K / yr</p>
                    <p className="mt-0.5 text-slate-500">Based on blended rates.</p>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {/* AI Recommendations */}
          <motion.div
            variants={cardVariants}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.25, delay: 0.08 }}
            className="relative overflow-hidden rounded-2xl border border-cyan-500/40 bg-gradient-to-br from-slate-950 via-slate-950 to-slate-900/90 p-4 shadow-[0_22px_60px_rgba(8,47,73,0.9)]"
          >
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.18),_transparent_55%),radial-gradient(circle_at_bottom_right,_rgba(129,140,248,0.18),_transparent_55%)] opacity-80" />
            <div className="relative">
              <div className={sectionTitleClass}>
                <span className="inline-flex items-center gap-2">
                  <span>AI Recommendations</span>
                  <span className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold text-cyan-200 border border-cyan-400/40">
                    🔮 Predicted Actions
                  </span>
                </span>
                <span className="text-[11px] text-slate-400">
                  Powered by DewDrop signal graph
                </span>
              </div>
              <div className="mt-3 space-y-3 text-xs">
                {recommendations.map((rec) => (
                  <div
                    key={rec.id}
                    className="rounded-xl border border-cyan-500/40 bg-slate-950/80 px-3 py-2.5 shadow-sm shadow-cyan-500/40"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-slate-50">
                        {rec.title}
                      </p>
                      <span className="text-[11px] text-cyan-200">
                        {(rec.confidence * 100).toFixed(0)}% confident
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-200">
                      {rec.description}
                    </p>
                    <p className="mt-1 text-[11px] text-slate-400">
                      Reason: {rec.reason}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-lg bg-cyan-500 px-2.5 py-1.5 text-[11px] font-medium text-slate-950 shadow-sm hover:bg-cyan-400 transition"
                      >
                        Create Workflow
                      </button>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-[11px] font-medium text-slate-100 hover:border-cyan-400/60 hover:text-cyan-100 transition"
                      >
                        Preview Path
                      </button>
                      <button
                        type="button"
                        className="ml-auto text-[11px] text-slate-400 hover:text-slate-200"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>

          {/* Alerts & Notifications */}
          {(isAdmin || isManager) && (
            <motion.div
              variants={cardVariants}
              initial="hidden"
              animate="visible"
              transition={{ duration: 0.25, delay: 0.11 }}
              className="rounded-2xl border border-slate-800/80 bg-slate-950/90 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.9)]"
            >
              <div className={sectionTitleClass}>
                <span>Alerts & Notifications</span>
                <span className="text-[11px] text-slate-500">
                  Issues that need your attention
                </span>
              </div>
              <div className="mt-3 space-y-2 text-xs">
                {alerts.map((alert) => (
                  <div
                    key={alert.id}
                    className="flex items-start justify-between gap-3 rounded-xl border border-slate-800/80 bg-slate-900/80 px-3 py-2.5"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                            alert.severity === "high"
                              ? "bg-rose-500/10 text-rose-300"
                              : alert.severity === "medium"
                              ? "bg-amber-500/10 text-amber-300"
                              : "bg-slate-500/10 text-slate-300"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              alert.severity === "high"
                                ? "bg-rose-400"
                                : alert.severity === "medium"
                                ? "bg-amber-400"
                                : "bg-slate-400"
                            }`}
                          />
                          <span className="uppercase tracking-[0.14em]">
                            {alert.severity} priority
                          </span>
                        </span>
                        <p className="text-[13px] font-medium text-slate-100">
                          {alert.title}
                        </p>
                      </div>
                      <p className="mt-1 text-[11px] text-slate-400">
                        {alert.description}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="mt-1 text-[11px] font-medium text-cyan-300 hover:text-cyan-200"
                    >
                      {alert.cta}
                    </button>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </section>
      </main>

      {/* Workflow Simulation Modal */}
      {isSimulationOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.18 }}
            className="w-full max-w-xl rounded-2xl border border-slate-800 bg-slate-950 p-5 text-xs shadow-[0_22px_70px_rgba(15,23,42,0.95)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                  Workflow Simulation Mode
                </p>
                <p className="mt-1 text-sm text-slate-100">
                  Dry‑run your automations across tools before promoting to
                  production.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsSimulationOpen(false)}
                className="text-[11px] text-slate-400 hover:text-slate-100"
              >
                Close
              </button>
            </div>

            <div className="mt-4 grid gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-3 text-xs">
              <div>
                <p className="text-[11px] text-slate-400">Simulated path</p>
                <p className="mt-1 text-sm text-slate-100">
                  Create Jira → Notify Slack → Update Notion
                </p>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-900 px-3 py-2 border border-slate-800">
                  <div className="flex items-center gap-2">
                    <span>🧩</span>
                    <span className="text-slate-100">Jira ticket created</span>
                  </div>
                  <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300">
                    ✔ Success
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-900 px-3 py-2 border border-slate-800">
                  <div className="flex items-center gap-2">
                    <span>💬</span>
                    <span className="text-slate-100">
                      Slack notification to #incident‑bridge
                    </span>
                  </div>
                  <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                    ⚠ Permission missing
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-900 px-3 py-2 border border-slate-800">
                  <div className="flex items-center gap-2">
                    <span>📝</span>
                    <span className="text-slate-100">
                      Notion incident page update
                    </span>
                  </div>
                  <span className="rounded-full bg-slate-500/10 px-2 py-0.5 text-[10px] text-slate-200">
                    ⏱ Deferred until Slack fixed
                  </span>
                </div>
              </div>
              <div className="mt-1 flex flex-col gap-2 border-t border-slate-800 pt-3 text-[11px] text-slate-400">
                <p>
                  No changes have been applied. This is a safe, simulated
                  preview to prevent failures and build trust in automation.
                </p>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    <span>Ready to promote after Slack permissions are fixed.</span>
                  </div>
                  <button
                    type="button"
                    className="rounded-lg bg-cyan-500 px-3 py-1.5 text-[11px] font-medium text-slate-950 hover:bg-cyan-400 transition"
                  >
                    Save Simulation as Draft Workflow
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;

