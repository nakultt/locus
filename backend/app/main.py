"""
Locus - Enterprise Integration Store
FastAPI Backend Entry Point
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
from app.routers import (
    auth,
    chat,
    conversations,
    google_oauth,
    linear_oauth,
    schedule,
    settings,
    slack_events,
    tasks,
    webhooks,
)
from app.services.worker import (
    calendar_agent_loop,
    merge_gate_loop,
    qa_email_loop,
    worker_loop,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and start the background PR worker."""
    Base.metadata.create_all(bind=engine)

    tasks = [
        asyncio.create_task(worker_loop()),
        asyncio.create_task(qa_email_loop()),
        asyncio.create_task(merge_gate_loop()),
        asyncio.create_task(calendar_agent_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Locus",
    description="Enterprise Integration Store - Connect your tools, command with chat",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration
# NOTE:
# - When allow_credentials=True, we CANNOT use allow_origins=["*"].
# - Browsers will reject such responses and FastAPI/Starlette will raise at startup.
#
# Production origins are listed explicitly; extra ones can be added via
# CORS_ORIGINS (comma-separated).
allowed_origins = [
    "https://locus-gamma.vercel.app",
]

_extra_origins = os.getenv("CORS_ORIGINS", "")
allowed_origins.extend(
    origin.strip() for origin in _extra_origins.split(",") if origin.strip()
)

# Any localhost port, for development. Next picks the next free port when 3000
# is taken, so a fixed list means CORS silently breaks whenever that happens.
LOCALHOST_ORIGIN_PATTERN = r"http://(localhost|127\.0\.0\.1):\d+"

# ...but only in development.
#
# The comment this replaces claimed the regex did not loosen production. It
# did: it was passed unconditionally, so a deployed instance accepted
# credentialed cross-origin requests from *any* page served on any localhost
# port — a locally installed application, a dev server for an untrusted
# repository, anything on the victim's own machine listening over HTTP.
#
# The blast radius today is small, because this API authenticates with a bearer
# token out of the frontend's own storage rather than a cookie, and a page on a
# different origin cannot read that. It is still a hole that costs nothing to
# close, and it stops being small the moment anything here starts using cookies.
#
# `ENV` is read rather than inverted from a debug flag so the safe state is the
# one you get by not configuring anything.
IS_DEVELOPMENT = os.getenv("ENV", "development").lower() not in {
    "production",
    "prod",
    "staging",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=LOCALHOST_ORIGIN_PATTERN if IS_DEVELOPMENT else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(google_oauth.router, prefix="/auth", tags=["Google OAuth"])
app.include_router(linear_oauth.router, prefix="/auth", tags=["Linear OAuth"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(conversations.router, prefix="/api", tags=["Conversations"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["Scheduler"])
app.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
app.include_router(slack_events.router, prefix="/webhooks", tags=["Webhooks"])


@app.get("/", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "Locus API"}


@app.get("/health", tags=["Health"])
async def detailed_health() -> dict[str, str]:
    """Detailed health check for Render."""
    return {
        "status": "healthy",
        "service": "Locus API",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
