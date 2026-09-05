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
from app.services.chat.llm import get_llm
from app.services.integrations import google_auth, project_board

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


async def reopen_for_qa(
    token: str, repo: str, issue_number: int, pr_number: int
) -> tuple[bool, str]:
    """
    Reopen an issue GitHub auto-closed at merge, when QA still has to sign off.

    `close_on_qa_signoff` stops *Locus* from closing the work item, but nothing
    stopped GitHub: a pull request body carrying `Closes #N` -- which the
    authoring driver writes, and which is what populates
    `closingIssuesReferences` for `get_linked_issues` -- closes the issue the
    moment it merges, and the close is attributed to whoever merged.

    So the setting was silently defeated on exactly the pull requests this
    pipeline authors: the ticket closed before any tester saw it, which is the
    outcome the setting exists to prevent -- a ticket closed while a bug is
    live drops off the board, the one place anyone would look for it.

    Reopening rather than dropping the keyword is deliberate. The keyword is
    load-bearing: `get_linked_issues` reads `closingIssuesReferences` to learn
    which issues this pull request resolves, and that is how the QA thread
    knows what to close on sign-off. Writing `Refs` instead would leave the
    thread with no issue to close and break the feature further along.

    Only reopens what is closed, so this is a no-op when the keyword was absent
    or a person deliberately closed the issue first. The comment says why, or
    the reopen reads as the bot fighting the merge.
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
        if current.json().get("state") != "closed":
            return True, f"#{issue_number} already open"

        reopened = await client.patch(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            headers=headers,
            json={"state": "open"},
        )
        if reopened.status_code != 200:
            return False, f"Could not reopen #{issue_number}"

        await client.post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            headers=headers,
            json={
                "body": (
                    f"#{pr_number} merged and GitHub closed this automatically. "
                    "Reopening: this repository closes work items on QA "
                    "sign-off, not at merge. The testing team has been "
                    "notified, and this closes when they confirm."
                )
            },
        )

    return True, f"Reopened #{issue_number} pending QA sign-off"


QA_BRIEF_PROMPT = """You are writing a short test brief for a QA engineer.

A pull request just merged. Describe what to verify, based only on the facts \
below. Do not invent features or file names that are not mentioned.

Pull request: {title}
Repository: {repo}
Files changed: {files_changed}

Linked issues and tickets:
{work_items}

Changes the reviewer asked for during review:
{review_asks}

Security findings the reviewer flagged:
{findings}

Write 3-6 bullet points naming concrete things to test, then one line on risk \
areas. Cover every change the reviewer asked for -- those were requested \
explicitly and are the most concrete statement of what this change had to do. \
Be specific and brief. Plain text, no Markdown headings."""


async def draft_qa_brief(
    result: PRAnalysisResult,
    review_asks: list[str] | None = None,
) -> str:
    """
    Write the "what to test" section of the QA email.

    Args:
        review_asks: What the reviewer asked for across the review rounds, in
            their own words. QA is precisely who needs these: "the reviewer
            asked for X" is a testable claim, and a brief built only from the
            diff and the ticket silently drops the requirement a human stated
            most plainly. Untrusted text -- this model has no tools bound.

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

    asks_text = "\n".join(f"- {a}" for a in (review_asks or [])) or "(none)"

    try:
        llm = get_llm(temperature=0.2)
        response = await llm.ainvoke(
            QA_BRIEF_PROMPT.format(
                title=ctx.title,
                repo=ctx.repo,
                files_changed=ctx.files_changed,
                work_items=work_items,
                review_asks=asks_text,
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
        f"Related work:\n{work_items}\n\n"
        f"The reviewer asked for:\n{asks_text}\n\n"
        f"Reviewer findings:\n{findings}"
    )


def _qa_email_text(result: PRAnalysisResult, brief: str) -> str:
    """
    The QA email body.

    Built here rather than inline at the send so the copy recorded in the
    timeline is the same string that was sent, not a reconstruction that can
    drift from it.

    The full report is linked when one was written. A tester deciding what to
    exercise wants the findings and the requirement context behind the change,
    and the brief is deliberately short -- without the link that detail exists
    but is unreachable from the message that asks for the work.
    """
    ctx = result.context
    report = f"Full analysis: {result.doc_url}\n\n" if result.doc_url else ""
    return (
        f"{ctx.title}\n"
        f"{ctx.url}\n\n"
        f"Merged by {ctx.author} · +{ctx.additions}/-{ctx.deletions} "
        f"across {ctx.files_changed} files\n\n"
        f"{report}"
        f"What to test\n------------\n{brief}\n\n"
        f"Reply to this email if something does not work — Locus will reopen "
        f"the ticket.\n"
    )


async def email_test_team(
    gmail_config: dict,
    recipients: list[str],
    result: PRAnalysisResult,
    brief: str,
    *,
    db=None,
    user_id: int | None = None,
) -> tuple[bool, str, str | None, str]:
    """
    Send the QA notification via the Gmail API.

    Returns the RFC Message-ID as well as the outcome: a reply carries it in
    In-Reply-To, which is the only reliable way to tie that reply back to this
    PR. Subject matching would break the moment someone edits the subject.

    The body is returned too, so the caller records the exact string that was
    sent rather than rendering it a second time -- a reconstruction drifts
    from what the recipient actually read.

    Returns:
        (succeeded, detail, message_id, body)
    """
    import base64
    from email.message import EmailMessage

    # Refreshed rather than read straight from storage: a Google access token
    # lives an hour and this runs from a merge that may land days after the
    # user connected Gmail, so the stored one is usually dead.
    access_token = await google_auth.valid_access_token(
        gmail_config, db=db, user_id=user_id, service="gmail"
    )
    body = _qa_email_text(result, brief)

    if not access_token:
        return False, "Gmail is not connected", None, body
    if not recipients:
        return False, "No test team recipients configured", None, body

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
    message.set_content(body)

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
            return (
                False,
                f"Gmail rejected the message ({response.status_code})",
                None,
                body,
            )

    return True, f"Notified {', '.join(recipients)}", message_id, body


async def post_qa_thread(
    slack_config: dict,
    channel: str,
    result: PRAnalysisResult,
    brief: str,
) -> tuple[str | None, str | None, str]:
    """
    Post the QA notification to Slack and return (thread_ts, channel_id, text).

    The timestamp is what later ties a tester's reply back to this PR -- a
    reply carries only a channel and thread_ts, nothing about the work items.

    The resolved channel id comes back with the post and must be the value we
    store: an inbound event identifies its channel by id ("C09..."), never by
    the "#web" name a user typed at registration, so storing the name means no
    reply ever matches.

    Returns:
        (ts, channel_id, text). The text is returned so the caller can record
        exactly what was posted -- reconstructing it later would drift from
        what the channel actually saw.
    """
    ctx = result.context
    # Linked when a report was written, for the same reason the email carries
    # it: the brief is short by design, and the detail behind it is otherwise
    # unreachable from the message asking for the work.
    report = f"\n:page_facing_up: <{result.doc_url}|Full analysis>" if result.doc_url else ""
    text = (
        f":test_tube: *Ready to test* - <{ctx.url}|{ctx.repo}#{ctx.pr_number}>\n"
        f"{ctx.title}{report}\n\n"
        f"*What to test*\n{brief}\n\n"
        "_Reply in this thread if something does not work._"
    )

    credentials = slack_config.get("credentials", {}) or {}
    bot_token = credentials.get("bot_token") or slack_config.get("api_key", "")
    if not bot_token:
        return None, None, text

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel, "text": text},
        )
        payload = response.json()

    if not payload.get("ok"):
        logger.warning("QA thread post rejected: %s", payload.get("error"))
        return None, None, text

    return payload.get("ts"), payload.get("channel"), text


async def run_merge_actions(
    result: PRAnalysisResult,
    integration_configs: dict[str, dict],
    jira_done_status: str = "Done",
    qa_recipients: list[str] | None = None,
    close_issues: bool = True,
    qa_slack_channel: str | None = None,
    review_asks: list[str] | None = None,
    close_on_qa_signoff: bool = False,
    project_board_sync: bool = True,
    project_column_map: dict[str, str] | None = None,
    db=None,
    user_id: int | None = None,
) -> MergeActionResult:
    """
    Apply post-merge actions.

    Each step is independent: a Jira permission error must not stop the QA
    email, and vice versa.

    Args:
        review_asks: What the reviewer asked for across the review rounds,
            passed to the QA brief so the testing team is told about the
            changes a human requested and not only what the diff touched.
        close_on_qa_signoff: When set, the merge neither transitions the ticket
            nor closes linked issues -- `qa_feedback` does both once the
            testing team confirms. The QA notification still goes out; it is
            the whole point of leaving the work item open.
        project_board_sync: Move each linked issue's Projects card to the
            column its stage maps to. Follows `close_on_qa_signoff` exactly as
            the Jira transition does: a merge that defers the close moves the
            card to `testing`, not to a done column, because the board must not
            claim the work is finished before a tester has said so.
    """
    outcome = MergeActionResult()
    ctx = result.context

    # Jira transitions.
    #
    # Skipped entirely when the work item closes on QA sign-off instead: the
    # merge has nothing true to say about the ticket at this point. Moving it
    # to a done status here would assert the change works before anyone has
    # checked, and moving it to an intermediate status assumes a workflow
    # stage that many boards do not have.
    jira_config = integration_configs.get("jira")
    if jira_config and not close_on_qa_signoff:
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
    if close_issues and not close_on_qa_signoff and github_token:
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

    # The other half of deferring the close: undo GitHub's own.
    #
    # Deliberately not gated on `close_issues`, which the branch above is.
    # That setting governs whether *Locus* closes an issue; this reopen undoes
    # a close GitHub performed on its own, which happens whatever the setting
    # says. Gated on both, the two most cautious choices on the form -- leave
    # issues alone, and wait for a tester -- combined into the outcome neither
    # asks for: GitHub closed the ticket at merge and nothing reopened it, so
    # the work vanished from the board before any tester saw it.
    #
    # Not raised past the merge -- a completed merge must not read as failed
    # because an issue could not be reopened, the same rule the board move
    # follows.
    elif close_on_qa_signoff and github_token:
        for issue in ctx.linked_issues:
            if issue.relation != "closes":
                continue
            try:
                ok, detail = await reopen_for_qa(
                    github_token, ctx.repo, issue.number, ctx.pr_number
                )
                (outcome.issues_closed if ok else outcome.errors).append(detail)
            except Exception as e:
                outcome.errors.append(f"#{issue.number}: {e}")

    # Project board.
    #
    # The stage is the one the work is genuinely at, which is why this reads
    # `close_on_qa_signoff` rather than always moving to a done column: a merge
    # that deferred the close has handed the work to the testing team, and a
    # card in Done would say the opposite of what the ticket being open says.
    # Every issue linked to the PR is moved, not only the ones it closes --
    # a card tracks the work, and a mention is enough to put it on the board.
    if project_board_sync and github_token:
        stage = "testing" if close_on_qa_signoff else "done"
        try:
            outcome.board_moves = await project_board.sync_issues(
                github_token,
                ctx.repo,
                [issue.number for issue in ctx.linked_issues],
                stage,
                column_map=project_column_map,
            )
        except Exception as e:
            # sync_issues swallows per-issue failures already; this guards the
            # call itself, on the same rule -- a completed merge must never be
            # reported as failed because a board could not be updated.
            outcome.errors.append(f"Project board sync failed: {e}")

    # QA notification in Slack, as a thread so replies are attributable.
    if qa_slack_channel and "slack" in integration_configs:
        try:
            brief = outcome.qa_brief or await draft_qa_brief(result, review_asks)
            outcome.qa_brief = brief
            (
                outcome.qa_thread_ts,
                outcome.qa_channel_id,
                outcome.qa_slack_text,
            ) = await post_qa_thread(
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
                brief = outcome.qa_brief or await draft_qa_brief(result, review_asks)
                ok, detail, message_id, body = await email_test_team(
                    gmail_config, qa_recipients, result, brief,
                    db=db, user_id=user_id,
                )
                # Recorded whether or not the send succeeded: a QA email that
                # failed to go out is more important to surface than one that
                # went out fine.
                outcome.qa_email_to = list(qa_recipients)
                outcome.qa_email_subject = (
                    f"[Ready to test] {result.context.repo}"
                    f"#{result.context.pr_number} — {result.context.title}"
                )
                # The body the send actually used, not a second render of it.
                # A reconstruction drifts from what the recipient saw, which
                # makes the record worse than useless.
                outcome.qa_email_body = body
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
