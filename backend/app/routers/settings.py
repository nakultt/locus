"""
User Settings Router
Local model backend status.

Locus runs entirely on a local OpenAI-compatible model server (MoE Model
Manager). There are no per-user model API keys to manage.
"""

from fastapi import APIRouter

from app import schemas
from app.services.llm import check_llm_available, describe_backend

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
