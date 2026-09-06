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
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_integration_configs
from app.services.authoring import authoring, authoring_flow
from app.services.pipeline import report_sync, task_board
from app.services.pipeline.agent_settings import resolve_settings

router = APIRouter()

# The board polls, and each refresh would otherwise cost two third-party calls
# per user. Cached briefly so a dashboard left open does not burn a GitHub rate
# limit.
#
# The cache holds the whole board, third-party halves and locally-derived
# halves together, so anything Locus itself knows is served up to a minute
# stale. That is fine for a stage that changes once per event and wrong for a
# state that is *happening* -- the client polls every ten seconds, and an
# "agent working" badge that appears fifty seconds after the run starts and
# lingers fifty seconds after it ends is worse than none, because it is
# describing the present and getting it wrong.
#
# So the live fields are re-stamped from the database on every cache hit. One
# indexed query against `authoring_attempts`, no third-party calls, which is
# what the cache exists to avoid.
ASSIGNED_TTL_SECONDS = 60

_assigned_cache: dict[int, tuple[float, schemas.TaskBoard]] = {}


def _cached_board(db: Session, owner_id: int) -> schemas.TaskBoard | None:
    entry = _assigned_cache.get(owner_id)
    if entry is None:
        return None
    stored_at, board = entry
    if time.monotonic() - stored_at > ASSIGNED_TTL_SECONDS:
        _assigned_cache.pop(owner_id, None)
        return None
    return _restamp_live(db, owner_id, board)


def _restamp_live(
    db: Session, owner_id: int, board: schemas.TaskBoard
) -> schemas.TaskBoard:
    """
    Refresh the fields that describe something in progress right now.

    Only what the database alone can answer. A card's stage, its pull requests
    and its messages all come from the same cached snapshot and stay there --
    re-deriving those would mean redoing the work the cache exists to skip.

    Failure returns the board untouched: a stale badge is a much smaller
    problem than a board that will not load.
    """
    try:
        running = authoring.running_attempts(db, owner_id=owner_id)
    except Exception:
        return board

    for card in board.needs_you + board.in_flight + board.recently_done:
        attempt = running.get(card.key)
        card.authoring_active = attempt is not None
        card.authoring_started_at = attempt.created_at if attempt else None
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
        cached = _cached_board(db, current_user.id)
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

    detail = task_board.detail_for(
        db, owner_id=current_user.id, card=card, settings=settings
    )

    # The document is created here rather than on the board listing. Opening a
    # task is one deliberate act by one person; a board refresh would create a
    # document for every assigned item at once, which is the same shape of
    # mistake as a refresh notifying a team twice. It is idempotent, so the
    # second open returns the same link.
    first_pr = card.pull_requests[0] if card.pull_requests else None
    detail.doc_url = await report_sync.ensure_for_ticket(
        db,
        owner_id=current_user.id,
        key=card.key,
        title=card.title,
        integration_configs=integration_configs,
        url=card.url,
        status=card.status,
        assignee=card.assignee,
        priority=card.priority,
        description=card.description,
        repo=first_pr.repo if first_pr else None,
        pr_number=first_pr.pr_number if first_pr else None,
    )
    return detail


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


def _mode_response(
    db: Session, owner_id: int, task_key: str, registration: models.RepoWebhook | None
) -> schemas.WorkItemMode:
    """Resolve the authoring mode for one work item and say where it came from."""
    settings = resolve_settings(db, owner_id, registration, ticket_key=task_key)
    override = db.query(models.WorkItemSettings).filter(
        models.WorkItemSettings.owner_id == owner_id,
        models.WorkItemSettings.ticket_key == task_key,
    ).first()

    return schemas.WorkItemMode(
        task_key=task_key,
        authoring_mode=schemas.AuthoringMode(settings.authoring_mode),
        autonomous_max_rounds=settings.autonomous_max_rounds,
        source=settings.sources.get("authoring_mode", "unset"),
        rounds_source=settings.sources.get("autonomous_max_rounds", "unset"),
        override=(
            schemas.AuthoringMode(override.authoring_mode)
            if override is not None and override.authoring_mode
            else None
        ),
        handed_back=settings.handed_back,
        handed_back_reason=settings.handed_back_reason,
        handed_back_at=override.handed_back_at if override is not None else None,
        preset_label=settings.preset_label,
    )


async def _registration_for_task(
    db: Session, current_user: models.User, task_key: str
) -> models.RepoWebhook | None:
    """
    Find the repo registration behind a task, 404ing if it is not the caller's.

    The board is rebuilt rather than trusted from the client, because the
    assignment check *is* the authorization check here. A task not on the
    caller's board returns 404 rather than 403: a 403 confirms the key exists,
    which is enough to enumerate other people's work.
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
        return None
    return db.query(models.RepoWebhook).filter(
        models.RepoWebhook.repo == card.pull_requests[0].repo,
        models.RepoWebhook.owner_id == current_user.id,
    ).first()


@router.get(
    "/mode",
    response_model=schemas.WorkItemMode,
    summary="The authoring mode a run on this work item would use",
)
async def get_task_mode(
    task_key: str = Query(..., description='Jira key, or "owner/repo#N"'),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.WorkItemMode:
    """Resolved mode plus the layer that supplied it, for one work item."""
    registration = await _registration_for_task(db, current_user, task_key)
    return _mode_response(db, current_user.id, task_key, registration)


@router.put(
    "/mode",
    response_model=schemas.WorkItemMode,
    summary="Override the authoring mode for one work item",
)
async def set_task_mode(
    payload: schemas.WorkItemModeUpdate,
    task_key: str = Query(..., description='Jira key, or "owner/repo#N"'),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.WorkItemMode:
    """
    Upsert the per-work-item override, or delete it when nothing is set.

    Autonomy is a judgement about *this ticket*: a dependency bump and a change
    to the credential path are not the same risk, and forcing one account-wide
    switch to cover both is why the mode would otherwise stay off everywhere.

    Clearing every field deletes the row rather than storing nulls -- a row of
    nulls reads as a deliberate choice to the next person who queries the
    table, where absence correctly reads as "inherit".
    """
    registration = await _registration_for_task(db, current_user, task_key)

    row = db.query(models.WorkItemSettings).filter(
        models.WorkItemSettings.owner_id == current_user.id,
        models.WorkItemSettings.ticket_key == task_key,
    ).first()

    mode = payload.authoring_mode.value if payload.authoring_mode else None
    rounds = payload.autonomous_max_rounds

    if mode is None and rounds is None:
        # Nothing left to say. Deleting also clears any handoff, which is what
        # makes "put it back on autonomous" a single action rather than
        # requiring the user to find a flag they never set.
        if row is not None:
            db.delete(row)
            db.commit()
    elif row is None:
        db.add(models.WorkItemSettings(
            ticket_key=task_key,
            authoring_mode=mode,
            autonomous_max_rounds=rounds,
            owner_id=current_user.id,
        ))
        db.commit()
    else:
        row.authoring_mode = mode
        row.autonomous_max_rounds = rounds
        # An explicit choice takes the item back off the handoff. The handoff
        # exists to stop the driver re-triggering itself, not to stop a person
        # from deciding otherwise.
        row.handed_back_at = None
        row.handed_back_reason = None
        db.commit()

    _assigned_cache.pop(current_user.id, None)
    return _mode_response(db, current_user.id, task_key, registration)


@router.get(
    "/attempts",
    response_model=list[schemas.AuthoringAttemptEntry],
    summary="Every authoring attempt recorded against a work item",
)
async def get_task_attempts(
    task_key: str = Query(..., description='Jira key, or "owner/repo#N"'),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[schemas.AuthoringAttemptEntry]:
    """
    The attempt history, oldest first, including the ones that opened nothing.

    This is where a handed-back item explains itself: "the agent has tried
    three things" and "the agent tried once and a reviewer pushed back twice"
    are different situations, and only the trigger on each row distinguishes
    them.
    """
    await _registration_for_task(db, current_user, task_key)
    return [
        schemas.AuthoringAttemptEntry(
            id=row.id,
            ticket_key=row.ticket_key,
            repo=row.repo,
            pr_number=row.pr_number,
            attempt=row.attempt,
            trigger=row.trigger,
            driver=row.driver,
            model=row.model,
            context_mode=row.context_mode,
            opened=bool(row.opened),
            error=row.error,
            files_changed=row.files_changed,
            lines_changed=row.lines_changed,
            duration_seconds=row.duration_seconds,
            created_at=row.created_at,
        )
        for row in authoring.attempts_for(db, current_user.id, task_key)
    ]


@router.post(
    "/author",
    response_model=schemas.AuthoringRunResponse,
    summary="Hand this work item to the authoring agent",
)
async def author_task(
    task_key: str = Query(..., description='Jira key, or "owner/repo#N"'),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.AuthoringRunResponse:
    """
    Run the authoring driver once against this work item.

    A board action, not a webhook, and deliberately so. The same rule
    `report_sync.ensure_for_ticket` follows: it is called when someone opens
    one task and never from the listing, because a refresh would act on every
    assigned item at once. Authoring on assignment has that shape with a far
    worse blast radius -- a morning's tickets would open a dozen pull requests
    together.

    This is the board's **second** write, and the invariant it amends said
    there was exactly one. That rule exists so a dashboard refresh cannot
    notify a team twice; one deliberate click that opens one pull request
    satisfies the reasoning behind it rather than breaking it.

    Everything after the pull request exists is the pipeline that already
    runs -- the `opened` webhook fires and nothing downstream learns which arm
    authored the change.

    That last sentence is why this runs a *rework* when the work item already
    has an open pull request rather than always starting fresh: the two
    triggers reach the same driver, so a click and a changes-requested webhook
    must land in the same place. Every arm now shares
    `authoring_flow.start_for_card`, which is what makes that structural
    rather than a rule two files have to keep agreeing on.
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

    repo = (
        card.pull_requests[0].repo
        if card.pull_requests
        else authoring_flow.repo_from_card(card)
    )
    registration = None
    if repo:
        # This account's registration, with no fallback past the owner.
        #
        # A fallback to "any registration for this repo" was here, from the
        # same workaround as the one in `report_sync.find_report`: a board
        # running as one account while the pipeline state belonged to another.
        # It is worse than a cross-user read. `resolve_settings` turns a
        # registration into `source_path`, `prepare_command` and
        # `test_command` -- a path on this server and two shell commands run
        # in the workspace -- so borrowing another account's row means running
        # their commands against their source tree on a click from someone who
        # never saw either.
        #
        # An unregistered repo resolves to the account's own defaults, which
        # is the correct answer and the case `PRAgentDefaults` exists for.
        registration = db.query(models.RepoWebhook).filter(
            models.RepoWebhook.repo == repo,
            models.RepoWebhook.owner_id == current_user.id,
        ).first()
    settings = resolve_settings(db, current_user.id, registration, ticket_key=task_key)

    async def _doc_url(resolved_repo: str) -> str | None:
        # The report link goes in the pull request body: a Google Doc nobody
        # links to is work nobody reads, and the analysis behind the ticket is
        # where the requirement context lives. A failure to fetch it costs the
        # link, never the run.
        #
        # Passed as a hook rather than done inside the shared path, because
        # creating the document is a write and the assignment sweep must not
        # make one per assigned ticket -- the same reason
        # `report_sync.ensure_for_ticket` is never called from the board
        # listing. A click is one deliberate act; a sweep is not.
        return await report_sync.ensure_for_ticket(
            db,
            owner_id=current_user.id,
            key=task_key,
            title=card.title,
            integration_configs=integration_configs,
            url=card.url,
            status=card.status,
            assignee=card.assignee,
            priority=card.priority,
            description=card.description,
            repo=resolved_repo,
        )

    try:
        result, attempt, _trigger = await authoring_flow.start_for_card(
            db,
            owner_id=current_user.id,
            card=card,
            settings=settings,
            integration_configs=integration_configs,
            doc_url_hook=_doc_url,
        )
    except authoring_flow.StartRefused as refused:
        # The shared path reports a refusal as data so the assignment sweep can
        # skip a work item without a web framework deciding for it. This is
        # where it becomes a status code.
        raise HTTPException(
            status_code=_REFUSAL_STATUS.get(refused.code, status.HTTP_409_CONFLICT),
            detail=refused.detail,
        ) from None

    _assigned_cache.pop(current_user.id, None)

    return schemas.AuthoringRunResponse(
        ticket_key=task_key,
        opened=result.opened,
        pr_number=result.pr_number,
        pr_url=result.pr_url,
        branch=result.branch,
        attempt=attempt,
        attempts_remaining=max(0, settings.autonomous_max_rounds + 1 - attempt),
        driver=result.driver,
        model=result.model,
        files_changed=result.files_changed,
        lines_changed=result.lines_changed,
        error=result.error,
        handed_back_reason=result.hand_back_reason,
    )


# What each refusal from the shared path means over HTTP. Kept beside the
# endpoint rather than in the service: the service's job is to say why it
# declined, and only a web caller cares which number that is.
_REFUSAL_STATUS = {
    "no_repo": status.HTTP_409_CONFLICT,
    "handed_back": status.HTTP_409_CONFLICT,
    "mode_off": status.HTTP_409_CONFLICT,
    "no_driver": status.HTTP_503_SERVICE_UNAVAILABLE,
    "cap": status.HTTP_429_TOO_MANY_REQUESTS,
}


