"""
Merging an approved pull request, and retrying when the gate is not yet ready.

Evaluating the gate once, at the moment the approval arrives, does not work.
GitHub computes mergeability lazily and asynchronously: the first read after
any change returns `mergeable: null`, and the approval webhook fires within a
second of the click. So the overwhelmingly common path is that Locus reads the
PR before GitHub has finished thinking about it, holds because unknown is not
yes, and -- with no retry -- leaves an approved PR sitting open forever.

The same applies to any check still running when the reviewer clicks approve.
GitHub emits no event when mergeability finishes computing, so there is nothing
to subscribe to; a sweep is the only mechanism that closes the gap.

`attempt_merge` is therefore written to be called repeatedly and to be
side-effect-free when it declines. `sweep_once` re-runs it for every approved
PR whose repo has auto-merge enabled.
"""

import logging

from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import SessionLocal
from app.services import github_pr, review_flow
from app.services.agent_settings import resolve_settings

logger = logging.getLogger(__name__)

# How often to re-check approved PRs that were not mergeable yet. Mergeability
# usually resolves within seconds; a running check can take minutes.
SWEEP_INTERVAL_SECONDS = 60

# Stop retrying after this long. A PR still blocked a day after approval is
# blocked on something a sweep cannot fix -- a real conflict, a red build, a
# finding -- and the reason was already reported when the approval landed.
MAX_RETRY_HOURS = 24


async def attempt_merge(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    review: models.PRReview,
    settings,
    integration_configs: dict[str, dict],
    head_sha: str | None = None,
) -> schemas.MergeGateResult:
    """
    Merge an approved PR, if every gate passes.

    Approval alone is not enough. A reviewer clicking approve is saying the
    change is right, not that CI passed -- they may not have looked, and on a
    fast-moving PR the checks may not have finished. This is the only path
    that writes to a default branch with no human in the loop, so the gate is
    evaluated independently of the approval and every refusal is reported.

    Declining is free: nothing is written and no message is sent, so this is
    safe to call on a timer until it either merges or times out.

    The merge itself is not the end of the flow: GitHub fires a
    `closed` + `merged=true` webhook for an API merge exactly as it does for a
    human one, which queues the ordinary merge job -- Jira transition, issue
    closing, QA notification. Nothing about that is special-cased here.
    """
    token = (integration_configs.get("github") or {}).get("api_key") or ""
    if not token:
        return schemas.MergeGateResult(blockers=["GitHub is not connected"])

    # Re-read the PR rather than trusting a webhook payload: mergeability and
    # the head commit may have moved since.
    try:
        pr = await github_pr.get_pull_request(token, repo, pr_number)
    except Exception as e:
        return schemas.MergeGateResult(blockers=[f"Could not read the PR: {e}"])

    if pr.get("merged"):
        return schemas.MergeGateResult(
            merged=True, detail="Already merged before the gate ran"
        )

    sha = (pr.get("head") or {}).get("sha") or head_sha or ""
    ci_state, failing = "success", []
    if sha:
        try:
            ci_state, failing = await github_pr.get_combined_ci_state(
                token, repo, sha
            )
        except Exception as e:
            return schemas.MergeGateResult(
                blockers=[f"Could not read CI status: {e}"]
            )

    # The most recent completed analysis carries the findings the gate
    # refuses to merge over.
    analysis = None
    last = (
        db.query(models.PRJob)
        .filter(
            models.PRJob.repo == repo,
            models.PRJob.pr_number == pr_number,
            models.PRJob.owner_id == owner_id,
            models.PRJob.status == schemas.PRJobStatus.completed.value,
            models.PRJob.result_json.isnot(None),
        )
        .order_by(models.PRJob.completed_at.desc())
        .first()
    )
    if last is not None:
        try:
            analysis = schemas.PRAnalysisResult.model_validate_json(last.result_json)
        except Exception:
            # A result stored under an older schema must not block a merge by
            # looking like a failure to read findings.
            analysis = None

    # Whether this pull request was written by the authoring agent, and what
    # it touched. Only consulted for a machine-authored one, so the file
    # listing is not fetched for the ordinary case.
    machine_authored = _is_machine_authored(db, owner_id, repo, pr_number)
    changed_paths: list[str] = []
    if machine_authored:
        try:
            changed_paths = [
                entry.get("filename", "")
                for entry in await github_pr.get_pr_files(token, repo, pr_number)
            ]
        except Exception:
            # A file listing that failed must not silently un-block the check
            # it feeds. Treated as "the workflow directory might be in there",
            # which holds the merge and says so.
            changed_paths = [".github/workflows/(file list unavailable)"]

    allowed, blockers = review_flow.evaluate_merge_gate(
        review, analysis, ci_state, failing, pr.get("mergeable"),
        changed_paths=changed_paths,
        machine_authored=machine_authored,
    )

    if not allowed:
        return schemas.MergeGateResult(blockers=blockers)

    merged, detail = await github_pr.merge_pull_request(
        token, repo, pr_number,
        merge_method=settings.merge_method,
        commit_title=f"{review.pr_title or 'Merge pull request'} (#{pr_number})",
    )

    return schemas.MergeGateResult(
        attempted=True, merged=merged, detail=detail,
        blockers=[] if merged else [detail],
    )


def _integration_configs(db: Session, owner_id: int) -> dict[str, dict]:
    """Decrypted credentials for one user, as the tools expect them."""
    configs: dict[str, dict] = {}
    for integration in crud.get_user_integrations(db, owner_id):
        config: dict = {}
        api_key = crud.get_integration_key(db, owner_id, integration.service_name)
        if api_key:
            config["api_key"] = api_key
        credentials = crud.get_integration_credentials(
            db, owner_id, integration.service_name
        )
        if credentials:
            config["credentials"] = credentials
        if config:
            configs[integration.service_name] = config
    return configs


async def sweep_once() -> int:
    """
    Retry the merge gate for every approved PR still waiting on it.

    Silent when it declines. The reason a PR is held was already reported when
    the approval landed, and repeating it every minute would train people to
    ignore the channel. Only a successful merge announces itself.

    Returns:
        How many pull requests were merged this sweep.
    """
    from datetime import UTC, datetime, timedelta

    db = SessionLocal()
    merged_count = 0

    try:
        cutoff = datetime.now(UTC) - timedelta(hours=MAX_RETRY_HOURS)

        pending = (
            db.query(models.PRReview)
            .filter(models.PRReview.state == schemas.ReviewState.approved.value)
            .all()
        )

        for review in pending:
            # created_at is naive on SQLite; compare defensively rather than
            # letting a timezone mismatch abort the whole sweep.
            stamp = review.updated_at or review.created_at
            if stamp is not None:
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=UTC)
                if stamp < cutoff:
                    continue

            registration = (
                db.query(models.RepoWebhook)
                .filter(
                    models.RepoWebhook.repo == review.repo,
                    models.RepoWebhook.owner_id == review.owner_id,
                )
                .first()
            )
            settings = resolve_settings(db, review.owner_id, registration)
            if not settings.auto_merge_on_approval:
                continue

            configs = _integration_configs(db, review.owner_id)

            try:
                gate = await attempt_merge(
                    db,
                    owner_id=review.owner_id,
                    repo=review.repo,
                    pr_number=review.pr_number,
                    review=review,
                    settings=settings,
                    integration_configs=configs,
                )
            except Exception:
                logger.exception(
                    "Merge sweep failed for %s#%s", review.repo, review.pr_number
                )
                continue

            if not gate.merged:
                continue

            merged_count += 1
            logger.info(
                "Auto-merged %s#%s on retry", review.repo, review.pr_number
            )

            channel = settings.review_slack_channel
            if channel and "slack" in configs:
                await review_flow.post_review_notification(
                    configs["slack"], channel,
                    review_flow.format_merge_gate(gate),
                )

    finally:
        db.close()

    return merged_count


def _is_machine_authored(db, owner_id: int, repo: str, pr_number: int) -> bool:
    """
    Whether the authoring agent opened this pull request.

    Read from `AuthoringAttempt` rather than from the commit author, because
    the question is who *produced* the change -- a rework a person then pushed
    to is still a machine-authored pull request, and the extra caution the gate
    applies to one is not something a follow-up commit should clear.
    """
    return db.query(models.AuthoringAttempt).filter(
        models.AuthoringAttempt.owner_id == owner_id,
        models.AuthoringAttempt.repo == repo,
        models.AuthoringAttempt.pr_number == pr_number,
        models.AuthoringAttempt.opened == 1,
    ).first() is not None
