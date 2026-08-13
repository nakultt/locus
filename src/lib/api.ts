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
  timezone?: string;
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
    body: JSON.stringify({
      email,
      password,
      name,
      // Captured at signup so scheduling uses the user's own clock rather
      // than the server's. Falls back to IST server-side if unavailable.
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }),
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
  timezone?: string;
}

export async function updateUser(data: UserUpdate): Promise<User> {
  return apiRequest<User>("/auth/user", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ============== Integration API ==============

export async function connectIntegration(
  serviceName: string,
  apiKey?: string,
  credentials?: Record<string, unknown>
): Promise<Integration> {
  return apiRequest<Integration>("/auth/connect", {
    method: "POST",
    body: JSON.stringify({
      service_name: serviceName,
      api_key: apiKey,
      credentials,
    }),
  });
}

export async function listIntegrations(): Promise<IntegrationList> {
  return apiRequest<IntegrationList>("/auth/integrations");
}

export async function disconnectIntegration(
  serviceName: string
): Promise<void> {
  return apiRequest<void>(`/auth/disconnect/${serviceName}`, {
    method: "DELETE",
  });
}

// ============== Chat API ==============

export async function sendChatMessage(
  message: string,
  smartMode: boolean = false,
  conversationId?: number
): Promise<ChatResponse> {
  return apiRequest<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      smart_mode: smartMode,
      conversation_id: conversationId,
    }),
  });
}

// ============== Conversations API ==============

export async function createConversation(title?: string): Promise<Conversation> {
  return apiRequest<Conversation>("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function getUserConversations(): Promise<ConversationList> {
  return apiRequest<ConversationList>("/api/conversations");
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
 * @param message - The chat message to send
 * @param onEvent - Callback for each SSE event
 * @param onError - Callback for errors
 * @param onComplete - Callback when stream completes
 * @param conversationId - Optional existing conversation ID
 * @returns Abort function to cancel the stream
 */
export function streamChatMessage(
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
    body: JSON.stringify({ message, conversation_id: conversationId }),
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

/**
 * Status of the local model backend (MoE Model Manager).
 * Locus runs entirely on local models; there are no API keys to manage.
 */
export interface LLMStatus {
  available: boolean;
  message: string;
  provider?: string;
  base_url?: string;
  fast_model?: string;
  smart_model?: string;
}

export async function checkLLMStatus(): Promise<LLMStatus> {
  return apiRequest<LLMStatus>("/api/settings/llm");
}

// ============== PR Context Agent ==============

export type PRJobStatus = "queued" | "running" | "completed" | "failed";
export type SecuritySeverity = "critical" | "high" | "medium" | "low" | "info";
export type FindingSource = "semgrep" | "gitleaks" | "llm";

export interface SecurityFinding {
  source: FindingSource;
  severity: SecuritySeverity;
  title: string;
  file_path: string;
  line?: number;
  description: string;
  rule_id?: string;
}

export interface RelatedTicket {
  key: string;
  summary?: string;
  status?: string;
  assignee?: string;
  url?: string;
  source: string;
}

export interface RelatedSlackThread {
  channel: string;
  permalink?: string;
  message_count: number;
  summary?: string;
  participants: string[];
}

export interface LinkedIssue {
  number: number;
  title: string;
  state: string;
  url: string;
  author?: string;
  body?: string;
  /** "closes" for a real GitHub link, "mentions" for a bare #N reference. */
  relation: string;
}

export interface RelatedDocument {
  title: string;
  url: string;
  modified_at?: string;
  excerpt: string;
  truncated: boolean;
}

export interface PRContext {
  repo: string;
  pr_number: number;
  title: string;
  author: string;
  url: string;
  branch?: string;
  ticket_keys: string[];
  tickets: RelatedTicket[];
  linked_issues: LinkedIssue[];
  slack_threads: RelatedSlackThread[];
  documents: RelatedDocument[];
  files_changed: number;
  additions: number;
  deletions: number;
}

export interface PRAnalysisResult {
  context: PRContext;
  /** Scanner-matched. Reported as fact. */
  confirmed_findings: SecurityFinding[];
  /** Model-generated. Must never be presented as confirmed. */
  unverified_findings: SecurityFinding[];
  summary: string;
  pr_comment_posted: boolean;
  slack_posted: boolean;
  doc_url?: string;
  tool_calls: ToolInvocation[];
  stages: PipelineStage[];
  merge_actions?: MergeActionResult;
  errors: string[];
}

export interface PRJob {
  id: number;
  status: PRJobStatus;
  repo: string;
  pr_number: number;
  action?: string;
  created_at: string;
  completed_at?: string;
  error?: string;
  /** Present on the list response so rows show progress without expanding. */
  stages: PipelineStage[];
}

export interface PRJobDetail extends PRJob {
  result?: PRAnalysisResult;
}

export interface RepoRegistration {
  id: number;
  repo: string;
  slack_channel?: string;
  export_to_docs?: boolean;
  context_docs?: string[];
  qa_emails?: string[];
  jira_done_status?: string;
  close_issues_on_merge?: boolean;
  enabled: boolean;
  /** Returned only when registering. */
  webhook_url?: string;
  /** Shown once at creation; never retrievable afterwards. */
  webhook_secret?: string;
}

export interface CapabilityStatus {
  key: string;
  label: string;
  available: boolean;
  required: boolean;
  hint: string;
}

export interface ServiceStatus {
  key: string;
  label: string;
  connected: boolean;
  required: boolean;
  capabilities: CapabilityStatus[];
}

export interface ToolInvocation {
  service: string;
  tool: string;
  query?: string;
  result_count: number;
  succeeded: boolean;
  detail?: string;
  duration_ms?: number;
}

export type StageState = "pending" | "running" | "done" | "skipped" | "failed";

export interface PipelineStage {
  key: string;
  label: string;
  /** "read" gathers context; "write" changes something outside Locus. */
  kind: string;
  state: StageState;
  detail?: string;
}

export interface MergeActionResult {
  jira_transitioned: string[];
  issues_closed: string[];
  qa_notified: boolean;
  qa_brief?: string;
  errors: string[];
}

export interface PRAgentSummary {
  total_jobs: number;
  completed: number;
  failed: number;
  running: number;
  queued: number;
  repos_registered: number;
  confirmed_findings: number;
  unverified_findings: number;
  github_connected: boolean;
  jira_connected: boolean;
  slack_connected: boolean;
  slack_search_enabled: boolean;
  semgrep_available: boolean;
  gitleaks_available: boolean;
  docs_connected?: boolean;
  services?: ServiceStatus[];
  public_base_url?: string;
}

export async function getPRAgentSummary(): Promise<PRAgentSummary> {
  return apiRequest<PRAgentSummary>("/webhooks/summary");
}

export async function listPRJobs(limit = 20): Promise<PRJob[]> {
  return apiRequest<PRJob[]>(`/webhooks/jobs?limit=${limit}`);
}

export async function getPRJob(jobId: number): Promise<PRJobDetail> {
  return apiRequest<PRJobDetail>(`/webhooks/jobs/${jobId}`);
}

export async function listRepos(): Promise<{
  repos: RepoRegistration[];
  total: number;
}> {
  return apiRequest("/webhooks/repos");
}

export async function registerRepo(
  repo: string,
  slackChannel?: string,
  exportToDocs = false,
  contextDocs: string[] = [],
  qaEmails: string[] = [],
  jiraDoneStatus = "Done",
  closeIssuesOnMerge = true
): Promise<RepoRegistration> {
  return apiRequest<RepoRegistration>("/webhooks/repos", {
    method: "POST",
    body: JSON.stringify({
      repo,
      slack_channel: slackChannel || null,
      export_to_docs: exportToDocs,
      context_docs: contextDocs,
      qa_emails: qaEmails,
      jira_done_status: jiraDoneStatus,
      close_issues_on_merge: closeIssuesOnMerge,
    }),
  });
}

export async function unregisterRepo(repo: string): Promise<void> {
  return apiRequest<void>(`/webhooks/repos/${repo}`, {
    method: "DELETE",
  });
}

export async function analyzePR(repo: string, prNumber: number): Promise<PRJob> {
  return apiRequest<PRJob>(`/webhooks/analyze/${repo}/${prNumber}`, {
    method: "POST",
  });
}

// ============== Adaptive Scheduler ==============

export type EventClass = "hard_fixed" | "soft_fixed" | "flexible";

export interface ScheduleMove {
  event_id: string;
  title: string;
  from_start?: string;
  to_start: string;
  duration_minutes: number;
  event_class: EventClass;
  attendee_count: number;
  reason: string;
}

export interface ScheduleProposal {
  trigger: string;
  timezone: string;
  moves: ScheduleMove[];
  additions: ScheduleMove[];
  /** Conflicts the solver could not resolve, and why. */
  blocked: string[];
  summary: string;
}

export interface CalendarConflict {
  first: { title: string; start: string; id: string };
  second: { title: string; start: string; id: string };
}

export async function getScheduleConflicts(days = 14): Promise<{
  total_events: number;
  conflicts: CalendarConflict[];
  total_conflicts: number;
}> {
  return apiRequest(`/api/schedule/conflicts?days=${days}`);
}

export async function planSchedule(
  title: string,
  start: string,
  durationMinutes = 60,
  attendees = 1
): Promise<ScheduleProposal> {
  return apiRequest<ScheduleProposal>("/api/schedule/plan", {
    method: "POST",
    body: JSON.stringify({
      title,
      start,
      duration_minutes: durationMinutes,
      attendees,
    }),
  });
}

/** Applies a plan the user has reviewed. Planning never writes. */
export async function applySchedule(
  moves: ScheduleMove[],
  additions: ScheduleMove[] = []
): Promise<{ applied: string[]; failed: string[] }> {
  return apiRequest("/api/schedule/apply", {
    method: "POST",
    body: JSON.stringify({ moves, additions }),
  });
}

// ============== Health Check ==============

export async function healthCheck(): Promise<{
  status: string;
  service: string;
}> {
  return apiRequest<{ status: string; service: string }>("/health");
}
