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
    logo: "/slack.png",
    authType: "api_key" as const,
    fields: [{ name: "api_key", label: "Bot Token", placeholder: "xoxb-..." }],
  },
  {
    id: "jira",
    title: "Jira",
    description: "Atlassian issue tracking and project management.",
    color: "text-blue-600",
    logo:"/jira.svg" ,
    authType: "api_key" as const,
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
    logo: "/notion.svg",
    authType: "api_key" as const,
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
    logo: "/gmail.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "calendar",
    title: "Google Calendar",
    description: "Scheduling and calendar management.",
    color: "text-green-600",
    logo:"/calendar.svg" ,
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "docs",
    title: "Google Docs",
    description: "Create and edit documents collaboratively.",
    color: "text-blue-600",
    logo: "/docs.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "sheets",
    title: "Google Sheets",
    description: "Spreadsheet creation and data management.",
    color: "text-green-600",
    logo: "/sheets.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "slides",
    title: "Google Slides",
    description: "Create stunning presentations.",
    color: "text-yellow-600",
    logo: "/slides.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "drive",
    title: "Google Drive",
    description: "Cloud file storage and sharing.",
    color: "text-blue-500",
    logo: "/logos/drive.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "forms",
    title: "Google Forms",
    description: "Create surveys and collect responses.",
    color: "text-purple-600",
    logo: "/forms.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
  },
  {
    id: "meet",
    title: "Google Meet",
    description: "Video meetings and conferencing.",
    color: "text-green-500",
    logo: "/meet.svg",
    authType: "oauth" as const,
    oauthProvider: "google",
    fields: [],
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
    <div className="mb-4">
  <img
    src={config.logo}
    alt={config.title}
    className="h-10 w-10"
  />
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

// OAuth Connect Modal Component
const OAuthConnectModal = ({
  integration,
  onClose,
  onConnect,
}: {
  integration: (typeof INTEGRATIONS)[0];
  onClose: () => void;
  onConnect: () => void;
}) => {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md mx-4">
        <h3 className="text-lg font-semibold mb-4">
          Connect {integration.title}
        </h3>
        <p className="text-muted-foreground mb-6">
          Connect your Google account to enable{" "}
          {integration.title.toLowerCase()} automation.
        </p>
        <div className="flex gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            className="flex-1"
          >
            Cancel
          </Button>
          <Button onClick={onConnect} className="flex-1 gap-2">
            <svg className="w-4 h-4" viewBox="0 0 24 24">
              <path
                fill="currentColor"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="currentColor"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="currentColor"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="currentColor"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            Sign in with Google
          </Button>
        </div>
      </div>
    </div>
  );
};

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
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // API Base URL
  const apiBaseUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

  // Handle OAuth callback URL parameters
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const success = urlParams.get("success");
    const errorParam = urlParams.get("error");
    const service = urlParams.get("service");

    if (success === "google_connected") {
      setSuccessMessage(
        `Successfully connected ${service || "Google services"}!`
      );
      // Refresh integrations list
      if (user?.id) {
        listIntegrations(user.id).then((result) => {
          const connected = new Set(
            result.integrations.map((i: Integration) => i.service_name)
          );
          setConnectedServices(connected);
        });
      }
      // Clear URL parameters
      window.history.replaceState({}, "", window.location.pathname);
    } else if (errorParam) {
      setError(`OAuth error: ${errorParam.replace(/_/g, " ")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [user?.id]);

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

  // Handle click on connect button - route to modal or OAuth
  const handleConnectClick = (config: (typeof INTEGRATIONS)[0]) => {
    setModalIntegration(config);
  };

  // Handle OAuth redirect
  const handleOAuthConnect = (config: (typeof INTEGRATIONS)[0]) => {
    if (!user?.id) {
      setError("Please log in first");
      return;
    }
    // Redirect to OAuth endpoint
    window.location.href = `${apiBaseUrl}/auth/google?user_id=${user.id}&service=${config.id}`;
  };

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

          {successMessage && (
            <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-700 flex items-center gap-2">
              <Check size={18} />
              {successMessage}
              <button
                onClick={() => setSuccessMessage(null)}
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
                  onConnect={() => handleConnectClick(config)}
                  onDisconnect={() => handleDisconnect(config.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Connect Modal - only for API key auth */}
      {modalIntegration && modalIntegration.authType === "api_key" && (
        <ConnectModal
          integration={modalIntegration}
          onClose={() => setModalIntegration(null)}
          onConnect={handleConnect}
        />
      )}

      {/* OAuth Modal - shows sign in button */}
      {modalIntegration && modalIntegration.authType === "oauth" && (
        <OAuthConnectModal
          integration={modalIntegration}
          onClose={() => setModalIntegration(null)}
          onConnect={() => handleOAuthConnect(modalIntegration)}
        />
      )}
    </section>
  );
}
