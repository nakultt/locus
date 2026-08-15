"""
Slack Events API receiver.

Handles QA replies to merge notifications. When a tester replies in the thread
Locus posted, the reply is classified and -- if it reports a failure -- the
Jira ticket and linked GitHub issues are reopened.

Like the GitHub webhook this cannot use a JWT: Slack has no user token to
present. Authenticity comes from Slack's v0 HMAC signature over the raw body,
verified before the payload is parsed.
"""

import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db
from app.services import comms_log
from app.services.agent_settings import resolve_settings
from app.services.qa_feedback import handle_qa_reply

logger = logging.getLogger(__name__)

router = APIRouter()

def _signing_secret() -> str:
    """
    Read the secret per request rather than binding it at import.

    Setting up the subscription is an edit-env-then-retry loop, and a value
    captured at import means the retry keeps failing until the server is
    restarted -- with nothing on screen explaining why.
    """
    return os.getenv("SLACK_SIGNING_SECRET", "")

# Slack rejects its own replays after 5 minutes; matching that window stops a
# captured request being replayed later.
MAX_TIMESTAMP_SKEW_SECONDS = 60 * 5


def verify_slack_signature(
    body: bytes, timestamp: str, signature: str, secret: str
) -> bool:
    """
    Verify Slack's v0 request signature.

    Args:
        body: Raw request body, exactly as received
        timestamp: X-Slack-Request-Timestamp header
        signature: X-Slack-Signature header
        secret: The app's signing secret

    Returns:
        True if the signature is valid and recent.
    """
    if not (secret and timestamp and signature):
        return False

    try:
        if abs(time.time() - int(timestamp)) > MAX_TIMESTAMP_SKEW_SECONDS:
            return False
    except ValueError:
        return False

    basestring = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected, signature)


@router.post(
    "/slack",
    summary="Slack Events API receiver",
)
async def slack_events(
    request: Request,
    x_slack_request_timestamp: str = Header(None),
    x_slack_signature: str = Header(None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Receive a Slack event.

    Slack retries any response slower than 3 seconds, so classification runs
    only for messages that match a tracked QA thread -- everything else returns
    immediately.
    """
    raw_body = await request.body()
    secret = _signing_secret()

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed payload"
        ) from e

    # Slack verifies a new endpoint by asking it to echo a challenge, and it
    # does so before the app is fully configured. Answer it ahead of the
    # signature gate: the challenge carries no data and grants no access, so
    # echoing it is safe, and refusing it makes the subscription unsavable --
    # which is the state that blocks every signed event that would follow.
    if payload.get("type") == "url_verification":
        if not secret:
            logger.warning(
                "Answering a Slack url_verification challenge while "
                "SLACK_SIGNING_SECRET is unset. Set it before real events "
                "arrive; they will be rejected until it is."
            )
        return {"challenge": payload.get("challenge", "")}

    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLACK_SIGNING_SECRET is not configured",
        )

    if not verify_slack_signature(
        raw_body, x_slack_request_timestamp or "", x_slack_signature or "",
        secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature"
        )

    event = payload.get("event", {})

    if event.get("type") != "message":
        return {"ok": True}

    # Ignore our own messages and edits/deletions, or the bot's QA notification
    # would classify itself and loop.
    if event.get("bot_id") or event.get("subtype"):
        return {"ok": True}

    thread_ts = event.get("thread_ts")
    channel = event.get("channel")
    if not thread_ts or not channel:
        return {"ok": True}

    # The timestamp alone is effectively unique -- it is a per-message clock
    # value, not a per-channel counter -- so match on it and use the channel
    # only to disambiguate. Rows written before the resolved channel id was
    # stored hold a "#web" style name that no inbound event will ever equal.
    candidates = db.query(models.QAThread).filter(
        models.QAThread.slack_thread_ts == thread_ts,
    ).all()

    thread = next(
        (t for t in candidates if t.slack_channel == channel),
        candidates[0] if candidates else None,
    )

    if not thread:
        return {"ok": True}

    # Backfill the id so the exact match works from here on.
    if thread.slack_channel != channel:
        thread.slack_channel = channel
        db.commit()

    integration_configs: dict[str, dict] = {}
    for integration in crud.get_user_integrations(db, thread.owner_id):
        config: dict = {}
        api_key = crud.get_integration_key(db, thread.owner_id, integration.service_name)
        if api_key:
            config["api_key"] = api_key
        credentials = crud.get_integration_credentials(
            db, thread.owner_id, integration.service_name
        )
        if credentials:
            config["credentials"] = credentials
        if config:
            integration_configs[integration.service_name] = config

    # A sign-off closes the work item, so this needs the same resolved settings
    # the merge path used -- which status counts as done, and whether closing
    # was deferred to here at all.
    registration = (
        db.query(models.RepoWebhook)
        .filter(
            models.RepoWebhook.repo == thread.repo,
            models.RepoWebhook.owner_id == thread.owner_id,
        )
        .first()
    )
    settings = resolve_settings(db, thread.owner_id, registration)

    try:
        outcome = await handle_qa_reply(
            reply_text=event.get("text", ""),
            integration_configs=integration_configs,
            repo=thread.repo,
            pr_url=thread.pr_url,
            ticket_keys=json.loads(thread.ticket_keys_json or "[]"),
            issue_numbers=json.loads(thread.issue_numbers_json or "[]"),
            slack_channel=channel,
            thread_ts=thread_ts,
            done_status=settings.jira_done_status,
            pr_number=thread.pr_number,
            close_on_signoff=settings.close_on_qa_signoff,
        )
    except Exception as e:
        logger.exception("QA reply handling failed for %s", thread.repo)
        return {"ok": True, "error": str(e)}

    # The tester's own words, with the verdict the classifier reached. Stored
    # together because "why did it reopen the ticket" is only answerable if
    # both are visible side by side.
    comms_log.record(
        db, owner_id=thread.owner_id, repo=thread.repo,
        pr_number=thread.pr_number,
        loop="qa", direction="received", channel="slack",
        participant=event.get("user"),
        target=channel,
        body=event.get("text", ""),
        outcome=outcome["verdict"],
    )

    if outcome["verdict"] == "broken":
        thread.resolved = 0  # Back in play until a later reply says otherwise.
        db.commit()
    elif outcome["verdict"] == "works":
        thread.resolved = 1
        db.commit()

    logger.info(
        "QA reply on %s#%s: %s (%s)",
        thread.repo, thread.pr_number, outcome["verdict"], outcome["reason"],
    )

    return {"ok": True, "verdict": outcome["verdict"]}
