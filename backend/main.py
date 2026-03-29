"""
Locus - Enterprise Integration Store
FastAPI Backend Entry Point
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import auth, chat, google_oauth, linear_oauth, conversations, settings


MCP_ENV_PREFIXES = [
    "MCP_GITHUB",
    "MCP_SLACK",
    "MCP_LINEAR",
    "MCP_ATLASSIAN",
    "MCP_NOTION",
    "MCP_GOOGLE_WORKSPACE",
    "MCP_BUGASURA",
]


def _mcp_server_configuration() -> dict[str, dict[str, str | bool]]:
    """Return non-secret MCP configuration status for readiness checks."""
    status: dict[str, dict[str, str | bool]] = {}
    for prefix in MCP_ENV_PREFIXES:
        name = prefix.replace("MCP_", "").lower()
        transport = os.getenv(f"{prefix}_TRANSPORT", "http").strip().lower() or "http"
        has_url = bool(os.getenv(f"{prefix}_URL", "").strip())
        has_command = bool(os.getenv(f"{prefix}_COMMAND", "").strip())
        configured = has_command if transport == "stdio" else has_url
        status[name] = {
            "transport": transport,
            "configured": configured,
        }
    return status


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    Base.metadata.create_all(bind=engine)
    yield


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


@app.get("/", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "Locus API"}


@app.get("/health", tags=["Health"])
async def detailed_health() -> dict[str, str]:
    """Detailed health check for Render."""
    mcp_status = _mcp_server_configuration()
    configured_count = sum(1 for cfg in mcp_status.values() if cfg.get("configured"))

    return {
        "status": "healthy" if configured_count > 0 else "degraded",
        "service": "Locus API",
        "version": "1.0.0",
        "mcp_servers_configured": str(configured_count),
    }


@app.get("/health/ready", tags=["Health"])
async def readiness_health() -> dict:
    """Readiness check with MCP server configuration visibility (non-secret)."""
    mcp_status = _mcp_server_configuration()
    configured_count = sum(1 for cfg in mcp_status.values() if cfg.get("configured"))
    status = "ready" if configured_count > 0 else "degraded"
    return {
        "status": status,
        "service": "Locus API",
        "mcp": mcp_status,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
