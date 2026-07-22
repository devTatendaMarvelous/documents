"""API key authentication for protected endpoints."""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException, status

from app.core.constants import API_KEY
from app.core.logger import get_logger, log_extra

logger = get_logger("security")


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """
    Validate the ``X-API-Key`` request header against the hardcoded API key.

    Raises:
        HTTPException: 401 when the header is missing or does not match.
    """
    provided = (x_api_key or "").strip() or None

    if not provided or provided != API_KEY:
        log_extra(
            logger,
            logging.WARNING,
            "Unauthorized request rejected",
            reason="invalid_or_missing_api_key",
            provided=bool(x_api_key),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": "Unauthorized",
                "message": "Invalid or missing X-API-Key header",
            },
        )

    return provided
