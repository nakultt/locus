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
from datetime import UTC, datetime

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
    ticket_key: str | None = None,
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
            ticket_key=ticket_key,
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
    ticket_key: str | None = None,
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
            ticket_key=ticket_key,
            query=query,
            body=None,
            outcome=f"{len(matches)} match(es)" if matches else "no matches",
        )

    for match in matches:
        record(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            loop="context", direction="received", channel="slack",
            ticket_key=ticket_key,
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
    ticket_key: str | None = None,
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
            ticket_key=ticket_key,
            participant=issue.get("author") or None,
            target=f"issue #{number}" if number else None,
            subject=issue.get("title"),
            body=issue.get("body") or None,
            permalink=issue.get("url"),
            outcome=issue.get("relation"),
        )


def cached_search(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None,
) -> tuple[datetime | None, list[dict]]:
    """
    What the last Slack search for this work item found, and when it ran.

    Returns `(searched_at, matches)`. The cache is always usable -- there is no
    freshness window, because discussion that was relevant an hour ago is still
    relevant now. `searched_at` is the watermark: the caller searches Slack for
    messages newer than it and merges, so nothing said since the last run is
    missed. `None` means this work item was never searched, and the caller
    should run a full search.

    Scoped to the ticket when there is one, so the second pull request on a
    work item inherits the first one's discussion instead of searching again.
    """
    query = db.query(models.CommunicationEvent).filter(
        models.CommunicationEvent.owner_id == owner_id,
        models.CommunicationEvent.channel == "slack",
        models.CommunicationEvent.loop == "context",
    )
    if ticket_key:
        query = query.filter(models.CommunicationEvent.ticket_key == ticket_key)
    else:
        query = query.filter(
            models.CommunicationEvent.repo == repo,
            models.CommunicationEvent.pr_number == pr_number,
        )

    events = query.order_by(models.CommunicationEvent.created_at).all()
    if not events:
        return None, []

    searched = [e for e in events if e.direction == "searched"]
    newest = max(
        (e.created_at for e in searched if e.created_at is not None),
        default=None,
    )
    if newest is None:
        # Messages with no search behind them cannot produce a watermark; an
        # incremental search from an unknown point would silently skip
        # whatever fell between. Fall back to a full search.
        return None, []
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=UTC)

    # Deduplicated by permalink. The cache accumulates over rounds and the
    # same message can be recorded by several rounds' searches; showing it
    # three times would read as three separate people saying it.
    matches: list[dict] = []
    seen: set[str] = set()
    from app.services.pipeline.review_flow import is_own_slack_notification

    for e in events:
        if e.direction != "received" or not e.body:
            continue
        # Locus's own notification, cached before the search learned to skip
        # bot posts. Dropped on the way out rather than deleted: the row is a
        # true record of what the search returned, and `full_report` renders
        # the log as the whole record. It is only wrong as *context*.
        if is_own_slack_notification(e.body):
            continue
        if e.permalink:
            if e.permalink in seen:
                continue
            seen.add(e.permalink)
        matches.append({
            "channel": e.target,
            "participant": e.participant,
            "text": e.body,
            "permalink": e.permalink,
            "query": e.query,
            "cached_at": e.created_at,
        })
    return newest, matches


def ticket_timeline(
    db: Session,
    *,
    owner_id: int,
    ticket_key: str,
) -> list[models.CommunicationEvent]:
    """
    Everything recorded for one work item, across every pull request it spans.

    This is what makes the second PR on a ticket start with the first one's
    context -- including the QA rejection that caused it to exist -- rather
    than from nothing.
    """
    events = (
        db.query(models.CommunicationEvent)
        .filter(
            models.CommunicationEvent.ticket_key == ticket_key,
            models.CommunicationEvent.owner_id == owner_id,
        )
        .order_by(
            models.CommunicationEvent.created_at,
            models.CommunicationEvent.id,
        )
        .all()
    )
    return events


def _ordering(event: models.CommunicationEvent) -> tuple[datetime, int]:
    """
    Sort key for a timeline: oldest first, ties broken by insertion order.

    Stored timestamps are naive on some backends and aware on others, and
    comparing the two raises, so the key normalizes before sorting.
    """
    stamp = event.created_at or datetime.min
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (stamp, event.id or 0)


def work_item_history(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None = None,
) -> list[models.CommunicationEvent]:
    """
    Everything recorded for this work item, for the written record.

    Deliberately wider than `timeline`, which inherits only Slack discussion
    from sibling pull requests because that is the context the analysis
    genuinely reused and marking anything else as inherited would imply it was
    read when it was not. The report document is the record, so it records
    everything: the earlier runs, the prior review rounds, and the QA thread
    why the work came back.

    Rows carrying this pull request's number are included whether or not they
    were stamped with the work item: a run that recorded events before it
    resolved the ticket key still recorded them about this change.
    """
    own = (
        db.query(models.CommunicationEvent)
        .filter(
            models.CommunicationEvent.repo == repo,
            models.CommunicationEvent.pr_number == pr_number,
            models.CommunicationEvent.owner_id == owner_id,
        )
        .all()
    )
    for event in own:
        event.inherited = False

    events = list(own)

    if ticket_key:
        seen_ids = {event.id for event in own}
        # Deduplicated by permalink as well as by id: the same Slack message is
        # recorded under each pull request on the ticket, and repeating it
        # would read as several people having said it.
        seen_links = {e.permalink for e in own if e.permalink}

        inherited_events = (
            db.query(models.CommunicationEvent)
            .filter(
                models.CommunicationEvent.owner_id == owner_id,
                models.CommunicationEvent.ticket_key == ticket_key,
            )
            .all()
        )

        for event in inherited_events:
            if event.id in seen_ids:
                continue
            if event.permalink and event.permalink in seen_links:
                continue
            if event.permalink:
                seen_links.add(event.permalink)
            # Marked so the document can say which attempt each row came from
            # rather than presenting the first PR's history as this one's.
            event.inherited = True
            events.append(event)

    return sorted(events, key=_ordering)


def timeline(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None = None,
) -> list[models.CommunicationEvent]:
    """
    Everything recorded for one PR, oldest first.

    When the PR belongs to a work item, the Slack discussion cached under that
    ticket by earlier pull requests is included too. That discussion is what
    the reviewer was actually given -- the analysis reuses it every round --
    so a timeline that showed only rows stamped with this PR's number would
    omit context the run demonstrably used. Inherited rows are marked
    `inherited` so the UI can say where they came from rather than implying
    they were found on this PR.
    """
    own = (
        db.query(models.CommunicationEvent)
        .filter(
            models.CommunicationEvent.repo == repo,
            models.CommunicationEvent.pr_number == pr_number,
            models.CommunicationEvent.owner_id == owner_id,
        )
        .all()
    )
    for event in own:
        event.inherited = False

    events = list(own)

    if ticket_key:
        inherited = (
            db.query(models.CommunicationEvent)
            .filter(
                models.CommunicationEvent.owner_id == owner_id,
                models.CommunicationEvent.ticket_key == ticket_key,
                models.CommunicationEvent.pr_number != pr_number,
                models.CommunicationEvent.channel == "slack",
                models.CommunicationEvent.direction == "received",
                models.CommunicationEvent.body.isnot(None),
            )
            .all()
        )
        # Deduplicated against what this PR already recorded: the same Slack
        # message can be stored under two PRs on the same ticket, and showing
        # it twice would read as two people saying it.
        seen = {e.permalink for e in own if e.permalink}
        for event in inherited:
            if event.permalink and event.permalink in seen:
                continue
            if event.permalink:
                seen.add(event.permalink)
            event.inherited = True
            events.append(event)

    events.sort(key=_ordering)
    return events
