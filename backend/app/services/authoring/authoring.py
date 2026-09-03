"""
The authoring driver contract.

The seam between "Locus decided this ticket should be written by an agent" and
whatever actually writes it. Small on purpose: it is what lets the OpenCode
driver be replaced later without touching the pipeline around it.

The driver's entire contract is **open a pull request and return its number**.
It does not merge, comment, notify, move a board card or close a ticket.
Everything after the pull request exists is the webhook-driven pipeline that
already runs, which is what makes autonomous mode a setting rather than a fork:
nothing downstream learns which arm authored the change.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.services.authoring import agent_runtime

# How much of the brief leaves the machine.
#
# `full` is what makes the output good -- the Slack discussion and the issue
# bodies are where the requirement actually lives. `ticket_only` drops them, so
# a team that cannot send internal discussion to a third party gets a usable
# mode rather than no mode. Recorded on every attempt, because the trade is
# per-pull-request information that a config value cannot answer retroactively.
#
# Whose choice it is has moved: this is a statement about a team's own
# discussion, so it is an account setting that falls back to
# LOCUS_AUTHORING_CONTEXT rather than a deployment constant. `agent_runtime`
# resolves it.
CONTEXT_MODES = agent_runtime.CONTEXT_MODES


def context_mode() -> str:
    return agent_runtime.context_mode()


class AuthoringRequest(BaseModel):
    """Everything a driver needs to write one attempt at one work item."""

    ticket_key: str
    title: str
    description: str | None = None
    repo: str  # "owner/name"
    # Blank means "whatever the repository's default branch is", which the
    # driver resolves from the checkout it is about to work in. Naming a
    # branch here would hard-code `main` for every repo still on `master`.
    base_branch: str = ""
    # The issue's linked branch, when GitHub's Development panel has one.
    existing_branch: str | None = None
    # `context_brief.build()` output, verbatim. Empty under `ticket_only`.
    context: str = ""
    # Every reviewer ask across every round, oldest first. A request satisfied
    # in round two is still something the rework must not undo.
    asks: list[str] = Field(default_factory=list)
    # QA's own words, on a post-rejection attempt.
    rejection: str | None = None
    attempt: int = 1
    # initial | changes_requested | qa_rejected
    trigger: str = "initial"
    # The resolved per-repo authoring settings this run should use, and the
    # report link to put in the pull request body.
    #
    # Threaded on the request rather than re-resolved inside the driver, so the
    # driver needs no database session and `resolve_settings` stays the only
    # place the chain is walked. The worker, the API and the driver cannot then
    # disagree about what a run will do.
    settings: dict = Field(default_factory=dict)

    def scoped(self) -> AuthoringRequest:
        """
        This request with the internal discussion stripped, under `ticket_only`.

        The asks and the rejection are kept: they are what the rework is
        responding to, and an attempt that cannot see them is not a rework.
        """
        if context_mode() == "full":
            return self
        return self.model_copy(update={"context": ""})


class AuthoringResult(BaseModel):
    """What one attempt produced, whether or not it opened anything."""

    opened: bool = False
    pr_number: int | None = None
    pr_url: str | None = None
    branch: str | None = None
    files_changed: int = 0
    lines_changed: int = 0
    # Populated on every outcome that is not an opened pull request. A driver
    # that returns neither a PR nor an error has told the caller nothing.
    error: str | None = None
    driver: str = "none"
    # Which model wrote the diff. The first question asked when an
    # agent-authored change turns out to be wrong, and a mutable config value
    # cannot answer it after the fact.
    model: str | None = None
    context_mode: str = "full"
    workspace_path: str | None = None
    source_path: str | None = None
    duration_seconds: float = 0.0
    # Set when the outcome means this work item should stop being retried --
    # a human's commits on the branch, for instance. Distinct from a failure,
    # which merely consumes an attempt.
    hand_back_reason: str | None = None


class AuthoringDriver(Protocol):
    """What Locus requires of anything that writes code."""

    name: str

    async def author(
        self, request: AuthoringRequest, integration_configs: dict
    ) -> AuthoringResult:
        ...


class NoneDriver:
    """
    The default. Returns an error rather than an empty success.

    The same distinction `comms_log` draws between a search that found nothing
    and one that never ran: "no driver is configured" and "the agent looked at
    this ticket and produced nothing" are different facts, and reporting the
    second when the first is true sends someone hunting through prompts for a
    problem that is one environment variable.
    """

    name = "none"

    async def author(
        self, request: AuthoringRequest, integration_configs: dict
    ) -> AuthoringResult:
        return AuthoringResult(
            opened=False,
            error=(
                "No authoring driver configured. Choose one under Settings > "
                "Automation > Agent runtime, or set LOCUS_AUTHORING_DRIVER."
            ),
            driver=self.name,
            context_mode=context_mode(),
        )


def get_driver(name: str | None = None) -> AuthoringDriver:
    """
    The configured driver, defaulting to one that does nothing and says so.

    Imported lazily: the OpenCode driver pulls in subprocess and git handling
    that nothing else needs, and a bad driver name must not break app startup.
    """
    resolved = (name or "").strip().lower() or agent_runtime.driver_name()

    if resolved == "opencode":
        from app.services.authoring.opencode_driver import OpenCodeDriver

        return OpenCodeDriver()

    return NoneDriver()


def record_attempt(
    db: Session,
    *,
    owner_id: int,
    request: AuthoringRequest,
    result: AuthoringResult,
) -> models.AuthoringAttempt:
    """
    Append one attempt to the history.

    Append-only, the same argument as `PRReviewRound`: a mutable counter can
    say the agent has tried three times but not why it tried again, and "the
    agent has tried three things" and "the agent tried once and a reviewer
    pushed back twice" are different situations needing different responses.

    Recording never raises on its own account -- the caller has usually just
    done real work, and losing the record must not lose that too.
    """
    row = models.AuthoringAttempt(
        owner_id=owner_id,
        ticket_key=request.ticket_key,
        repo=request.repo,
        pr_number=result.pr_number,
        attempt=request.attempt,
        trigger=request.trigger,
        driver=result.driver,
        model=result.model,
        context_mode=result.context_mode,
        source_path=result.source_path,
        workspace_path=result.workspace_path,
        opened=1 if result.opened else 0,
        error=result.error,
        files_changed=result.files_changed,
        lines_changed=result.lines_changed,
        duration_seconds=result.duration_seconds,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def attempts_for(db: Session, owner_id: int, ticket_key: str) -> list[models.AuthoringAttempt]:
    """Every attempt under one work item, oldest first."""
    return db.query(models.AuthoringAttempt).filter(
        models.AuthoringAttempt.owner_id == owner_id,
        models.AuthoringAttempt.ticket_key == ticket_key,
    ).order_by(models.AuthoringAttempt.created_at.asc()).all()


def hand_back(
    db: Session, *, owner_id: int, ticket_key: str, reason: str
) -> models.WorkItemSettings:
    """
    Stop autonomous mode for one work item, and record why.

    Written before anything is announced. The reverse order -- announcing a
    handoff that did not persist -- re-triggers the driver on the next event,
    so the person reads "it is yours now" while the agent keeps working.
    """
    row = db.query(models.WorkItemSettings).filter(
        models.WorkItemSettings.owner_id == owner_id,
        models.WorkItemSettings.ticket_key == ticket_key,
    ).first()

    if row is None:
        row = models.WorkItemSettings(ticket_key=ticket_key, owner_id=owner_id)
        db.add(row)

    row.handed_back_at = datetime.now(UTC)
    row.handed_back_reason = reason
    db.commit()
    db.refresh(row)
    return row


# Per (owner, repo). The rubber-stamping mitigation.
#
# The approval that opens the merge gate is a review submitted by a real
# person, so the risk autonomous mode adds is not the absence of a human -- it
# is more pull requests arriving than anyone can genuinely read, with
# auto-merge making a fast click terminal. An interlock between the two
# settings would not touch that; a cap does. Reviewer attention is the scarce
# resource this whole mode spends, which is the same argument behind the diff
# size caps.
# Resolved per account through `agent_runtime`; the module-level name is the
# deployment default, kept because it is what the environment variable means.
MAX_OPEN_AUTONOMOUS_PRS = int(os.getenv("LOCUS_MAX_OPEN_AUTONOMOUS_PRS") or 3)


def max_open_autonomous_prs() -> int:
    """The cap for the account whose work is running now."""
    return agent_runtime.max_open_prs(MAX_OPEN_AUTONOMOUS_PRS)


def open_autonomous_prs(db: Session, *, owner_id: int, repo: str) -> int:
    """
    Agent-authored pull requests on this repo that have not merged yet.

    Counted from `AuthoringAttempt` joined to the review state rather than from
    GitHub: a PR Locus opened and a PR a person opened are indistinguishable to
    GitHub, and the cap is about the ones this mode produced.
    """
    numbers = {
        row.pr_number
        for row in db.query(models.AuthoringAttempt).filter(
            models.AuthoringAttempt.owner_id == owner_id,
            models.AuthoringAttempt.repo == repo,
            models.AuthoringAttempt.opened == 1,
            models.AuthoringAttempt.pr_number.isnot(None),
        ).all()
        if row.pr_number
    }
    if not numbers:
        return 0

    merged = {
        review.pr_number
        for review in db.query(models.PRReview).filter(
            models.PRReview.owner_id == owner_id,
            models.PRReview.repo == repo,
            models.PRReview.pr_number.in_(numbers),
            models.PRReview.state == "merged",
        ).all()
    }
    return len(numbers - merged)


def throughput_exceeded(db: Session, *, owner_id: int, repo: str) -> bool:
    return (
        open_autonomous_prs(db, owner_id=owner_id, repo=repo)
        >= max_open_autonomous_prs()
    )


def next_attempt_number(db: Session, *, owner_id: int, ticket_key: str) -> int:
    """
    The number this attempt would carry.

    Counts *every* recorded attempt, not the ones that opened something. That
    is decision 3: a run that timed out, blew the diff cap or failed the test
    gate spends an attempt exactly as a rejected review does, or a
    reliably-failing ticket retries forever and the bound protects nothing.
    """
    return len(attempts_for(db, owner_id, ticket_key)) + 1


def gather_asks(db: Session, *, owner_id: int, ticket_key: str) -> list[str]:
    """
    Every reviewer ask across every round of every pull request on this item.

    Read from the append-only `PRReviewRound` rather than
    `PRReview.pending_asks`, which `record_merged` clears on its way past. And
    every round is carried rather than only the last, since a request satisfied
    in round two is still something the rework must not undo.
    """
    from app.services.pipeline import work_item as work_item_service

    reviews = work_item_service.sibling_reviews(
        db, owner_id=owner_id, ticket_key=ticket_key
    )
    if not reviews:
        return []

    rounds = db.query(models.PRReviewRound).filter(
        models.PRReviewRound.review_id.in_([r.id for r in reviews]),
    ).order_by(models.PRReviewRound.created_at.asc()).all()

    asks: list[str] = []
    for entry in rounds:
        body = (entry.body or "").strip()
        if entry.outcome == "changes_requested" and body and body not in asks:
            asks.append(body)
    return asks


def should_retry(
    db: Session,
    *,
    owner_id: int,
    ticket_key: str,
    settings,
    repo: str | None = None,
    human_pushed: bool = False,
) -> tuple[bool, str]:
    """
    Whether the driver should take another swing at this work item.

    Returns `(retry, reason)`. The reason is always populated on a refusal,
    because every refusal is either announced or held silently and both need to
    say why somewhere.

    Refuses when the item is handed back, when the mode is not autonomous, when
    the bound is spent, when a human has pushed to the branch since the last
    attempt, or when the throughput cap is reached.

    Nothing before this is dangerous; nothing before this is complete either.
    Shipping the driver without the bound means the first reviewer who requests
    changes twice gets an agent that reworks forever, and `round_number` -- the
    signal that makes a stalled review visible -- stops meaning anything.
    """
    if getattr(settings, "handed_back", False):
        return False, settings.handed_back_reason or "This work item was handed back"

    if settings.authoring_mode != "autonomous":
        return False, "Autonomous mode is off for this work item"

    if human_pushed:
        # A person took it over. The same rule as a human commit at authoring
        # time, and for the same reason: an agent overwriting somebody's work
        # is the worst thing it can do quietly.
        return False, "A human has pushed to this branch"

    attempts = len(attempts_for(db, owner_id, ticket_key))
    allowed = settings.autonomous_max_rounds + 1
    if attempts >= allowed:
        return False, (
            f"Locus attempted this {attempts} time{'s' if attempts != 1 else ''} "
            f"and the bound is {allowed}"
        )

    if repo and throughput_exceeded(db, owner_id=owner_id, repo=repo):
        # Held silently by the caller. A held retry that reports every time
        # trains people to ignore the channel, the same rule
        # `automerge.sweep_once` follows.
        return False, (
            f"{max_open_autonomous_prs()} agent-authored pull requests are "
            f"already open on {repo}"
        )

    return True, ""


def handoff_message(
    ticket_key: str, *, attempts: int, reason: str, pr_url: str | None = None
) -> str:
    """
    What the team is told when a work item comes back.

    States the count and what happens next, because "Locus gave up" tells
    somebody nothing they can act on. The branch, the review thread and the
    report are named as unchanged: the most useful thing to know is that
    picking it up costs nothing beyond reading what is already there.
    """
    lines = [
        f"*{ticket_key} is yours now.*",
        "",
        f"Locus attempted this {attempts} time{'s' if attempts != 1 else ''} "
        f"and stopped: {reason}",
        "",
        "The branch, the review thread and the report are unchanged — nothing "
        "was rolled back, so picking it up costs only reading what is there.",
    ]
    if pr_url:
        lines += ["", pr_url]
    return "\n".join(lines)
