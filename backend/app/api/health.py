"""`/api/health` — liveness + configuration reporting.

The frontend calls this on boot to display a connection badge, and ops use it
to confirm which provider configuration is active.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    llm_provider: str
    embedding_model: str


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Report liveness and the active (non-secret) configuration.

    Deliberately does NOT echo API keys or merged secret material.
    """
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.version,
        llm_provider=settings.llm_provider,
        embedding_model=settings.embedding_model,
    )
