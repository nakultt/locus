/**
 * API Client for Locus Backend
 * Handles all HTTP requests to the FastAPI backend
 */

// API Base URL - change this when deploying
const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ============== Types ==============

export interface User {
  id: number;
  email: string;
  name?: string;
  token?: string;
  created_at?: string;
}

export interface ActionResult {
  service: string;
  action: string;
  success: boolean;
  result?: string;
  error?: string;
}

export interface ChatResponse {
  message: string;
  actions_taken: ActionResult[];
  raw_response?: string;
}

export interface Integration {
  id: number;
  service_name: string;
  owner_id: number;
  created_at?: string;
  is_connected: boolean;
}

export interface IntegrationList {
  integrations: Integration[];
  total: number;
}

export interface ApiError {
  detail: string;
  error_code?: string;
}

// ============== Helper Functions ==============

function getAuthToken(): string | null {
  const user = localStorage.getItem("locus_user");
  if (user) {
    try {
      const parsed = JSON.parse(user);
      return parsed.token || null;
    } catch {
      return null;
    }
  }
  return null;
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const error: ApiError = await response.json().catch(() => ({
      detail: `Request failed with status ${response.status}`,
    }));
    throw new Error(error.detail);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

// ============== Auth API ==============

export async function signup(
  email: string,
  password: string,
  name?: string
): Promise<User> {
  return apiRequest<User>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export async function login(email: string, password: string): Promise<User> {
  return apiRequest<User>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

// ============== Integration API ==============

export async function connectIntegration(
  userId: number,
  serviceName: string,
  apiKey?: string,
  credentials?: Record<string, unknown>
): Promise<Integration> {
  return apiRequest<Integration>("/auth/connect", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      service_name: serviceName,
      api_key: apiKey,
      credentials,
    }),
  });
}

export async function listIntegrations(
  userId: number
): Promise<IntegrationList> {
  return apiRequest<IntegrationList>(`/auth/integrations/${userId}`);
}

export async function disconnectIntegration(
  userId: number,
  serviceName: string
): Promise<void> {
  return apiRequest<void>(`/auth/disconnect/${userId}/${serviceName}`, {
    method: "DELETE",
  });
}

// ============== Chat API ==============

export async function sendChatMessage(
  userId: number,
  message: string
): Promise<ChatResponse> {
  return apiRequest<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, message }),
  });
}

export async function getSupportedCommands(): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/api/supported-commands");
}

// ============== Health Check ==============

export async function healthCheck(): Promise<{
  status: string;
  service: string;
}> {
  return apiRequest<{ status: string; service: string }>("/health");
}
