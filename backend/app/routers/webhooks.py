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
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models, schemas, security
from app.database import SessionLocal, get_db
from app.services.pr_agent import analyze_pull_request

router = APIRouter()

# PR actions worth analyzing. Ignoring the rest keeps us from re-running on
# label changes, assignments, and other noise.
ANALYZED_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


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

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload"
        ) from e

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
    if action not in ANALYZED_ACTIONS:
        return {"message": f"Ignoring action: {action}"}

    pr = payload.get("pull_request", {})
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

        # Load this user's credentials directly. Only safe because the service
        # tools take credentials per call rather than through module globals.
        integration_configs: dict[str, dict] = {}
        for integration in crud.get_user_integrations(db, job.owner_id):
            config: dict = {}
            api_key = crud.get_integration_key(db, job.owner_id, integration.service_name)
            if api_key:
                config["api_key"] = api_key
            credentials = crud.get_integration_credentials(
                db, job.owner_id, integration.service_name
            )
            if credentials:
                config["credentials"] = credentials
            if config:
                integration_configs[integration.service_name] = config

        result = await analyze_pull_request(
            repo=job.repo,
            pr_number=job.pr_number,
            integration_configs=integration_configs,
            post_comment=True,
            slack_channel=registration.slack_channel if registration else None,
        )

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
