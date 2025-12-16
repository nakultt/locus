import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { CommandCenter } from "./components/CommandCenter";
import { LoginPage } from "./components/LoginPage";

const RootApp: React.FC = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  if (!isAuthenticated) {
    return (
      <LoginPage
        onSubmit={() => {
          // Here you could call a real auth API.
          // On success, we switch to the Command Center UI.
          setIsAuthenticated(true);
        }}
      />
    );
  }

  return <CommandCenter />;
};

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RootApp />
  </React.StrictMode>
);



