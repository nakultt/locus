"use client";

/**
 * API Client for Locus Backend
 * Handles all HTTP requests to the FastAPI backend
 */

// API Base URL - change this when deploying
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

const STORAGE_KEY = "locus_user";
const REMEMBER_KEY = "locus_remember";

/**
 * A request the backend rejected for identity reasons -- a missing, invalid,
 * or expired token, or one naming an account that no longer exists.
 *
 * Distinguished from an ordinary Error so callers can tell "you are not signed
 * in" apart from "the server failed". A plain Error carrying only the detail
 * string could not be told apart without matching on prose.
 */
export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

/**
 * Notified whenever a request is rejected for identity reasons.
 *
 * Clearing storage is not enough on its own: AuthContext holds the user in
 * React state, and a component tree already rendered stays "signed in" until
 * something tells it otherwise. This is that signal.
 */
type SessionExpiredHandler = () => void;

let sessionExpiredHandler: SessionExpiredHandler | null = null;

export function onSessionExpired(handler: SessionExpiredHandler): () => void {
  sessionExpiredHandler = handler;
  return () => {
    if (sessionExpiredHandler === handler) sessionExpiredHandler = null;
  };
}

/**
 * Drop the stored session from both storages and notify the app.
 *
 * Lives here rather than in AuthContext because the API layer is where a dead
 * session is discovered, and it must be cleared before the next request reuses
 * the same token.
 */
export function clearStoredSession(): void {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(REMEMBER_KEY);
  sessionStorage.removeItem(STORAGE_KEY);
  sessionExpiredHandler?.();
}

export function getAuthToken(): string | null {
  // Check localStorage first (Remember Me was checked), then sessionStorage
  // (Remember Me was not). A malformed entry is treated as no token.
  for (const store of [localStorage, sessionStorage]) {
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) continue;
    try {
      return JSON.parse(raw).token || null;
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

    // A 401 means the stored session is no longer usable -- expired, invalid,
    // or naming a deleted account. Clear it here rather than leaving it for a
    // caller to notice: every subsequent request would otherwise resend the
    // same dead token and fail identically, leaving the UI stuck signed in.
    if (response.status === 401) {
      clearStoredSession();
      throw new AuthError(error.detail);
    }

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

  const token = getAuthToken();

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
        // Same rule as apiRequest: a dead session is cleared where it is
        // found, so the next request does not resend the same token.
        if (response.status === 401) {
          clearStoredSession();
          throw new AuthError("Your session has expired. Please sign in again.");
        }
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
 * One backend Locus can be pointed at, and whether it is ready to use.
 * The key itself is never sent to the browser — only whether one is set.
 */
export interface LLMProviderOption {
  id: string;
  label: string;
  is_local: boolean;
  active: boolean;
  api_key_env: string;
  api_key_configured: boolean;
  fast_model: string;
  smart_model: string;
}

/**
 * Status of the configured model backend.
 *
 * Locus defaults to the local MoE Model Manager. `LLM_PROVIDER` on the backend
 * points it at OpenAI, Anthropic or Gemini instead, which changes where the
 * code the analysis passes read is sent — so the status names the active
 * provider rather than assuming local.
 */
export interface LLMStatus {
  available: boolean;
  message: string;
  provider?: string;
  is_local?: boolean;
  base_url?: string;
  fast_model?: string;
  smart_model?: string;
  api_key_env?: string | null;
  api_key_configured?: boolean;
  providers?: LLMProviderOption[];
}

export async function checkLLMStatus(): Promise<LLMStatus> {
  return apiRequest<LLMStatus>("/api/settings/llm");
}

/**
 * Whether each integration is actually working.
 *
 * The background loops swallow their own failures so one dead integration
 * cannot stop the others. This is where that silence surfaces — a Gmail token
 * that expired days ago otherwise shows up only as QA replies no longer
 * arriving, which reads as nobody replying.
 *
 * Only services with a recorded attempt appear; one never called is absent
 * rather than reported healthy.
 */
export interface IntegrationHealthEntry {
  service: string;
  healthy: boolean;
  consecutive_failures: number;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
}

export async function fetchIntegrationHealth(): Promise<IntegrationHealthEntry[]> {
  return apiRequest<IntegrationHealthEntry[]>("/api/settings/integration-health");
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
  /** Non-security review findings, P1 first. */
  review_findings: ReviewFinding[];
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
  /** The searches behind those stages, so a count can be checked against them. */
  tool_calls?: ToolInvocation[];
}

export interface PRJobDetail extends PRJob {
  result?: PRAnalysisResult;
}

export interface RepoRegistration extends Partial<AuthoringSettings> {
  id: number;
  repo: string;
  slack_channel?: string;
  export_to_docs?: boolean;
  context_docs?: string[];
  qa_emails?: string[];
  jira_done_status?: string;
  close_issues_on_merge?: boolean;
  /** Hold the ticket and issues open until the testing team signs off. */
  close_on_qa_signoff?: boolean;
  /** GitHub logins expected to review this repo. */
  reviewers?: string[];
  /** "login, @slack, email" per line. */
  reviewer_contacts?: string | null;
  /** Review pings go here; falls back to slack_channel when unset. */
  review_slack_channel?: string | null;
  /** Merge automatically once approved and the gate passes. Off by default. */
  auto_merge_on_approval?: boolean;
  merge_method?: MergeMethod;
  /**
   * Move each linked issue's GitHub Projects card as the pipeline advances.
   *
   * On by default, unlike auto-merge: this writes a status field on a card
   * rather than to a branch, and never moves a card backwards.
   */
  project_board_sync?: boolean;
  /** "stage: column" per line. Blank uses the default map. */
  project_column_map?: string | null;
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

export type ReviewPriority = "p1" | "p2" | "p3";

export interface ReviewFinding {
  priority: ReviewPriority;
  title: string;
  file_path: string;
  line?: number;
  description: string;
  category: string;
}

export interface ToolInvocation {
  service: string;
  tool: string;
  query?: string;
  result_count: number;
  succeeded: boolean;
  detail?: string;
  duration_ms?: number;
  /** What the search matched, so a count can be sanity-checked. */
  matches: string[];
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
  /**
   * Project board cards moved, one line per issue.
   *
   * Empty when the issue is on no board or the card was already in place —
   * a line on every push saying "already in In progress" would train people
   * to skip the section.
   */
  board_moves?: string[];
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

/** Where a PR sits in the senior-dev loop. Only `approved` clears the gate. */
export type ReviewState =
  | "awaiting_review"
  | "changes_requested"
  | "approved"
  | "merged";

export type ReviewOutcome =
  | "review_requested"
  | "approved"
  | "changes_requested"
  | "commented"
  | "resubmitted";

export interface ReviewRound {
  round_number: number;
  outcome: ReviewOutcome;
  reviewer?: string | null;
  /** The reviewer's own words. Canonical; the checklist is derived from it. */
  body?: string | null;
  head_sha?: string | null;
  created_at?: string | null;
}

export interface PRReviewSummary {
  id: number;
  repo: string;
  pr_number: number;
  pr_url?: string | null;
  pr_title?: string | null;
  author?: string | null;
  state: ReviewState;
  /** Increments on each changes-requested -> re-review cycle. Starts at 1. */
  round_number: number;
  last_reviewer?: string | null;
  updated_at?: string | null;
}

export interface PRReviewDetail extends PRReviewSummary {
  pending_asks: string[];
  rounds: ReviewRound[];
}

export interface PRReviewList {
  reviews: PRReviewSummary[];
  total: number;
  awaiting_review: number;
  changes_requested: number;
  approved: number;
}

/** Merged PRs are excluded unless asked for: the loop is over for them. */
export async function listReviews(includeMerged = false): Promise<PRReviewList> {
  return apiRequest<PRReviewList>(
    `/webhooks/reviews?include_merged=${includeMerged}`
  );
}

/** Which loop a message belongs to. "context" is the pre-review gathering pass. */
export type CommLoop = "review" | "qa" | "context";
export type CommDirection = "searched" | "sent" | "received";
export type CommChannel = "slack" | "email" | "github";

export interface CommunicationEvent {
  id: number;
  loop: CommLoop;
  direction: CommDirection;
  channel: CommChannel;
  participant?: string | null;
  target?: string | null;
  subject?: string | null;
  /** The message itself, verbatim. */
  body?: string | null;
  /** What was searched for. Present when direction is "searched". */
  query?: string | null;
  permalink?: string | null;
  outcome?: string | null;
  succeeded: boolean;
  created_at?: string | null;
  /**
   * Found on a sibling PR for the same work item and reused as context here,
   * rather than found on this PR. Shown either way — the reviewer was given
   * it — but labelled, so it does not read as discussion about this PR.
   */
  inherited?: boolean;
}

export interface ReviewerContact {
  login: string;
  slack?: string | null;
  email?: string | null;
}

export interface PRActivity {
  repo: string;
  pr_number: number;
  pr_url?: string | null;
  pr_title?: string | null;
  review?: PRReviewDetail | null;
  reviewer_contacts: ReviewerContact[];
  qa_notified: boolean;
  qa_resolved?: boolean | null;
  qa_channel?: string | null;
  qa_recipients: string[];
  events: CommunicationEvent[];
}

export type WorklistKind =
  | "changes_requested"
  | "qa_rejected"
  | "qa_unanswered"
  | "approved_not_merged"
  | "delivery_failed"
  | "awaiting_review";

export interface WorklistItem {
  kind: WorklistKind;
  blocked_on_you: boolean;
  repo: string;
  pr_number: number;
  pr_url?: string | null;
  headline: string;
  /** Model-written checklist — for scanning. */
  detail: string[];
  /** The asker's own words — what someone actually acts on. */
  quotes: string[];
  actor?: string | null;
  age_hours: number;
  round_number: number;
  /** A person asked, rather than a model producing a finding. */
  from_human: boolean;
}

export interface WorklistTask {
  key: string;
  repo: string;
  title?: string | null;
  pull_requests: number[];
  items: WorklistItem[];
  needs_you: boolean;
  age_hours: number;
  round_number: number;
}

export interface Worklist {
  needs_you: WorklistTask[];
  waiting_on_others: WorklistTask[];
  total_needs_you: number;
}

/** Ordered server-side, so the UI cannot disagree about what is most urgent. */
export async function getWorklist(): Promise<Worklist> {
  return apiRequest<Worklist>("/webhooks/worklist");
}

/** Both loops and the full message traffic for one PR, in one request. */
export async function getPRActivity(
  repo: string,
  prNumber: number
): Promise<PRActivity> {
  return apiRequest<PRActivity>(`/webhooks/activity/${repo}/${prNumber}`);
}

export async function getReview(
  repo: string,
  prNumber: number
): Promise<PRReviewDetail> {
  return apiRequest<PRReviewDetail>(`/webhooks/reviews/${repo}/${prNumber}`);
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

/**
 * What a repo registration says, as an options object.
 *
 * This was fifteen positional arguments, which is unreadable at the call site
 * and silently reorderable. The authoring dial would have made it eighteen.
 */
export interface RegisterRepoOptions {
  repo: string;
  slackChannel?: string;
  exportToDocs?: boolean;
  contextDocs?: string[];
  qaEmails?: string[];
  jiraDoneStatus?: string;
  closeIssuesOnMerge?: boolean;
  closeOnQaSignoff?: boolean;
  reviewers?: string[];
  reviewerContacts?: string;
  reviewSlackChannel?: string;
  autoMergeOnApproval?: boolean;
  mergeMethod?: MergeMethod;
  projectBoardSync?: boolean;
  projectColumnMap?: string;
  /** Who writes the code for this repo's tickets. */
  authoringMode?: AuthoringMode;
  /** The first attempt plus this many reworks. */
  autonomousMaxRounds?: number;
  presetLabel?: string;
  /** Where this repo is checked out locally; blank falls back to LOCUS_CODE_ROOT. */
  sourcePath?: string;
  /** Run once in the fresh worktree before the agent. */
  prepareCommand?: string;
  /** The authoring test gate; blank means no gate. */
  testCommand?: string;
}

export async function registerRepo(
  options: RegisterRepoOptions
): Promise<RepoRegistration> {
  return apiRequest<RepoRegistration>("/webhooks/repos", {
    method: "POST",
    body: JSON.stringify({
      repo: options.repo,
      slack_channel: options.slackChannel || null,
      export_to_docs: options.exportToDocs ?? false,
      context_docs: options.contextDocs ?? [],
      qa_emails: options.qaEmails ?? [],
      jira_done_status: options.jiraDoneStatus || "Done",
      close_issues_on_merge: options.closeIssuesOnMerge ?? true,
      close_on_qa_signoff: options.closeOnQaSignoff ?? false,
      reviewers: options.reviewers ?? [],
      reviewer_contacts: options.reviewerContacts || null,
      review_slack_channel: options.reviewSlackChannel || null,
      auto_merge_on_approval: options.autoMergeOnApproval ?? false,
      merge_method: options.mergeMethod ?? "squash",
      project_board_sync: options.projectBoardSync ?? true,
      project_column_map: options.projectColumnMap || null,
      authoring_mode: options.authoringMode ?? "assisted",
      autonomous_max_rounds: options.autonomousMaxRounds ?? 2,
      preset_label: options.presetLabel || null,
      source_path: options.sourcePath || null,
      prepare_command: options.prepareCommand || null,
      test_command: options.testCommand || null,
    }),
  });
}

export type MergeMethod = "squash" | "merge" | "rebase";

/**
 * Who writes the code for a work item.
 *
 * `assisted` is a person. `autonomous` hands the ticket to the authoring
 * driver, whose model is remote — the brief leaves the machine, unlike every
 * model that reads your code automatically.
 */
export type AuthoringMode = "assisted" | "autonomous";

/** The authoring dials, shared by the repo registration and the defaults. */
export interface AuthoringSettings {
  authoring_mode: AuthoringMode;
  autonomous_max_rounds: number;
  /** Display only; the backend resolver decides what a run does. */
  preset_label?: string | null;
  source_path?: string | null;
  prepare_command?: string | null;
  test_command?: string | null;
}

export interface PRAgentDefaults extends AuthoringSettings {
  slack_channel?: string | null;
  export_to_docs: boolean;
  qa_emails: string[];
  jira_done_status: string;
  close_issues_on_merge: boolean;
  close_on_qa_signoff: boolean;
  reviewers: string[];
  reviewer_contacts?: string | null;
  review_slack_channel?: string | null;
  auto_merge_on_approval: boolean;
  merge_method: MergeMethod;
  /** Keep GitHub Projects cards in step with the pipeline, for every repo. */
  project_board_sync: boolean;
  /** Default stage-to-column map, one "stage: column" per line. */
  project_column_map?: string | null;
  /**
   * Google Docs read on every run, for every repo.
   *
   * These accumulate with a repo's own rather than being overridden by them:
   * a repo that pins its own spec should still be reviewed against the
   * organisation's standards.
   */
  context_docs: string[];
}

export interface AuthoringPreset {
  name: string;
  label: string;
  description: string;
  /**
   * The dials this preset writes into form state.
   *
   * Applied at write time only. The backend resolver never reads a preset —
   * expanding one at read time would be a second resolution layer above it.
   */
  values: Partial<PRAgentDefaults>;
}

/** Named starting points for the authoring dials, from the backend's one dict. */
export async function getAuthoringPresets(): Promise<AuthoringPreset[]> {
  const body = await apiRequest<{ presets: AuthoringPreset[] }>(
    "/webhooks/presets"
  );
  return body.presets;
}

/**
 * Whether saved settings still match the preset they name.
 *
 * Mirrors `presets.matches` on the backend: only the keys the preset states
 * are compared, so a repo that set a Slack channel has not thereby modified
 * the preset.
 */
export function matchesPreset(
  preset: AuthoringPreset,
  values: Partial<PRAgentDefaults>
): boolean {
  return (Object.keys(preset.values) as (keyof PRAgentDefaults)[]).every(
    (key) => values[key] === preset.values[key]
  );
}

/** Account-wide fallbacks used by any repo that does not set its own. */
export async function getPRAgentDefaults(): Promise<PRAgentDefaults> {
  return apiRequest<PRAgentDefaults>("/webhooks/defaults");
}

export async function savePRAgentDefaults(
  defaults: PRAgentDefaults
): Promise<PRAgentDefaults> {
  return apiRequest<PRAgentDefaults>("/webhooks/defaults", {
    method: "PUT",
    body: JSON.stringify(defaults),
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

// --- Task board -----------------------------------------------------------

export type TaskSource = "github" | "jira";

/**
 * Where a task sits in the automated pipeline.
 *
 * Everything between `assigned` and `done` is automated except the coding, so
 * a stage not yet reached says where the work is -- not what Locus skipped.
 */
export type TaskStage =
  | "assigned"
  /** The authoring agent is writing, or has written, the first draft. */
  | "authoring"
  | "branch_created"
  | "in_progress"
  | "analyzed"
  | "in_review"
  | "changes_requested"
  | "approved"
  | "merged"
  | "testing"
  | "done";

export interface TaskStageStatus {
  stage: TaskStage;
  label: string;
  state: StageState;
  detail?: string | null;
}

/**
 * A branch linked to an issue through GitHub's Development panel.
 *
 * Only affirmative links appear -- the "create a branch" button or the
 * `createLinkedBranch` mutation. A branch that merely names the issue is not
 * one of these and is not shown as one.
 */
export interface LinkedBranch {
  name: string;
  repo?: string | null;
}

export interface TaskPullRequest {
  repo: string;
  pr_number: number;
  url?: string | null;
  title?: string | null;
  author?: string | null;
  review_state?: ReviewState | null;
  round_number: number;
  last_reviewer?: string | null;
}

export interface TaskCard {
  key: string;
  source: TaskSource;
  title: string;
  url: string;
  status?: string | null;
  assignee?: string | null;
  issue_type?: string | null;
  priority?: string | null;
  updated_at?: string | null;

  /** The requirement as whoever filed it stated it. */
  description?: string | null;

  stage: TaskStage;
  stages: TaskStageStatus[];
  pull_requests: TaskPullRequest[];

  /**
   * Branches linked in GitHub's Development panel. The only evidence work has
   * started before a pull request exists -- without it the card reads as
   * untouched while someone is actively writing the code.
   */
  linked_branches: LinkedBranch[];

  /**
   * The work item's written record, when one exists.
   *
   * This is the link handed to the senior dev and the testing team, so it is
   * on the card rather than only in the detail response -- it is the thing
   * someone opens the board to fetch. Null until a document exists; the board
   * never creates one.
   */
  doc_url?: string | null;

  items: WorklistItem[];
  needs_you: boolean;
  blocked_reason?: string | null;
  age_hours: number;
  round_number: number;

  /**
   * Who writes the code for this work item, resolved by the backend through
   * the same chain a run would use — so the chip and the run cannot disagree.
   */
  authoring_mode: AuthoringMode;
  /** "work_item", "repo", "defaults", "unset", or "handed_back". */
  authoring_source: string;
  /**
   * Handed back after the bound ran out, or because a human took the branch
   * over. Styled as attention rather than error: it is the mode working.
   */
  handed_back: boolean;
  handed_back_reason?: string | null;
  authoring_attempts: number;
}

/** The authoring mode a run on one work item would use, and where it came from. */
export interface WorkItemMode {
  task_key: string;
  authoring_mode: AuthoringMode;
  autonomous_max_rounds: number;
  source: string;
  rounds_source: string;
  override?: AuthoringMode | null;
  handed_back: boolean;
  handed_back_reason?: string | null;
  handed_back_at?: string | null;
  preset_label?: string | null;
}

/** One recorded run of the authoring driver, opened or not. */
export interface AuthoringAttempt {
  id: number;
  ticket_key: string;
  repo?: string | null;
  pr_number?: number | null;
  attempt: number;
  /** initial | changes_requested | qa_rejected */
  trigger: string;
  driver: string;
  model?: string | null;
  context_mode?: string | null;
  opened: boolean;
  error?: string | null;
  files_changed: number;
  lines_changed: number;
  duration_seconds: number;
  created_at?: string | null;
}

export interface AuthoringRun {
  ticket_key: string;
  opened: boolean;
  pr_number?: number | null;
  pr_url?: string | null;
  branch?: string | null;
  attempt: number;
  attempts_remaining: number;
  driver: string;
  model?: string | null;
  files_changed: number;
  lines_changed: number;
  error?: string | null;
  handed_back_reason?: string | null;
}

export async function getTaskMode(taskKey: string): Promise<WorkItemMode> {
  return apiRequest<WorkItemMode>(
    `/tasks/mode?task_key=${encodeURIComponent(taskKey)}`
  );
}

/**
 * Override the mode for one work item. A null mode clears the override and
 * inherits again — absence means "inherit", where a stored null would read as
 * a deliberate choice.
 */
export async function setTaskMode(
  taskKey: string,
  authoringMode: AuthoringMode | null,
  autonomousMaxRounds?: number | null
): Promise<WorkItemMode> {
  return apiRequest<WorkItemMode>(
    `/tasks/mode?task_key=${encodeURIComponent(taskKey)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        authoring_mode: authoringMode,
        autonomous_max_rounds: autonomousMaxRounds ?? null,
      }),
    }
  );
}

export async function getTaskAttempts(
  taskKey: string
): Promise<AuthoringAttempt[]> {
  return apiRequest<AuthoringAttempt[]>(
    `/tasks/attempts?task_key=${encodeURIComponent(taskKey)}`
  );
}

/** Hand this work item to the authoring agent. The board's second write. */
export async function authorTask(taskKey: string): Promise<AuthoringRun> {
  return apiRequest<AuthoringRun>(
    `/tasks/author?task_key=${encodeURIComponent(taskKey)}`,
    { method: "POST" }
  );
}

export interface TaskBoard {
  needs_you: TaskCard[];
  in_flight: TaskCard[];
  /** Finished in the last week. A record, not a queue — never acted on. */
  recently_done: TaskCard[];
  /** Open work only, so the count does not grow every time something ships. */
  total: number;
  github_available: boolean;
  jira_available: boolean;
  unavailable: string[];
}

export interface TaskDetail {
  card: TaskCard;
  analysis?: PRAnalysisResult | null;
  job_status?: string | null;
  job_error?: string | null;
  reviews: PRReviewDetail[];
  reviewer_contacts: ReviewerContact[];
  qa_notified: boolean;
  qa_resolved?: boolean | null;
  qa_channel?: string | null;
  qa_recipients: string[];
  events: CommunicationEvent[];

  /** The task's report document. Null when Google Docs is not connected. */
  doc_url?: string | null;
}

/**
 * Every task assigned to you, ordered by what is waiting on you.
 *
 * The assigned half is cached server-side for a minute, so a polling
 * dashboard does not burn a GitHub rate limit. Pass `refresh` after an action
 * that should change a card's position.
 */
export async function getTaskBoard(refresh = false): Promise<TaskBoard> {
  return apiRequest<TaskBoard>(`/tasks${refresh ? "?refresh=true" : ""}`);
}

/**
 * One task's whole pipeline: analysis, review rounds, and every message.
 *
 * The key goes in a query parameter because it legitimately contains "/" and
 * "#" -- `acme/api#42` in a path segment would need double-escaping.
 */
export async function getTaskDetail(taskKey: string): Promise<TaskDetail> {
  return apiRequest<TaskDetail>(
    `/tasks/detail?task_key=${encodeURIComponent(taskKey)}`
  );
}

/** Re-run the analysis on the task's most recent pull request. */
export async function analyzeTask(taskKey: string): Promise<PRJob> {
  return apiRequest<PRJob>(
    `/tasks/analyze?task_key=${encodeURIComponent(taskKey)}`,
    { method: "POST" }
  );
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

/**
 * Whether you can be reached, and until when.
 *
 * Carries a state and a time and nothing else — no title, no attendee, no
 * location. The type is the enforcement: this same value is what the Slack
 * busy reply is built from, and it is posted into a channel other people read.
 */
export interface Availability {
  state: "free" | "busy" | "focus" | "off_hours";
  until?: string | null;
  next_free?: string | null;
}

export interface InterruptionEntry {
  id: number;
  occurred_at?: string | null;
  channel: string;
  participant?: string | null;
  slack_channel?: string | null;
  availability_state: string;
  importance: string;
  /** reviewer | worklist | classifier — the third is the only model-made claim. */
  importance_source: string;
  replied: boolean;
  reply_body?: string | null;
  excerpt?: string | null;
}

/** The same value the Slack reply uses, so the channel and the UI agree. */
export async function getAvailability(): Promise<Availability> {
  return apiRequest<Availability>("/api/schedule/availability");
}

export async function getInterruptions(): Promise<InterruptionEntry[]> {
  return apiRequest<InterruptionEntry[]>("/api/schedule/interruptions");
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
