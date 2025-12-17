import { Button } from "./button";
import { Card } from "./card";
import { Check, X, Loader2, Link2, Unlink } from "lucide-react";
import { useState, useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  listIntegrations,
  connectIntegration,
  disconnectIntegration,
  type Integration,
} from "@/lib/api";

// Supported integrations with their configs
const INTEGRATIONS = [
  {
    id: "slack",
    title: "Slack",
    description: "Team communication and collaboration hub.",
    color: "text-purple-600",
    fields: [{ name: "api_key", label: "Bot Token", placeholder: "xoxb-..." }],
  },
  {
    id: "jira",
    title: "Jira",
    description: "Atlassian issue tracking and project management.",
    color: "text-blue-600",
    fields: [
      { name: "api_key", label: "API Token", placeholder: "Your API token" },
      {
        name: "email",
        label: "Email",
        placeholder: "you@company.com",
        isCredential: true,
      },
      {
        name: "url",
        label: "Jira URL",
        placeholder: "https://company.atlassian.net",
        isCredential: true,
      },
    ],
  },
  {
    id: "notion",
    title: "Notion",
    description: "All-in-one workspace for notes and projects.",
    color: "text-gray-900",
    fields: [
      {
        name: "api_key",
        label: "Integration Token",
        placeholder: "secret_...",
      },
    ],
  },
  {
    id: "gmail",
    title: "Gmail",
    description: "Email management and automation.",
    color: "text-red-500",
    fields: [
      { name: "api_key", label: "API Key", placeholder: "Your Gmail API key" },
    ],
  },
  {
    id: "calendar",
    title: "Google Calendar",
    description: "Scheduling and calendar management.",
    color: "text-green-600",
    fields: [
      {
        name: "api_key",
        label: "API Key",
        placeholder: "Your Calendar API key",
      },
    ],
  },
];

// Connect Modal Component
const ConnectModal = ({
  integration,
  onClose,
  onConnect,
}: {
  integration: (typeof INTEGRATIONS)[0];
  onClose: () => void;
  onConnect: (apiKey: string, credentials?: Record<string, string>) => void;
}) => {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    const apiKey = values["api_key"] || "";
    const credentials: Record<string, string> = {};

    integration.fields.forEach((field) => {
      if (field.isCredential && values[field.name]) {
        credentials[field.name] = values[field.name];
      }
    });

    await onConnect(
      apiKey,
      Object.keys(credentials).length > 0 ? credentials : undefined
    );
    setIsLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md mx-4">
        <h3 className="text-lg font-semibold mb-4">
          Connect {integration.title}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          {integration.fields.map((field) => (
            <div key={field.name}>
              <label className="block text-sm font-medium mb-1">
                {field.label}
              </label>
              <input
                type="text"
                placeholder={field.placeholder}
                value={values[field.name] || ""}
                onChange={(e) =>
                  setValues({ ...values, [field.name]: e.target.value })
                }
                className="w-full px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
                required
              />
            </div>
          ))}
          <div className="flex gap-3 pt-4">
            <Button
              type="button"
              variant="secondary"
              onClick={onClose}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading} className="flex-1">
              {isLoading ? (
                <Loader2 className="animate-spin mr-2" size={16} />
              ) : null}
              Connect
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Integration Card Component
const IntegrationCard = ({
  config,
  isConnected,
  isLoading,
  onConnect,
  onDisconnect,
}: {
  config: (typeof INTEGRATIONS)[0];
  isConnected: boolean;
  isLoading: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
}) => (
  <Card className="p-6">
    <div className="relative">
      <div className={`text-3xl mb-4 ${config.color}`}>
        {config.id === "slack" && "💬"}
        {config.id === "jira" && "🎫"}
        {config.id === "notion" && "📝"}
        {config.id === "gmail" && "📧"}
        {config.id === "calendar" && "📅"}
      </div>

      <div className="space-y-2 pb-6">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-medium">{config.title}</h3>
          {isConnected && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-green-700 bg-green-100 rounded-full">
              <Check size={12} /> Connected
            </span>
          )}
        </div>
        <p className="text-muted-foreground text-sm">{config.description}</p>
      </div>

      <div className="flex gap-3 border-t border-dashed pt-6">
        {isConnected ? (
          <Button
            variant="destructive"
            size="sm"
            onClick={onDisconnect}
            disabled={isLoading}
            className="gap-1"
          >
            {isLoading ? (
              <Loader2 className="animate-spin" size={14} />
            ) : (
              <Unlink size={14} />
            )}
            Disconnect
          </Button>
        ) : (
          <Button
            variant="default"
            size="sm"
            onClick={onConnect}
            disabled={isLoading}
            className="gap-1"
          >
            {isLoading ? (
              <Loader2 className="animate-spin" size={14} />
            ) : (
              <Link2 size={14} />
            )}
            Connect
          </Button>
        )}
      </div>
    </div>
  </Card>
);

// Main Component
export default function IntegrationsSection() {
  const { user } = useAuth();
  const [connectedServices, setConnectedServices] = useState<Set<string>>(
    new Set()
  );
  const [loadingService, setLoadingService] = useState<string | null>(null);
  const [modalIntegration, setModalIntegration] = useState<
    (typeof INTEGRATIONS)[0] | null
  >(null);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch connected integrations on mount
  useEffect(() => {
    const fetchIntegrations = async () => {
      if (!user?.id) {
        setIsLoadingList(false);
        return;
      }

      try {
        const result = await listIntegrations(user.id);
        const connected = new Set(
          result.integrations.map((i: Integration) => i.service_name)
        );
        setConnectedServices(connected);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load integrations"
        );
      } finally {
        setIsLoadingList(false);
      }
    };

    fetchIntegrations();
  }, [user?.id]);

  const handleConnect = async (
    apiKey: string,
    credentials?: Record<string, string>
  ) => {
    if (!user?.id || !modalIntegration) return;

    setLoadingService(modalIntegration.id);
    try {
      await connectIntegration(
        user.id,
        modalIntegration.id,
        apiKey,
        credentials
      );
      setConnectedServices((prev) => new Set([...prev, modalIntegration.id]));
      setModalIntegration(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect");
    } finally {
      setLoadingService(null);
    }
  };

  const handleDisconnect = async (serviceId: string) => {
    if (!user?.id) return;

    setLoadingService(serviceId);
    try {
      await disconnectIntegration(user.id, serviceId);
      setConnectedServices((prev) => {
        const next = new Set(prev);
        next.delete(serviceId);
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect");
    } finally {
      setLoadingService(null);
    }
  };

  return (
    <section>
      <div className="py-12">
        <div className="mx-auto max-w-5xl px-6">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-semibold md:text-4xl">
              Your Integrations
            </h2>
            <p className="text-muted-foreground mt-4">
              Connect your tools to enable AI-powered automation.
            </p>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 flex items-center gap-2">
              <X size={18} />
              {error}
              <button
                onClick={() => setError(null)}
                className="ml-auto text-sm underline"
              >
                Dismiss
              </button>
            </div>
          )}

          {isLoadingList ? (
            <div className="flex justify-center py-12">
              <Loader2
                className="animate-spin text-muted-foreground"
                size={32}
              />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {INTEGRATIONS.map((config) => (
                <IntegrationCard
                  key={config.id}
                  config={config}
                  isConnected={connectedServices.has(config.id)}
                  isLoading={loadingService === config.id}
                  onConnect={() => setModalIntegration(config)}
                  onDisconnect={() => handleDisconnect(config.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Connect Modal */}
      {modalIntegration && (
        <ConnectModal
          integration={modalIntegration}
          onClose={() => setModalIntegration(null)}
          onConnect={handleConnect}
        />
      )}
    </section>
  );
}
