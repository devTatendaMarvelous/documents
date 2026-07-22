"""Health check endpoint (public, no authentication)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Health check payload."""

    status: str = Field(examples=["ok"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Returns service status. Does not require an API key.",
)
async def health_check() -> HealthResponse:
    """Return a simple OK status for load balancers and monitoring."""
    return HealthResponse(status="ok")
