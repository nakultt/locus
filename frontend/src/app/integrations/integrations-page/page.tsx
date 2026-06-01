"use client";
import { AppLayout } from "@/ui/app-layout";
import IntegrationsSection from "@/ui/integrations/integration-components";

export default function IntegrationsPage() {
  return (
    <AppLayout>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <IntegrationsSection />
      </div>
    </AppLayout>
  );
}
