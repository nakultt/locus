/**
 * What can be connected, and what each connection buys.
 *
 * Split out of the view so the catalogue is data rather than JSX. The
 * `description` fields used to be marketing lines — "All-in-one workspace for
 * notes and projects" — which describe the third party rather than what Locus
 * does once it is connected. Someone on this page is deciding whether to hand
 * over a token; the useful sentence is what stops working without it.
 */

export type AuthKind = "api_key" | "oauth";

export interface CatalogField {
  name: string;
  label: string;
  placeholder: string;
  /** Stored under `credentials` rather than as the top-level api_key. */
  isCredential?: boolean;
  optional?: boolean;
  help?: string;
  /** Rendered as a password field — a token pasted in the clear is shoulder-surfable. */
  secret?: boolean;
}

export interface CatalogEntry {
  id: string;
  title: string;
  /** What Locus does with it. */
  description: string;
  logo: string;
  authType: AuthKind;
  oauthProvider?: "google" | "linear";
  fields: CatalogField[];
  /** The pipeline cannot run at all without these. */
  required?: boolean;
}

export interface CatalogGroup {
  id: string;
  title: string;
  description: string;
  /** One OAuth consent covers the whole group, so the group carries the action. */
  sharedOAuth?: "google";
  entries: CatalogEntry[];
}

export const CATALOG: CatalogGroup[] = [
  {
    id: "core",
    title: "Code and tickets",
    description:
      "Where the work is defined and where the change lands. GitHub is the one thing the pipeline cannot run without.",
    entries: [
      {
        id: "github",
        title: "GitHub",
        description:
          "Reads pull requests, diffs and linked issues; posts the analysis comment, requests reviews and merges when the gate allows it.",
        logo: "/github.svg",
        authType: "api_key",
        required: true,
        fields: [
          {
            name: "api_key",
            label: "Personal access token",
            placeholder: "ghp_…",
            secret: true,
            help: "Needs `repo`. Add `project` as well if you want Projects cards to move — `repo` does not include it.",
          },
        ],
      },
      {
        id: "jira",
        title: "Jira",
        description:
          "Reads the ticket behind a branch and transitions it on merge. Transitions are forward-only.",
        logo: "/jira.svg",
        authType: "api_key",
        fields: [
          {
            name: "api_key",
            label: "API token",
            placeholder: "Your Atlassian API token",
            secret: true,
          },
          {
            name: "email",
            label: "Account email",
            placeholder: "you@company.com",
            isCredential: true,
          },
          {
            name: "url",
            label: "Site URL",
            placeholder: "https://company.atlassian.net",
            isCredential: true,
          },
          {
            name: "default_project_key",
            label: "Default project key",
            placeholder: "KAN",
            isCredential: true,
            optional: true,
            help: "Where new tickets go when you don't name a project. Without it the assistant has to look your projects up first.",
          },
        ],
      },
      {
        id: "linear",
        title: "Linear",
        description: "An alternative to Jira for reading and updating work items.",
        logo: "/linear.svg",
        authType: "oauth",
        oauthProvider: "linear",
        fields: [],
      },
    ],
  },
  {
    id: "comms",
    title: "Conversation",
    description:
      "Where the requirement was actually agreed, and where the pipeline reports back.",
    entries: [
      {
        id: "slack",
        title: "Slack",
        description:
          "Searches history for the discussion behind a change, posts summaries and review requests, and runs the QA thread.",
        logo: "/slack.svg",
        authType: "api_key",
        fields: [
          {
            name: "api_key",
            label: "Bot token",
            placeholder: "xoxb-…",
            secret: true,
            help: "Posts messages.",
          },
          {
            name: "user_token",
            label: "User token",
            placeholder: "xoxp-…",
            isCredential: true,
            optional: true,
            secret: true,
            help: "Searching history needs this. A bot token cannot call search.messages, and without it the analysis silently loses its best source of requirement context.",
          },
        ],
      },
      {
        id: "notion",
        title: "Notion",
        description: "Reads pages as additional written context for a review.",
        logo: "/notion.png",
        authType: "api_key",
        fields: [
          {
            name: "api_key",
            label: "Integration token",
            placeholder: "secret_…",
            secret: true,
          },
        ],
      },
    ],
  },
  {
    id: "google",
    title: "Google Workspace",
    description:
      "One consent screen grants every scope below, so connecting once lights all of them up.",
    sharedOAuth: "google",
    entries: [
      {
        id: "gmail",
        title: "Gmail",
        description: "Sends the QA brief and polls for the tester's reply.",
        logo: "/gmail.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "calendar",
        title: "Calendar",
        description:
          "Reads your primary calendar for conflicts, availability and focus blocks.",
        logo: "/calendar.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "docs",
        title: "Docs",
        description:
          "Reads your standards documents, and writes the full report — one document per work item, rewritten in place.",
        logo: "/docs.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "drive",
        title: "Drive",
        description: "Finds the documents related to a change.",
        logo: "/drive.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "sheets",
        title: "Sheets",
        description: "Reads and writes spreadsheets from chat.",
        logo: "/sheets.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "slides",
        title: "Slides",
        description: "Builds and edits presentations from chat.",
        logo: "/slides.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "forms",
        title: "Forms",
        description: "Creates forms and reads responses from chat.",
        logo: "/forms.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
      {
        id: "meet",
        title: "Meet",
        description: "Attaches conferencing links to scheduled events.",
        logo: "/meet.svg",
        authType: "oauth",
        oauthProvider: "google",
        fields: [],
      },
    ],
  },
];

export const ALL_ENTRIES: CatalogEntry[] = CATALOG.flatMap((g) => g.entries);
