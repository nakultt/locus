"""
User Settings Router
Model backend configuration and status.

Which model backend Locus runs on is a setting, not a deployment constant:
the provider, the endpoint and the API key are entered here and stored per
user, Fernet-encrypted like every other credential. The environment stays as
the deployment-wide default for anyone who has not set one, so a single-tenant
install keeps working with nothing configured.

No endpoint returns a stored key -- only whether one is set. That is why
`LLMConfigUpdate.api_key` is optional rather than required: a form that cannot
read the key back must be able to save the rest without erasing it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.services import integration_health
from app.services.chat import llm_config
from app.services.chat.llm import (
    available_providers,
    check_llm_available,
    describe_backend,
    normalize_provider,
)

router = APIRouter()


@router.get(
    "/llm",
    response_model=schemas.LLMStatus,
    summary="Model backend status"
)
async def llm_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.LLMStatus:
    """
    Report whether the configured backend can serve a request.

    The frontend uses this to tell the user to start MoE Model Manager, or to
    set the missing API key, rather than letting chat fail with an opaque
    connection error. It also names which provider is active, because pointing
    the analysis passes at a hosted API changes where your code goes.

    Reported for *this user's* settings, which is what their work will
    actually run on -- a status page describing the deployment default while
    the user's own provider is misconfigured is worse than no status page.
    """
    llm_config.bind_for_user(db, current_user.id)

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
        source=str(backend["source"]),
    )


def _config_out(db: Session, user_id: int) -> schemas.LLMConfigOut:
    """The saved settings, with the providers list the form renders from."""
    setting = crud.get_llm_setting(db, user_id)

    # The provider list is computed against the user's own bound config, so
    # "key set" on each row is a statement about their key rather than the
    # deployment's.
    llm_config.bind_for_user(db, user_id)
    providers = [schemas.LLMProviderOption(**p) for p in available_providers()]

    if not setting:
        return schemas.LLMConfigOut(configured=False, providers=providers)

    return schemas.LLMConfigOut(
        provider=setting.provider,
        base_url=setting.base_url,
        fast_model=setting.fast_model,
        smart_model=setting.smart_model,
        timeout_seconds=setting.timeout_seconds,
        api_key_configured=bool(setting.encrypted_api_key),
        configured=True,
        providers=providers,
    )


@router.get(
    "/llm-config",
    response_model=schemas.LLMConfigOut,
    summary="The model backend this account runs on",
)
async def get_llm_config(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.LLMConfigOut:
    """
    What this user saved, exactly as saved.

    Blank fields are returned blank rather than filled in with what they
    resolve to: a blank means "inherit the deployment default", and rendering
    the resolved value would make the next save pin it permanently.
    """
    return _config_out(db, current_user.id)


@router.put(
    "/llm-config",
    response_model=schemas.LLMConfigOut,
    summary="Point this account at a model backend",
)
async def put_llm_config(
    payload: schemas.LLMConfigUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.LLMConfigOut:
    """
    Save the provider, endpoint, model ids, timeout and API key.

    The provider is normalized rather than validated into a 422: the same
    rule the environment already follows, where an unrecognized value falls
    back to local. Failing towards the backend that sends nothing off the
    machine is the safe direction.
    """
    crud.upsert_llm_setting(
        db,
        current_user.id,
        provider=normalize_provider(payload.provider) if payload.provider else None,
        base_url=payload.base_url,
        fast_model=payload.fast_model,
        smart_model=payload.smart_model,
        timeout_seconds=payload.timeout_seconds,
        api_key=payload.api_key,
        # `None` means the field was omitted, which leaves the stored key
        # alone; an explicit "" clears it.
        api_key_provided=payload.api_key is not None,
    )
    return _config_out(db, current_user.id)


@router.delete(
    "/llm-config",
    response_model=schemas.LLMConfigOut,
    summary="Fall back to the deployment default",
)
async def delete_llm_config(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.LLMConfigOut:
    """Drop the saved settings, including the key, and inherit the default."""
    crud.delete_llm_setting(db, current_user.id)
    llm_config.clear()
    return _config_out(db, current_user.id)


@router.post(
    "/llm-config/test",
    response_model=schemas.LLMStatus,
    summary="Try a backend without saving it",
)
async def test_llm_config(
    payload: schemas.LLMConfigUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.LLMStatus:
    """
    Check the submitted settings against the real endpoint before saving.

    Saving first and reading the status afterwards would mean a wrong endpoint
    takes the account's analysis down until it is corrected. The submitted
    values are bound for this request only; nothing is written.

    An omitted key falls back to the stored one, so an endpoint or model id
    can be tested without retyping a key the browser was never given.
    """
    stored = crud.get_llm_setting(db, current_user.id)
    api_key = payload.api_key
    if api_key is None and stored:
        existing = llm_config.from_row(stored)
        api_key = existing.api_key

    llm_config.bind(
        llm_config.LLMConfig(
            provider=normalize_provider(payload.provider) if payload.provider else None,
            base_url=payload.base_url,
            fast_model=payload.fast_model,
            smart_model=payload.smart_model,
            api_key=api_key,
            timeout_seconds=payload.timeout_seconds,
        )
    )

    try:
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
            source=str(backend["source"]),
        )
    finally:
        # A test must not leave the request bound to settings nobody saved.
        llm_config.clear()


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
