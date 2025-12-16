import React, { useMemo, useState } from "react";

type Cmd = { id: string; title: string; desc?: string; time: string; group: string };

const MOCK: Cmd[] = [
  { id: "c1", title: "Deploy infra report", desc: "Run infra audit and deploy report", time: "09:12", group: "Today" },
  { id: "c2", title: "Create Jira: BUG-441", desc: "Create ticket with priority high", time: "08:05", group: "Today" },
  { id: "c3", title: "Slack: Notify team", desc: "Notify #eng about release", time: "Yesterday", group: "Yesterday" },
  { id: "c4", title: "Export analytics", desc: "Export last 7 days usage", time: "Yesterday", group: "Yesterday" },
  { id: "c5", title: "Archive old incidents", desc: "Archive resolved incidents", time: "2d", group: "Previous" },
];

export const Sidebar: React.FC<{ onSelect?: (cmd: Cmd) => void }> = ({ onSelect }) => {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ Today: true, Yesterday: true, Previous: false });

  const groups = useMemo(() => Array.from(new Set(MOCK.map((m) => m.group))), []);

  const filtered = useMemo(() => {
    return MOCK.filter((m) => m.title.toLowerCase().includes(query.toLowerCase()) || m.desc?.toLowerCase().includes(query.toLowerCase()));
  }, [query]);

  return (
    <aside className="relative z-20 flex h-full w-64 flex-none flex-col border-r border-slate-200 bg-white/60 p-3 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/40">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Command History</h3>
        <button onClick={() => setQuery("")} className="text-xs text-slate-500">Clear</button>
      </div>

      <div className="mb-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search commands"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none"
        />
      </div>

      <div className="overflow-y-auto pb-6">
        {groups.map((g) => {
          const items = filtered.filter((f) => f.group === g);
          return (
            <div key={g} className="mb-2">
              <button
                onClick={() => setExpanded((s) => ({ ...s, [g]: !s[g] }))}
                className="flex w-full items-center justify-between px-1 py-2 text-xs text-slate-600"
              >
                <span className="font-medium">{g}</span>
                <span className="text-slate-400">{items.length}</span>
              </button>

              <div className={`mt-2 space-y-2 transition-all ${expanded[g] ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"}`}>
                {items.map((it) => (
                  <button
                    key={it.id}
                    onClick={() => onSelect?.(it)}
                    className="group w-full rounded-lg px-3 py-2 text-left hover:bg-slate-50/80 dark:hover:bg-slate-800/60"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">{it.title}</div>
                        <div className="text-xs text-slate-500 mt-0.5 truncate">{it.desc}</div>
                      </div>
                      <div className="ml-3 text-xs text-slate-400">{it.time}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
};

export default Sidebar;
