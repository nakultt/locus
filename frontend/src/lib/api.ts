/**
 * API Client for Locus Backend
 * Handles all HTTP requests to the FastAPI backend
 */

// API Base URL - change this when deploying
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

// ============== Types ==============

export interface User {
  id: string;
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
  conversation_id?: number;
}

export interface Integration {
  id: string;
  provider: string;
}

export interface IntegrationList {
  integrations: Integration[];
  total: number;
}

export interface ApiError {
  detail: string;
  error_code?: string;
}

export interface Conversation {
  id: string;
  title: string;
  owner_id: string;
  created_at: string;
  updated_at?: string;
}

export interface ConversationList {
  conversations: Conversation[];
  total: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  actions_taken?: ActionResult[];
  created_at: string;
}

// ============== Helper Functions ==============

function getAuthToken(): string | null {
  // Check localStorage first (Remember Me was checked)
  const localUser = localStorage.getItem("locus_user");
  if (localUser) {
    try {
      const parsed = JSON.parse(localUser);
      return parsed.token || null;
    } catch {
      return null;
    }
  }
  
  // Check sessionStorage (Remember Me was not checked)
  const sessionUser = sessionStorage.getItem("locus_user");
  if (sessionUser) {
    try {
      const parsed = JSON.parse(sessionUser);
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
  return apiRequest<User>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export async function login(
  email: string, 
  password: string,
  rememberMe: boolean = false
): Promise<User> {
  return apiRequest<User>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, remember_me: rememberMe }),
  });
}

export interface UserUpdate {
  email?: string;
  password?: string;
  name?: string;
}

export async function updateUser(userId: string, data: UserUpdate): Promise<User> {
  return apiRequest<User>(`/auth/user/${userId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ============== Integration API ==============

export async function connectIntegration(
  userId: string,
  serviceName: string,
  apiKey?: string,
  credentials?: Record<string, unknown>
): Promise<Integration> {
  return apiRequest<Integration>(`/api/users/${userId}/integrations`, {
    method: "POST",
    body: JSON.stringify({
      user_id: String(userId),
      provider: serviceName,
      credentials_json: JSON.stringify(credentials || { api_key: apiKey }),
    }),
  });
}

export async function listIntegrations(
  userId: string
): Promise<IntegrationList> {
  const integrations = await apiRequest<Integration[]>(`/api/users/${userId}/integrations`);
  return { integrations, total: integrations.length };
}

export async function disconnectIntegration(
  userId: string,
  integrationId: string
): Promise<void> {
  return apiRequest<void>(`/api/users/${userId}/integrations/${integrationId}`, {
    method: "DELETE",
  });
}

// ============== Chat API ==============

export async function sendChatMessage(
  userId: string,
  message: string,
  smartMode: boolean = false,
  conversationId?: string
): Promise<ChatResponse> {
  return apiRequest<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      message,
      smart_mode: smartMode,
      conversation_id: conversationId,
    }),
  });
}

// ============== Conversations API ==============

export async function createConversation(
  userId: string,
  title?: string
): Promise<Conversation> {
  return apiRequest<Conversation>(`/api/users/${userId}/conversations`, {
    method: "POST",
    body: JSON.stringify({ title: title || "New Conversation" }),
  });
}

export async function getUserConversations(
  userId: string
): Promise<ConversationList> {
  const conversations = await apiRequest<Conversation[]>(`/api/users/${userId}/conversations`);
  return { conversations, total: conversations.length };
}

export async function getConversationMessages(
  userId: string,
  conversationId: string
): Promise<Message[]> {
  return apiRequest<Message[]>(`/api/users/${userId}/conversations/${conversationId}/messages`);
}

export async function updateConversationTitle(
  userId: string,
  conversationId: string,
  title: string
): Promise<Conversation> {
  return apiRequest<Conversation>(`/api/users/${userId}/conversations/${conversationId}`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(
  userId: string,
  conversationId: string
): Promise<void> {
  return apiRequest<void>(`/api/users/${userId}/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

// ============== Streaming Chat API ==============

export type TaskStatusType = "pending" | "in_progress" | "completed" | "failed";

export interface TaskUpdate {
  task_id: string;
  service: string;
  action: string;
  description: string;
  status: TaskStatusType;
  tool_name?: string;
  result?: string;
  error?: string;
  depends_on?: string[];
}

export interface TaskPlanData {
  tasks: TaskUpdate[];
  total: number;
  completed: number;
  failed: number;
  current_task_id?: string;
}

export interface StreamEvent {
  event_type:
    | "planning"
    | "plan"
    | "task_started"
    | "task_completed"
    | "task_failed"
    | "complete"
    | "error";
  data: {
    status?: string;
    message?: string;
    tasks?: TaskUpdate[];
    total?: number;
    completed?: number;
    failed?: number;
    task_id?: string;
    service?: string;
    action?: string;
    description?: string;
    result?: string;
    error?: string;
    actions_taken?: ActionResult[];
    total_tasks?: number;
    completed_tasks?: number;
    failed_tasks?: number;
    conversation_id?: string;
  };
}

/**
 * Stream chat messages with real-time task progress updates.
 * Uses Server-Sent Events (SSE) for live updates.
 *
 * @param userId - The user's ID
 * @param message - The chat message to send
 * @param onEvent - Callback for each SSE event
 * @param onError - Callback for errors
 * @param onComplete - Callback when stream completes
 * @param conversationId - Optional existing conversation ID
 * @returns Abort function to cancel the stream
 */
export function streamChatMessage(
  userId: string,
  message: string,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
  onComplete: () => void,
  conversationId?: string
): () => void {
  const abortController = new AbortController();

  const token = (() => {
    // Check localStorage first (Remember Me was checked)
    const localUser = localStorage.getItem("locus_user");
    if (localUser) {
      try {
        const parsed = JSON.parse(localUser);
        return parsed.token || null;
      } catch {
        return null;
      }
    }
    // Check sessionStorage (Remember Me was not checked)
    const sessionUser = sessionStorage.getItem("locus_user");
    if (sessionUser) {
      try {
        const parsed = JSON.parse(sessionUser);
        return parsed.token || null;
      } catch {
        return null;
      }
    }
    return null;
  })();

  fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ 
      user_id: userId, 
      message,
      conversation_id: conversationId 
    }),
    signal: abortController.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");

        // Keep the last incomplete line in the buffer
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              onEvent(data as StreamEvent);
            } catch (e) {
              console.error("Failed to parse SSE data:", e);
            }
          }
        }
      }

      onComplete();
    })
    .catch((error) => {
      if (error.name !== "AbortError") {
        onError(error);
      }
    });

  return () => abortController.abort();
}

export async function getSupportedCommands(): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/api/supported-commands");
}

// ============== Settings API ==============

export interface GeminiKeyStatus {
  has_key: boolean;
  message: string;
}

export async function setGeminiKey(
  userId: string,
  apiKey: string
): Promise<GeminiKeyStatus> {
  return apiRequest<GeminiKeyStatus>(`/api/users/${userId}/settings/gemini-key`, {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function checkGeminiKey(userId: string): Promise<GeminiKeyStatus> {
  return apiRequest<GeminiKeyStatus>(`/api/users/${userId}/settings`);
}

export async function deleteGeminiKey(
  userId: string
): Promise<GeminiKeyStatus> {
  return apiRequest<GeminiKeyStatus>(`/api/users/${userId}/settings/gemini-key`, {
    method: "DELETE",
  });
}

// ============== Health Check ==============

export async function healthCheck(): Promise<{
  status: string;
  service: string;
}> {
  return apiRequest<{ status: string; service: string }>("/health");
}
