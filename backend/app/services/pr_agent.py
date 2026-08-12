"""
PR Context Agent
When a pull request opens, gather the context scattered across Jira, Linear and
Slack, scan the diff for vulnerabilities, comment on the PR, and post a summary
to Slack.

The value here is the stitching: Slack holds the discussion, Jira holds the
requirement, GitHub holds the code, and nothing joins them. This does.

Pipeline stages are individually fault-tolerant. A Slack outage should still
produce a PR comment carrying the Jira context and the security findings.
"""

import logging

import httpx

from app.schemas import (
    PRAnalysisResult,
    PRContext,
    RelatedSlackThread,
    RelatedTicket,
    SecurityFinding,
    SecuritySeverity,
)
from app.services import github_pr, linking
from app.services.security_scan import scan_changes

logger = logging.getLogger(__name__)

# Severity ordering for display.
_SEVERITY_RANK = {
    SecuritySeverity.critical: 0,
    SecuritySeverity.high: 1,
    SecuritySeverity.medium: 2,
    SecuritySeverity.low: 3,
    SecuritySeverity.info: 4,
}

_SEVERITY_ICON = {
    SecuritySeverity.critical: "🔴",
    SecuritySeverity.high: "🟠",
    SecuritySeverity.medium: "🟡",
    SecuritySeverity.low: "🔵",
    SecuritySeverity.info: "⚪",
}


# ============== Context gathering ==============

async def fetch_jira_tickets(
    ticket_keys: list[str],
    jira_config: dict,
) -> list[RelatedTicket]:
    """Look up ticket details in Jira. Unknown keys are skipped silently."""
    api_token = jira_config.get("api_key", "")
    credentials = jira_config.get("credentials", {}) or {}
    email = credentials.get("email", "")
    base_url = (credentials.get("url", "") or "").rstrip("/")

    if not (api_token and email and base_url):
        return []

    tickets: list[RelatedTicket] = []
    async with httpx.AsyncClient(timeout=30.0, auth=(email, api_token)) as client:
        for key in ticket_keys:
            try:
                response = await client.get(
                    f"{base_url}/rest/api/3/issue/{key}",
                    params={"fields": "summary,status,assignee"},
                    headers={"Accept": "application/json"},
                )
                if response.status_code != 200:
                    continue

                fields = response.json().get("fields", {})
                assignee = fields.get("assignee") or {}
                status = fields.get("status") or {}

                tickets.append(RelatedTicket(
                    key=key,
                    summary=fields.get("summary"),
                    status=status.get("name"),
                    assignee=assignee.get("displayName"),
                    url=f"{base_url}/browse/{key}",
                    source="jira",
                ))
            except Exception:
                # A single unresolvable ticket must not fail the pipeline.
                continue

    return tickets


async def search_slack_threads(
    ticket_keys: list[str],
    repo: str,
    pr_number: int,
    slack_config: dict,
) -> list[RelatedSlackThread]:
    """
    Find Slack discussion about this work.

    Searches for each ticket key and for the PR URL. Requires a user token
    (xoxp-); search.messages is not available to bot tokens.
    """
    credentials = slack_config.get("credentials", {}) or {}
    user_token = credentials.get("user_token", "")

    if not user_token:
        # Slack is connected but cannot be searched. Say so: otherwise the PR
        # comment silently omits its "Prior discussion" section with no clue why.
        logger.info(
            "Slack connected without a user token (xoxp-); skipping message "
            "search for %s#%s. Add one in Integrations to enable it.",
            repo, pr_number,
        )
        return []

    queries = list(ticket_keys)
    queries.append(f"github.com/{repo}/pull/{pr_number}")

    threads: list[RelatedSlackThread] = []
    seen_permalinks: set[str] = set()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                response = await client.get(
                    "https://slack.com/api/search.messages",
                    headers={"Authorization": f"Bearer {user_token}"},
                    params={"query": query, "count": 5},
                )
                payload = response.json()
                if not payload.get("ok"):
                    continue

                for match in payload.get("messages", {}).get("matches", []):
                    permalink = match.get("permalink", "")
                    if permalink in seen_permalinks:
                        continue
                    seen_permalinks.add(permalink)

                    threads.append(RelatedSlackThread(
                        channel=match.get("channel", {}).get("name", "unknown"),
                        permalink=permalink,
                        message_count=1,
                        summary=(match.get("text", "") or "")[:280],
                        participants=[match.get("username", "")] if match.get("username") else [],
                    ))
            except Exception:
                continue

    return threads


# ============== Rendering ==============

def _render_findings(findings: list[SecurityFinding], heading: str, caveat: str) -> str:
    """Render one findings table."""
    if not findings:
        return ""

    ordered = sorted(findings, key=lambda f: _SEVERITY_RANK.get(f.severity, 9))

    lines = [f"### {heading}", "", caveat, ""]
    for finding in ordered:
        icon = _SEVERITY_ICON.get(finding.severity, "⚪")
        location = finding.file_path
        if finding.line:
            location += f":{finding.line}"

        lines.append(f"- {icon} **{finding.severity.value.upper()}** — {finding.title}")
        lines.append(f"  `{location}`")
        if finding.description:
            lines.append(f"  {finding.description}")
        lines.append("")

    return "\n".join(lines)


def render_pr_comment(result: PRAnalysisResult) -> str:
    """Render the analysis as a GitHub PR comment."""
    ctx = result.context
    parts: list[str] = ["## 🧭 Locus PR Context", ""]

    # Related tickets
    if ctx.tickets:
        parts.append("### Related tickets")
        parts.append("")
        for ticket in ctx.tickets:
            line = f"- [{ticket.key}]({ticket.url}) — {ticket.summary or 'no summary'}"
            details = [d for d in (ticket.status, ticket.assignee) if d]
            if details:
                line += f" _({' · '.join(details)})_"
            parts.append(line)
        parts.append("")
    elif ctx.ticket_keys:
        parts.append(
            f"### Related tickets\n\nReferenced but not found: "
            f"{', '.join(f'`{k}`' for k in ctx.ticket_keys)}\n"
        )

    # Slack discussion
    if ctx.slack_threads:
        parts.append("### Prior discussion")
        parts.append("")
        for thread in ctx.slack_threads[:5]:
            snippet = (thread.summary or "").replace("\n", " ")
            if thread.permalink:
                parts.append(f"- [#{thread.channel}]({thread.permalink}) — {snippet}")
            else:
                parts.append(f"- #{thread.channel} — {snippet}")
        parts.append("")

    # Security: two separate sections, never merged.
    confirmed = _render_findings(
        result.confirmed_findings,
        "🔒 Security findings (confirmed)",
        "_Matched by static analysis rules._",
    )
    if confirmed:
        parts.append(confirmed)

    unverified = _render_findings(
        result.unverified_findings,
        "🔍 Possible issues (unverified)",
        "_Model-generated and **not** confirmed by a scanner. Verify before acting._",
    )
    if unverified:
        parts.append(unverified)

    if not result.confirmed_findings and not result.unverified_findings:
        parts.append("### 🔒 Security\n\nNo issues detected in the changed code.\n")

    if result.errors:
        parts.append("<details><summary>Pipeline notes</summary>\n")
        for error in result.errors:
            parts.append(f"- {error}")
        parts.append("\n</details>\n")

    parts.append("---")
    parts.append("<sub>Posted by Locus. Updated in place on each push.</sub>")

    return "\n".join(parts)


def render_slack_summary(result: PRAnalysisResult) -> str:
    """Render a short Slack summary."""
    ctx = result.context
    confirmed = len(result.confirmed_findings)
    unverified = len(result.unverified_findings)

    lines = [
        f"*<{ctx.url}|{ctx.repo}#{ctx.pr_number}>* — {ctx.title}",
        f"by {ctx.author} · +{ctx.additions}/-{ctx.deletions} across {ctx.files_changed} files",
    ]

    if ctx.tickets:
        lines.append("Tickets: " + ", ".join(t.key for t in ctx.tickets))

    if confirmed:
        critical = sum(
            1 for f in result.confirmed_findings
            if f.severity in (SecuritySeverity.critical, SecuritySeverity.high)
        )
        flag = f"🔴 {confirmed} confirmed finding(s)"
        if critical:
            flag += f", {critical} high or critical"
        lines.append(flag)
    elif unverified:
        lines.append(f"🔍 {unverified} unverified issue(s) flagged for review")
    else:
        lines.append("✅ No security findings")

    return "\n".join(lines)


# ============== Pipeline ==============

async def analyze_pull_request(
    repo: str,
    pr_number: int,
    integration_configs: dict[str, dict],
    post_comment: bool = True,
    slack_channel: str | None = None,
    enable_llm_review: bool = True,
) -> PRAnalysisResult:
    """
    Run the full PR analysis pipeline.

    Args:
        repo: "owner/name"
        pr_number: PR number
        integration_configs: Decrypted per-user credentials by service
        post_comment: Whether to write the comment back to the PR
        slack_channel: Channel for the summary; None to skip
        enable_llm_review: Whether to run the unverified LLM pass

    Returns:
        The analysis result, including anything that went wrong.
    """
    errors: list[str] = []

    github_config = integration_configs.get("github", {})
    github_token = github_config.get("api_key", "")

    if not github_token:
        raise ValueError("GitHub is not connected for this user.")

    # 1. PR metadata
    pr = await github_pr.get_pull_request(github_token, repo, pr_number)
    branch = pr.get("head", {}).get("ref")

    try:
        commit_messages = await github_pr.get_pr_commits(github_token, repo, pr_number)
    except Exception as e:
        commit_messages = []
        errors.append(f"Could not read commits: {e}")

    # 2. Ticket keys
    ticket_keys = linking.extract_from_pr(
        title=pr.get("title"),
        branch=branch,
        body=pr.get("body"),
        commit_messages=commit_messages,
    )

    context = PRContext(
        repo=repo,
        pr_number=pr_number,
        title=pr.get("title", ""),
        author=pr.get("user", {}).get("login", "unknown"),
        url=pr.get("html_url", ""),
        branch=branch,
        ticket_keys=ticket_keys,
        files_changed=pr.get("changed_files", 0),
        additions=pr.get("additions", 0),
        deletions=pr.get("deletions", 0),
    )

    # 3. Jira context
    if ticket_keys and "jira" in integration_configs:
        try:
            context.tickets = await fetch_jira_tickets(
                ticket_keys, integration_configs["jira"]
            )
        except Exception as e:
            errors.append(f"Jira lookup failed: {e}")

    # 4. Slack context
    if "slack" in integration_configs:
        try:
            context.slack_threads = await search_slack_threads(
                ticket_keys, repo, pr_number, integration_configs["slack"]
            )
        except Exception as e:
            errors.append(f"Slack search failed: {e}")

    # 5. Security scan.
    # Semgrep needs real source files; the diff is used for secret scanning and
    # the LLM review, where what changed matters more than whole-file context.
    confirmed: list[SecurityFinding] = []
    unverified: list[SecurityFinding] = []
    try:
        diff = await github_pr.get_pr_diff(github_token, repo, pr_number)

        head_sha = pr.get("head", {}).get("sha") or branch or "HEAD"
        try:
            changed_files, file_notes = await github_pr.get_changed_file_contents(
                github_token, repo, pr_number, head_sha
            )
            errors.extend(file_notes)
        except Exception as e:
            changed_files = {}
            errors.append(f"Could not fetch changed files: {e}")

        confirmed, unverified, scan_errors = await scan_changes(
            files=changed_files,
            diff_text=diff,
            enable_llm_review=enable_llm_review,
        )
        errors.extend(scan_errors)
    except Exception as e:
        errors.append(f"Security scan failed: {e}")

    result = PRAnalysisResult(
        context=context,
        confirmed_findings=confirmed,
        unverified_findings=unverified,
        errors=errors,
    )
    result.summary = render_slack_summary(result)

    # 6. Write back to the PR
    if post_comment:
        try:
            await github_pr.upsert_pr_comment(
                github_token, repo, pr_number, render_pr_comment(result)
            )
            result.pr_comment_posted = True
        except Exception as e:
            result.errors.append(f"Could not post PR comment: {e}")

    # 7. Slack summary
    if slack_channel and "slack" in integration_configs:
        try:
            bot_token = (
                integration_configs["slack"].get("credentials", {}) or {}
            ).get("bot_token") or integration_configs["slack"].get("api_key", "")

            if bot_token:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        "https://slack.com/api/chat.postMessage",
                        headers={"Authorization": f"Bearer {bot_token}"},
                        json={"channel": slack_channel, "text": result.summary},
                    )
                    if response.json().get("ok"):
                        result.slack_posted = True
                    else:
                        result.errors.append(
                            f"Slack post rejected: {response.json().get('error')}"
                        )
        except Exception as e:
            result.errors.append(f"Could not post to Slack: {e}")

    return result
