import React, { useState } from "react";

interface HistoryItem {
  id: string;
  command: string;
  description: string;
  timestamp: string;
  group: "today" | "yesterday" | "previous";
}

interface SidebarProps {
  history: HistoryItem[];
  selectedId: string | null;
  onHistoryClick: (item: HistoryItem) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  history,
  selectedId,
  onHistoryClick,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [expandedGroups, setExpandedGroups] = useState({
    today: true,
    yesterday: true,
    previous: true,
  });

  const toggleGroup = (group: keyof typeof expandedGroups) => {
    setExpandedGroups((prev) => ({
      ...prev,
      [group]: !prev[group],
    }));
  };

  const filteredHistory = history.filter((item) =>
    item.command.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const groupedHistory = {
    today: filteredHistory.filter((item) => item.group === "today"),
    yesterday: filteredHistory.filter((item) => item.group === "yesterday"),
    previous: filteredHistory.filter((item) => item.group === "previous"),
  };

  const groupTitles = {
    today: "Today",
    yesterday: "Yesterday",
    previous: "Previous",
  };

  return (
    <div className="w-64 bg-white border-r border-gray-200 flex flex-col shadow-sm">
      <div className="px-4 py-4 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-900">Command History</h2>
      </div>

      <div className="px-4 py-3 border-b border-gray-200">
        <input
          type="text"
          placeholder="Search commands..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {Object.entries(groupedHistory).map(([group, items]) => (
          <div key={group} className="border-b border-gray-100 last:border-b-0">
            <button
              type="button"
              onClick={() => toggleGroup(group as keyof typeof expandedGroups)}
              className="w-full px-4 py-2 text-left flex items-center justify-between hover:bg-gray-50 transition-colors"
            >
              <span className="text-xs font-medium text-gray-700 uppercase tracking-wide">
                {groupTitles[group as keyof typeof groupTitles]} ({items.length})
              </span>
              <svg
                className={`w-4 h-4 text-gray-500 transition-transform ${
                  expandedGroups[group as keyof typeof expandedGroups] ? "rotate-90" : ""
                }`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 5l7 7-7 7"
                />
              </svg>
            </button>
            {expandedGroups[group as keyof typeof expandedGroups] && (
              <div className="px-2 pb-2 space-y-1">
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onHistoryClick(item)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg transition-all ${
                      selectedId === item.id
                        ? "bg-cyan-50 border border-cyan-200 text-cyan-900 shadow-sm"
                        : "hover:bg-gray-50 text-gray-700 border border-transparent hover:shadow-sm"
                    }`}
                  >
                    <p className="text-sm font-medium truncate">{item.command}</p>
                    <p className="text-xs text-gray-500 mt-0.5 truncate">{item.description}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{item.timestamp}</p>
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

export default Sidebar;