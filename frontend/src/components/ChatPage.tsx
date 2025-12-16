import React from "react";

const now = () => {
  const d = new Date();
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

const ChatPage: React.FC = () => {
  const assistantMsgs = [
    { id: "a1", text: "Hello! I’m your AI assistant. How can I help you today?", time: now() },
    { id: "a2", text: "I’ve received your message. Let me process that for you.", time: now() },
    { id: "a3", text: "I’ve received your message. Let me process that for you.", time: now() },
  ];

  const userMsgs = [{ id: "u1", text: "xyz", time: now() }, { id: "u2", text: "hello", time: now() }];

  return (
    <div className="min-h-screen bg-white text-slate-900">
      {/* Top Header */}
      <header className="flex items-center gap-4 border-b border-slate-200 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-white shadow">
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 12h18M12 3v18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
          <div>
            <div className="text-lg font-semibold">AI Assistant</div>
            <div className="text-xs text-slate-500">Enterprise Automation Platform</div>
          </div>
        </div>
      </header>

      <div className="flex h-[calc(100vh-72px)]">
        {/* Sidebar */}
        <aside className="w-64 flex-none bg-slate-50 border-r border-slate-100 p-4 overflow-y-auto">
          <h3 className="text-sm font-semibold mb-3">Command History</h3>
          <input placeholder="Search commands..." className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-cyan-300" />

          <div className="space-y-4 text-sm">
            <div>
              <div className="text-xs font-semibold text-slate-600 mb-2">TODAY</div>
              <div className="space-y-2">
                <div className="rounded-lg p-3 bg-white border border-slate-100 shadow-sm">
                  <div className="font-medium">Create a Jira ticket for bug fix</div>
                  <div className="text-xs text-slate-500 mt-1">Automate ticket creation and assignment</div>
                </div>
                <div className="rounded-lg p-3 bg-white border border-slate-100 shadow-sm">
                  <div className="font-medium">Send notification to Slack channel</div>
                  <div className="text-xs text-slate-500 mt-1">Broadcast updates to team</div>
                </div>
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-slate-600 mb-2">YESTERDAY</div>
              <div className="space-y-2">
                <div className="rounded-lg p-3 bg-white border border-slate-100 shadow-sm">
                  <div className="font-medium">Update Salesforce opportunity</div>
                  <div className="text-xs text-slate-500 mt-1">Modify deal pipeline information</div>
                </div>
                <div className="rounded-lg p-3 bg-white border border-slate-100 shadow-sm">
                  <div className="font-medium">Generate weekly report</div>
                  <div className="text-xs text-slate-500 mt-1">Compile analytics and metrics</div>
                </div>
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-slate-600 mb-2">PREVIOUS</div>
              <div className="space-y-2">
                <div className="rounded-lg p-3 bg-white border border-slate-100 shadow-sm">
                  <div className="font-medium">Schedule team meeting</div>
                  <div className="text-xs text-slate-500 mt-1">Book calendar slots for discussion</div>
                </div>
              </div>
            </div>
          </div>
        </aside>

        {/* Main Chat Area */}
        <main className="flex-1 p-6 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6">
            {/* Assistant messages */}
            {assistantMsgs.map((m, idx) => (
              <div key={m.id} className="flex items-start gap-3">
                <div className="flex-none h-9 w-9 rounded-full bg-gradient-to-br from-cyan-500 to-violet-500 flex items-center justify-center text-white text-xs font-semibold">AI</div>
                <div className="flex-1">
                  <div className="rounded-xl bg-white shadow-sm px-4 py-3 border border-slate-100">
                    <div className="text-sm text-slate-800">{m.text}</div>
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                    <span>{m.time}</span>
                    <span className="text-emerald-600 font-medium">completed</span>
                  </div>
                </div>
              </div>
            ))}

            {/* User messages right aligned */}
            {userMsgs.map((u) => (
              <div key={u.id} className="flex justify-end">
                <div className="max-w-xs">
                  <div className="rounded-xl bg-gradient-to-br from-cyan-500 to-blue-500 text-white px-4 py-2 shadow-sm text-sm">{u.text}</div>
                  <div className="text-xs text-slate-400 mt-1 text-right">{u.time}</div>
                </div>
              </div>
            ))}

            {/* Input bar */}
            <div className="sticky bottom-4 left-0">
              <div className="mx-auto max-w-3xl px-0">
                <div className="flex items-center gap-3 bg-white rounded-full border border-slate-200 px-3 py-2 shadow-sm">
                  <button className="p-2 text-slate-500 hover:text-slate-700">
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 1.5a2.5 2.5 0 00-2.5 2.5v4a2.5 2.5 0 005 0v-4A2.5 2.5 0 0012 1.5z"/><path d="M19 11v1a7 7 0 01-14 0v-1"/><path d="M12 19v3"/></svg>
                  </button>
                  <input className="flex-1 outline-none px-3 text-sm" placeholder="Type your message..." />
                  <button className="p-2 bg-cyan-600 rounded-full text-white hover:bg-cyan-700">
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M22 2L11 13"/><path d="M22 2l-7 20 2-7 7-7z"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default ChatPage;
