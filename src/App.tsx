import { Routes, Route } from "react-router-dom";
import { Component } from "@/ui/the-infinite-grid";
import Chatbot from "@/pages/chatbot";
import Settings from "@/pages/settings";
import IntegrationsSection from "@/ui/integrations/integration-components";
import { AppLayout } from "@/ui/app-layout";
import { Component as LoginPage } from "@/ui/auth/login";
import SignupPage from "@/pages/signup";

// Wrapper component for pages that need the app layout
const WithLayout = ({ children }: { children: React.ReactNode }) => (
  <AppLayout>{children}</AppLayout>
);

export default function App() {
  return (
    <Routes>
      {/* Landing page - no sidebar */}
      <Route path="/" element={<Component />} />

      {/* Auth pages - no sidebar */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      {/* Pages with sidebar layout */}
      <Route
        path="/chatbot"
        element={
          <WithLayout>
            <Chatbot />
          </WithLayout>
        }
      />
      <Route
        path="/settings"
        element={
          <WithLayout>
            <Settings />
          </WithLayout>
        }
      />
      <Route
        path="/integrations/integrations-page"
        element={
          <WithLayout>
            <IntegrationsSection />
          </WithLayout>
        }
      />
    </Routes>
  );
}
