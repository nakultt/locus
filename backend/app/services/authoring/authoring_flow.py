"""
The automatic retries, and the handoff when the bound runs out.

Two triggers reach this: a reviewer requesting changes, and the testing team
rejecting a merged change. Both are the pipeline saying "this is not done",
which is exactly what an authoring attempt answers -- and both funnel through
one function so the two cannot drift into behaving differently.

The QA retry deliberately opens a *new* pull request. That is what
`work_item.resolve_key` and `sibling_reviews` were built for: the new PR
inherits the rejection history for free, so the fix opens carrying the reason
the work came back.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import models
from app.services.authoring import authoring
from app.services.integrations import github_pr
from app.services.pipeline import comms_log, context_brief, work_item

logger = logging.getLogger(__name__)


async def maybe_retry(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None,
    settings,
    integration_configs: dict,
    trigger: str,
    slack_channel: str | None = None,
    rejection: str | None = None,
) -> authoring.AuthoringResult | None:
    """
    Take another swing at this work item, or hand it back, or hold silently.

    Returns the result when the driver ran, None when it did not. Every path
    swallows its own failure: a retry that could not start must not take the
    review notification or the QA reopen down with it, the same rule the loops
    already follow.
    """
    if not ticket_key:
        # A work item is never guessed. Attaching a key we inferred would put
        # one team's history in front of another team's pull request.
        return None

    driver = authoring.get_driver()
    if driver.name == "none":
        return None

    retry, reason = authoring.should_retry(
        db,
        owner_id=owner_id,
        ticket_key=ticket_key,
        settings=settings,
        repo=repo,
    )

    if not retry:
        await _refuse(
            db,
            owner_id=owner_id,
            repo=repo,
            pr_number=pr_number,
            ticket_key=ticket_key,
            settings=settings,
            integration_configs=integration_configs,
            reason=reason,
            slack_channel=slack_channel,
        )
        return None

    attempt = authoring.next_attempt_number(
        db, owner_id=owner_id, ticket_key=ticket_key
    )
    review = db.query(models.PRReview).filter(
        models.PRReview.owner_id == owner_id,
        models.PRReview.repo == repo,
        models.PRReview.pr_number == pr_number,
    ).first()

    request = authoring.AuthoringRequest(
        ticket_key=ticket_key,
        title=(review.pr_title if review else None) or ticket_key,
        repo=repo,
        # A QA rejection opens a new pull request on a new branch; a rework
        # continues the branch the reviewer has already read.
        existing_branch=None,
        context=_context(db, owner_id, repo, pr_number, ticket_key),
        asks=authoring.gather_asks(db, owner_id=owner_id, ticket_key=ticket_key),
        rejection=rejection,
        attempt=attempt,
        trigger=trigger,
        settings={
            "source_path": settings.source_path,
            "prepare_command": settings.prepare_command,
            "test_command": settings.test_command,
            "attempts_remaining": max(
                0, settings.autonomous_max_rounds + 1 - attempt
            ),
        },
    ).scoped()

    try:
        result = await driver.author(request, integration_configs)
    except Exception as exc:
        logger.warning("Authoring retry failed for %s: %s", ticket_key, exc)
        result = authoring.AuthoringResult(
            opened=False, error=f"The driver raised: {exc}", driver=driver.name
        )

    authoring.record_attempt(db, owner_id=owner_id, request=request, result=result)

    if result.hand_back_reason:
        await _hand_back(
            db,
            owner_id=owner_id,
            repo=repo,
            pr_number=pr_number,
            ticket_key=ticket_key,
            reason=result.hand_back_reason,
            integration_configs=integration_configs,
            slack_channel=slack_channel,
            pr_url=result.pr_url,
        )
        return result

    if not result.opened:
        # The attempt is spent either way. Check whether that was the last one
        # and hand it back now rather than waiting for the next event, which
        # may never come.
        spent, spent_reason = authoring.should_retry(
            db, owner_id=owner_id, ticket_key=ticket_key,
            settings=settings, repo=repo,
        )
        if not spent and "already open" not in spent_reason:
            await _hand_back(
                db,
                owner_id=owner_id,
                repo=repo,
                pr_number=pr_number,
                ticket_key=ticket_key,
                reason=f"{spent_reason}. Last error: {result.error}",
                integration_configs=integration_configs,
                slack_channel=slack_channel,
            )

    return result


async def _refuse(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str,
    settings,
    integration_configs: dict,
    reason: str,
    slack_channel: str | None,
) -> None:
    """
    Handle a refusal to retry.

    The throughput cap holds **silently**: a held retry that reports every time
    trains people to ignore the channel, the same rule `automerge.sweep_once`
    follows. A spent bound is announced once, because the work is now waiting
    on a person who does not otherwise know that.
    """
    if "already open" in reason:
        return
    if settings.authoring_mode != "autonomous" or getattr(settings, "handed_back", False):
        # Not a refusal so much as the mode simply being off. Nothing to say.
        return

    await _hand_back(
        db,
        owner_id=owner_id,
        repo=repo,
        pr_number=pr_number,
        ticket_key=ticket_key,
        reason=reason,
        integration_configs=integration_configs,
        slack_channel=slack_channel,
    )


async def _hand_back(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str,
    reason: str,
    integration_configs: dict,
    slack_channel: str | None,
    pr_url: str | None = None,
) -> None:
    """
    End autonomous mode for this work item and say so.

    **The database write commits before the announcement.** The reverse --
    announcing a handoff that did not persist -- re-triggers the driver on the
    next event, so the team reads "it is yours now" while the agent keeps
    working. A failed announcement leaves the work correctly stopped; a failed
    write leaves it running with everybody told otherwise.
    """
    existing = db.query(models.WorkItemSettings).filter(
        models.WorkItemSettings.owner_id == owner_id,
        models.WorkItemSettings.ticket_key == ticket_key,
    ).first()
    if existing is not None and existing.handed_back_at is not None:
        # Already handed back. Announcing again is the repeat that gets a bot
        # muted, and a muted bot takes the review pings with it.
        return

    authoring.hand_back(db, owner_id=owner_id, ticket_key=ticket_key, reason=reason)

    attempts = len(authoring.attempts_for(db, owner_id, ticket_key))
    message = authoring.handoff_message(
        ticket_key, attempts=attempts, reason=reason, pr_url=pr_url
    )

    sent = False
    if slack_channel and "slack" in integration_configs:
        try:
            from app.services.pipeline.review_flow import post_review_notification

            sent = await post_review_notification(
                integration_configs["slack"], slack_channel, message
            )
        except Exception as exc:
            logger.warning("Could not announce the handoff for %s: %s", ticket_key, exc)

    comms_log.record(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number,
        ticket_key=ticket_key,
        loop="review", direction="sent", channel="slack",
        target=slack_channel or "(no channel configured)",
        body=message,
        outcome="handed_back",
        succeeded=sent,
    )


def _context(
    db: Session, owner_id: int, repo: str, pr_number: int, ticket_key: str
) -> str:
    """The work item's accumulated context, or nothing if it cannot be built."""
    try:
        return context_brief.build(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number,
            ticket_key=ticket_key,
        )
    except Exception as exc:
        logger.debug("Context brief unavailable for %s: %s", ticket_key, exc)
        return ""


async def human_pushed_since_last_attempt(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str,
    integration_configs: dict,
) -> bool:
    """
    Whether somebody other than the agent has pushed to this pull request.

    Read from GitHub rather than from a local checkout, because the branch a
    reviewer is looking at is the remote one. A failure returns False: refusing
    to retry because a lookup failed would make the mode stop working whenever
    GitHub is slow, which is indistinguishable from the bound being spent.
    """
    token = (integration_configs.get("github") or {}).get("api_key") or (
        integration_configs.get("github") or {}
    ).get("token")
    if not token:
        return False

    last = db.query(models.AuthoringAttempt).filter(
        models.AuthoringAttempt.owner_id == owner_id,
        models.AuthoringAttempt.ticket_key == ticket_key,
        models.AuthoringAttempt.opened == 1,
    ).order_by(models.AuthoringAttempt.created_at.desc()).first()
    if last is None:
        return False

    try:
        authors = await github_pr.get_pr_commit_authors(token, repo, pr_number)
    except Exception:
        return False

    from app.services.authoring.opencode_driver import agent_email

    # The resolved identity, not the module constant: an account that set its
    # own commit address would otherwise have every one of its agent's own
    # commits read as a human's, handing back work the agent itself wrote.
    address = agent_email().lower()
    return any(email.lower() != address for email in authors)


def key_for(db: Session, *, owner_id: int, repo: str, pr_number: int) -> str | None:
    """The work item behind a pull request, never guessed into existence."""
    return work_item.resolve_key(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number
    )
