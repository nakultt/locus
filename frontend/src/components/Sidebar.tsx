import React, { useState } from "react";

interface HistoryItem {
  id: string;
  command: string;
  timestamp: string;
  group: "today" | "yesterday" | "previous";
}

interface SidebarProps {
  onHistoryClick: (command: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ onHistoryClick }) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(["today", "yesterday"]));

  const commandHistory: HistoryItem[] = [
    { id: "h1", command: "Create a Jira ticket for bug fix", timestamp: "10:30 AM", group: "today" },
    { id: "h2", command: "Send notification to Slack channel", timestamp: "09:15 AM", group: "today" },
    { id: "h3", command: "Update Salesforce opportunity status", timestamp: "4:20 PM", group: "yesterday" },
    { id: "h4", command: "Generate weekly report", timestamp: "2:45 PM", group: "yesterday" },
    { id: "h5", command: "Schedule team meeting", timestamp: "11:00 AM", group: "previous" },
    { id: "h6", command: "Check integration health status", timestamp: "3:30 PM", group: "previous" },
  ];

  const filteredHistory = commandHistory.filter(item =>
    item.command.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const groupedHistory = filteredHistory.reduce((acc, item) => {
    if (!acc[item.group]) acc[item.group] = [];
    acc[item.group].push(item);
    return acc;
  }, {} as Record<string, HistoryItem[]>);

  const toggleGroup = (group: string) => {
    const newExpanded = new Set(expandedGroups);
    if (newExpanded.has(group)) {
      newExpanded.delete(group);
    } else {
      newExpanded.add(group);
    }
    setExpandedGroups(newExpanded);
  };

  const groupLabels = {
    today: "Today",
    yesterday: "Yesterday",
    previous: "Previous"
  };

  return (
    <div className="w-80 bg-white/95 backdrop-blur-md border-r border-gray-200/50 shadow-xl flex flex-col">
      {/* Header */}
      <div className="p-6 border-b border-gray-200/50">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Command History</h2>

        {/* Search */}
        <div className="relative">
          <input
            type="text"
            placeholder="Search commands..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full px-4 py-2 pl-10 bg-gray-50/80 border border-gray-200/50 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-transparent transition-all"
          />
          <svg className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
      </div>

      {/* History List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {Object.entries(groupedHistory).map(([group, items]) => (
          <div key={group} className="space-y-1">
            <button
              onClick={() => toggleGroup(group)}
              className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50/50 rounded-lg transition-all"
            >
              <span>{groupLabels[group as keyof typeof groupLabels]}</span>
              <svg
                className={`w-4 h-4 transition-transform ${expandedGroups.has(group) ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {expandedGroups.has(group) && (
              <div className="space-y-1 ml-2">
                {items.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => onHistoryClick(item.command)}
                    className="w-full text-left px-3 py-3 rounded-xl border border-transparent hover:border-cyan-200/50 hover:bg-cyan-50/30 transition-all group"
                  >
                    <p className="text-sm font-medium text-gray-900 group-hover:text-cyan-900 truncate">
                      {item.command}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">{item.timestamp}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};