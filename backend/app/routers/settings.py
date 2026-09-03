"""
User Settings Router
Model backend status.

Locus runs on a local OpenAI-compatible model server (MoE Model Manager) by
default, and can be pointed at OpenAI, Anthropic or Gemini instead with
`LLM_PROVIDER` plus that provider's key. Keys are environment configuration,
not per-user data, and no endpoint here returns one -- only whether one is set.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.services import integration_health
from app.services.chat.llm import (
    available_providers,
    check_llm_available,
    describe_backend,
)

router = APIRouter()


@router.get(
    "/llm",
    response_model=schemas.LLMStatus,
    summary="Model backend status"
)
async def llm_status() -> schemas.LLMStatus:
    """
    Report whether the configured backend can serve a request.

    The frontend uses this to tell the user to start MoE Model Manager, or to
    set the missing API key, rather than letting chat fail with an opaque
    connection error. It also names which provider is active, because pointing
    the analysis passes at a hosted API changes where your code goes.
    """
    available, message = await check_llm_available()
    backend = describe_backend()

    return schemas.LLMStatus(
        available=available,
        message=message,
        provider=backend["provider"],
        is_local=bool(backend["is_local"]),
        base_url=backend["base_url"],
        fast_model=backend["fast_model"],
        smart_model=backend["smart_model"],
        api_key_env=backend["api_key_env"],
        api_key_configured=bool(backend["api_key_configured"]),
        providers=[schemas.LLMProviderOption(**p) for p in available_providers()],
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
