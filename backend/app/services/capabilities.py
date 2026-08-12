"""
Per-capability readiness for the PR Context Agent.

A service being "connected" is too coarse to be useful. GitHub with a token
lacking `repo` scope can read PRs but not comment; Slack with only a bot token
can post but cannot search. When a run produces thin results the dashboard has
to say which specific capability was missing, not just which service.
"""

from dataclasses import dataclass, field

from app.services.security_scan import gitleaks_available, semgrep_available


@dataclass
class Capability:
    """One concrete thing the pipeline can or cannot do."""

    key: str
    label: str
    available: bool
    # Required capabilities block the pipeline entirely; optional ones only
    # mean less context in the output.
    required: bool = False
    hint: str = ""


@dataclass
class ServiceReadiness:
    """A service and the individual capabilities it provides."""

    key: str
    label: str
    connected: bool
    required: bool = False
    capabilities: list[Capability] = field(default_factory=list)

    @property
    def fully_ready(self) -> bool:
        return self.connected and all(c.available for c in self.capabilities)


def build_readiness(
    integration_configs: dict[str, dict],
    smtp_configured: bool = False,
) -> list[ServiceReadiness]:
    """
    Describe what the pipeline can currently do, capability by capability.

    Args:
        integration_configs: Decrypted per-service credentials
        smtp_configured: Whether QA notification email is set up

    Returns:
        One entry per service, each listing its individual capabilities.
    """
    github = integration_configs.get("github") or {}
    jira = integration_configs.get("jira") or {}
    slack = integration_configs.get("slack") or {}
    slack_credentials = slack.get("credentials") or {}
    docs = integration_configs.get("docs") or integration_configs.get("drive") or {}
    gmail = integration_configs.get("gmail") or {}

    github_connected = bool(github.get("api_key"))
    jira_connected = bool(
        jira.get("api_key") and (jira.get("credentials") or {}).get("url")
    )
    slack_connected = bool(
        slack_credentials.get("bot_token") or slack.get("api_key")
    )
    docs_connected = bool((docs.get("credentials") or {}).get("access_token"))
    gmail_connected = bool((gmail.get("credentials") or {}).get("access_token"))

    return [
        ServiceReadiness(
            key="github",
            label="GitHub",
            connected=github_connected,
            required=True,
            capabilities=[
                Capability(
                    "pull_requests", "Pull requests", github_connected, required=True,
                    hint="Read PR metadata, diffs and changed files",
                ),
                Capability(
                    "issues", "Issues", github_connected,
                    hint="Resolve linked issues and close them on merge",
                ),
                Capability(
                    "comments", "PR comments", github_connected, required=True,
                    hint="Post the review back to the pull request",
                ),
            ],
        ),
        ServiceReadiness(
            key="jira",
            label="Jira",
            connected=jira_connected,
            capabilities=[
                Capability(
                    "issue_lookup", "Ticket lookup", jira_connected,
                    hint="Fetch summary, status and assignee for referenced keys",
                ),
                Capability(
                    "search", "Ticket search", jira_connected,
                    hint="Find the ticket by topic when the PR references no key",
                ),
                Capability(
                    "transition", "Status transition", jira_connected,
                    hint="Move the ticket forward when the PR merges",
                ),
            ],
        ),
        ServiceReadiness(
            key="slack",
            label="Slack",
            connected=slack_connected,
            capabilities=[
                Capability(
                    "post", "Post message", slack_connected,
                    hint="Bot token (xoxb-) — posts the PR summary",
                ),
                Capability(
                    "read_channel", "Read channels", slack_connected,
                    hint="Bot token — requires the bot to be invited to the channel",
                ),
                Capability(
                    # The separate token is why this can be missing while the
                    # rest of Slack works.
                    "search", "Search history",
                    bool(slack_credentials.get("user_token")),
                    hint="Needs a user token (xoxp-) with search:read; bot tokens cannot search",
                ),
            ],
        ),
        ServiceReadiness(
            key="docs",
            label="Google Docs",
            connected=docs_connected,
            capabilities=[
                Capability(
                    "read_context", "Read as context", docs_connected,
                    hint="Feed design docs and specs to the reviewer",
                ),
                Capability(
                    "export", "Export report", docs_connected,
                    hint="Write each analysis to a Doc",
                ),
            ],
        ),
        ServiceReadiness(
            key="email",
            label="QA email",
            connected=gmail_connected or smtp_configured,
            capabilities=[
                Capability(
                    "notify", "Notify testers", gmail_connected or smtp_configured,
                    hint="Email the test team when a PR merges",
                ),
            ],
        ),
        ServiceReadiness(
            key="scanners",
            label="Security scanners",
            connected=semgrep_available() or gitleaks_available(),
            capabilities=[
                Capability(
                    "semgrep", "Semgrep", semgrep_available(),
                    hint="Static analysis — produces confirmed findings",
                ),
                Capability(
                    "gitleaks", "Gitleaks", gitleaks_available(),
                    hint="Detects committed credentials",
                ),
            ],
        ),
    ]
