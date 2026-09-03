import { Suspense } from "react";
import SettingsView from "@/features/settings/settings-view";

/**
 * The active tab lives in the query string so it can be linked to, which means
 * `useSearchParams` — and Next opts a whole route out of static rendering when
 * that hook is used without a Suspense boundary, failing only at build time.
 */
export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
          <div className="h-8 w-40 animate-pulse rounded-md bg-surface-3" />
        </div>
      }
    >
      <SettingsView />
    </Suspense>
  );
}
