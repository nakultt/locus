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
  conversation_id?: number;
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

export interface Conversation {
  id: number;
  title: string;
  owner_id: number;
  created_at: string;
  updated_at?: string;
}

export interface ConversationList {
  conversations: Conversation[];
  total: number;
}

export interface Message {
  id: number;
  conversation_id: number;
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
  return apiRequest<User>("/auth/signup", {
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

export async function updateUser(userId: number, data: UserUpdate): Promise<User> {
  return apiRequest<User>(`/auth/user/${userId}`, {
    method: "PUT",
    body: JSON.stringify(data),
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
  message: string,
  smartMode: boolean = false,
  conversationId?: number
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
  userId: number,
  title?: string
): Promise<Conversation> {
  return apiRequest<Conversation>("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, title }),
  });
}

export async function getUserConversations(
  userId: number
): Promise<ConversationList> {
  return apiRequest<ConversationList>(`/api/conversations/${userId}`);
}

export async function getConversationMessages(
  conversationId: number
): Promise<Message[]> {
  return apiRequest<Message[]>(`/api/conversations/${conversationId}/messages`);
}

export async function updateConversationTitle(
  conversationId: number,
  title: string
): Promise<Conversation> {
  return apiRequest<Conversation>(`/api/conversations/${conversationId}`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(
  conversationId: number
): Promise<void> {
  return apiRequest<void>(`/api/conversations/${conversationId}`, {
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
    conversation_id?: number;
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
  userId: number,
  message: string,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
  onComplete: () => void,
  conversationId?: number
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
  userId: number,
  apiKey: string
): Promise<GeminiKeyStatus> {
  return apiRequest<GeminiKeyStatus>("/api/settings/gemini-key", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, api_key: apiKey }),
  });
}

export async function checkGeminiKey(userId: number): Promise<GeminiKeyStatus> {
  return apiRequest<GeminiKeyStatus>(`/api/settings/gemini-key/${userId}`);
}

export async function deleteGeminiKey(
  userId: number
): Promise<GeminiKeyStatus> {
  return apiRequest<GeminiKeyStatus>(`/api/settings/gemini-key/${userId}`, {
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
