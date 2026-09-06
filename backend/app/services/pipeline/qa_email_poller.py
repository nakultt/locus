"""
Gmail poller for QA replies.

Slack replies arrive by webhook; email cannot. Gmail's push notifications
require a Cloud Pub/Sub topic and a `users.watch` registration that expires
every seven days, so a renewal job is needed either way -- at which point
polling is the simpler mechanism with fewer moving parts.

Replies are matched by the `In-Reply-To` header against the Message-ID stored
when the notification was sent. Subject matching would break the moment someone
edits the subject line or their client rewrites it.
"""

import base64
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx

from app import models
from app.core.database import SessionLocal
from app.core.dependencies import get_integration_configs
from app.services import integration_health
from app.services.integrations import google_auth
from app.services.pipeline import comms_log, report_sync
from app.services.pipeline.agent_settings import resolve_settings
from app.services.pipeline.pr_agent import work_item_keys_for
from app.services.pipeline.qa_feedback import handle_qa_reply

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"

# How often to check for replies. QA feedback is not latency-sensitive; a few
# minutes is imperceptible and keeps well clear of Gmail's quota.
POLL_INTERVAL_SECONDS = 180

# Threads older than this are no longer watched. A reply weeks after a merge is
# almost certainly about something else.
THREAD_MAX_AGE_DAYS = 14


def _header(payload: dict, name: str) -> str:
    """Read a header from a Gmail message payload, case-insensitively."""
    target = name.lower()
    for header in payload.get("payload", {}).get("headers", []):
        if header.get("name", "").lower() == target:
            return header.get("value", "")
    return ""


def _plain_text(payload: dict) -> str:
    """
    Extract the plain-text body from a Gmail message.

    Walks MIME parts depth-first and takes the first text/plain it finds;
    text/html is skipped because a classifier reading markup is noisier than
    one reading prose.
    """

    def walk(part: dict) -> str | None:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode(
                    "utf-8", errors="replace"
                )
        for child in part.get("parts", []) or []:
            found = walk(child)
            if found:
                return found
        return None

    return (walk(payload.get("payload", {})) or "").strip()


def strip_quoted_reply(text: str) -> str:
    """
    Drop the quoted original from a reply.

    Without this the classifier reads our own "Reply if something does not
    work" boilerplate back and can classify the quote instead of the answer.
    """
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Gmail's attribution line, then everything below it, is the quote.
        if stripped.startswith(">"):
            continue
        if stripped.startswith("On ") and stripped.endswith("wrote:"):
            break
        # Common client separators.
        if stripped in ("--", "---", "-----Original Message-----"):
            break
        lines.append(line)

    return "\n".join(lines).strip()


async def fetch_replies(access_token: str, since: datetime) -> list[dict]:
    """
    Fetch recent inbox messages that are replies.

    Args:
        access_token: Google OAuth access token
        since: Only consider messages newer than this

    Returns:
        Message payloads, newest first.
    """
    after = int(since.timestamp())
    query = f"in:inbox after:{after}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {access_token}"}

        listing = await client.get(
            f"{GMAIL_API}/messages",
            headers=headers,
            params={"q": query, "maxResults": 25},
        )
        if listing.status_code != 200:
            logger.debug("Gmail list failed: %s", listing.status_code)
            return []

        messages = []
        for entry in listing.json().get("messages", []):
            detail = await client.get(
                f"{GMAIL_API}/messages/{entry['id']}",
                headers=headers,
                params={"format": "full"},
            )
            if detail.status_code == 200:
                messages.append(detail.json())

    return messages


async def poll_once() -> int:
    """
    Check for QA replies and act on any found.

    Returns:
        How many replies were processed.
    """
    db = SessionLocal()
    processed = 0

    try:
        cutoff = datetime.now(UTC) - timedelta(days=THREAD_MAX_AGE_DAYS)

        # Only users with an unresolved emailed thread are worth polling.
        open_threads = (
            db.query(models.QAThread)
            .filter(
                models.QAThread.resolved == 0,
                models.QAThread.email_message_id.isnot(None),
                models.QAThread.created_at >= cutoff,
            )
            .all()
        )
        if not open_threads:
            return 0

        by_owner: dict[int, dict[str, models.QAThread]] = {}
        for thread in open_threads:
            by_owner.setdefault(thread.owner_id, {})[thread.email_message_id] = thread

        for owner_id, threads in by_owner.items():
            # Refreshed, not read raw. This loop runs indefinitely and a Google
            # access token lives an hour, so reading the stored one meant every
            # poll after the first hour failed -- which looks exactly like the
            # testing team not replying.
            configs = get_integration_configs(db, owner_id)
            access_token = await google_auth.valid_access_token(
                configs.get("gmail") or {},
                db=db, user_id=owner_id, service="gmail",
            )
            if not access_token:
                continue

            try:
                messages = await fetch_replies(access_token, cutoff)
            except Exception as e:
                # Swallowed so one user's dead credential does not stop the
                # loop for everyone -- but recorded, because a token that
                # expired days ago is otherwise invisible: QA replies simply
                # stop arriving, which reads as nobody replying.
                logger.debug("Gmail poll failed for user %s: %s", owner_id, e)
                integration_health.record_failure(
                    db, owner_id=owner_id, service="gmail", error=str(e)
                )
                continue

            integration_health.record_success(
                db, owner_id=owner_id, service="gmail"
            )

            for message in messages:
                # In-Reply-To is the reliable link. References is checked too,
                # since some clients only populate that on deep threads.
                in_reply_to = _header(message, "In-Reply-To")
                references = _header(message, "References")

                thread = threads.get(in_reply_to)
                if not thread:
                    thread = next(
                        (t for mid, t in threads.items() if mid and mid in references),
                        None,
                    )
                if not thread:
                    continue

                body = strip_quoted_reply(_plain_text(message))
                if not body:
                    continue

                # The same function the Gmail fetch above used, not a local
                # copy of its loop: the copy that was here omitted the Google
                # client id and secret, so the report export downstream could
                # not refresh a token older than an hour.
                integration_configs = get_integration_configs(db, owner_id)

                # A sign-off by email closes the work item exactly as one in
                # Slack does; the channel the tester chose must not change the
                # outcome.
                registration = (
                    db.query(models.RepoWebhook)
                    .filter(
                        models.RepoWebhook.repo == thread.repo,
                        models.RepoWebhook.owner_id == thread.owner_id,
                    )
                    .first()
                )
                settings = resolve_settings(db, thread.owner_id, registration)

                thread_tickets = json.loads(thread.ticket_keys_json or "[]")
                thread_issues = json.loads(thread.issue_numbers_json or "[]")
                work_keys = work_item_keys_for(
                    thread.repo, thread_tickets, thread_issues
                )

                try:
                    outcome = await handle_qa_reply(
                        reply_text=body,
                        integration_configs=integration_configs,
                        repo=thread.repo,
                        pr_url=thread.pr_url,
                        ticket_keys=thread_tickets,
                        issue_numbers=thread_issues,
                        slack_channel=thread.slack_channel,
                        thread_ts=thread.slack_thread_ts,
                        done_status=settings.jira_done_status,
                        pr_number=thread.pr_number,
                        close_on_signoff=settings.close_on_qa_signoff,
                        project_board_sync=settings.project_board_sync,
                        project_column_map=settings.project_column_map,
                        db=db,
                        owner_id=thread.owner_id,
                        review_slack_channel=settings.review_slack_channel,
                    )
                except Exception:
                    logger.exception("QA email reply handling failed for %s", thread.repo)
                    continue

                # Stamped with the work item, exactly as the Slack path does:
                # the channel a tester happened to reply through must not
                # change what the record says, and everything that reads a
                # rejection back matches on `ticket_key`.
                comms_log.record(
                    db, owner_id=owner_id, repo=thread.repo,
                    pr_number=thread.pr_number,
                    loop="qa", direction="received", channel="email",
                    participant=_header(message, "From") or None,
                    target=thread.pr_url,
                    body=body,
                    outcome=outcome["verdict"],
                    ticket_key=work_keys[0] if work_keys else None,
                )

                processed += 1
                logger.info(
                    "QA email reply on %s#%s: %s (%s)",
                    thread.repo, thread.pr_number,
                    outcome["verdict"], outcome["reason"],
                )

                if outcome["verdict"] == "works":
                    thread.resolved = 1
                    db.commit()

                # The tester's answer is the last thing that happens to a
                # change, and it is exactly what someone reading the record
                # later wants: whether it actually worked.
                #
                # The Slack path has always done this. This one did not, so
                # the report was complete or missing its ending depending on
                # which channel the tester happened to reply through -- and
                # a tester who replies by email is the ordinary case, since
                # the brief reaches them there. `close_on_qa_signoff` is
                # careful to behave identically across both channels for
                # exactly this reason; the document has to as well.
                #
                # Failure is swallowed: refresh already returns the stored URL
                # rather than raising, and a sign-off that genuinely happened
                # must not be reported as failed because a document could not
                # be rewritten.
                try:
                    await report_sync.refresh(
                        db, owner_id=thread.owner_id, repo=thread.repo,
                        pr_number=thread.pr_number,
                        integration_configs=integration_configs,
                    )
                except Exception:
                    logger.warning(
                        "Could not refresh the report for %s#%s after a QA email",
                        thread.repo, thread.pr_number, exc_info=True,
                    )

        return processed

    finally:
        db.close()
