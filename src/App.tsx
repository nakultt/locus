import { Routes, Route } from "react-router-dom";
import { Component } from "@/ui/the-infinite-grid";
import Chatbot from "@/pages/chatbot";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Component />} />
      <Route path="/chatbot" element={<Chatbot />} />
    </Routes>
  );
}
