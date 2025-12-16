import React from "react";
import { Link } from "react-router-dom";

interface Integration {
  id: string;
  name: string;
  category: string;
  description: string;
  logo: string;
  connected: boolean;
}

const integrations: Integration[] = [
  {
    id: "slack",
    name: "Slack",
    category: "Communication",
    description: "Team messaging and notifications",
    logo: "💬",
    connected: true,
  },
  {
    id: "jira",
    name: "Jira",
    category: "Development",
    description: "Issue tracking and project management",
    logo: "🎯",
    connected: false,
  },
  {
    id: "notion",
    name: "Notion",
    category: "Documentation",
    description: "Knowledge base and documentation",
    logo: "📝",
    connected: true,
  },
  {
    id: "servicenow",
    name: "ServiceNow",
    category: "Support",
    description: "IT service management and support",
    logo: "🔧",
    connected: false,
  },
  {
    id: "sap-salesforce",
    name: "SAP / Salesforce",
    category: "Business Processes",
    description: "Enterprise resource & CRM systems",
    logo: "🏢",
    connected: true,
  },
  {
    id: "google-workspace",
    name: "Google Workspace",
    category: "Collaboration",
    description: "Docs, Sheets, Mail, and Calendar",
    logo: "📊",
    connected: false,
  },
];

interface IntegrationCardProps {
  integration: Integration;
}

const IntegrationCard: React.FC<IntegrationCardProps> = ({ integration }) => {
  return (
    <div className="bg-white rounded-2xl shadow-md hover:shadow-lg transition-all duration-300 hover:-translate-y-1 border border-gray-100 overflow-hidden group">
      <div className="p-6">
        {/* Category Tag */}
        <div className="flex justify-between items-start mb-4">
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
            {integration.category}
          </span>
        </div>

        {/* Logo and Name */}
        <div className="flex items-center gap-3 mb-3">
          <div className="w-12 h-12 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-xl flex items-center justify-center text-2xl shadow-sm">
            {integration.logo}
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{integration.name}</h3>
            <p className="text-sm text-gray-600">{integration.description}</p>
          </div>
        </div>

        {/* Status Badge */}
        <div className="flex items-center justify-between">
          <span
            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
              integration.connected
                ? "bg-green-100 text-green-800"
                : "bg-gray-100 text-gray-800"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full mr-1.5 ${
                integration.connected ? "bg-green-500" : "bg-gray-400"
              }`}
            />
            {integration.connected ? "Connected" : "Not Connected"}
          </span>

          {/* Action Button */}
          <button
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
              integration.connected
                ? "bg-cyan-500 text-white hover:bg-cyan-600 shadow-md hover:shadow-lg"
                : "bg-gray-900 text-white hover:bg-gray-800 shadow-md hover:shadow-lg"
            }`}
          >
            {integration.connected ? "Manage" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
};

export const IntegrationHub: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to="/chat"
              className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 19l-7-7 7-7"
                />
              </svg>
              Back to AI Assistant
            </Link>
            <div className="h-6 w-px bg-gray-300"></div>
            <h1 className="text-xl font-semibold text-gray-900">Integration Hub</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="px-6 py-8">
        <div className="max-w-6xl mx-auto">
          {/* Page Title */}
          <div className="text-center mb-8">
            <h2 className="text-3xl font-bold text-gray-900 mb-2">Connect Your Tools</h2>
            <p className="text-gray-600 max-w-2xl mx-auto">
              Integrate with your favorite tools to automate workflows, sync data, and enhance productivity across your entire stack.
            </p>
          </div>

          {/* Integration Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {integrations.map((integration) => (
              <IntegrationCard key={integration.id} integration={integration} />
            ))}
          </div>

          {/* Footer Note */}
          <div className="text-center mt-12">
            <p className="text-sm text-gray-500">
              Need help with integrations? Check our{" "}
              <a href="#" className="text-cyan-600 hover:text-cyan-700 font-medium">
                documentation
              </a>{" "}
              or contact{" "}
              <a href="#" className="text-cyan-600 hover:text-cyan-700 font-medium">
                support
              </a>
              .
            </p>
          </div>
        </div>
      </main>
    </div>
  );
};

export default IntegrationHub;