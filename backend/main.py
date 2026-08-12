"""
Locus - Enterprise Integration Store
FastAPI Backend Entry Point
"""

import asyncio
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
    webhooks,
)
from app.services.worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and start the background PR worker."""
    Base.metadata.create_all(bind=engine)

    worker_task = asyncio.create_task(worker_loop())
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
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
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://locus-gamma.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
