"""
FastAPI Document & Image Service application entry point.

Exposes upload, retrieval, deletion, and health endpoints. Files are stored
exclusively on the local filesystem — no database is used.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import Scope

from app.api import files, health, upload
from app.core.config import get_settings
from app.core.constants import API_KEY
from app.core.logger import get_logger, log_extra, setup_logging

setup_logging()
logger = get_logger("main")

# Paths that do not require an API key (only the health probe is public)
PUBLIC_PATHS: frozenset[str] = frozenset({"/health"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Enforce ``X-API-Key`` on every request except ``GET /health``.

    This protects StaticFiles mounts as well as API routes. Route-level
    ``Depends(verify_api_key)`` remains as a second layer for OpenAPI docs.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path

        if path == "/health" or path in PUBLIC_PATHS:
            return await call_next(request)

        provided = (
            request.headers.get("X-API-Key")
            or request.headers.get("x-api-key")
            or request.headers.get("X-Api-Key")
        )
        if provided:
            provided = provided.strip()

        if not provided or provided != API_KEY:
            log_extra(
                logger,
                logging.WARNING,
                "Unauthorized request",
                path=path,
                method=request.method,
                reason="invalid_or_missing_api_key",
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "error": "Unauthorized",
                    "message": "Invalid or missing X-API-Key header",
                    "status_code": 401,
                },
            )

        return await call_next(request)


class MultiDirectoryStaticFiles(StaticFiles):
    """
    StaticFiles that resolves files from multiple directories in order.

    Enables a single ``/files/`` mount for both documents and original images.
    """

    def __init__(self, directories: list[str | Path], **kwargs: Any) -> None:
        dirs = [str(Path(d).resolve()) for d in directories]
        if not dirs:
            raise ValueError("At least one directory is required")
        super().__init__(directory=dirs[0], **kwargs)
        self._directories = dirs

    def lookup_path(self, path: str) -> tuple[str, Any]:
        """Return the first matching file across configured directories."""
        for directory in self._directories:
            full = Path(directory) / path
            try:
                full = full.resolve()
                # Prevent path traversal outside the storage directory
                if not str(full).startswith(directory):
                    continue
                if full.is_file():
                    stat_result = full.stat()
                    return str(full), stat_result
            except OSError:
                continue
        return "", None

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        await super().__call__(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ensure storage and log directories exist on startup."""
    settings = get_settings()
    settings.ensure_directories()
    log_extra(
        logger,
        logging.INFO,
        "Application starting",
        app=settings.app_name,
        version=settings.app_version,
        port=settings.port,
        max_upload_size=settings.max_upload_size,
    )
    yield
    log_extra(logger, logging.INFO, "Application shutting down")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Production-ready Document & Image Service. "
            "Upload, process, serve, and delete files over HTTP. "
            "All endpoints except ``GET /health`` require the ``X-API-Key`` header."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    application.add_middleware(APIKeyMiddleware)
    _register_exception_handlers(application)

    # Routers first so DELETE /files/{filename} and documented GET handlers
    # take precedence over the StaticFiles mounts for the same prefixes.
    _register_routers(application)
    _mount_static(application)

    # Advertise X-API-Key in OpenAPI so Swagger "Authorize" works
    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "ApiKeyAuth"
        ] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
        schema["security"] = [{"ApiKeyAuth": []}]
        health = schema.get("paths", {}).get("/health", {})
        for operation in health.values():
            if isinstance(operation, dict):
                operation["security"] = []
        application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore[method-assign]

    return application


def _register_routers(application: FastAPI) -> None:
    """Attach API routers."""
    application.include_router(health.router)
    application.include_router(upload.router)
    application.include_router(files.router)


def _mount_static(application: FastAPI) -> None:
    """
    Expose all storage directories under ``/files/`` via StaticFiles.

    The API route ``GET /files/{filename}`` is registered first and takes
    precedence (logging + consistent MIME handling). The mount remains as a
    filesystem-backed fallback for the same prefix.
    """
    settings = get_settings()
    settings.ensure_directories()

    application.mount(
        "/files",
        MultiDirectoryStaticFiles(
            directories=[
                settings.documents_dir,
                settings.images_dir,
                settings.optimized_dir,
                settings.thumbnails_dir,
            ],
        ),
        name="files",
    )


def _error_payload(
    *,
    status_code: int,
    error: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    """Build a consistent JSON error body."""
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
        "message": message,
        "status_code": status_code,
    }
    if details is not None:
        payload["details"] = details
    return payload


def _register_exception_handlers(application: FastAPI) -> None:
    """Ensure every error response is JSON (never HTML)."""

    @application.exception_handler(HTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            body = (
                detail
                if "status_code" in detail
                else {**detail, "status_code": exc.status_code}
            )
        else:
            body = _error_payload(
                status_code=exc.status_code,
                error=_status_label(exc.status_code),
                message=str(detail),
            )
        return JSONResponse(status_code=exc.status_code, content=body)

    @application.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                status_code=exc.status_code,
                error=_status_label(exc.status_code),
                message=str(exc.detail),
            ),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_payload(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                error="Unprocessable Entity",
                message="Request validation failed",
                details=exc.errors(),
            ),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        log_extra(
            logger,
            logging.ERROR,
            "Unhandled exception",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error="Internal Server Error",
                message="An unexpected error occurred",
            ),
        )


def _status_label(code: int) -> str:
    """Map common HTTP status codes to short labels."""
    labels = {
        400: "Bad Request",
        401: "Unauthorized",
        404: "Not Found",
        413: "Payload Too Large",
        415: "Unsupported Media Type",
        422: "Unprocessable Entity",
        500: "Internal Server Error",
    }
    return labels.get(code, "Error")


app = create_app()
