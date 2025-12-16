import React from "react";

const Header: React.FC = () => {
  return (
    <header className="fixed left-0 right-0 top-0 z-30 mx-auto flex h-14 items-center justify-between gap-4 rounded-b-2xl bg-white/6 px-4 backdrop-blur-md backdrop-saturate-110 shadow-md shadow-slate-900/10 dark:bg-slate-900/50">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-400 to-violet-500 text-white shadow-sm">
            {/* Integration / plug icon */}
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M9.6 3.6a2.4 2.4 0 013.4 0l1 1a1.8 1.8 0 012.5 2.5l-1 1a2.4 2.4 0 010 3.4 2.4 2.4 0 01-3.4 0l-1-1a1.8 1.8 0 00-2.5-2.5l-1 1a2.4 2.4 0 11-3.4-3.4l1-1a1.8 1.8 0 012.5-2.5l1 1z" stroke="none" />
            </svg>
          </div>

          <div className="leading-tight">
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <span>AI Assistant</span>
              <span className="rounded-full bg-slate-100/60 px-2 py-0.5 text-[11px] font-medium text-slate-700 dark:bg-slate-800/40 dark:text-slate-200">Integration Hub</span>
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Enterprise Automation Platform</div>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-700 hover:bg-slate-100/60 dark:text-slate-200 transition" aria-label="Notifications">
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1" />
          </svg>
          <span className="absolute -top-0.5 -right-0.5 inline-block h-2 w-2 rounded-full bg-red-500 ring-2 ring-white" />
        </button>

        <button className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-700 hover:bg-slate-100/60 dark:text-slate-200 transition" aria-label="Settings">
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>

        <div className="relative inline-flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-blue-600 text-white shadow">
          <span className="text-sm font-medium">JD</span>
          <span className="absolute -bottom-1 -right-1 inline-flex h-2 w-2 items-center justify-center rounded-full bg-white text-[9px] text-slate-900">▾</span>
        </div>
      </div>
    </header>
  );
};

export default Header;
