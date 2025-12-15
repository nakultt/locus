export type MessageRole = "user" | "system" | "assistant";

export type MessageIntent =
  | "jira"
  | "slack"
  | "calendar"
  | "servicenow"
  | "github"
  | "generic";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  intent?: MessageIntent;
  meta?: {
    summary?: string;
    urgency?: "low" | "normal" | "high";
    actions?: Array<{
      id: string;
      label: string;
      type?: "primary" | "secondary";
    }>;
    tags?: string[];
  };
}


