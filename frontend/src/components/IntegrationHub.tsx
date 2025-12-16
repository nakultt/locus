import React from "react";
import { Header } from "./Header";

interface Integration {
  id: string;
  name: string;
  category: string;
  description: string;
  logo: string; // Placeholder for logo URL or icon
  isConnected: boolean;
}

const integrations: Integration[] = [
  {
    id: "slack",
    name: "Slack",
    category: "Communication",
    description: "Team messaging and notifications",
    logo: "slack", // We'll use text or icon
    isConnected: true,
  },
  {
    id: "jira",
    name: "Jira",
    category: "Development",
    description: "Issue tracking and project management",
    logo: "jira",
    isConnected: false,
  },
  {
    id: "notion",
    name: "Notion",
    category: "Documentation",
    description: "Knowledge base and documentation",
    logo: "notion",
    isConnected: true,
  },
  {
    id: "servicenow",
    name: "ServiceNow",
    category: "Support",
    description: "IT service management and support",
    logo: "servicenow",
    isConnected: false,
  },
  {
    id: "sap-salesforce",
    name: "SAP / Salesforce",
    category: "Business Processes",
    description: "Enterprise resource & CRM systems",
    logo: "sap",
    isConnected: true,
  },
  {
    id: "google-workspace",
    name: "Google Workspace",
    category: "Collaboration",
    description: "Docs, Sheets, Mail, and Calendar",
    logo: "google",
    isConnected: false,
  },
];

const IntegrationCard: React.FC<{ integration: Integration }> = ({ integration }) => {
  return (
    <div className="bg-white rounded-2xl shadow-md hover:shadow-lg transition-all duration-300 hover:-translate-y-1 border border-gray-100 overflow-hidden group">
      <div className="p-6">
        {/* Logo and Category */}
        <div className="flex items-start justify-between mb-4">
          <div className="w-12 h-12 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-xl flex items-center justify-center text-white font-bold text-lg">
            {integration.logo.charAt(0).toUpperCase()}
          </div>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded-full">
            {integration.category}
          </span>
        </div>

        {/* Name and Description */}
        <h3 className="text-lg font-bold text-gray-900 mb-2">{integration.name}</h3>
        <p className="text-sm text-gray-600 mb-4">{integration.description}</p>

        {/* Status Badge */}
        <div className="flex items-center justify-between">
          <span
            className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${
              integration.isConnected
                ? "bg-green-100 text-green-800"
                : "bg-gray-100 text-gray-800"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full mr-2 ${
                integration.isConnected ? "bg-green-500" : "bg-gray-400"
              }`}
            ></span>
            {integration.isConnected ? "Connected" : "Not Connected"}
          </span>

          {/* Action Button */}
          <button
            className={`px-4 py-2 rounded-lg font-medium transition-all duration-200 ${
              integration.isConnected
                ? "bg-cyan-500 text-white hover:bg-cyan-600 shadow-md"
                : "bg-gray-200 text-gray-700 hover:bg-gray-300"
            } group-hover:scale-105`}
          >
            {integration.isConnected ? "Manage" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
};

export const IntegrationHub: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <div className="pt-20 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="text-center mb-12">
            <h1 className="text-3xl font-bold text-gray-900 mb-4">Integration Hub</h1>
            <p className="text-lg text-gray-600">
              Connect and manage your third-party integrations for seamless automation
            </p>
          </div>

          {/* Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {integrations.map((integration) => (
              <IntegrationCard key={integration.id} integration={integration} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};