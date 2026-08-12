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
from app.services.qa_feedback import handle_qa_reply

logger = logging.getLogger(__name__)

router = APIRouter()

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

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

    if not SLACK_SIGNING_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLACK_SIGNING_SECRET is not configured",
        )

    if not verify_slack_signature(
        raw_body, x_slack_request_timestamp or "", x_slack_signature or "",
        SLACK_SIGNING_SECRET,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature"
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed payload"
        ) from e

    # Slack verifies a new endpoint by asking it to echo a challenge.
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

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

    thread = db.query(models.QAThread).filter(
        models.QAThread.slack_thread_ts == thread_ts,
        models.QAThread.slack_channel == channel,
    ).first()

    if not thread:
        return {"ok": True}

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
        )
    except Exception as e:
        logger.exception("QA reply handling failed for %s", thread.repo)
        return {"ok": True, "error": str(e)}

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
