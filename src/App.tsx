import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Component } from "@/ui/the-infinite-grid";
import { AppLayout } from "@/ui/app-layout";
import { Component as LoginPage } from "@/ui/auth/login";
import SignupPage from "@/pages/signup";
import { AuthProvider, useAuth } from "@/context/AuthContext";

// Authenticated routes are split out so the landing and auth pages do not
// carry the chat bundle (react-markdown and friends are ~45 kB gzipped).
const Chatbot = lazy(() => import("@/pages/chatbot"));
const Settings = lazy(() => import("@/pages/settings"));
const PRAgentDashboard = lazy(() => import("@/pages/pr-agent"));
const SchedulerPage = lazy(() => import("@/pages/scheduler"));
const IntegrationsSection = lazy(() => import("@/ui/integrations/integration-components"));

const RouteFallback = () => (
  <div className="min-h-screen flex items-center justify-center bg-background">
    <div className="animate-pulse text-muted-foreground">Loading...</div>
  </div>
);

// Protected route wrapper
const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};
const WithLayout = ({ children }: { children: React.ReactNode }) => (
  <AppLayout>
    <Suspense fallback={<RouteFallback />}>{children}</Suspense>
  </AppLayout>
);

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Landing page - no sidebar */}
        <Route path="/" element={<Component />} />

        {/* Auth pages - no sidebar */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />

        {/* Protected pages with sidebar layout */}
        <Route
          path="/chatbot"
          element={
            <ProtectedRoute>
              <WithLayout>
                <Chatbot />
              </WithLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/pr-agent"
          element={
            <ProtectedRoute>
              <WithLayout>
                <PRAgentDashboard />
              </WithLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/scheduler"
          element={
            <ProtectedRoute>
              <WithLayout>
                <SchedulerPage />
              </WithLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <WithLayout>
                <Settings />
              </WithLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/integrations/integrations-page"
          element={
            <ProtectedRoute>
              <WithLayout>
                <div className="flex-1 min-h-0 overflow-y-auto">
                    <IntegrationsSection />
                </div>
              </WithLayout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
