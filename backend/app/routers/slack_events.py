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
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db
from app.dependencies import get_integration_configs
from app.services import availability as availability_service
from app.services import comms_log, interruption, report_sync
from app.services.agent_settings import resolve_settings
from app.services.qa_feedback import handle_qa_reply
from app.services.review_flow import post_review_notification

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
    if not channel:
        return {"ok": True}

    # The `thread_ts` requirement is relaxed for the interruption branch only:
    # a top-level channel mention carries none, and being pinged in a channel
    # is the ordinary case. The QA lookup below still requires one, because a
    # QA reply is by construction a threaded reply.
    if not thread_ts:
        return await _maybe_answer_interruption(db, event, channel, None)

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
        # Not a QA reply. Placed *after* the lookup, deliberately: a QA reply
        # must reach `qa_feedback` and never be intercepted by the auto-
        # responder. The `bot_id` / `subtype` early-return above protects this
        # path too -- the busy reply is posted by the bot, and without that
        # guard it would answer itself, the same self-triggering failure the
        # `@locus ignore` marker rule prevents.
        return await _maybe_answer_interruption(db, event, channel, thread_ts)

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
            project_board_sync=settings.project_board_sync,
            project_column_map=settings.project_column_map,
            db=db,
            owner_id=thread.owner_id,
            review_slack_channel=settings.review_slack_channel,
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

    # The tester's answer is the last thing that happens to a change, and it is
    # exactly what someone reading the record later wants: whether it actually
    # worked. Rewritten after the reply is logged so the document includes it.
    await report_sync.refresh(
        db, owner_id=thread.owner_id, repo=thread.repo,
        pr_number=thread.pr_number,
        integration_configs=integration_configs,
    )

    logger.info(
        "QA reply on %s#%s: %s (%s)",
        thread.repo, thread.pr_number, outcome["verdict"], outcome["reason"],
    )

    return {"ok": True, "verdict": outcome["verdict"]}


async def _maybe_answer_interruption(
    db: Session,
    event: dict,
    channel: str,
    thread_ts: str | None,
) -> dict:
    """
    Answer somebody who reached the owner while they were booked.

    Off by default, and it stays quiet in every case it is not certain about:
    no enabled agent, no mention of this user, a calendar that cannot be read,
    or a thread already answered today.

    Never holds a pipeline message. This branch only ever *adds* a reply to a
    message nothing else claimed; the review request, the QA brief and the
    merge notification are sent by their own paths regardless of what the
    calendar says.
    """
    text = event.get("text", "") or ""
    mentioned = re.findall(r"<@([A-Z0-9]+)>", text)
    if not mentioned:
        return {"ok": True}

    rows = db.query(models.TimeAgentSettings).filter(
        models.TimeAgentSettings.enabled == 1,
        models.TimeAgentSettings.auto_reply_busy == 1,
        models.TimeAgentSettings.slack_member_id.in_(mentioned),
    ).all()
    if not rows:
        return {"ok": True}

    settings = rows[0]
    user = db.query(models.User).filter(models.User.id == settings.owner_id).first()
    if user is None:
        return {"ok": True}

    availability = await availability_service.for_user(db, user, settings)
    if availability.state == "free":
        # Nothing to say. An auto-responder that fires when you are reachable
        # is noise from the first message.
        return {"ok": True}

    importance, source = await interruption.judge(
        db, owner_id=user.id, participant=event.get("user"), text=text
    )

    if interruption.already_replied(
        db, owner_id=user.id, thread_ts=thread_ts, channel=channel
    ):
        # Recorded but not answered: the strip should still show that somebody
        # reached them, and a second reply is what gets the bot muted.
        interruption.record(
            db, owner_id=user.id, participant=event.get("user"),
            thread_ts=thread_ts, channel=channel, availability=availability,
            importance=importance, importance_source=source,
            replied=False, reply_body=None, excerpt=text,
        )
        return {"ok": True}

    slots = _free_slots(db, user, settings, availability, importance)
    body = interruption.compose_reply(
        availability, timezone=user.timezone, importance=importance, slots=slots
    )

    sent = False
    try:
        configs = get_integration_configs(db, user.id)
        if "slack" in configs:
            sent = await post_review_notification(
                configs["slack"], channel, body, thread_ts=thread_ts
            )
    except Exception as e:
        logger.warning("Could not post a busy reply: %s", e)

    interruption.record(
        db, owner_id=user.id, participant=event.get("user"),
        thread_ts=thread_ts, channel=channel, availability=availability,
        importance=importance, importance_source=source,
        # `replied` records what actually reached the channel. A failed send
        # must not start the once-a-day cooldown, or a Slack outage silences
        # the responder for a day.
        replied=sent,
        reply_body=body if sent else None,
        excerpt=text,
    )

    return {"ok": True}


def _free_slots(db, user, settings, availability, importance: str) -> list:
    """
    Candidate times to offer, on an important interruption only.

    Sent as *options*, never as a booking: writing to somebody else's calendar
    from an automated reply is a write nobody approved. A failure returns
    nothing, so the reply degrades to the plain version rather than not going
    out.
    """
    if importance != "important" or availability.state == "off_hours":
        return []

    try:
        from app.routers.schedule import events_from_raw
        from app.services import calendar as calendar_service
        from app.services.scheduler import find_free_slot

        configs = get_integration_configs(db, user.id)
        if "calendar" not in configs:
            return []

        calendar_service.get_calendar_tools(
            credentials=configs["calendar"].get("credentials", {}),
            timezone=user.timezone,
        )
        raw, error = calendar_service.fetch_events("today", "in 3 days")
        if error:
            return []

        events = events_from_raw(db, user, raw)
        after = availability.next_free or availability.until
        if after is None:
            return []

        slot = find_free_slot(30, after, events)
        return [slot] if slot else []
    except Exception as e:
        logger.debug("Could not find free slots for an interruption: %s", e)
        return []
