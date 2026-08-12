"""
Locus - Enterprise Integration Store
FastAPI Backend Entry Point
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import (
    auth,
    chat,
    conversations,
    google_oauth,
    linear_oauth,
    settings,
    slack_events,
    webhooks,
)
from app.services.worker import qa_email_loop, worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and start the background PR worker."""
    Base.metadata.create_all(bind=engine)

    tasks = [
        asyncio.create_task(worker_loop()),
        asyncio.create_task(qa_email_loop()),
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

# Any localhost port, for development. Vite picks the next free port when its
# default is taken, so a fixed list means CORS silently breaks whenever that
# happens. A regex covers every dev port without loosening production, which
# still only matches the explicit origins above.
LOCALHOST_ORIGIN_PATTERN = r"http://(localhost|127\.0\.0\.1):\d+"

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=LOCALHOST_ORIGIN_PATTERN,
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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
