"""
Webhook Router
Inbound GitHub events for the PR Context Agent.

This router is intentionally unauthenticated in the JWT sense -- GitHub cannot
present a user token. Authenticity comes from the HMAC-SHA256 signature over
the raw request body, verified against the per-repo secret before the payload
is parsed at all.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models, schemas, security
from app.database import SessionLocal, get_db
from app.dependencies import get_current_user, get_integration_configs
from app.services import (
    automerge,
    comms_log,
    context_brief,
    finding_diff,
    github_pr,
    report_sync,
    review_flow,
    suppression,
    work_item,
    worklist,
)
from app.services.agent_settings import resolve_settings
from app.services.capabilities import build_readiness
from app.services.google_docs_context import extract_document_id
from app.services.merge_actions import run_merge_actions
from app.services.pr_agent import analyze_pull_request
from app.services.security_scan import gitleaks_available, semgrep_available

logger = logging.getLogger(__name__)

router = APIRouter()

# Public origin GitHub will POST to. Locally this is a tunnel URL (cloudflared
# or ngrok), since GitHub cannot reach localhost. Only used to build the
# payload URL shown after registering a repo.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

# PR actions worth analyzing. Ignoring the rest keeps us from re-running on
# label changes, assignments, and other noise.
ANALYZED_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}

# A merged PR triggers the post-merge actions instead of a fresh analysis.
MERGE_ACTION = "merged"

# Review-loop actions. These do not re-run the analysis pipeline -- the diff
# has not changed -- they advance the review state and notify.
REVIEW_SUBMITTED_ACTION = "review_submitted"
REVIEW_REQUESTED_ACTION = "review_requested"
REVIEW_ACTIONS = {REVIEW_SUBMITTED_ACTION, REVIEW_REQUESTED_ACTION}


def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify GitHub's HMAC-SHA256 signature.

    Args:
        payload: Raw request body, exactly as received
        signature: The X-Hub-Signature-256 header value
        secret: The repo's webhook secret

    Returns:
        True if the signature is valid.
    """
    if not signature or not signature.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    # Constant-time compare; a plain == leaks timing information.
    return hmac.compare_digest(expected, signature)


def _parse_webhook_body(raw_body: bytes, content_type: str) -> dict | None:
    """
    Decode a webhook body under either content type GitHub offers.

    The hook's "Content type" setting picks between raw JSON and a form post
    carrying the JSON in a `payload` field. Both are legitimate; a repo with
    two hooks configured differently sends both. Returns None if undecodable.

    Signature verification still runs over the raw bytes, so accepting the
    form encoding does not widen what we trust.
    """
    if "x-www-form-urlencoded" in content_type.lower():
        encoded = parse_qs(raw_body.decode("utf-8", errors="replace")).get("payload")
        if not encoded:
            return None
        raw_body = encoded[0].encode("utf-8")

    try:
        parsed = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    return parsed if isinstance(parsed, dict) else None


@router.post(
    "/github",
    status_code=status.HTTP_202_ACCEPTED,
    summary="GitHub webhook receiver"
)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Receive a GitHub webhook and queue a PR analysis job.

    Returns immediately. GitHub times out at 10 seconds and the pipeline takes
    considerably longer, so the work is persisted and handed to a worker.
    """
    # Read the raw body BEFORE parsing -- the signature covers exact bytes.
    raw_body = await request.body()

    if x_github_event == "ping":
        return {"message": "pong"}

    if x_github_event not in (
        "pull_request", "pull_request_review", "issue_comment"
    ):
        return {"message": f"Ignoring event: {x_github_event}"}

    payload = _parse_webhook_body(raw_body, request.headers.get("content-type", ""))
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload"
        )

    repo_full_name = payload.get("repository", {}).get("full_name")
    if not repo_full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload missing repository"
        )

    # Find the registration for this repo and verify against its secret.
    registration = db.query(models.RepoWebhook).filter(
        models.RepoWebhook.repo == repo_full_name,
        models.RepoWebhook.enabled == 1,
    ).first()

    if not registration:
        # Do not reveal whether the repo is registered.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unrecognized webhook"
        )

    secret = security.decrypt_token(registration.encrypted_secret)
    if not verify_github_signature(raw_body, x_hub_signature_256 or "", secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )

    # A comment carrying an `@locus` command. Handled here rather than queued:
    # it runs a regex over a fixed vocabulary and writes one row, so the
    # webhook can answer within GitHub's timeout without a worker.
    #
    # The comment body is untrusted -- anyone who can comment on the pull
    # request wrote it -- so no model reads it and the only reachable effect
    # is suppressing a finding on this pull request. Nothing here touches
    # another repository or sends anything outward.
    if x_github_event == "issue_comment":
        return await _handle_comment_command(db, payload, registration)

    action = payload.get("action", "")
    pr = payload.get("pull_request", {}) or {}
    review_payload: dict | None = None

    if x_github_event == "pull_request_review":
        # "edited" rewrites a review body and "dismissed" revokes a verdict
        # without supplying a new one; neither is a fresh decision to record.
        if action != "submitted":
            return {"message": f"Ignoring review action: {action}"}

        review = payload.get("review", {}) or {}
        action = REVIEW_SUBMITTED_ACTION
        review_payload = {
            "review_state": review.get("state"),
            "reviewer": (review.get("user") or {}).get("login"),
            "body": review.get("body"),
        }
    elif action == "review_requested":
        action = REVIEW_REQUESTED_ACTION
        # GitHub sends requested_reviewer for a person and requested_team for
        # a team; only one is present on any given event.
        requested = payload.get("requested_reviewer") or {}
        review_payload = {
            "reviewer": requested.get("login") or (
                payload.get("requested_team") or {}
            ).get("slug"),
        }
    elif action == "closed":
        # "closed" with merged=true is the only signal GitHub gives for a merge.
        if not pr.get("merged"):
            return {"message": "Ignoring closed-without-merge"}
        action = MERGE_ACTION
    elif action not in ANALYZED_ACTIONS:
        return {"message": f"Ignoring action: {action}"}

    if pr.get("draft"):
        return {"message": "Ignoring draft PR"}

    if review_payload is not None:
        # Identity fields the review row needs but cannot look up later.
        review_payload.update({
            "pr_url": pr.get("html_url"),
            "pr_title": pr.get("title"),
            "author": (pr.get("user") or {}).get("login"),
        })

    job = models.PRJob(
        repo=repo_full_name,
        pr_number=pr.get("number"),
        action=action,
        head_sha=pr.get("head", {}).get("sha"),
        payload_json=json.dumps(review_payload) if review_payload else None,
        status=schemas.PRJobStatus.queued.value,
        owner_id=registration.owner_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    queued = "Review event queued" if action in REVIEW_ACTIONS else "Analysis queued"
    return {"message": queued, "job_id": job.id}


@router.post(
    "/repos",
    response_model=schemas.RepoRegistration,
    status_code=status.HTTP_201_CREATED,
    summary="Register a repository for PR analysis",
)
async def register_repo(
    request: schemas.RepoRegister,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.RepoRegistration:
    """
    Register a repo and mint its webhook secret.

    The secret is returned exactly once, here. It is stored encrypted and there
    is no endpoint that reads it back -- re-register to rotate.
    """
    secret = secrets.token_urlsafe(32)

    # Accept full Docs URLs or bare ids; store ids only.
    doc_ids = [
        doc_id
        for raw in request.context_docs
        if (doc_id := extract_document_id(raw))
    ]
    stored_docs = "\n".join(doc_ids) if doc_ids else None

    # Basic sanity only; a bad address surfaces as a send failure, not a 400.
    emails = [e.strip() for e in request.qa_emails if e.strip() and "@" in e]
    stored_emails = "\n".join(emails) if emails else None

    # Accept "@octocat" or "octocat"; GitHub logins carry no leading sigil.
    reviewers = [r.strip().lstrip("@") for r in request.reviewers if r.strip()]
    stored_reviewers = "\n".join(reviewers) if reviewers else None

    existing = db.query(models.RepoWebhook).filter(
        models.RepoWebhook.repo == request.repo,
        models.RepoWebhook.owner_id == current_user.id,
    ).first()

    if existing:
        # Re-registering rotates the secret; the old one stops working.
        existing.encrypted_secret = security.encrypt_token(secret)
        existing.slack_channel = request.slack_channel
        existing.export_to_docs = 1 if request.export_to_docs else 0
        existing.context_doc_ids = stored_docs
        existing.qa_emails = stored_emails
        existing.jira_done_status = request.jira_done_status
        existing.close_issues_on_merge = 1 if request.close_issues_on_merge else 0
        existing.close_on_qa_signoff = 1 if request.close_on_qa_signoff else 0
        existing.reviewers = stored_reviewers
        existing.reviewer_contacts = request.reviewer_contacts
        existing.review_slack_channel = request.review_slack_channel
        existing.auto_merge_on_approval = 1 if request.auto_merge_on_approval else 0
        existing.merge_method = request.merge_method.value
        existing.enabled = 1
        registration = existing
    else:
        registration = models.RepoWebhook(
            repo=request.repo,
            encrypted_secret=security.encrypt_token(secret),
            slack_channel=request.slack_channel,
            export_to_docs=1 if request.export_to_docs else 0,
            context_doc_ids=stored_docs,
            qa_emails=stored_emails,
            jira_done_status=request.jira_done_status,
            close_issues_on_merge=1 if request.close_issues_on_merge else 0,
            close_on_qa_signoff=1 if request.close_on_qa_signoff else 0,
            reviewers=stored_reviewers,
            reviewer_contacts=request.reviewer_contacts,
            review_slack_channel=request.review_slack_channel,
            auto_merge_on_approval=1 if request.auto_merge_on_approval else 0,
            merge_method=request.merge_method.value,
            enabled=1,
            owner_id=current_user.id,
        )
        db.add(registration)

    db.commit()
    db.refresh(registration)

    return schemas.RepoRegistration(
        id=registration.id,
        repo=registration.repo,
        slack_channel=registration.slack_channel,
        export_to_docs=bool(registration.export_to_docs),
        context_docs=doc_ids,
        qa_emails=emails,
        jira_done_status=registration.jira_done_status,
        close_issues_on_merge=bool(registration.close_issues_on_merge),
        close_on_qa_signoff=bool(registration.close_on_qa_signoff),
        reviewers=reviewers,
        reviewer_contacts=registration.reviewer_contacts,
        review_slack_channel=registration.review_slack_channel,
        auto_merge_on_approval=bool(registration.auto_merge_on_approval),
        merge_method=registration.merge_method or "squash",
        enabled=True,
        webhook_url=f"{PUBLIC_BASE_URL.rstrip('/')}/webhooks/github",
        webhook_secret=secret,
    )


@router.get(
    "/repos",
    response_model=schemas.RepoRegistrationList,
    summary="List registered repositories",
)
async def list_repos(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.RepoRegistrationList:
    """List a user's registered repos. Secrets are never returned."""
    rows = db.query(models.RepoWebhook).filter(
        models.RepoWebhook.owner_id == current_user.id
    ).all()

    return schemas.RepoRegistrationList(
        repos=[
            schemas.RepoRegistration(
                id=r.id,
                repo=r.repo,
                slack_channel=r.slack_channel,
                export_to_docs=bool(r.export_to_docs),
                context_docs=(r.context_doc_ids or "").splitlines() if r.context_doc_ids else [],
                qa_emails=(r.qa_emails or "").splitlines() if r.qa_emails else [],
                jira_done_status=r.jira_done_status or "Done",
                close_issues_on_merge=bool(r.close_issues_on_merge),
                close_on_qa_signoff=bool(r.close_on_qa_signoff),
                reviewers=(r.reviewers or "").splitlines() if r.reviewers else [],
                reviewer_contacts=r.reviewer_contacts,
                review_slack_channel=r.review_slack_channel,
                auto_merge_on_approval=bool(r.auto_merge_on_approval),
                merge_method=r.merge_method or "squash",
                enabled=bool(r.enabled),
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.delete(
    "/repos/{owner}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister a repository",
)
async def unregister_repo(
    owner: str,
    name: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove a repo registration. Its webhook secret stops being accepted."""
    registration = db.query(models.RepoWebhook).filter(
        models.RepoWebhook.repo == f"{owner}/{name}",
        models.RepoWebhook.owner_id == current_user.id,
    ).first()

    if not registration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Repository not registered"
        )

    db.delete(registration)
    db.commit()


@router.get(
    "/defaults",
    response_model=schemas.PRAgentDefaults,
    summary="Read account-wide PR agent defaults",
)
async def get_defaults(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRAgentDefaults:
    """
    Fallbacks applied to any repo that does not set its own.

    Returns the schema defaults when nothing has been saved yet, so the client
    never has to special-case a missing row.
    """
    row = db.query(models.PRAgentDefaults).filter(
        models.PRAgentDefaults.owner_id == current_user.id
    ).first()

    if not row:
        return schemas.PRAgentDefaults()

    return schemas.PRAgentDefaults(
        slack_channel=row.slack_channel,
        export_to_docs=bool(row.export_to_docs),
        qa_emails=[e for e in (row.qa_emails or "").splitlines() if e.strip()],
        jira_done_status=row.jira_done_status,
        close_issues_on_merge=bool(row.close_issues_on_merge),
        close_on_qa_signoff=bool(row.close_on_qa_signoff),
        reviewers=[r for r in (row.reviewers or "").splitlines() if r.strip()],
        reviewer_contacts=row.reviewer_contacts,
        review_slack_channel=row.review_slack_channel,
        auto_merge_on_approval=bool(row.auto_merge_on_approval),
        merge_method=row.merge_method or "squash",
        context_docs=[
            d for d in (row.context_doc_ids or "").splitlines() if d.strip()
        ],
    )


@router.put(
    "/defaults",
    response_model=schemas.PRAgentDefaults,
    summary="Save account-wide PR agent defaults",
)
async def save_defaults(
    request: schemas.PRAgentDefaultsUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRAgentDefaults:
    """Create or replace this account's defaults. One row per user."""
    # Same leniency as repo registration: a malformed address surfaces as a
    # send failure rather than blocking the whole save.
    emails = [e.strip() for e in request.qa_emails if e.strip() and "@" in e]
    reviewers = [r.strip().lstrip("@") for r in request.reviewers if r.strip()]

    # Accept full Docs URLs or bare ids; store ids only, as registration does.
    doc_ids = [
        doc_id
        for raw in request.context_docs
        if (doc_id := extract_document_id(raw))
    ]

    row = db.query(models.PRAgentDefaults).filter(
        models.PRAgentDefaults.owner_id == current_user.id
    ).first()

    if not row:
        row = models.PRAgentDefaults(owner_id=current_user.id)
        db.add(row)

    row.slack_channel = (request.slack_channel or "").strip() or None
    row.export_to_docs = 1 if request.export_to_docs else 0
    row.qa_emails = "\n".join(emails) if emails else None
    row.jira_done_status = request.jira_done_status or "Done"
    row.close_issues_on_merge = 1 if request.close_issues_on_merge else 0
    row.close_on_qa_signoff = 1 if request.close_on_qa_signoff else 0
    row.reviewers = "\n".join(reviewers) if reviewers else None
    row.reviewer_contacts = (request.reviewer_contacts or "").strip() or None
    row.review_slack_channel = (request.review_slack_channel or "").strip() or None
    row.auto_merge_on_approval = 1 if request.auto_merge_on_approval else 0
    row.merge_method = request.merge_method.value
    row.context_doc_ids = "\n".join(doc_ids) if doc_ids else None

    db.commit()
    db.refresh(row)

    return schemas.PRAgentDefaults(
        slack_channel=row.slack_channel,
        export_to_docs=bool(row.export_to_docs),
        qa_emails=emails,
        jira_done_status=row.jira_done_status,
        close_issues_on_merge=bool(row.close_issues_on_merge),
        close_on_qa_signoff=bool(row.close_on_qa_signoff),
        reviewers=reviewers,
        reviewer_contacts=row.reviewer_contacts,
        review_slack_channel=row.review_slack_channel,
        auto_merge_on_approval=bool(row.auto_merge_on_approval),
        merge_method=row.merge_method or "squash",
        context_docs=doc_ids,
    )


@router.post(
    "/analyze/{owner}/{name}/{pr_number}",
    response_model=schemas.PRJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Analyze a pull request now",
)
async def trigger_analysis(
    owner: str,
    name: str,
    pr_number: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRJobResponse:
    """
    Queue analysis of an existing PR without waiting for a webhook.

    Useful for testing the pipeline, re-running after fixing a credential, and
    demoing against a PR that is already open.
    """
    job = models.PRJob(
        repo=f"{owner}/{name}",
        pr_number=pr_number,
        action="manual",
        status=schemas.PRJobStatus.queued.value,
        owner_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return schemas.PRJobResponse.model_validate(job)


@router.get(
    "/jobs",
    response_model=list[schemas.PRJobResponse],
    summary="Recent PR analysis jobs",
)
async def list_jobs(
    limit: int = 20,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[schemas.PRJobResponse]:
    """List recent jobs, newest first -- the place to look when a run fails."""
    jobs = (
        db.query(models.PRJob)
        .filter(models.PRJob.owner_id == current_user.id)
        .order_by(models.PRJob.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    responses: list[schemas.PRJobResponse] = []
    for job in jobs:
        response = schemas.PRJobResponse.model_validate(job)

        # Lift the stage list and the searches out of the stored result so the
        # run list can show which steps ran, what was queried and what matched,
        # without a request per row.
        if job.result_json:
            try:
                stored = json.loads(job.result_json)
                response.stages = [
                    schemas.PipelineStage.model_validate(s)
                    for s in stored.get("stages", [])
                ]
                response.tool_calls = [
                    schemas.ToolInvocation.model_validate(c)
                    for c in stored.get("tool_calls", [])
                ]
            except (json.JSONDecodeError, ValueError):
                pass

        responses.append(response)

    return responses


@router.get(
    "/jobs/{job_id}",
    response_model=schemas.PRJobDetail,
    summary="One job with its full analysis result",
)
async def get_job(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRJobDetail:
    """Fetch a job including the gathered context and security findings."""
    job = db.query(models.PRJob).filter(
        models.PRJob.id == job_id,
        models.PRJob.owner_id == current_user.id,
    ).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    result = None
    if job.result_json:
        try:
            result = schemas.PRAnalysisResult.model_validate_json(job.result_json)
        except Exception:
            # A stored result from an older schema should not 500 the endpoint.
            result = None

    detail = schemas.PRJobDetail.model_validate(job)
    detail.result = result
    return detail


@router.get(
    "/reviews",
    response_model=schemas.PRReviewList,
    summary="Pull requests in the senior-dev review loop",
)
async def list_reviews(
    include_merged: bool = False,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRReviewList:
    """
    The review queue, most recently active first.

    Merged PRs are excluded by default: the loop is over for them and the
    queue is meant to show what still needs someone's attention.
    """
    query = db.query(models.PRReview).filter(
        models.PRReview.owner_id == current_user.id
    )

    if not include_merged:
        query = query.filter(
            models.PRReview.state != schemas.ReviewState.merged.value
        )

    rows = query.order_by(
        models.PRReview.updated_at.desc().nullslast(),
        models.PRReview.created_at.desc(),
    ).all()

    return schemas.PRReviewList(
        reviews=[schemas.PRReviewSummary.model_validate(r) for r in rows],
        total=len(rows),
        awaiting_review=sum(
            1 for r in rows
            if r.state == schemas.ReviewState.awaiting_review.value
        ),
        changes_requested=sum(
            1 for r in rows
            if r.state == schemas.ReviewState.changes_requested.value
        ),
        approved=sum(
            1 for r in rows if r.state == schemas.ReviewState.approved.value
        ),
    )


@router.get(
    "/reviews/{owner}/{name}/{pr_number}",
    response_model=schemas.PRReviewDetail,
    summary="One pull request's full review history",
)
async def get_review(
    owner: str,
    name: str,
    pr_number: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRReviewDetail:
    """
    Every round of the loop for one PR, oldest first.

    A PR belonging to another account returns 404 rather than 403 -- a 403
    would confirm the review exists, which is enough to enumerate other
    people's repositories.
    """
    review = db.query(models.PRReview).filter(
        models.PRReview.repo == f"{owner}/{name}",
        models.PRReview.pr_number == pr_number,
        models.PRReview.owner_id == current_user.id,
    ).first()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )

    return review_flow.to_detail(review)


@router.get(
    "/worklist",
    response_model=schemas.Worklist,
    summary="What is waiting on you, across every task",
)
async def get_worklist(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.Worklist:
    """
    The user's outstanding work, grouped by task and ordered by urgency.

    Ordering is settled server-side so the API and the UI cannot disagree
    about what is most urgent. Sorted by whether the ball is with you, then by
    staleness -- a task on its fifth round for three days is a conversation
    that is not converging, which is the signal the per-PR views cannot show.
    """
    return worklist.build(db, owner_id=current_user.id)


@router.get(
    "/activity/{owner}/{name}/{pr_number}",
    response_model=schemas.PRActivity,
    summary="Both loops for one PR, with every message searched, sent, and received",
)
async def get_pr_activity(
    owner: str,
    name: str,
    pr_number: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRActivity:
    """
    The full story of one pull request: review loop, QA loop, and the actual
    message traffic behind both.

    Returned as one payload rather than three endpoints because the UI shows
    them interleaved on a single timeline -- fetching separately would make
    ordering a client-side concern and let the two halves disagree about what
    happened when.

    Returns 404 rather than 403 for another account's PR, like every other
    per-resource endpoint here.
    """
    repo = f"{owner}/{name}"

    review = db.query(models.PRReview).filter(
        models.PRReview.repo == repo,
        models.PRReview.pr_number == pr_number,
        models.PRReview.owner_id == current_user.id,
    ).first()

    qa = db.query(models.QAThread).filter(
        models.QAThread.repo == repo,
        models.QAThread.pr_number == pr_number,
        models.QAThread.owner_id == current_user.id,
    ).order_by(models.QAThread.created_at.desc()).first()

    # The work item, so the timeline can include the Slack discussion cached
    # under it by earlier PRs -- context this PR's analysis was actually given.
    activity_ticket = None
    if review and review.ticket_keys:
        activity_ticket = review.ticket_keys.splitlines()[0].strip() or None

    events = comms_log.timeline(
        db, owner_id=current_user.id, repo=repo, pr_number=pr_number,
        ticket_key=activity_ticket,
    )

    # A PR with no review, no QA thread, and no messages was never seen at
    # all -- distinct from one that was processed and produced nothing.
    if review is None and qa is None and not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No activity recorded for this pull request",
        )

    registration = db.query(models.RepoWebhook).filter(
        models.RepoWebhook.repo == repo,
        models.RepoWebhook.owner_id == current_user.id,
    ).first()
    settings = resolve_settings(db, current_user.id, registration)

    # Every configured reviewer, plus anyone who actually reviewed. Someone
    # who reviewed without being on the list is exactly who you want to see.
    logins = list(settings.reviewers)
    if review and review.last_reviewer and review.last_reviewer not in logins:
        logins.append(review.last_reviewer)

    contacts = [
        schemas.ReviewerContact(
            login=login,
            slack=settings.reviewer_contacts.get(login, {}).get("slack"),
            email=settings.reviewer_contacts.get(login, {}).get("email"),
        )
        for login in logins
    ]

    return schemas.PRActivity(
        repo=repo,
        pr_number=pr_number,
        pr_url=(review.pr_url if review else None) or (qa.pr_url if qa else None),
        pr_title=review.pr_title if review else None,
        review=review_flow.to_detail(review) if review else None,
        reviewer_contacts=contacts,
        qa_notified=qa is not None,
        qa_resolved=bool(qa.resolved) if qa else None,
        qa_channel=qa.slack_channel if qa else settings.slack_channel,
        qa_recipients=settings.qa_emails,
        events=[
            schemas.CommunicationEvent.model_validate(e) for e in events
        ],
    )


@router.get(
    "/summary",
    response_model=schemas.PRAgentSummary,
    summary="PR agent dashboard summary",
)
async def agent_summary(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PRAgentSummary:
    """
    Headline counts plus a readiness picture for the PR agent.

    The dashboard uses this to explain why a run produced thin results -- a
    missing Slack user token or an absent scanner is invisible otherwise.
    """
    jobs = db.query(models.PRJob).filter(models.PRJob.owner_id == current_user.id).all()

    confirmed = unverified = 0
    for job in jobs:
        if not job.result_json:
            continue
        try:
            data = json.loads(job.result_json)
            confirmed += len(data.get("confirmed_findings", []))
            unverified += len(data.get("unverified_findings", []))
        except (json.JSONDecodeError, AttributeError):
            continue

    by_status: dict[str, int] = {}
    for job in jobs:
        by_status[job.status] = by_status.get(job.status, 0) + 1

    slack_credentials = crud.get_integration_credentials(db, current_user.id, "slack") or {}

    # Build the per-capability view from the same credential shape the pipeline
    # sees, so the dashboard cannot disagree with what a run would actually do.
    configs: dict[str, dict] = {}
    for integration in crud.get_user_integrations(db, current_user.id):
        entry: dict = {}
        key = crud.get_integration_key(db, current_user.id, integration.service_name)
        if key:
            entry["api_key"] = key
        creds = crud.get_integration_credentials(db, current_user.id, integration.service_name)
        if creds:
            entry["credentials"] = creds
        if entry:
            configs[integration.service_name] = entry

    services = [
        schemas.ServiceStatus(
            key=s.key,
            label=s.label,
            connected=s.connected,
            required=s.required,
            capabilities=[
                schemas.CapabilityStatus(
                    key=c.key, label=c.label, available=c.available,
                    required=c.required, hint=c.hint,
                )
                for c in s.capabilities
            ],
        )
        for s in build_readiness(configs)
    ]

    return schemas.PRAgentSummary(
        total_jobs=len(jobs),
        completed=by_status.get("completed", 0),
        failed=by_status.get("failed", 0),
        running=by_status.get("running", 0),
        queued=by_status.get("queued", 0),
        repos_registered=db.query(models.RepoWebhook).filter(
            models.RepoWebhook.owner_id == current_user.id
        ).count(),
        confirmed_findings=confirmed,
        unverified_findings=unverified,
        github_connected=crud.get_integration(db, current_user.id, "github") is not None,
        jira_connected=crud.get_integration(db, current_user.id, "jira") is not None,
        slack_connected=crud.get_integration(db, current_user.id, "slack") is not None,
        slack_search_enabled=bool(slack_credentials.get("user_token")),
        docs_connected=crud.get_integration(db, current_user.id, "docs") is not None,
        semgrep_available=semgrep_available(),
        gitleaks_available=gitleaks_available(),
        services=services,
        public_base_url=PUBLIC_BASE_URL,
    )


def _latest_doc_url(db: SessionLocal, job: models.PRJob) -> str | None:
    """
    The URL of this pull request's report document.

    Read from the report row rather than from an old job payload: the document
    is rewritten in place, so its id is stable and one row is the truth. Falls
    back to the last completed run's stored URL for pull requests whose report
    predates that row. Returns None when no run wrote a document, the common
    case with Docs export off.
    """
    # By work item first: a later pull request on the same task shares the
    # task's document, and looking only by PR would report it as having none.
    report = report_sync.find_report(
        db,
        owner_id=job.owner_id,
        repo=job.repo,
        pr_number=job.pr_number,
        ticket_key=work_item.resolve_key(
            db, owner_id=job.owner_id, repo=job.repo, pr_number=job.pr_number
        ),
    )
    if report is not None:
        return f"https://docs.google.com/document/d/{report.document_id}/edit"

    previous = (
        db.query(models.PRJob)
        .filter(
            models.PRJob.owner_id == job.owner_id,
            models.PRJob.repo == job.repo,
            models.PRJob.pr_number == job.pr_number,
            models.PRJob.status == schemas.PRJobStatus.completed.value,
            models.PRJob.result_json.isnot(None),
        )
        .order_by(models.PRJob.created_at.desc())
        .first()
    )
    if previous is None:
        return None

    try:
        return json.loads(previous.result_json).get("doc_url")
    except (json.JSONDecodeError, AttributeError):
        # A result stored under an older schema must not break the notification
        # it was only meant to decorate.
        return None


async def _run_review_job(
    db: SessionLocal,
    job: models.PRJob,
    settings,
    integration_configs: dict[str, dict],
) -> None:
    """
    Advance the senior-dev review loop for one review event.

    Kept separate from the analysis path because the two share nothing but the
    job row: this reads a verdict and writes state, where the other reads a
    diff and writes a comment.
    """
    payload = json.loads(job.payload_json) if job.payload_json else {}

    if job.action == REVIEW_SUBMITTED_ACTION:
        review = await review_flow.record_review_submitted(
            db,
            owner_id=job.owner_id,
            repo=job.repo,
            pr_number=job.pr_number,
            review_state=payload.get("review_state") or "",
            reviewer=payload.get("reviewer"),
            body=payload.get("body"),
            head_sha=job.head_sha,
            pr_url=payload.get("pr_url"),
            pr_title=payload.get("pr_title"),
            author=payload.get("author"),
        )
        # The reviewer's own words, recorded before any verdict handling --
        # a commented review is still something a human said about this PR,
        # and the timeline is the only place it would otherwise be visible.
        if payload.get("body") or payload.get("reviewer"):
            comms_log.record(
                db, owner_id=job.owner_id, repo=job.repo,
                pr_number=job.pr_number,
                loop="review", direction="received", channel="github",
                participant=payload.get("reviewer"),
                target=f"PR #{job.pr_number}",
                body=payload.get("body"),
                outcome=payload.get("review_state"),
            )

        # A "commented" review records history but carries no verdict, so
        # there is nothing to announce.
        if review is None or review.state not in (
            schemas.ReviewState.approved.value,
            schemas.ReviewState.changes_requested.value,
        ):
            return

        outcome = (
            schemas.ReviewOutcome.approved
            if review.state == schemas.ReviewState.approved.value
            else schemas.ReviewOutcome.changes_requested
        )
        asks = [
            line.strip()
            for line in (review.pending_asks or "").splitlines()
            if line.strip()
        ]
    else:
        review = review_flow.record_review_requested(
            db,
            owner_id=job.owner_id,
            repo=job.repo,
            pr_number=job.pr_number,
            reviewer=payload.get("reviewer"),
            pr_url=payload.get("pr_url"),
            pr_title=payload.get("pr_title"),
            author=payload.get("author"),
        )
        outcome = schemas.ReviewOutcome.review_requested
        asks = []

    # An approval is what opens the merge gate. Everything else only notifies.
    gate: schemas.MergeGateResult | None = None
    if (
        outcome is schemas.ReviewOutcome.approved
        and settings.auto_merge_on_approval
    ):
        gate = await _try_auto_merge(db, job, review, settings, integration_configs)

    channel = settings.review_slack_channel
    if not channel or "slack" not in integration_configs:
        return

    # A specific requested reviewer beats the configured list: the point of
    # the message is to reach whoever the ball is actually with.
    expected = [payload["reviewer"]] if payload.get("reviewer") else settings.reviewers

    text = review_flow.format_review_notification(
        review, outcome, review.last_reviewer, asks, expected,
        # A review event runs no analysis of its own -- the diff has not
        # changed -- but the verdict it carries is new, so the document is
        # rewritten with it before the link goes out.
        doc_url=await report_sync.refresh(
            db, owner_id=job.owner_id, repo=job.repo,
            pr_number=job.pr_number,
            integration_configs=integration_configs,
        ),
    )
    if gate is not None:
        text += "\n" + review_flow.format_merge_gate(gate)

    sent = await review_flow.post_review_notification(
        integration_configs["slack"], channel, text
    )
    comms_log.record(
        db, owner_id=job.owner_id, repo=job.repo, pr_number=job.pr_number,
        loop="review", direction="sent", channel="slack",
        target=channel,
        participant=", ".join(expected) if expected else None,
        body=text,
        outcome=outcome.value,
        succeeded=sent,
    )


async def _try_auto_merge(
    db: SessionLocal,
    job: models.PRJob,
    review: models.PRReview,
    settings,
    integration_configs: dict[str, dict],
) -> schemas.MergeGateResult:
    """
    Try to merge on the approval event.

    The real work lives in `automerge.attempt_merge`, which is also driven on
    a timer -- a gate evaluated only here would leave a PR stuck whenever
    GitHub had not finished computing mergeability at the instant the approval
    arrived, which is the common case rather than the rare one.
    """
    return await automerge.attempt_merge(
        db,
        owner_id=job.owner_id,
        repo=job.repo,
        pr_number=job.pr_number,
        review=review,
        settings=settings,
        integration_configs=integration_configs,
        head_sha=job.head_sha,
    )


async def _handle_comment_command(
    db: Session,
    payload: dict,
    registration: models.RepoWebhook,
) -> dict:
    """
    Act on an `@locus` command in a pull request comment.

    Only `created` comments on pull requests are considered. GitHub sends
    `issue_comment` for plain issues too, and those have no findings to
    dismiss; an edited comment is not a fresh instruction.

    Locus's own comments are ignored outright. The comment it posts ends with
    an `@locus ignore` hint, and acting on that would make the bot obey its
    own instructions -- the exact confused-deputy shape the untrusted-text
    rules exist to prevent.
    """
    if payload.get("action") != "created":
        return {"message": "Ignoring comment action"}

    issue = payload.get("issue") or {}
    if not issue.get("pull_request"):
        return {"message": "Ignoring comment on a non-PR issue"}

    comment = payload.get("comment") or {}
    body = comment.get("body") or ""
    author = (comment.get("user") or {}).get("login") or ""

    # Our own comment quotes the command syntax; obeying it would be the bot
    # instructing itself.
    if github_pr.COMMENT_MARKER in body or github_pr.INLINE_MARKER in body:
        return {"message": "Ignoring own comment"}

    commands = suppression.parse_commands(body)
    if not commands:
        return {"message": "No command found"}

    repo = registration.repo
    pr_number = issue.get("number")
    if not pr_number:
        return {"message": "Comment carries no pull request number"}

    # The findings this command can refer to are the ones last reported.
    stored = finding_diff.previous_result(
        db, owner_id=registration.owner_id, repo=repo, pr_number=pr_number
    )
    if stored is None:
        return {"message": "No analysis to act on yet"}

    try:
        analysis = schemas.PRAnalysisResult.model_validate(stored)
    except Exception:
        return {"message": "Stored analysis could not be read"}

    applied: list[str] = []
    unmatched: list[str] = []

    for command in commands:
        if not command.suppresses:
            # `explain` is recognised but does nothing yet; it is accepted so
            # the vocabulary is stable and a user is not told it is invalid.
            continue

        matched = suppression.match_finding(analysis, command.target)
        if matched is None:
            unmatched.append(command.target)
            continue

        file_path, title = matched
        suppression.suppress(
            db,
            owner_id=registration.owner_id,
            repo=repo,
            pr_number=pr_number,
            file_path=file_path,
            title=title,
            suppressed_by=author,
            reason=command.reason,
        )
        applied.append(title)

    logger.info(
        "Locus command on %s#%s by %s: %s suppressed, %s unmatched",
        repo, pr_number, author, len(applied), len(unmatched),
    )

    return {
        "message": "Command processed",
        "suppressed": applied,
        "unmatched": unmatched,
    }


async def run_pr_job(job_id: int) -> None:
    """
    Execute a queued PR analysis job.

    Opens its own session: the request that queued this job is long gone.
    """
    db = SessionLocal()
    try:
        job = db.query(models.PRJob).filter(models.PRJob.id == job_id).first()
        # `running` is the normal case: the worker claims the job atomically
        # before calling this. `queued` is accepted for direct callers -- the
        # manual re-run endpoint and the tests -- which have no claim step.
        # Anything terminal is left alone, so a completed job is never re-run.
        if not job or job.status not in (
            schemas.PRJobStatus.queued.value,
            schemas.PRJobStatus.running.value,
        ):
            return

        if job.status == schemas.PRJobStatus.queued.value:
            job.status = schemas.PRJobStatus.running.value
            job.started_at = datetime.now(UTC)
            db.commit()

        registration = db.query(models.RepoWebhook).filter(
            models.RepoWebhook.repo == job.repo,
            models.RepoWebhook.owner_id == job.owner_id,
        ).first()

        # Safe to load credentials outside a request because the service
        # tools take them per call rather than through module globals.
        integration_configs = get_integration_configs(db, job.owner_id)

        is_merge = job.action == MERGE_ACTION

        # Per-repo settings win; the account defaults fill the rest. A repo
        # that was never registered still gets the user's global behaviour
        # rather than silently doing nothing.
        settings = resolve_settings(db, job.owner_id, registration)

        # Review events advance the loop and notify. They deliberately skip
        # the analysis pipeline: the diff has not changed since the last run,
        # and re-scanning it would rewrite the PR comment with identical
        # findings every time a reviewer clicks approve.
        if job.action in REVIEW_ACTIONS:
            await _run_review_job(db, job, settings, integration_configs)
            job.status = schemas.PRJobStatus.completed.value
            job.completed_at = datetime.now(UTC)
            db.commit()
            return

        # A push to a pull request someone has already looked at goes back to
        # the reviewer, whatever state the review was in. Why it is going back
        # has to be captured *before* the call, which overwrites the state.
        #
        # The approval case is the one that matters most: a reviewer approved
        # a diff, the diff changed, and the auto-merge sweep re-evaluates the
        # gate every minute -- so leaving the approval standing merges commits
        # nobody read.
        resubmitted = None
        resubmit_reason = None
        if job.action == "synchronize":
            state_before = db.query(models.PRReview.state).filter(
                models.PRReview.repo == job.repo,
                models.PRReview.pr_number == job.pr_number,
                models.PRReview.owner_id == job.owner_id,
            ).scalar()

            resubmitted = review_flow.record_resubmission(
                db,
                owner_id=job.owner_id,
                repo=job.repo,
                pr_number=job.pr_number,
                head_sha=job.head_sha,
            )

            if resubmitted is not None:
                if state_before == schemas.ReviewState.approved.value:
                    resubmit_reason = "approval_revoked"
                elif state_before == schemas.ReviewState.awaiting_review.value:
                    resubmit_reason = "updated_during_review"

        # The branch and title, for reading the work item off a pull request
        # that has never been analyzed. Cheap next to the pipeline that
        # follows, and its failure costs only the inherited context.
        job_pr_title = job_branch = job_pr_body = None
        gh_key = (integration_configs.get("github") or {}).get("api_key")
        if gh_key:
            try:
                pr_meta = await github_pr.get_pull_request(
                    gh_key, job.repo, job.pr_number
                )
                job_pr_title = pr_meta.get("title")
                job_pr_body = pr_meta.get("body")
                job_branch = (pr_meta.get("head") or {}).get("ref")
            except Exception as e:
                logger.info(
                    "Could not read %s#%s for work-item lookup: %s",
                    job.repo, job.pr_number, e,
                )

        # Everything already known about this work item, so the reviewer sees
        # what earlier rounds asked for and what QA rejected -- not just what
        # this run happened to gather.
        #
        # A previous run on this same pull request recorded the key, which
        # covers every push after the first. The first run on a *new* pull
        # request has no such row, and that is precisely the reopened-ticket
        # case: QA rejects a merged change, the ticket goes back to In
        # Progress, and the fix arrives on a new branch. Reading the key off
        # the branch and title instead lets that PR inherit the history --
        # including why QA rejected the last attempt, which is the one thing
        # it most needs.
        prior_ticket = work_item.resolve_key(
            db,
            owner_id=job.owner_id,
            repo=job.repo,
            pr_number=job.pr_number,
            title=job_pr_title,
            branch=job_branch,
            body=job_pr_body,
        )

        accumulated = context_brief.requirement_context(
            db, owner_id=job.owner_id, repo=job.repo,
            pr_number=job.pr_number, ticket_key=prior_ticket,
        ) or None

        # Everything Slack has already told us about this work item, and when
        # we last asked. The cache is always used; the timestamp makes the
        # search that follows incremental, so a run costs one call and still
        # sees anything said since the last one.
        searched_at, cached_matches = comms_log.cached_search(
            db, owner_id=job.owner_id, repo=job.repo, pr_number=job.pr_number,
            ticket_key=prior_ticket,
        )

        comms: dict = {}
        # The previous completed run's findings, so this one can report what
        # moved. Fetched here rather than inside the pipeline, which takes
        # data rather than a database session.
        prior_findings = finding_diff.previous_result(
            db,
            owner_id=job.owner_id,
            repo=job.repo,
            pr_number=job.pr_number,
            before_job_id=job.id,
        )

        result = await analyze_pull_request(
            accumulated_context=accumulated,
            cached_slack=cached_matches,
            slack_searched_at=searched_at,
            previous_findings=prior_findings,
            suppressed=suppression.active_for(
                db, owner_id=job.owner_id, repo=job.repo,
                pr_number=job.pr_number,
            ),
            comms=comms,
            repo=job.repo,
            pr_number=job.pr_number,
            integration_configs=integration_configs,
            # For refreshing the Google token the Docs export needs, and
            # writing the refreshed one back so the next run starts valid.
            db=db,
            owner_id=job.owner_id,
            # A merged PR is closed; re-commenting on it adds noise. The merge
            # actions and the QA email carry the outcome instead.
            post_comment=not is_merge,
            slack_channel=settings.slack_channel,
            export_to_docs=settings.export_to_docs,
            context_doc_ids=settings.context_doc_ids,
        )

        # The work item this PR belongs to. Keys everything recorded below,
        # and lets the worklist group several PRs into one task.
        ticket_keys = comms.get("ticket_keys") or []
        primary_ticket = ticket_keys[0] if ticket_keys else None

        if ticket_keys:
            review_row = db.query(models.PRReview).filter(
                models.PRReview.repo == job.repo,
                models.PRReview.pr_number == job.pr_number,
                models.PRReview.owner_id == job.owner_id,
            ).first()
            if review_row is None:
                # Created here rather than waiting for a review event. The
                # keys are what makes this pull request findable as a sibling
                # of the work item, and a PR analyzed but never reviewed used
                # to store none -- so the next attempt on a reopened ticket
                # could not find it and started with no history.
                review_row = models.PRReview(
                    repo=job.repo,
                    pr_number=job.pr_number,
                    pr_url=result.context.url,
                    pr_title=result.context.title,
                    author=result.context.author,
                    state=schemas.ReviewState.awaiting_review.value,
                    round_number=1,
                    owner_id=job.owner_id,
                )
                db.add(review_row)
            review_row.ticket_keys = "\n".join(ticket_keys)
            db.commit()

        # A new pull request retrying work that already merged once. This is
        # the reopened-ticket shape: the first attempt merged, QA rejected it,
        # the ticket went back to In Progress, and the fix arrives on a fresh
        # branch. The reviewer is being asked to look at something that has
        # been through the loop before, and the reason it came back is the
        # context they most need -- so it is announced rather than left for
        # them to reconstruct from the ticket.
        if job.action == "opened" and primary_ticket:
            retry, previous = work_item.is_retry(
                db, owner_id=job.owner_id, repo=job.repo,
                pr_number=job.pr_number, ticket_key=primary_ticket,
            )
            if retry and previous is not None:
                rejection = work_item.qa_rejection(
                    db, owner_id=job.owner_id, ticket_key=primary_ticket,
                )
                result.stages.append(schemas.PipelineStage(
                    key="retry_of", label="Retry of earlier work", kind="read",
                    state=schemas.StageState.done,
                    detail=(
                        f"{primary_ticket} was previously merged as "
                        f"{previous.repo}#{previous.pr_number}"
                        + (" and rejected by QA" if rejection else "")
                    ),
                ))

                channel = settings.review_slack_channel
                if channel and "slack" in integration_configs:
                    retry_text = review_flow.format_retry_notice(
                        repo=job.repo,
                        pr_number=job.pr_number,
                        pr_url=result.context.url,
                        pr_title=result.context.title,
                        ticket_key=primary_ticket,
                        previous=previous,
                        qa_rejected=rejection is not None,
                        reviewers=settings.reviewers,
                        doc_url=result.doc_url,
                    )
                    sent = await review_flow.post_review_notification(
                        integration_configs["slack"], channel, retry_text
                    )
                    comms_log.record(
                        db, owner_id=job.owner_id, repo=job.repo,
                        pr_number=job.pr_number,
                        loop="review", direction="sent", channel="slack",
                        target=channel,
                        participant=", ".join(settings.reviewers) or None,
                        body=retry_text,
                        outcome="retry_of_previous",
                        ticket_key=primary_ticket,
                        succeeded=sent,
                    )

        # Linked and mentioned GitHub issues, with the text of each.
        if comms.get("issues"):
            comms_log.record_issues(
                db, owner_id=job.owner_id, repo=job.repo,
                pr_number=job.pr_number, issues=comms["issues"],
                ticket_key=primary_ticket,
            )

        # What was searched for in Slack, and every message it returned.
        if comms.get("slack_queries") or comms.get("slack_matches"):
            comms_log.record_search_matches(
                db, owner_id=job.owner_id, repo=job.repo,
                pr_number=job.pr_number,
                queries=comms.get("slack_queries") or [],
                matches=comms.get("slack_matches") or [],
                ticket_key=primary_ticket,
            )

        if resubmitted is not None:
            stage_detail = f"round {resubmitted.round_number}, awaiting review"
            if resubmit_reason == "approval_revoked":
                stage_detail = (
                    f"approval withdrawn — round {resubmitted.round_number}, "
                    f"awaiting review"
                )
            elif resubmit_reason == "updated_during_review":
                stage_detail = (
                    f"updated mid-review — still round "
                    f"{resubmitted.round_number}"
                )
            result.stages.append(schemas.PipelineStage(
                key="review_round", label="Return to reviewer", kind="write",
                state=schemas.StageState.done,
                detail=stage_detail,
            ))
            channel = settings.review_slack_channel
            if channel and "slack" in integration_configs:
                # What the reviewer asked for, and what actually changed
                # since the commit they reviewed. Both are already stored:
                # pending_asks from their review, head_sha on that round.
                prior_asks = [
                    line.strip()
                    for line in (resubmitted.pending_asks or "").splitlines()
                    if line.strip()
                ]
                reviewed_sha = next(
                    (
                        r.head_sha for r in reversed(resubmitted.rounds)
                        if r.outcome == schemas.ReviewOutcome.changes_requested.value
                        and r.head_sha
                    ),
                    None,
                )
                changed_files: list[dict] = []
                gh_token = (integration_configs.get("github") or {}).get("api_key")
                if gh_token and reviewed_sha and job.head_sha:
                    changed_files = await github_pr.compare_commits(
                        gh_token, job.repo, reviewed_sha, job.head_sha
                    )

                resubmit_text = review_flow.format_review_notification(
                    resubmitted,
                    schemas.ReviewOutcome.resubmitted,
                    resubmitted.last_reviewer,
                    prior_asks,
                    settings.reviewers,
                    changed_files=changed_files,
                    # This round's report, written moments ago by the run
                    # above -- not a stored one from an earlier round.
                    doc_url=result.doc_url,
                    resubmit_reason=resubmit_reason,
                )
                sent = await review_flow.post_review_notification(
                    integration_configs["slack"], channel, resubmit_text
                )
                comms_log.record(
                    db, owner_id=job.owner_id, repo=job.repo,
                    pr_number=job.pr_number,
                    loop="review", direction="sent", channel="slack",
                    target=channel,
                    participant=", ".join(settings.reviewers) or None,
                    body=resubmit_text,
                    outcome=resubmit_reason or "resubmitted",
                    succeeded=sent,
                )

        if is_merge:
            # Read before record_merged, which clears pending_asks on its way
            # past. What the reviewer asked for is the most concrete statement
            # of what this change had to do, and the testing team is who needs
            # it -- a brief built only from the diff and the ticket drops it.
            review_asks = review_flow.asks_for_qa(
                db, owner_id=job.owner_id, repo=job.repo, pr_number=job.pr_number
            )

            # Close the review loop before the QA loop opens. A merged PR must
            # not keep showing up in a review queue.
            review_flow.record_merged(
                db, owner_id=job.owner_id, repo=job.repo, pr_number=job.pr_number
            )

            result.merge_actions = await run_merge_actions(
                result,
                integration_configs,
                jira_done_status=settings.jira_done_status,
                qa_recipients=settings.qa_emails,
                close_issues=settings.close_issues_on_merge,
                qa_slack_channel=settings.slack_channel,
                review_asks=review_asks,
                close_on_qa_signoff=settings.close_on_qa_signoff,
                db=db,
                user_id=job.owner_id,
            )

            # Surface merge outcomes in the same stage timeline as the reads.
            merge_result = result.merge_actions
            result.stages.append(schemas.PipelineStage(
                key="jira_transition", label="Move Jira ticket", kind="write",
                state=(
                    schemas.StageState.done if merge_result.jira_transitioned
                    else schemas.StageState.skipped
                ),
                detail="; ".join(merge_result.jira_transitioned) or "no tickets to move",
            ))
            result.stages.append(schemas.PipelineStage(
                key="close_issues", label="Close linked issues", kind="write",
                state=(
                    schemas.StageState.done if merge_result.issues_closed
                    else schemas.StageState.skipped
                ),
                detail="; ".join(merge_result.issues_closed) or "no issues to close",
            ))
            # Named per channel rather than "Slack and/or email". The vague
            # wording let a rejected email hide behind a successful Slack post,
            # which is the reading that matters: the testing team may include
            # people who only ever see one of the two.
            qa_delivered = []
            if merge_result.qa_thread_ts:
                qa_delivered.append("Slack thread posted")
            if merge_result.qa_email_message_id:
                qa_delivered.append(
                    f"email sent to {', '.join(merge_result.qa_email_to)}"
                )
            qa_attempted_email = bool(merge_result.qa_email_body)
            if qa_attempted_email and not merge_result.qa_email_message_id:
                qa_delivered.append("email FAILED")

            result.stages.append(schemas.PipelineStage(
                key="notify_qa", label="Notify test team", kind="write",
                state=(
                    schemas.StageState.done
                    if merge_result.qa_thread_ts
                    and (not qa_attempted_email or merge_result.qa_email_message_id)
                    else schemas.StageState.failed if qa_delivered
                    else schemas.StageState.skipped
                ),
                detail=(
                    "; ".join(qa_delivered)
                    or "no QA channel or recipients configured"
                ),
            ))

            # What the test team was actually told, in both channels.
            merge_out = result.merge_actions
            if merge_out.qa_slack_text:
                comms_log.record(
                    db, owner_id=job.owner_id, repo=job.repo,
                    pr_number=job.pr_number,
                    loop="qa", direction="sent", channel="slack",
                    target=settings.slack_channel,
                    body=merge_out.qa_slack_text,
                    outcome="ready_to_test",
                    succeeded=bool(merge_out.qa_thread_ts),
                )
            if merge_out.qa_email_body:
                comms_log.record(
                    db, owner_id=job.owner_id, repo=job.repo,
                    pr_number=job.pr_number,
                    loop="qa", direction="sent", channel="email",
                    target=", ".join(merge_out.qa_email_to),
                    participant=", ".join(merge_out.qa_email_to),
                    subject=merge_out.qa_email_subject,
                    body=merge_out.qa_email_body,
                    outcome="ready_to_test",
                    # This row's own evidence, not `qa_notified` -- that flag
                    # is shared with the Slack post, so a successful thread
                    # made a rejected email read as delivered. The message id
                    # exists only when Gmail accepted the send, exactly as
                    # `qa_thread_ts` is the Slack post's own proof.
                    succeeded=bool(merge_out.qa_email_message_id),
                )

            # Record the thread so a tester's reply can be traced back to the
            # work items it should reopen -- a Slack reply carries none of that.
            merge = result.merge_actions
            if merge and (merge.qa_thread_ts or merge.qa_email_message_id):
                db.add(models.QAThread(
                    repo=job.repo,
                    pr_number=job.pr_number,
                    pr_url=result.context.url,
                    # Prefer the id Slack resolved the post to; an inbound
                    # event never carries the "#web" name typed at
                    # registration, so storing that name matches nothing.
                    slack_channel=(
                        merge.qa_channel_id
                        or settings.slack_channel
                    ),
                    slack_thread_ts=merge.qa_thread_ts,
                    email_message_id=merge.qa_email_message_id,
                    ticket_keys_json=json.dumps([t.key for t in result.context.tickets]),
                    issue_numbers_json=json.dumps([
                        i.number for i in result.context.linked_issues
                        if i.relation == "closes"
                    ]),
                    owner_id=job.owner_id,
                ))
                db.commit()

        job.result_json = result.model_dump_json()
        job.status = schemas.PRJobStatus.completed.value
        job.completed_at = datetime.now(UTC)
        db.commit()

    except Exception as e:
        job = db.query(models.PRJob).filter(models.PRJob.id == job_id).first()
        if job:
            job.status = schemas.PRJobStatus.failed.value
            job.error = str(e)
            job.completed_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()
