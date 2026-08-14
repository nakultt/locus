"""
Task Router
The work assigned to a user, and how far each piece has travelled.

Where `/webhooks` is organized around pull requests -- the machine's unit of
work -- these endpoints are organized around the work item, which is the unit
a person is actually assigned. A ticket with no pull request yet is real work
and appears here; it appears nowhere in the PR-shaped views.

Identity is derived from the connected credentials rather than configured.
Nothing here accepts a user id, an assignee, or a login: the token decides
whose work is returned, exactly as every other endpoint takes identity from
the JWT.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.dependencies import get_current_user, get_integration_configs
from app.services import task_board
from app.services.agent_settings import resolve_settings

router = APIRouter()

# The board polls, and each refresh would otherwise cost two third-party calls
# per user. Cached briefly so a dashboard left open does not burn a GitHub rate
# limit; the pull request, review and message halves stay live from the
# database, so everything Locus itself produced is never stale.
ASSIGNED_TTL_SECONDS = 60

_assigned_cache: dict[int, tuple[float, schemas.TaskBoard]] = {}


def _cached_board(owner_id: int) -> schemas.TaskBoard | None:
    entry = _assigned_cache.get(owner_id)
    if entry is None:
        return None
    stored_at, board = entry
    if time.monotonic() - stored_at > ASSIGNED_TTL_SECONDS:
        _assigned_cache.pop(owner_id, None)
        return None
    return board


@router.get(
    "",
    response_model=schemas.TaskBoard,
    summary="Every task assigned to you, with its pipeline position",
)
async def get_task_board(
    refresh: bool = Query(
        False, description="Bypass the assigned-item cache and re-query the sources"
    ),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.TaskBoard:
    """
    The board: assigned GitHub issues and Jira tickets, joined to their PRs.

    Ordering is settled server-side -- needs-you first, then staleness -- so
    the API and the UI cannot disagree about what is most urgent.

    A source that fails is reported in `unavailable` rather than rendered as
    an empty queue: "nothing assigned" and "Jira did not answer" mean very
    different things to someone deciding what to work on.
    """
    if not refresh:
        cached = _cached_board(current_user.id)
        if cached is not None:
            return cached

    integration_configs = get_integration_configs(db, current_user.id)
    board = await task_board.build(
        db, owner_id=current_user.id, integration_configs=integration_configs
    )

    _assigned_cache[current_user.id] = (time.monotonic(), board)
    return board


def _find_card(board: schemas.TaskBoard, task_key: str) -> schemas.TaskCard | None:
    return next(
        (
            card for card in (board.needs_you + board.in_flight)
            if card.key == task_key
        ),
        None,
    )


@router.get(
    "/detail",
    response_model=schemas.TaskDetail,
    summary="One task's full pipeline, with every message behind it",
)
async def get_task_detail(
    task_key: str = Query(..., description='Jira key, or "owner/repo#N"'),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.TaskDetail:
    """
    Everything about one task: stages, analysis, review rounds and messages.

    The key is taken as a query parameter rather than a path segment because
    it legitimately contains both "/" and "#" -- `acme/api#42` in a path would
    have to be double-escaped by every caller.

    A task that is not assigned to this user returns 404, not 403. A 403 would
    confirm the key exists, which is enough to enumerate other people's work.
    """
    integration_configs = get_integration_configs(db, current_user.id)
    board = await task_board.build(
        db, owner_id=current_user.id, integration_configs=integration_configs
    )

    card = _find_card(board, task_key)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    # Settings are resolved against the registration of the repo the work is
    # actually happening in, so the QA and reviewer contacts shown are the ones
    # a run would really use.
    registration = None
    if card.pull_requests:
        registration = db.query(models.RepoWebhook).filter(
            models.RepoWebhook.repo == card.pull_requests[0].repo,
            models.RepoWebhook.owner_id == current_user.id,
        ).first()
    settings = resolve_settings(db, current_user.id, registration)

    return task_board.detail_for(
        db, owner_id=current_user.id, card=card, settings=settings
    )


@router.post(
    "/analyze",
    response_model=schemas.PRJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run the analysis for a task's pull request",
)
async def analyze_task(
    task_key: str = Query(..., description='Jira key, or "owner/repo#N"'),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRJobResponse:
    """
    Queue an analysis of the task's most recent pull request.

    This is the only write the board offers. Everything else the pipeline does
    reaches other people -- a Slack post, a QA email, a merge -- and stays
    driven by webhooks and the background loops rather than by a button, so a
    dashboard refresh can never notify a team twice.

    A task with no pull request yet has nothing to analyze and returns 404.
    """
    integration_configs = get_integration_configs(db, current_user.id)
    board = await task_board.build(
        db, owner_id=current_user.id, integration_configs=integration_configs
    )

    card = _find_card(board, task_key)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    if not card.pull_requests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This task has no pull request to analyze yet",
        )

    target = card.pull_requests[-1]
    job = models.PRJob(
        repo=target.repo,
        pr_number=target.pr_number,
        action="manual",
        status=schemas.PRJobStatus.queued.value,
        owner_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # The board's assigned half is cached; a queued run changes the pipeline
    # position, so drop it rather than showing a stale stage for a minute.
    _assigned_cache.pop(current_user.id, None)

    return schemas.PRJobResponse.model_validate(job)
