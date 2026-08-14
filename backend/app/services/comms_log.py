"""
Recording what Locus searched, sent, and received.

The dashboard could already say Slack was searched and the test team was
emailed. It could not say what was searched for, what came back, or what was
actually sent -- which is the first question anyone asks about a surprising
run, and what decides whether the agent gets trusted.

Two rules here:

**Logging never fails the work it describes.** Every helper swallows its own
errors. A message that was genuinely sent must not be reported as failed
because the record of it could not be written, and a Slack post must not be
retried because logging raised after it succeeded.

**Bodies are stored, not summaries.** A truncated record answers the easy
questions and none of the hard ones. The cap here is high enough to keep whole
messages and low enough that one pasted logfile cannot fill the table.
"""

import logging

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

# Slack's own message limit is 40k characters. Storing a little beyond that
# covers email, which has no practical limit, without letting one pasted
# stack trace dominate a page of history.
MAX_BODY_CHARS = 20_000


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    text = str(text)
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[:MAX_BODY_CHARS] + "\n… (truncated)"


def record(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    loop: str,
    direction: str,
    channel: str,
    body: str | None = None,
    participant: str | None = None,
    target: str | None = None,
    subject: str | None = None,
    query: str | None = None,
    permalink: str | None = None,
    outcome: str | None = None,
    succeeded: bool = True,
) -> None:
    """
    Append one communication event.

    Commits immediately: these are a record of things that already happened
    outside Locus, so they must survive a later failure in the same job. A
    Slack message that was sent stays sent whether or not the rest of the run
    succeeds, and the timeline should say so.
    """
    try:
        db.add(models.CommunicationEvent(
            repo=repo,
            pr_number=pr_number,
            loop=loop,
            direction=direction,
            channel=channel,
            participant=participant,
            target=target,
            subject=subject,
            body=_clip(body),
            query=_clip(query) if query is None else query[:512],
            permalink=permalink,
            outcome=outcome,
            succeeded=1 if succeeded else 0,
            owner_id=owner_id,
        ))
        db.commit()
    except Exception as e:
        # Never let bookkeeping break the thing it is describing.
        logger.warning("Could not record communication event: %s", e)
        try:
            db.rollback()
        except Exception:
            pass


def record_search_matches(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    queries: list[str],
    matches: list[dict],
) -> None:
    """
    Record a Slack search: the queries tried, and every message they returned.

    The queries are logged even when nothing matched. A search that finds no
    prior discussion looks identical to a search that was never run, and only
    the query makes the difference visible.
    """
    for query in queries:
        record(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            loop="context", direction="searched", channel="slack",
            query=query,
            body=None,
            outcome=f"{len(matches)} match(es)" if matches else "no matches",
        )

    for match in matches:
        record(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            loop="context", direction="received", channel="slack",
            participant=match.get("participant"),
            target=match.get("channel"),
            body=match.get("text"),
            permalink=match.get("permalink"),
            query=match.get("query"),
        )


def record_issues(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    issues: list[dict],
) -> None:
    """
    Record the GitHub issues this PR links or mentions, with their text.

    An issue body is context a human wrote about this work -- the same kind of
    thing as a Slack thread, and worth reading for the same reason. The
    relation is carried as the outcome because "closes" and "mentions" are
    materially different: only the former is closed on merge, and showing them
    identically would overstate the relationship.
    """
    for issue in issues:
        number = issue.get("number")
        record(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            loop="context", direction="received", channel="github",
            participant=issue.get("author") or None,
            target=f"issue #{number}" if number else None,
            subject=issue.get("title"),
            body=issue.get("body") or None,
            permalink=issue.get("url"),
            outcome=issue.get("relation"),
        )


def timeline(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
) -> list[models.CommunicationEvent]:
    """Everything recorded for one PR, oldest first."""
    return (
        db.query(models.CommunicationEvent)
        .filter(
            models.CommunicationEvent.repo == repo,
            models.CommunicationEvent.pr_number == pr_number,
            models.CommunicationEvent.owner_id == owner_id,
        )
        .order_by(
            models.CommunicationEvent.created_at,
            models.CommunicationEvent.id,
        )
        .all()
    )
