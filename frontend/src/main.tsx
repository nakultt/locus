import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { LoginPage } from "./components/LoginPage";
import ChatPage from "./components/ChatPage";

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

  return <ChatPage />;
};

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RootApp />
  </React.StrictMode>
);



