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
import os
import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models, schemas, security
from app.database import SessionLocal, get_db
from app.dependencies import get_current_user, get_integration_configs
from app.services.agent_settings import resolve_settings
from app.services.capabilities import build_readiness
from app.services.google_docs_context import extract_document_id
from app.services.merge_actions import run_merge_actions
from app.services.pr_agent import analyze_pull_request
from app.services.security_scan import gitleaks_available, semgrep_available

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

    if x_github_event != "pull_request":
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

    action = payload.get("action", "")
    pr = payload.get("pull_request", {})

    # "closed" with merged=true is the only signal GitHub gives for a merge.
    if action == "closed":
        if not pr.get("merged"):
            return {"message": "Ignoring closed-without-merge"}
        action = MERGE_ACTION
    elif action not in ANALYZED_ACTIONS:
        return {"message": f"Ignoring action: {action}"}

    if pr.get("draft"):
        return {"message": "Ignoring draft PR"}

    job = models.PRJob(
        repo=repo_full_name,
        pr_number=pr.get("number"),
        action=action,
        head_sha=pr.get("head", {}).get("sha"),
        status=schemas.PRJobStatus.queued.value,
        owner_id=registration.owner_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return {"message": "Analysis queued", "job_id": job.id}


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

    db.commit()
    db.refresh(row)

    return schemas.PRAgentDefaults(
        slack_channel=row.slack_channel,
        export_to_docs=bool(row.export_to_docs),
        qa_emails=emails,
        jira_done_status=row.jira_done_status,
        close_issues_on_merge=bool(row.close_issues_on_merge),
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


async def run_pr_job(job_id: int) -> None:
    """
    Execute a queued PR analysis job.

    Opens its own session: the request that queued this job is long gone.
    """
    db = SessionLocal()
    try:
        job = db.query(models.PRJob).filter(models.PRJob.id == job_id).first()
        if not job or job.status != schemas.PRJobStatus.queued.value:
            return

        job.status = schemas.PRJobStatus.running.value
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

        result = await analyze_pull_request(
            repo=job.repo,
            pr_number=job.pr_number,
            integration_configs=integration_configs,
            # A merged PR is closed; re-commenting on it adds noise. The merge
            # actions and the QA email carry the outcome instead.
            post_comment=not is_merge,
            slack_channel=settings.slack_channel,
            export_to_docs=settings.export_to_docs,
            context_doc_ids=settings.context_doc_ids,
        )

        if is_merge:
            result.merge_actions = await run_merge_actions(
                result,
                integration_configs,
                jira_done_status=settings.jira_done_status,
                qa_recipients=settings.qa_emails,
                close_issues=settings.close_issues_on_merge,
                qa_slack_channel=settings.slack_channel,
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
            result.stages.append(schemas.PipelineStage(
                key="notify_qa", label="Notify test team", kind="write",
                state=(
                    schemas.StageState.done if merge_result.qa_notified
                    else schemas.StageState.skipped
                ),
                detail=(
                    "Slack thread and/or email sent" if merge_result.qa_notified
                    else "no QA channel or recipients configured"
                ),
            ))

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
