import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import "./index.css";
import { LoginPage } from "./components/LoginPage";
import { ChatPage } from "./components/ChatPage";
import { IntegrationHub } from "./components/IntegrationHub";

type Role = "admin" | "manager" | "user";

const RootApp: React.FC = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [userRole, setUserRole] = useState<Role>("user");

  if (!isAuthenticated) {
    return (
      <LoginPage
        onSubmit={(payload) => {
          // Here you could call a real auth API.
          // On success, we switch to the ChatPage UI.
          setUserRole(payload.role);
          setIsAuthenticated(true);
        }}
      />
    );
  }

  return (
    <Router>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/integrations" element={<IntegrationHub />} />
      </Routes>
    </Router>
  );
};

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RootApp />
  </React.StrictMode>
);



