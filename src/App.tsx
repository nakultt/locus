import { Routes, Route, Navigate } from "react-router-dom";
import { Component } from "@/ui/the-infinite-grid";
import Chatbot from "@/pages/chatbot";
import Settings from "@/pages/settings";
import IntegrationsSection from "@/ui/integrations/integration-components";
import { AppLayout } from "@/ui/app-layout";
import { Component as LoginPage } from "@/ui/auth/login";
import SignupPage from "@/pages/signup";
import { AuthProvider, useAuth } from "@/context/AuthContext";

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
  <AppLayout>{children}</AppLayout>
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
               <div className="h-full overflow-y-auto">
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
