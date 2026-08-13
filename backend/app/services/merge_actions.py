"""
Actions taken when a pull request merges.

Transitions the Jira ticket, closes linked GitHub issues, and emails the test
team with what to verify.

Transitions are forward-only. A misconfigured target status must never drag a
whole team's board backwards, so a transition that would move a ticket to an
earlier workflow stage -- or reopen a closed one -- is refused rather than
applied.
"""

import logging
from uuid import uuid4

import httpx

from app.schemas import MergeActionResult, PRAnalysisResult
from app.services.llm import get_llm

logger = logging.getLogger(__name__)

# Workflow stages, earliest first. A transition is allowed only if the target
# ranks at or above the current status.
_STAGE_ORDER = [
    {"backlog", "to do", "todo", "open", "new", "created"},
    {"in progress", "in development", "in dev", "started", "doing"},
    {"in review", "code review", "review", "in qa", "qa"},
    {"ready for testing", "ready to test", "testing", "verify"},
    {"done", "closed", "resolved", "complete", "completed", "shipped"},
]


def _stage_rank(status: str | None) -> int:
    """Rank a status name by workflow stage. Unknown statuses rank -1."""
    if not status:
        return -1
    normalized = status.strip().lower()
    for rank, names in enumerate(_STAGE_ORDER):
        if normalized in names:
            return rank
    return -1


def is_forward_transition(current: str | None, target: str) -> bool:
    """
    Whether moving `current` -> `target` advances the workflow.

    An unknown status on either side is allowed through: custom workflows are
    common, and refusing everything unrecognized would make the feature useless
    for most teams. What this reliably blocks is the recognizable regression --
    Done back to In Progress.
    """
    current_rank = _stage_rank(current)
    target_rank = _stage_rank(target)

    if current_rank < 0 or target_rank < 0:
        return True

    return target_rank >= current_rank


async def transition_jira_ticket(
    jira_config: dict,
    ticket_key: str,
    target_status: str,
) -> tuple[bool, str]:
    """
    Move a Jira ticket to `target_status`, if that is a forward move.

    Returns:
        (succeeded, human-readable detail)
    """
    api_token = jira_config.get("api_key", "")
    credentials = jira_config.get("credentials", {}) or {}
    email = credentials.get("email", "")
    base_url = (credentials.get("url", "") or "").rstrip("/")

    if not (api_token and email and base_url):
        return False, "Jira is not fully configured"

    async with httpx.AsyncClient(timeout=30.0, auth=(email, api_token)) as client:
        # Current status, to check the move is forward.
        detail = await client.get(
            f"{base_url}/rest/api/3/issue/{ticket_key}",
            params={"fields": "status"},
            headers={"Accept": "application/json"},
        )
        if detail.status_code != 200:
            return False, f"{ticket_key} not found"

        current = (
            detail.json().get("fields", {}).get("status", {}).get("name")
        )

        if not is_forward_transition(current, target_status):
            return False, (
                f"{ticket_key} is already '{current}'; refusing to move it "
                f"backwards to '{target_status}'"
            )

        # Jira transitions are addressed by id, not by target name.
        available = await client.get(
            f"{base_url}/rest/api/3/issue/{ticket_key}/transitions",
            headers={"Accept": "application/json"},
        )
        if available.status_code != 200:
            return False, f"Could not list transitions for {ticket_key}"

        transition_id = None
        for transition in available.json().get("transitions", []):
            name = transition.get("name", "")
            to_name = (transition.get("to") or {}).get("name", "")
            if target_status.lower() in (name.lower(), to_name.lower()):
                transition_id = transition.get("id")
                break

        if not transition_id:
            return False, (
                f"No transition to '{target_status}' available from '{current}'"
            )

        applied = await client.post(
            f"{base_url}/rest/api/3/issue/{ticket_key}/transitions",
            json={"transition": {"id": transition_id}},
            headers={"Content-Type": "application/json"},
        )
        if applied.status_code not in (200, 204):
            return False, f"Transition rejected ({applied.status_code})"

    return True, f"{ticket_key}: {current} → {target_status}"


async def close_github_issue(
    token: str, repo: str, issue_number: int, pr_number: int
) -> tuple[bool, str]:
    """
    Close a GitHub issue and note which PR resolved it.

    Only closes issues that are currently open, so re-running on an already
    merged PR is a no-op rather than an error.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        current = await client.get(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            headers=headers,
        )
        if current.status_code != 200:
            return False, f"Issue #{issue_number} not found"
        if current.json().get("state") == "closed":
            return True, f"#{issue_number} already closed"

        await client.post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            headers=headers,
            json={"body": f"Resolved by #{pr_number}. Closing."},
        )

        closed = await client.patch(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            headers=headers,
            json={"state": "closed", "state_reason": "completed"},
        )
        if closed.status_code != 200:
            return False, f"Could not close #{issue_number}"

    return True, f"Closed #{issue_number}"


QA_BRIEF_PROMPT = """You are writing a short test brief for a QA engineer.

A pull request just merged. Describe what to verify, based only on the facts \
below. Do not invent features or file names that are not mentioned.

Pull request: {title}
Repository: {repo}
Files changed: {files_changed}

Linked issues and tickets:
{work_items}

Security findings the reviewer flagged:
{findings}

Write 3-6 bullet points naming concrete things to test, then one line on risk \
areas. Be specific and brief. Plain text, no Markdown headings."""


async def draft_qa_brief(result: PRAnalysisResult) -> str:
    """
    Write the "what to test" section of the QA email.

    Falls back to a factual summary if the model is unavailable -- the email
    should still go out.
    """
    ctx = result.context

    work_items = "\n".join(
        [f"- {t.key}: {t.summary or ''}" for t in ctx.tickets]
        + [f"- #{i.number}: {i.title}" for i in ctx.linked_issues]
    ) or "(none referenced)"

    findings = "\n".join(
        f"- [{f.severity.value}] {f.title} ({f.file_path})"
        for f in result.confirmed_findings + result.unverified_findings
    ) or "(none)"

    try:
        llm = get_llm(temperature=0.2)
        response = await llm.ainvoke(
            QA_BRIEF_PROMPT.format(
                title=ctx.title,
                repo=ctx.repo,
                files_changed=ctx.files_changed,
                work_items=work_items,
                findings=findings,
            )
        )
        content = response.content
        text = content if isinstance(content, str) else str(content)
        if text.strip():
            return text.strip()
    except Exception as e:
        logger.debug("QA brief generation failed: %s", e)

    return (
        f"Verify the changes in {ctx.repo}#{ctx.pr_number} ({ctx.title}).\n\n"
        f"Related work:\n{work_items}\n\nReviewer findings:\n{findings}"
    )


async def email_test_team(
    gmail_config: dict,
    recipients: list[str],
    result: PRAnalysisResult,
    brief: str,
) -> tuple[bool, str, str | None]:
    """
    Send the QA notification via the Gmail API.

    Returns the RFC Message-ID as well as the outcome: a reply carries it in
    In-Reply-To, which is the only reliable way to tie that reply back to this
    PR. Subject matching would break the moment someone edits the subject.

    Returns:
        (succeeded, detail, message_id)
    """
    import base64
    from email.message import EmailMessage

    credentials = gmail_config.get("credentials", {}) or {}
    access_token = credentials.get("access_token")
    if not access_token:
        return False, "Gmail is not connected", None
    if not recipients:
        return False, "No test team recipients configured", None

    ctx = result.context

    # Set our own Message-ID rather than letting Gmail assign one: the value
    # has to be known here to be stored, and Gmail's is only discoverable via
    # a follow-up fetch.
    domain = "locus.local"
    message_id = f"<qa-{ctx.repo.replace('/', '-')}-{ctx.pr_number}-{uuid4().hex[:12]}@{domain}>"

    message = EmailMessage()
    message["Message-ID"] = message_id
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"[Ready to test] {ctx.repo}#{ctx.pr_number} — {ctx.title}"
    message.set_content(
        f"{ctx.title}\n"
        f"{ctx.url}\n\n"
        f"Merged by {ctx.author} · +{ctx.additions}/-{ctx.deletions} "
        f"across {ctx.files_changed} files\n\n"
        f"What to test\n------------\n{brief}\n\n"
        f"Reply to this email if something does not work — Locus will reopen "
        f"the ticket.\n"
    )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
        )
        if response.status_code not in (200, 202):
            return False, f"Gmail rejected the message ({response.status_code})", None

    return True, f"Notified {', '.join(recipients)}", message_id


async def post_qa_thread(
    slack_config: dict,
    channel: str,
    result: PRAnalysisResult,
    brief: str,
) -> tuple[str | None, str | None]:
    """
    Post the QA notification to Slack and return (thread_ts, channel_id).

    The timestamp is what later ties a tester's reply back to this PR -- a
    reply carries only a channel and thread_ts, nothing about the work items.

    The resolved channel id comes back with the post and must be the value we
    store: an inbound event identifies its channel by id ("C09..."), never by
    the "#web" name a user typed at registration, so storing the name means no
    reply ever matches.

    Returns:
        (ts, channel_id), or (None, None) if posting failed.
    """
    credentials = slack_config.get("credentials", {}) or {}
    bot_token = credentials.get("bot_token") or slack_config.get("api_key", "")
    if not bot_token:
        return None, None

    ctx = result.context
    text = (
        f":test_tube: *Ready to test* - <{ctx.url}|{ctx.repo}#{ctx.pr_number}>\n"
        f"{ctx.title}\n\n"
        f"*What to test*\n{brief}\n\n"
        "_Reply in this thread if something does not work._"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel, "text": text},
        )
        payload = response.json()

    if not payload.get("ok"):
        logger.warning("QA thread post rejected: %s", payload.get("error"))
        return None, None

    return payload.get("ts"), payload.get("channel")


async def run_merge_actions(
    result: PRAnalysisResult,
    integration_configs: dict[str, dict],
    jira_done_status: str = "Done",
    qa_recipients: list[str] | None = None,
    close_issues: bool = True,
    qa_slack_channel: str | None = None,
) -> MergeActionResult:
    """
    Apply post-merge actions.

    Each step is independent: a Jira permission error must not stop the QA
    email, and vice versa.
    """
    outcome = MergeActionResult()
    ctx = result.context

    # Jira transitions
    jira_config = integration_configs.get("jira")
    if jira_config:
        for ticket in ctx.tickets:
            try:
                ok, detail = await transition_jira_ticket(
                    jira_config, ticket.key, jira_done_status
                )
                (outcome.jira_transitioned if ok else outcome.errors).append(detail)
            except Exception as e:
                outcome.errors.append(f"{ticket.key}: {e}")

    # GitHub issues
    github_token = (integration_configs.get("github") or {}).get("api_key")
    if close_issues and github_token:
        for issue in ctx.linked_issues:
            # Only issues the PR formally closes; a mention is not a promise.
            if issue.relation != "closes":
                continue
            try:
                ok, detail = await close_github_issue(
                    github_token, ctx.repo, issue.number, ctx.pr_number
                )
                (outcome.issues_closed if ok else outcome.errors).append(detail)
            except Exception as e:
                outcome.errors.append(f"#{issue.number}: {e}")

    # QA notification in Slack, as a thread so replies are attributable.
    if qa_slack_channel and "slack" in integration_configs:
        try:
            brief = outcome.qa_brief or await draft_qa_brief(result)
            outcome.qa_brief = brief
            outcome.qa_thread_ts, outcome.qa_channel_id = await post_qa_thread(
                integration_configs["slack"], qa_slack_channel, result, brief
            )
            if outcome.qa_thread_ts:
                outcome.qa_notified = True
            else:
                outcome.errors.append("Could not post the QA thread to Slack")
        except Exception as e:
            outcome.errors.append(f"Slack QA notification failed: {e}")

    # QA notification by email
    if qa_recipients:
        gmail_config = integration_configs.get("gmail")
        if gmail_config:
            try:
                brief = outcome.qa_brief or await draft_qa_brief(result)
                ok, detail, message_id = await email_test_team(
                    gmail_config, qa_recipients, result, brief
                )
                if ok:
                    outcome.qa_notified = True
                    outcome.qa_brief = brief
                    outcome.qa_email_message_id = message_id
                else:
                    outcome.errors.append(detail)
            except Exception as e:
                outcome.errors.append(f"QA notification failed: {e}")
        else:
            outcome.errors.append(
                "QA recipients configured but Gmail is not connected"
            )

    return outcome
