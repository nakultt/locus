"""
Answering for the owner when they are booked.

Where an interruption comes from, whether it matters, and what gets said back.

Three rules shape all of it. Importance is decided **deterministically first**,
because "your reviewer, mid-round" is a fact and a classifier's opinion is not.
The reply carries a state and a time and nothing else, because it is posted
into a channel other people read. And it fires **once per thread per day**: a
repeating auto-responder gets the bot muted, and a muted bot takes the review
pings and the QA threads down with it.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app import models, schemas
from app.core.datetimes import resolve_timezone

logger = logging.getLogger(__name__)

# One reply per thread per day. Load-bearing, not polish.
REPLY_COOLDOWN_HOURS = 24

CLASSIFIER_PROMPT = """Someone sent this message to a colleague who is currently \
unavailable. Decide how urgent it is.

Reply with JSON only:
{{"importance": "important" | "routine" | "unclear", "reason": "<one line>"}}

- "important": it blocks them, or asks for a decision they are waiting on.
- "routine": everything else, including questions that can wait an hour.
- "unclear": you genuinely cannot tell.

The message:
{message}"""


def find_work_item_keys(text: str) -> list[str]:
    """
    Work item keys named in a message: "LOC-42", "#7", "acme/api#7".

    A regex over a fixed shape, deliberately -- the same reasoning as the
    `@locus ignore` parser. This decides whether somebody's message escalates,
    and a model deciding that is a model deciding when to interrupt a focus
    block.
    """
    keys = re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", text or "")
    keys += re.findall(r"\b[\w.-]+/[\w.-]+#\d+\b", text or "")
    return list(dict.fromkeys(keys))


def sender_is_reviewer(db: Session, owner_id: int, participant: str | None) -> bool:
    """
    Whether this person is reviewing something of yours right now.

    A reviewer mid-round is the clearest case there is: they are blocked on you
    by construction, and the whole review loop exists to keep that from
    stalling.
    """
    if not participant:
        return False

    handle = participant.lstrip("@").lower()
    open_states = ("awaiting_review", "changes_requested", "approved")

    reviews = db.query(models.PRReview).filter(
        models.PRReview.owner_id == owner_id,
        models.PRReview.state.in_(open_states),
    ).all()

    for review in reviews:
        for name in (review.last_reviewer, review.author):
            if name and name.lstrip("@").lower() == handle:
                return True
    return False


def names_blocked_work(db: Session, owner_id: int, text: str) -> bool:
    """Whether the message names a work item the worklist reports blocked on you."""
    keys = find_work_item_keys(text)
    if not keys:
        return False

    try:
        from app.services.pipeline import worklist

        blocked = {
            task.key for task in worklist.build(db, owner_id=owner_id).needs_you
        }
    except Exception as exc:
        logger.debug("Worklist unavailable while judging an interruption: %s", exc)
        return False

    return any(key in blocked for key in keys)


async def classify(text: str) -> tuple[str, str]:
    """
    The fallback judgement, when neither deterministic test fired.

    **No tools bound**, following `qa_feedback.classify_reply` exactly: this
    model reads a message written by anyone who can post in a channel, and it
    returns a label and nothing else.

    `unclear` resolves to **routine**. The busy reply goes out either way, so
    the two failure modes are "an important message got a plain reply" and "a
    focus block was interrupted over nothing". The second is worse.
    """
    if not text or not text.strip():
        return "routine", "Empty message"

    try:
        from app.services.chat.llm import get_llm, message_text

        llm = get_llm(temperature=0)
        response = await llm.ainvoke(CLASSIFIER_PROMPT.format(message=text[:2000]))
        raw = message_text(response).strip()

        # Local models frequently wrap JSON in a markdown fence.
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            raw = raw.strip()

        payload = json.loads(raw)
        label = str(payload.get("importance", "unclear")).lower()
        reason = str(payload.get("reason", ""))[:200]
    except Exception as exc:
        logger.debug("Interruption classifier unavailable: %s", exc)
        return "routine", "Classifier unavailable"

    return ("important" if label == "important" else "routine"), reason


async def judge(
    db: Session, *, owner_id: int, participant: str | None, text: str
) -> tuple[str, str]:
    """
    How important this message is, and which test decided.

    Returns `(importance, source)` where source is `reviewer`, `worklist` or
    `classifier`. Deterministic tests run first and short-circuit, so the model
    is only consulted when neither fact applies -- and the UI can then render
    the model's answer as the weaker claim it is.
    """
    if sender_is_reviewer(db, owner_id, participant):
        return "important", "reviewer"

    if names_blocked_work(db, owner_id, text):
        return "important", "worklist"

    importance, _ = await classify(text)
    return importance, "classifier"


def already_replied(
    db: Session, *, owner_id: int, thread_ts: str | None, channel: str | None
) -> bool:
    """
    Whether this thread already got a reply today.

    Load-bearing rather than polish: a repeating auto-responder gets the bot
    muted, and a muted bot takes the review pings and QA threads with it.

    Matched on the thread when there is one and on the channel otherwise -- a
    top-level channel mention carries no `thread_ts`, and being pinged in a
    channel is the ordinary case.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=REPLY_COOLDOWN_HOURS)

    query = db.query(models.InterruptionEvent).filter(
        models.InterruptionEvent.owner_id == owner_id,
        models.InterruptionEvent.replied == 1,
        models.InterruptionEvent.occurred_at >= cutoff,
    )
    if thread_ts:
        query = query.filter(models.InterruptionEvent.thread_ts == thread_ts)
    else:
        query = query.filter(
            models.InterruptionEvent.slack_channel == channel,
            models.InterruptionEvent.thread_ts.is_(None),
        )

    return query.first() is not None


def compose_reply(
    availability: schemas.Availability,
    *,
    timezone: str | None,
    importance: str,
    slots: list | None = None,
) -> str:
    """
    The reply, as it will be sent.

    State and end time only. It **names its timezone** -- "booked until 15:30
    IST", never "until 15:30": anything the backend formats for a human names
    its zone, and `google_meet` stamping "UTC" onto server-local times is the
    bug that rule was written from.

    `focus` and `busy` read differently, because a meeting has an end time and
    a focus block is a choice. Off-hours gets the plainest version and no
    reschedule offer -- there is nothing to reschedule around.
    """
    tz = resolve_timezone(timezone)
    label = _zone_label(tz, timezone)

    if availability.state == "off_hours":
        when = _clock(availability.next_free, tz, label)
        return (
            "Thanks — outside working hours right now. "
            + (f"Back {when}." if when else "Back tomorrow.")
        )

    until = _clock(availability.until, tz, label)
    free = _clock(availability.next_free, tz, label)

    if availability.state == "focus":
        body = (
            f"Thanks — heads-down until {until}."
            if until else "Thanks — heads-down right now."
        )
    else:
        body = (
            f"Thanks — in a meeting until {until}."
            if until else "Thanks — unavailable right now."
        )

    if free and free != until:
        body += f" Free from {free}."

    if importance == "important" and slots:
        # Options, never a booking. Writing to somebody else's calendar from an
        # automated reply is a write nobody approved.
        offered = ", ".join(_clock(slot.start, tz, label) for slot in slots[:3])
        body += f" If it cannot wait, these are open: {offered}."

    return body


def _clock(moment: datetime | None, tz, label: str) -> str:
    if moment is None:
        return ""
    return f"{moment.astimezone(tz).strftime('%H:%M')} {label}"


def _zone_label(tz, name: str | None) -> str:
    """
    A short zone name for the reply.

    Falls back to the IANA name rather than to nothing: "15:30 Asia/Kolkata" is
    clumsy and unambiguous, where "15:30" is neither.
    """
    try:
        abbreviation = datetime.now(tz).strftime("%Z")
        if abbreviation and not abbreviation.startswith(("+", "-")):
            return abbreviation
    except Exception:
        pass
    return name or "UTC"


def record(
    db: Session,
    *,
    owner_id: int,
    participant: str | None,
    thread_ts: str | None,
    channel: str | None,
    availability: schemas.Availability,
    importance: str,
    importance_source: str,
    replied: bool,
    reply_body: str | None,
    excerpt: str | None,
    proposal_id: int | None = None,
) -> models.InterruptionEvent:
    """
    Store what happened, with the reply **as sent**.

    Passed in rather than reconstructed: a reconstruction drifts from what the
    channel actually saw, which makes the record worse than useless.
    """
    row = models.InterruptionEvent(
        owner_id=owner_id,
        participant=participant,
        thread_ts=thread_ts,
        slack_channel=channel,
        availability_state=availability.state,
        importance=importance,
        importance_source=importance_source,
        replied=1 if replied else 0,
        reply_body=reply_body,
        excerpt=(excerpt or "")[:500] or None,
        proposal_id=proposal_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
