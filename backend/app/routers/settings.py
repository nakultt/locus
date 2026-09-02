"""
User Settings Router
Local model backend status.

Locus runs entirely on a local OpenAI-compatible model server (MoE Model
Manager). There are no per-user model API keys to manage.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.services import integration_health
from app.services.chat.llm import check_llm_available, describe_backend

router = APIRouter()


@router.get(
    "/llm",
    response_model=schemas.LLMStatus,
    summary="Local model backend status"
)
async def llm_status() -> schemas.LLMStatus:
    """
    Report whether the local model server is reachable and has a model loaded.

    The frontend uses this to tell the user to start MoE Model Manager, rather
    than letting chat fail with an opaque connection error.
    """
    available, message = await check_llm_available()
    backend = describe_backend()

    return schemas.LLMStatus(
        available=available,
        message=message,
        provider=backend["provider"],
        base_url=backend["base_url"],
        fast_model=backend["fast_model"],
        smart_model=backend["smart_model"],
    )


@router.get(
    "/integration-health",
    response_model=list[schemas.IntegrationHealthEntry],
    summary="Whether each integration is actually working",
)
async def integration_health_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> list[schemas.IntegrationHealthEntry]:
    """
    Last success, last failure, and the current failure streak per service.

    The background loops swallow their own errors so one dead integration
    cannot stop the rest. This is where that silence surfaces: a Gmail token
    that expired days ago otherwise shows up only as QA replies mysteriously
    no longer arriving.

    Only services with a recorded attempt appear. One never called is absent
    rather than reported healthy.
    """
    return [
        schemas.IntegrationHealthEntry(**entry)
        for entry in integration_health.summary(db, owner_id=current_user.id)
    ]
