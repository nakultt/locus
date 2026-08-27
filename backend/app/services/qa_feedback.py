"""
QA feedback handling.

After a PR merges Locus notifies the test team. When a tester replies, this
decides what the reply says about the change: a pass closes the ticket and the
linked issues, a failure reopens them.

Closing happens here rather than at merge. The two are different claims --
"merged" says the code landed, "done" says it works -- and this pipeline exists
because a human still has to confirm the second. Closing optimistically at
merge is right whenever QA passes and wrong in both cases that need attention:
a rejected change and an unanswered thread. A ticket closed while a bug is
still live disappears from the board, which is the one place anyone would look
for it. The cost of moving it here is that a thread nobody answers leaves the
ticket open, so `worklist` surfaces a stale QA thread as something waiting on
you.

The classifier runs on a bare LLM with no tools bound. Reply text is written by
whoever can post in the channel, and the outcome drives real state changes, so
the model returns a verdict and nothing more; acting on that verdict is the
caller's job.

Ambiguity is a first-class outcome. "The retry works but the timeout is 30s
now?" is neither pass nor fail, and guessing either way is worse than asking:
a wrong reopen reverses a merge decision, a wrong dismissal buries a real bug.
The PR author is notified instead.
"""

import json
import logging
from enum import Enum

import httpx

from app.services import project_board
from app.services.llm import get_llm
from app.services.merge_actions import close_github_issue, transition_jira_ticket

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    """What a QA reply says about the change."""

    WORKS = "works"
    BROKEN = "broken"
    UNCLEAR = "unclear"
    # Chatter that is not feedback at all ("thanks!", "looking now").
    NOT_FEEDBACK = "not_feedback"


CLASSIFIER_PROMPT = """A tester replied to a notification about a merged code change.
Decide what their reply says about whether the change works.

Reply to classify:
---
{reply}
---

Answer with one verdict:
- "broken": the tester reports something not working, a regression, or a failure
- "works": the tester confirms it works or passes testing
- "unclear": mixed, partial, a question, or a new concern that is not clearly \
a failure of this change
- "not_feedback": acknowledgement or chatter with no test result \
("thanks", "looking at it now", "on it")

Choose "unclear" whenever you are unsure. A wrong "broken" reverses a merge \
decision and a wrong "works" buries a real bug, so ambiguity must be surfaced \
to a human rather than guessed.

Return ONLY JSON:
{{"verdict": "broken|works|unclear|not_feedback", "reason": "one short sentence"}}"""


async def classify_reply(reply_text: str) -> tuple[Verdict, str]:
    """
    Decide what a QA reply reports.

    Returns:
        (verdict, one-line reason). Unparseable output yields UNCLEAR, so a
        model failure surfaces to a human rather than triggering an action.
    """
    if not reply_text or not reply_text.strip():
        return Verdict.NOT_FEEDBACK, "Empty reply"

    try:
        llm = get_llm(temperature=0)
        response = await llm.ainvoke(CLASSIFIER_PROMPT.format(reply=reply_text[:2000]))
        content = response.content
        text = (content if isinstance(content, str) else str(content)).strip()

        # Local models frequently wrap JSON in a markdown fence.
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            text = text.strip()

        payload = json.loads(text)
        verdict = Verdict(str(payload.get("verdict", "unclear")).lower())
        return verdict, str(payload.get("reason", ""))[:200]

    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("QA classifier returned unusable output: %s", e)
        return Verdict.UNCLEAR, "Could not interpret the reply"
    except Exception as e:
        logger.warning("QA classifier failed: %s", e)
        return Verdict.UNCLEAR, f"Classifier unavailable: {e}"


async def reopen_jira_ticket(
    jira_config: dict,
    ticket_key: str,
    reason: str,
    reopen_status: str = "In Progress",
) -> tuple[bool, str]:
    """
    Move a ticket back into work after a failed test, and record why.

    This is the one place a backwards transition is correct, so it deliberately
    bypasses the forward-only guard in merge_actions.
    """
    api_token = jira_config.get("api_key", "")
    credentials = jira_config.get("credentials", {}) or {}
    email = credentials.get("email", "")
    base_url = (credentials.get("url", "") or "").rstrip("/")

    if not (api_token and email and base_url):
        return False, "Jira is not fully configured"

    async with httpx.AsyncClient(timeout=30.0, auth=(email, api_token)) as client:
        transitions = await client.get(
            f"{base_url}/rest/api/3/issue/{ticket_key}/transitions",
            headers={"Accept": "application/json"},
        )
        if transitions.status_code != 200:
            return False, f"Could not list transitions for {ticket_key}"

        transition_id = None
        for transition in transitions.json().get("transitions", []):
            name = transition.get("name", "").lower()
            to_name = (transition.get("to") or {}).get("name", "").lower()
            if reopen_status.lower() in (name, to_name):
                transition_id = transition.get("id")
                break

        if not transition_id:
            return False, f"No transition to '{reopen_status}' available"

        applied = await client.post(
            f"{base_url}/rest/api/3/issue/{ticket_key}/transitions",
            json={"transition": {"id": transition_id}},
            headers={"Content-Type": "application/json"},
        )
        if applied.status_code not in (200, 204):
            return False, f"Transition rejected ({applied.status_code})"

        # Leave the tester's words on the ticket; a bare status flip loses why.
        await client.post(
            f"{base_url}/rest/api/3/issue/{ticket_key}/comment",
            json={
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": f"Reopened after QA feedback: {reason}",
                        }],
                    }],
                }
            },
            headers={"Content-Type": "application/json"},
        )

    return True, f"{ticket_key} reopened ({reopen_status})"


async def reopen_github_issue(
    token: str, repo: str, issue_number: int, reason: str
) -> tuple[bool, str]:
    """Reopen a closed issue and record the QA feedback that caused it."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        reopened = await client.patch(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}",
            headers=headers,
            json={"state": "open", "state_reason": "reopened"},
        )
        if reopened.status_code != 200:
            return False, f"Could not reopen #{issue_number}"

        await client.post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            headers=headers,
            json={"body": f"Reopened after QA feedback: {reason}"},
        )

    return True, f"Reopened #{issue_number}"


async def notify_pr_author(
    slack_config: dict,
    channel: str,
    thread_ts: str | None,
    pr_url: str,
    reply_text: str,
    reason: str,
) -> bool:
    """
    Ask a human to judge an ambiguous reply.

    Posted into the same thread so the question sits with the reply it is about.
    """
    credentials = slack_config.get("credentials", {}) or {}
    bot_token = credentials.get("bot_token") or slack_config.get("api_key", "")
    if not bot_token:
        return False

    text = (
        f":grey_question: Unclear QA feedback on <{pr_url}|this PR> — "
        f"someone should take a look.\n"
        f"> {reply_text[:300]}\n"
        f"_{reason}_\n"
        f"No ticket was changed."
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={
                "channel": channel,
                "text": text,
                **({"thread_ts": thread_ts} if thread_ts else {}),
            },
        )
        return bool(response.json().get("ok"))


async def handle_qa_reply(
    reply_text: str,
    integration_configs: dict[str, dict],
    repo: str,
    pr_url: str,
    ticket_keys: list[str],
    issue_numbers: list[int],
    slack_channel: str | None = None,
    thread_ts: str | None = None,
    reopen_status: str = "In Progress",
    done_status: str = "Done",
    pr_number: int = 0,
    close_on_signoff: bool = False,
    project_board_sync: bool = True,
    project_column_map: dict[str, str] | None = None,
    db=None,
    owner_id: int | None = None,
    review_slack_channel: str | None = None,
) -> dict:
    """
    Act on a QA reply.

    A pass closes the work item and a failure reopens it. Both directions live
    here because the testing team's verdict is what the ticket state is meant
    to reflect -- the merge only says the code landed.

    Args:
        done_status: Jira status a passing sign-off moves the ticket to.
        pr_number: Named in the GitHub issue comment, so the close records
            which change was verified.
        db: A session, when the caller has one. Only the autonomous retry
            needs it, and it stays optional so a caller that has no session --
            or a deployment with no authoring driver -- keeps working exactly
            as before.

    Returns:
        A summary of the verdict and anything that changed.
    """
    verdict, reason = await classify_reply(reply_text)

    outcome: dict = {
        "verdict": verdict.value,
        "reason": reason,
        "reopened_tickets": [],
        "reopened_issues": [],
        "closed_tickets": [],
        "closed_issues": [],
        "board_moves": [],
        "author_notified": False,
        "errors": [],
    }

    if verdict == Verdict.NOT_FEEDBACK:
        return outcome

    if verdict == Verdict.WORKS:
        # The board is moved on any sign-off, including when the merge already
        # closed the work item. Closing is guarded because re-closing could undo
        # a deliberate reopen; moving a card to the done column cannot -- the
        # tester just said the change works, which is the most authoritative
        # statement anything in this pipeline produces about that.
        github_token = (integration_configs.get("github") or {}).get("api_key")
        if project_board_sync and github_token:
            outcome["board_moves"] = await project_board.sync_issues(
                github_token, repo, issue_numbers, "done",
                column_map=project_column_map,
            )

        # Only when the merge deferred closing to here. Otherwise the work item
        # was already closed at merge and re-closing it would either no-op or,
        # on a ticket someone deliberately reopened, undo their decision.
        if not close_on_signoff:
            return outcome

        # Sign-off is what closes the work item, not the merge. "Merged" and
        # "done" are different claims, and this pipeline exists because they
        # are: closing at merge asserts completion at the one moment the
        # pipeline itself does not believe it, and a ticket closed while a bug
        # is still live is invisible -- it drops off the board, which is where
        # anyone would look for it.
        jira_config = integration_configs.get("jira")
        if jira_config:
            for key in ticket_keys:
                try:
                    ok, detail = await transition_jira_ticket(
                        jira_config, key, done_status
                    )
                    target = "closed_tickets" if ok else "errors"
                    outcome[target].append(detail)
                except Exception as e:
                    outcome["errors"].append(f"{key}: {e}")

        if github_token:
            for number in issue_numbers:
                try:
                    ok, detail = await close_github_issue(
                        github_token, repo, number, pr_number
                    )
                    target = "closed_issues" if ok else "errors"
                    outcome[target].append(detail)
                except Exception as e:
                    outcome["errors"].append(f"#{number}: {e}")

        return outcome

    if verdict == Verdict.UNCLEAR:
        if slack_channel and "slack" in integration_configs:
            outcome["author_notified"] = await notify_pr_author(
                integration_configs["slack"], slack_channel, thread_ts,
                pr_url, reply_text, reason,
            )
        return outcome

    # Verdict.BROKEN -- undo the merge-time state changes.
    jira_config = integration_configs.get("jira")
    if jira_config:
        for key in ticket_keys:
            try:
                ok, detail = await reopen_jira_ticket(
                    jira_config, key, reason, reopen_status
                )
                target = "reopened_tickets" if ok else "errors"
                outcome[target].append(detail)
            except Exception as e:
                outcome["errors"].append(f"{key}: {e}")

    github_token = (integration_configs.get("github") or {}).get("api_key")

    # The one legitimate backwards move on the board. Everywhere else a
    # regression is refused, because the stage is derived from live state that
    # can wobble and a card a human dragged forward must not be walked back by
    # a refresh. A rejection is different: a tester has explicitly said the
    # change does not work, the ticket is being reopened on the strength of it,
    # and leaving the card in a done column would contradict the ticket.
    if project_board_sync and github_token:
        for number in issue_numbers:
            try:
                move = await project_board.move_card(
                    github_token, repo, number, "in_progress",
                    column_map=project_column_map,
                    allow_backwards=True,
                )
            except Exception as e:
                outcome["errors"].append(f"#{number}: board update failed: {e}")
                continue
            if move.error:
                outcome["errors"].append(f"#{number}: {move.error}")
            elif move.moved:
                outcome["board_moves"].append(f"#{number}: {move.detail}")

    if github_token:
        for number in issue_numbers:
            try:
                ok, detail = await reopen_github_issue(
                    github_token, repo, number, reason
                )
                target = "reopened_issues" if ok else "errors"
                outcome[target].append(detail)
            except Exception as e:
                outcome["errors"].append(f"#{number}: {e}")

    # The second authoring trigger, fired after the reopen rather than before
    # it: the ticket must be back in play whether or not an agent picks it up,
    # and a retry that raised before the reopen would leave a rejected change
    # marked done.
    #
    # This opens a *new* pull request, which is exactly what
    # `work_item.resolve_key` and `sibling_reviews` were built for -- the new
    # PR inherits the rejection history for free, so the fix opens carrying the
    # reason the work came back.
    if db is not None and owner_id is not None and ticket_keys:
        await _maybe_author_fix(
            db,
            owner_id=owner_id,
            repo=repo,
            pr_number=pr_number,
            ticket_keys=ticket_keys,
            rejection=reply_text,
            integration_configs=integration_configs,
            review_slack_channel=review_slack_channel or slack_channel,
            outcome=outcome,
        )

    return outcome


async def _maybe_author_fix(
    db,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_keys: list[str],
    rejection: str,
    integration_configs: dict,
    review_slack_channel: str | None,
    outcome: dict,
) -> None:
    """
    Take an authoring swing at a rejected change, if the work item allows one.

    Runs identically for a Slack reply and a Gmail one -- the channel a tester
    happened to choose must not change what happens next.

    Swallows its own failure into `outcome["errors"]`: the reopen has already
    happened and is the part that matters, and a driver that could not start
    must not make a completed reopen read as a failed one.
    """
    from app.services import authoring_flow
    from app.services.agent_settings import resolve_settings

    for key in ticket_keys:
        try:
            from app import models

            registration = db.query(models.RepoWebhook).filter(
                models.RepoWebhook.repo == repo,
                models.RepoWebhook.owner_id == owner_id,
            ).first()
            settings = resolve_settings(db, owner_id, registration, ticket_key=key)
            if settings.authoring_mode != "autonomous":
                continue

            result = await authoring_flow.maybe_retry(
                db,
                owner_id=owner_id,
                repo=repo,
                pr_number=pr_number,
                ticket_key=key,
                settings=settings,
                integration_configs=integration_configs,
                trigger="qa_rejected",
                slack_channel=review_slack_channel,
                rejection=rejection,
            )
            if result is not None and result.opened:
                outcome.setdefault("authored", []).append(
                    f"{key}: opened #{result.pr_number}"
                )
        except Exception as e:
            outcome["errors"].append(f"{key}: authoring retry failed: {e}")
